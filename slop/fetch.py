"""`slop fetch URL --to DIR`: download one shared file (the owner's song, stems zip, reference images) safely.

  slop fetch "https://drive.google.com/file/d/<id>/view?usp=sharing" --to audio
  slop fetch "https://www.dropbox.com/scl/fi/<...>/song.wav?rlkey=<...>&dl=0" --to audio
  slop fetch https://example.com/song.wav --to /workspace/inbox --sha256 <hex>

Link kinds:
  Google Drive file links (/file/d/ID/..., open?id=ID, uc?id=ID, /u/N/uc?id=ID, drive.usercontent.google.com/
    download?id=ID) are turned into the direct download URL, keeping a resourcekey= (older shared files need it); for
    big files Drive answers with a "can't scan for viruses" page first - its
    confirm form (or the old confirm cookie / token) is followed once. Folders and Google Docs/Sheets/Slides are refused
    with what to do instead.
  Dropbox share links get dl=1 (a folder link then downloads as a .zip).
  Anything else: plain HTTP(S) GET (redirects followed).
Refuses an HTML page (sign-in page, "file not shared", quota page, a web page instead of the file) by Content-Type
and by sniffing the first bytes. Streams to DIR/<name>.part, then renames; reports size and sha256; --sha256 verifies.
Idempotent: the same content already at DIR/<name> is kept ("unchanged"); different content gets <name>-2.ext unless
--force. Relative --to is relative to the project folder when --project/SLOP_PROJECT is given, else to the cwd.
Free (no provider spend). Progress goes to SLOP_PROGRESS_FILE, so `slop job start -- fetch URL --to DIR` shows it.
"""
from __future__ import annotations

import hashlib
import html
import http.client
import http.cookiejar
import os
import re
import shlex
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from . import util
from .config import SlopError, resolve_project

DRIVE_DOWNLOAD = "https://drive.usercontent.google.com/download"
UA = "Mozilla/5.0 (X11; Linux x86_64) claudia-fetch"
CHUNK = 1 << 20
DEFAULT_MAX_MB = 4096
AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a", ".aiff", ".aif", ".ogg"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".webm"}


# ====================================================================== link kinds
def drive_id(url: str) -> str | None:
    """The file id of a Google Drive file link, else None."""
    u = urllib.parse.urlparse(url)
    host = (u.hostname or "").lower()
    if host not in ("drive.google.com", "docs.google.com", "drive.usercontent.google.com"):
        return None
    m = re.search(r"/file/d/([A-Za-z0-9_-]{10,})", u.path)
    if m:
        return m.group(1)
    q = urllib.parse.parse_qs(u.query)
    if q.get("id") and re.fullmatch(r"[A-Za-z0-9_-]{10,}", q["id"][0]) and \
            (u.path.rstrip("/") == "" or re.search(r"/(uc|open|download)/?$", u.path) or u.path.startswith("/uc")):
        return q["id"][0]  # /uc, /open, /download, also under an account prefix: /u/0/uc?id=...
    return None


def classify(url: str) -> tuple[str, str]:
    """(kind, download url). kind: drive | dropbox | http. Raises SlopError for links that cannot be a file."""
    url = (url or "").strip()
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise SlopError(f"not a web link: {url!r} - give the full https://... address of the shared file")
    host = u.hostname.lower()
    if host in ("drive.google.com", "docs.google.com"):
        if "/folders/" in u.path or "folderview" in u.path:
            raise SlopError("that is a Google Drive FOLDER link: open the folder, share each file ('Anyone with the "
                            "link'), and fetch the file links one by one (or download the folder as a .zip and share "
                            "that file)")
        if re.search(r"/(document|spreadsheets|presentation|forms)/d/", u.path):
            raise SlopError("that is a Google Docs/Sheets/Slides link, not a file: in it use File > Download, upload "
                            "the downloaded file to Drive, share it ('Anyone with the link') and fetch that link")
    did = drive_id(url)
    if did:
        rk = urllib.parse.parse_qs(u.query).get("resourcekey")  # older shared files need their resource key
        return "drive", f"{DRIVE_DOWNLOAD}?id={did}&export=download" + (
            f"&resourcekey={urllib.parse.quote(rk[0], safe='')}" if rk and rk[0] else "")
    if host in ("dropbox.com", "www.dropbox.com"):
        q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if k not in ("dl", "raw")]
        q.append(("dl", "1"))
        return "dropbox", urllib.parse.urlunparse(u._replace(query=urllib.parse.urlencode(q)))
    return "http", url


# ====================================================================== Drive confirm page
class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms: list[dict] = []
        self._cur: dict | None = None
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._cur = {"action": a.get("action") or "", "method": (a.get("method") or "get").lower(), "fields": {}}
            self.forms.append(self._cur)
        elif tag == "input" and self._cur is not None and a.get("name"):
            if (a.get("type") or "text").lower() in ("hidden", "text", "submit"):
                self._cur["fields"][a["name"]] = a.get("value") or ""
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "form":
            self._cur = None
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def drive_confirm_url(page: str, base_url: str, cookies: http.cookiejar.CookieJar | None = None) -> str | None:
    """The URL that confirms a Drive "can't scan this file for viruses" download, or None."""
    p = _FormParser()
    try:
        p.feed(page)
    except Exception:  # noqa: BLE001 - malformed HTML: fall through to the regex/cookie forms
        pass
    for f in p.forms:
        if "confirm" in f["fields"] or "download" in f["action"]:
            action = urllib.parse.urljoin(base_url, html.unescape(f["action"]) or base_url)
            if f["fields"]:
                sep = "&" if "?" in action else "?"
                return action + sep + urllib.parse.urlencode(f["fields"])
            return action
    m = re.search(r"""href=["']([^"']*confirm=[^"']+)["']""", page)
    if m:
        return urllib.parse.urljoin(base_url, html.unescape(m.group(1)))
    m = re.search(r"confirm=([0-9A-Za-z_-]+)", page)
    tok = m.group(1) if m else None
    if not tok and cookies is not None:
        tok = next((c.value for c in cookies if c.name.startswith("download_warning")), None)
    if tok:
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(base_url).query))
        q["confirm"] = tok
        return urllib.parse.urlunparse(urllib.parse.urlparse(base_url)._replace(query=urllib.parse.urlencode(q)))
    return None


# ====================================================================== helpers
def looks_html(head: bytes) -> bool:
    s = head[:1024].lstrip().lower()
    return s.startswith(b"<!doctype html") or s.startswith(b"<html") or (s.startswith(b"<") and b"<html" in s[:512])


def filename_from(resp, url: str) -> str:
    cd = resp.headers.get("Content-Disposition") or ""
    name = None
    m = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", cd, re.I)
    if m:
        name = urllib.parse.unquote(m.group(2).strip().strip('"'), encoding=(m.group(1) or "utf-8").strip() or "utf-8")
    if not name:
        m = re.search(r'filename\s*=\s*"([^"]+)"', cd, re.I) or re.search(r"filename\s*=\s*([^;]+)", cd, re.I)
        if m:
            name = m.group(1).strip()
    if not name:
        name = urllib.parse.unquote(Path(urllib.parse.urlparse(resp.geturl() or url).path).name)
    return safe_name(name) or "download.bin"


def safe_name(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1].strip().strip(".")
    name = re.sub(r"[\x00-\x1f<>:\"|?*]+", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name[:180]


def _html_refusal(kind: str, page: str, final_url: str) -> str:
    title = ""
    p = _FormParser()
    try:
        p.feed(page)
        title = re.sub(r"\s+", " ", p.title).strip()
    except Exception:  # noqa: BLE001
        pass
    low = page.lower()
    why = f"the link returned a web page{f' ({title!r})' if title else ''}, not the file"
    if kind == "drive":
        if "accounts.google.com" in (final_url or "") or "signin" in low or "sign in" in low:
            return why + (": the file is not shared publicly. In Drive: Share > General access > 'Anyone with the "
                          "link' (Viewer), then fetch the link again")
        if "quota" in low or "too many users" in low:
            return why + (": Drive's download quota for this file is used up for now (too many downloads). Try "
                          "again later, or the owner makes a copy (File > Make a copy) and shares the copy's link")
        return why + ": make sure it is a FILE link shared as 'Anyone with the link' (Share > Copy link)"
    if kind == "dropbox":
        return why + ": make sure the Dropbox link is a share link that anyone can open (it may have expired)"
    return why + ": give the DIRECT link to the file (on the page: right-click the download button > Copy link)"


def _resolve_dir(to: str, project: str | None) -> Path:
    p = Path(to).expanduser()
    if p.is_absolute():
        return p
    pname = project or os.environ.get("SLOP_PROJECT")
    if pname:
        return resolve_project(pname) / p
    return Path.cwd() / p


def _next_hint(dest: Path, project: str | None) -> str:
    """The next command for the saved file. Every path is shell-quoted (owner exports have spaces and brackets:
    'My Song (final).wav'); project is a --project value as core_cli.project_ref gives it (already quoted)."""
    ext = dest.suffix.lower()
    pf = f"--project {project} " if project else "--project NAME "
    q = shlex.quote
    if ext in AUDIO_EXT:
        return f"slop {pf}song ingest {q(str(dest))}"
    if ext == ".zip":
        return f"unzip it: python3 -m zipfile -e {q(str(dest))} {q(str(dest.parent / dest.stem))}"
    if ext in IMAGE_EXT:
        return f"put plate images in one folder, then: slop {pf}plates ingest {q(str(dest.parent))}"
    if ext in VIDEO_EXT:
        return "a video: check it with ffprobe before using it"
    return ""


# ====================================================================== download
def fetch(url: str, to: Path, name: str | None = None, force: bool = False, sha256: str | None = None,
          max_mb: float = DEFAULT_MAX_MB, timeout: float = 60) -> dict:
    kind, dl = classify(url)
    want = (sha256 or "").strip().lower() or None
    if want and not re.fullmatch(r"[0-9a-f]{64}", want):
        raise SlopError("--sha256 must be 64 hex characters")
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def open_(u: str):
        try:
            return opener.open(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=timeout)
        except urllib.error.HTTPError as e:
            hint = {401: "it needs a sign-in: share it publicly ('Anyone with the link')",
                    403: "access denied: the link is private, expired, or the host blocks downloads",
                    404: "not found: check the link (copy it again from the share dialog)",
                    429: "the host is rate-limiting: wait a few minutes and retry"}.get(e.code, "")
            raise SlopError(f"download failed: HTTP {e.code} from {urllib.parse.urlparse(u).hostname}"
                            + (f" - {hint}" if hint else "")) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SlopError(f"download failed: cannot reach {urllib.parse.urlparse(u).hostname} "
                            f"({getattr(e, 'reason', e)}); check the link and the network") from None

    def read(r, n: int) -> bytes:
        try:
            return r.read(n)
        except (http.client.HTTPException, OSError, urllib.error.URLError, TimeoutError) as e:
            r.close()
            raise SlopError(f"download interrupted ({type(e).__name__}: {e}); run the same command again") from None

    def is_html(r, head: bytes) -> bool:
        ct = (r.headers.get_content_type() or "").lower()
        return ct in ("text/html", "application/xhtml+xml") or looks_html(head)

    limit = int(max_mb * 1024 * 1024)

    def size_of(r) -> int | None:
        t = r.headers.get("Content-Length")
        t = int(t) if t and t.isdigit() else None
        if t and t > limit and (r.headers.get_content_type() or "").lower() != "text/html":
            r.close()
            raise SlopError(f"the file is {util.human_bytes(t)}, over --max-mb {max_mb:g}: raise --max-mb if that "
                            "is expected")
        return t

    resp = open_(dl)
    size_of(resp)
    head = read(resp, 65536)
    if kind == "drive" and is_html(resp, head):
        page = (head + read(resp, 2_000_000)).decode("utf-8", "replace")
        resp.close()
        nxt = drive_confirm_url(page, resp.geturl() or dl, jar)
        if not nxt:
            raise SlopError(_html_refusal(kind, page, resp.geturl()))
        resp = open_(nxt)
        size_of(resp)
        head = read(resp, 65536)
    ctype = (resp.headers.get_content_type() or "").lower()
    if is_html(resp, head):
        page = head.decode("utf-8", "replace")
        final = resp.geturl()
        resp.close()
        raise SlopError(_html_refusal(kind, page, final))

    fname = safe_name(name) if name else filename_from(resp, dl)
    if not fname:
        raise SlopError("give a file name with --name (the link does not say one)")
    to = Path(to)
    to.mkdir(parents=True, exist_ok=True)
    total = size_of(resp)
    part = to / (fname + ".part")
    h = hashlib.sha256()
    n = 0
    t0 = time.monotonic()
    last = 0.0
    from .job import write_progress
    try:
        with open(part, "wb") as f:
            chunk = head
            while chunk:
                f.write(chunk)
                h.update(chunk)
                n += len(chunk)
                if n > limit:
                    raise SlopError(f"the download passed --max-mb {max_mb:g} ({util.human_bytes(n)}): stopped. Raise "
                                    "--max-mb if the file really is that big")
                now = time.monotonic()
                if now - last > 0.5:
                    last = now
                    eta = ((total - n) / (n / max(now - t0, 1e-3))) if total and n else None
                    write_progress(n, total, f"downloading {fname}", round(eta, 1) if eta is not None else None,
                                   stage="fetch")
                chunk = read(resp, CHUNK)
    except SlopError:
        part.unlink(missing_ok=True)
        raise
    except (OSError, urllib.error.URLError, TimeoutError) as e:
        part.unlink(missing_ok=True)
        raise SlopError(f"download interrupted after {util.human_bytes(n)} ({e}); run the same command again") from None
    finally:
        resp.close()
    if total is not None and n != total:
        part.unlink(missing_ok=True)
        raise SlopError(f"download incomplete: got {n} of {total} bytes; run the same command again")
    if n == 0:
        part.unlink(missing_ok=True)
        raise SlopError("the link returned an empty file: check that it points at the file itself")
    digest = h.hexdigest()
    if want and digest != want:
        part.unlink(missing_ok=True)
        raise SlopError(f"sha256 mismatch: got {digest}, expected {want} - the file differs from what was promised; "
                        "not saved")
    dest = to / fname
    status = "saved"
    if dest.exists():
        if dest.is_file() and _sha256(dest) == digest:
            part.unlink(missing_ok=True)
            status = "unchanged"
        elif force:
            os.replace(part, dest)
            status = "replaced"
        else:
            stem, ext = dest.stem, dest.suffix
            k = 2
            while (to / f"{stem}-{k}{ext}").exists():
                k += 1
            dest = to / f"{stem}-{k}{ext}"
            os.replace(part, dest)
            status = "saved-as-new-name"
    else:
        os.replace(part, dest)
    write_progress(n, n, f"downloaded {dest.name}", final=True, stage="fetch")
    return {"file": str(dest.resolve()), "name": dest.name, "bytes": n, "size": util.human_bytes(n), "sha256": digest,
            "content_type": ctype, "source": kind, "status": status, "seconds": round(time.monotonic() - t0, 2)}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_fetch(args) -> dict:
    to = _resolve_dir(args.to, args.project)
    r = fetch(args.url, to, name=args.name, force=args.force, sha256=args.sha256, max_mb=args.max_mb,
              timeout=args.timeout)
    ref = None
    if args.project or os.environ.get("SLOP_PROJECT"):
        try:
            from .core_cli import project_ref
            ref = project_ref(resolve_project(args.project))
        except SlopError:
            ref = None
    nxt = _next_hint(Path(r["file"]), ref)
    word = {"saved": "saved", "replaced": "replaced the old file:", "unchanged": "already there (same content):",
            "saved-as-new-name": "a different file had that name, so saved as"}[r["status"]]
    lines = [f"{word} {r['file']}", f"  {r['size']} ({r['bytes']} bytes), sha256 {r['sha256']}, from {r['source']}"]
    if nxt:
        lines.append(f"next: {nxt}")
    r["next"] = nxt
    r["text"] = "\n".join(lines)
    return r


def register(sub) -> None:
    p = sub.add_parser("fetch", help="download a shared file (Google Drive, Dropbox, HTTPS) with size + sha256",
                       description="Download ONE file from a share link: Google Drive file links (the big-file "
                                   "confirm step included), Dropbox (dl=1), or a plain HTTPS URL. Refuses web pages "
                                   "(sign-in, not shared, quota). Example: slop --project my-song fetch "
                                   "\"https://drive.google.com/file/d/ID/view\" --to audio")
    p.add_argument("url", help="the share link (quote it)")
    p.add_argument("--to", required=True, metavar="DIR",
                   help="folder to save into (relative = inside the project when --project is given)")
    p.add_argument("--name", help="file name to save as (default: from the server, else the link)")
    p.add_argument("--sha256", help="expected sha256: refuse a different file")
    p.add_argument("--force", action="store_true", help="replace a different file of the same name")
    p.add_argument("--max-mb", type=float, default=DEFAULT_MAX_MB, help=f"size limit (default {DEFAULT_MAX_MB} MB)")
    p.add_argument("--timeout", type=float, default=60, help="network timeout per read, seconds")
    util.add_common_flags(p)
    util.json_usage_errors(p)
    p.set_defaults(func=cmd_fetch)
