"""`slop gen image --provider codex`: API-style stills on the user's ChatGPT plan, through the Codex CLI.

Codex has a built-in image tool (`image_gen.imagegen`, feature `image_generation`, stable and on by default in
codex-cli 0.160; its system skill is `$imagegen`). Codex saves each picture under $CODEX_HOME/generated_images/…
("imagegen needs a few minutes to finish"). No API key is involved: it runs on the user's ChatGPT plan and its image
limits. Verified from the 0.160.0 binary and its bundled skill text; never called for real by the test suite.

One image = one `codex exec` run:
  codex exec --json --skip-git-repo-check -c forced_login_method="chatgpt" --enable image_generation -s read-only
             -C <scratch> -o <scratch>/last-message.txt [-i REF …] -        (prompt on stdin; stdin then closed)
with OPENAI_API_KEY / CODEX_API_KEY removed (plan only). The run is read-only: Codex itself saves the picture; this
module finds it (the image item's saved path, else the "SAVED <path>" reply, else the newest new file under
$CODEX_HOME/generated_images) and copies it to plates/cands/<plate>/<k>.<ext> with the same sidecar as the OpenRouter
path (model "codex/imagegen", so `--jobs` re-runs skip images already made). Ledger: provider "codex", $0, note "plan".

Aspect ratio is a composition instruction in the prompt (the tool has no size argument); the sidecar records the real
pixel size. Each image takes 1-4 minutes, so the command starts itself as a background `slop job` (`slop job wait ID`).
`--jobs` runs plates/jobs.json one image at a time (a dry run without --yes, like the OpenRouter batch).
References (`-i`): `--ref` takes an image file or a plate candidate PLATE[:K] (as in slop/gen/images.py; links are
refused: the tool takes files), and a job's own "refs" (the lead anchor `slop plates book --anchor PLATE` writes into
every lead plate's job) are attached too; resume counts only images made with the same references.

EXPERIMENTAL: no image has been made with a real ChatGPT plan yet (the command line was accepted by codex-cli 0.160
while logged out); the event shape of the image tool and the plan's image limits are unverified [U].
One codex image run at a time on this computer (lock $SLOP_HOME/agents/imagegen/run.lock), so the last-resort search
of $CODEX_HOME/generated_images (preferring the run's own <thread_id>/ folder) can never pick another run's picture.
The scratch folder agents/imagegen/<stamp> is deleted after a success and kept (named in the error) after a failure.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .. import ledger, util
from ..config import SlopError, resolve_project

MODEL = "codex/imagegen"
PROVIDER = "codex"
DEFAULT_TIMEOUT_S = 600
MAX_N = 10
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")
LIMIT_RE = re.compile(r"(?i)usage limit|rate limit|limit reached|quota|too many requests|try again (?:at|in)")
AUTH_RE = re.compile(r"(?i)not logged in|log ?in|sign ?in|authenticat|unauthori[sz]ed|401")
ASPECT_WORDS = {"16:9": "a wide landscape 16:9 frame", "9:16": "a tall portrait 9:16 frame", "1:1": "a square 1:1 frame",
                "4:3": "a landscape 4:3 frame", "3:4": "a portrait 3:4 frame", "21:9": "an ultra-wide 21:9 frame",
                "3:2": "a landscape 3:2 frame", "2:3": "a portrait 2:3 frame"}


class CodexImageError(SlopError):
    def __init__(self, msg: str, kind: str = "failed"):
        super().__init__(msg)
        self.kind = kind                     # failed | limit | auth | timeout | noimage


# ------------------------------------------------------------------------------------------------- helpers
def _engines():
    from ..agents import engines as E
    return E


def codex_home() -> Path:
    return _engines().codex_home()


def _pcmd(pdir: Path, rest: str) -> str:
    from .images import _pcmd as pc
    return pc(pdir, rest)


def sniff_ext(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def image_size(path: Path) -> list[int] | None:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return [int(im.width), int(im.height)]
    except Exception:  # noqa: BLE001 - PIL missing or unreadable: fall back to the PNG header
        pass
    try:
        b = Path(path).read_bytes()[:32]
        if b[:8] == b"\x89PNG\r\n\x1a\n":
            return [int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")]
    except OSError:
        pass
    return None


def build_prompt(prompt: str, aspect: str | None, n_refs: int) -> str:
    frame = ASPECT_WORDS.get(aspect or "16:9", f"a {aspect} frame")
    lines = [
        "Generate exactly ONE image with your built-in image generation tool (the $imagegen skill / image_gen tool).",
        "Do not use any CLI fallback or API key, do not write code, and do not run shell commands.",
        f"Composition: {frame}.",
    ]
    if n_refs:
        lines.append(f"Use the {n_refs} attached image(s) as the visual reference (identity, style, layout) as the "
                     "description says.")
    lines += ["Image description (use it as written; add no text, captions, logos or watermarks unless it asks):",
              "<<<", prompt.strip(), ">>>",
              "When the tool has returned the image, reply with exactly one line: SAVED <the full path of the image "
              "file>."]
    return "\n".join(lines) + "\n"


def _walk_paths(obj, out: list) -> None:
    """Every saved-image path or inline image payload in an event item."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and k in ("saved_path", "savedPath", "path", "file", "image_path") \
                    and v.lower().endswith(IMG_EXTS):
                out.append(("path", v))
            elif isinstance(v, str) and k in ("result", "b64_json", "image_base64") and len(v) > 200:
                out.append(("b64", v))
            else:
                _walk_paths(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_paths(v, out)


def parse_events(lines: list[str]) -> dict:
    """thread id, image candidates, the last reply, an error, usage - from `codex exec --json` lines."""
    r = {"thread_id": None, "images": [], "last_text": "", "error": None, "revised_prompt": None, "usage": None}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        t = ev.get("type")
        if t == "thread.started":
            r["thread_id"] = ev.get("thread_id")
        elif t in ("item.completed", "item.updated", "item.started"):
            it = ev.get("item") or {}
            if it.get("type") == "agent_message" and t == "item.completed":
                r["last_text"] = str(it.get("text") or "")
            elif "image" in str(it.get("type") or "").lower() or any(k in it for k in ("saved_path", "savedPath")):
                if t == "item.completed":
                    _walk_paths(it, r["images"])
                    r["revised_prompt"] = it.get("revised_prompt") or it.get("revisedPrompt") or r["revised_prompt"]
            elif it.get("type") == "error":
                r["error"] = str(it.get("message") or it)[:500]
        elif t == "turn.completed":
            r["usage"] = ev.get("usage")
        elif t in ("turn.failed", "error"):
            e = ev.get("error") if "error" in ev else ev.get("message")
            r["error"] = (e.get("message") if isinstance(e, dict) else str(e or ev))[:500]
    return r


def _new_images(since: float, thread_id: str | None = None) -> list[Path]:
    """Images Codex saved since `since`: only in the run's own generated_images/<thread_id>/ folder when it exists."""
    root = codex_home() / "generated_images"
    if not root.is_dir():
        return []
    if thread_id and re.fullmatch(r"[\w.-]+", thread_id) and (root / thread_id).is_dir():
        root = root / thread_id
    out = []
    for p in root.rglob("*"):
        try:
            if p.is_file() and p.suffix.lower() in IMG_EXTS and p.stat().st_mtime >= since - 1:
                out.append(p)
        except OSError:
            continue
    return sorted(out, key=lambda p: p.stat().st_mtime)


def _pick_image(ev: dict, last_msg: str, since: float, scratch: Path) -> tuple[bytes | None, str]:
    import base64
    for kind, v in reversed(ev["images"]):
        if kind == "path":
            p = Path(v)
            if p.is_file():
                return p.read_bytes(), str(p)
        else:
            try:
                return base64.b64decode(v.split(",", 1)[-1]), "inline"
            except ValueError:
                continue
    m = re.search(r"SAVED\s+(\S.*?)\s*$", last_msg or ev.get("last_text") or "", re.M)
    if m:
        p = Path(m.group(1).strip().strip("`'\""))
        if p.is_file() and p.suffix.lower() in IMG_EXTS:
            return p.read_bytes(), str(p)
    new = _new_images(since, ev.get("thread_id"))
    if new:
        return new[-1].read_bytes(), str(new[-1])
    for p in sorted(scratch.glob("*")):
        if p.suffix.lower() in IMG_EXTS:
            return p.read_bytes(), str(p)
    return None, ""


# ------------------------------------------------------------------------------------------------- one run at a time
@contextmanager
def one_at_a_time():
    """Hold $SLOP_HOME/agents/imagegen/run.lock for one codex image run. POSIX: flock (the kernel frees it when the
    holder dies; a waiter blocks and is woken when it is freed). Elsewhere: an O_EXCL file with the holder's pid."""
    d = _engines().agents_dir() / "imagegen"
    d.mkdir(parents=True, exist_ok=True)
    lock = d / "run.lock"
    try:
        import fcntl
    except ImportError:                                  # pragma: no cover - Windows
        fcntl = None
    if fcntl is not None:
        f = open(lock, "a+", encoding="utf-8")
        try:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                _waiting_note()
                fcntl.flock(f, fcntl.LOCK_EX)            # blocks; `slop job cancel ID` stops the wait
            f.seek(0)
            f.truncate()
            f.write(str(os.getpid()))
            f.flush()
            yield
        finally:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            finally:
                f.close()
        return
    from ..agents.login import pid_alive              # pragma: no cover - Windows
    said = False
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                holder = int(lock.read_text(encoding="utf-8").strip() or 0)
            except (OSError, ValueError):
                holder = 0
            if holder and not pid_alive(holder):
                stale = lock.with_name(f"run.lock.{os.getpid()}.stale")
                try:
                    lock.replace(stale)
                    stale.unlink()
                except OSError:
                    pass
                continue
            if not said:
                _waiting_note()
                said = True
            time.sleep(1.0)
    try:
        yield
    finally:
        try:
            if lock.read_text(encoding="utf-8").strip() == str(os.getpid()):
                lock.unlink()
        except OSError:
            pass


def _waiting_note() -> None:
    try:
        from ..job import write_progress
        write_progress(msg="waiting: another codex image run is going (one at a time on this computer)")
    except Exception:  # noqa: BLE001 - progress is advisory
        pass


# ------------------------------------------------------------------------------------------------- one run
def check_login() -> None:
    E = _engines()
    b = E.find("codex")
    if not b:
        raise CodexImageError("the Codex CLI is not installed: slop agents install codex, then slop agents login codex",
                              "auth")
    rc, out, err = E.run_cli("codex", ["login", "status"], timeout=30)
    text = (out + err).lower()
    if rc != 0 or "logged in" not in text:
        raise CodexImageError("Codex is not signed in with a ChatGPT plan: slop agents login codex", "auth")
    if "chatgpt" not in text:
        raise CodexImageError("Codex is signed in with an API key, not a ChatGPT plan; this provider uses the plan "
                              "only: slop agents login codex --force (choose the ChatGPT sign-in)", "auth")


def run_codex(prompt_text: str, refs: list[str], timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    """One `codex exec` image run (one at a time on this computer). Returns {data, ext, src, thread_id, secs,
    revised_prompt, reply, scratch}."""
    with one_at_a_time():
        return _run_codex(prompt_text, refs, timeout)


def _run_codex(prompt_text: str, refs: list[str], timeout: float) -> dict:
    E = _engines()
    b = E.find("codex")
    if not b:
        raise CodexImageError("the Codex CLI is not installed: slop agents install codex", "auth")
    base = E.agents_dir() / "imagegen"
    base.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-", dir=base))
    last = scratch / "last-message.txt"
    argv = b["argv"] + ["exec", "--json", "--skip-git-repo-check", "-c", 'forced_login_method="chatgpt"',
                        "--enable", "image_generation", "-s", "read-only", "-C", str(scratch), "-o", str(last)]
    for r in refs:
        argv += ["-i", str(r)]
    argv.append("-")
    t0 = time.time()
    m0 = time.monotonic()
    lines: list[str] = []
    kw = {"start_new_session": True} if os.name != "nt" else {}
    p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=E.base_env("codex"), cwd=str(scratch), text=True, encoding="utf-8", errors="replace", **kw)
    err_buf: list[str] = []
    t_err = threading.Thread(target=lambda: err_buf.append(p.stderr.read() or ""), daemon=True)
    t_err.start()
    try:
        p.stdin.write(prompt_text)
        p.stdin.close()
    except OSError:
        pass

    def reader():
        for line in p.stdout:
            lines.append(line)
            try:
                from ..job import write_progress
                ev = json.loads(line)
                it = ev.get("item") or {}
                if ev.get("type") == "item.started" and "image" in str(it.get("type") or ""):
                    write_progress(msg="codex: generating the image")
            except Exception:  # noqa: BLE001 - progress is advisory
                pass
    t_out = threading.Thread(target=reader, daemon=True)
    t_out.start()
    t_out.join(timeout)
    timed_out = t_out.is_alive()
    if timed_out:
        try:
            if os.name != "nt":
                import signal
                os.killpg(p.pid, signal.SIGTERM)
            else:  # pragma: no cover
                p.kill()
        except OSError:
            pass
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        p.kill()
    t_err.join(2)
    secs = round(time.monotonic() - m0, 1)
    ev = parse_events(lines)
    reply = ev["last_text"] or (last.read_text(encoding="utf-8", errors="replace") if last.is_file() else "")
    data, src = _pick_image(ev, reply, t0, scratch)
    stderr = "".join(err_buf)[-1500:]
    if data is None:
        msg = ev["error"] or (reply.strip()[:300] if reply.strip() else "") or stderr.strip()[-300:]
        if timed_out:
            raise CodexImageError(f"no image after {int(timeout)} s (codex was stopped)", "timeout")
        if msg and LIMIT_RE.search(msg):
            raise CodexImageError(f"the ChatGPT plan's limit is reached ({msg[:200]}). Check it with `slop agents "
                                  "status codex --limits`; run this again after the reset", "limit")
        if msg and AUTH_RE.search(msg) and "image" not in msg.lower():
            raise CodexImageError(f"Codex could not use the ChatGPT sign-in ({msg[:200]}): slop agents login codex "
                                  "--force", "auth")
        raise CodexImageError("Codex finished without an image" + (f": {msg[:300]}" if msg else "")
                              + f" (exit {p.returncode}; its files: {scratch})", "noimage")
    ext = sniff_ext(data)
    if not ext:
        raise CodexImageError(f"Codex returned a file that is not a PNG/JPEG/WebP image ({src})", "noimage")
    return {"data": data, "ext": ext, "src": src, "thread_id": ev["thread_id"], "secs": secs,
            "revised_prompt": ev["revised_prompt"], "reply": reply.strip()[:300], "scratch": str(scratch)}


def ref_files(pdir: Path, refs: list[str] | None, in_project: bool = False) -> list[dict]:
    """References for `codex exec -i`: image files or plate candidates PLATE[:K] (also PLATE#K, PLATE~K; no K = the
    plate's pick), resolved like the OpenRouter path's (slop/gen/images.py resolve_refs). The plan's image tool takes
    attached FILES, so an https or data: link is refused (download it first) before any run."""
    from .images import resolve_refs
    rs = resolve_refs(pdir, refs, in_project=in_project)
    links = [r["ref"] for r in rs if str(r["src"]).startswith(("http://", "https://", "data:"))]
    if links:
        short = links[0] if len(links[0]) <= 60 else links[0][:57] + "..."
        raise SlopError(f"--ref {short}: the ChatGPT plan's image tool (--provider codex) takes image files, not links: "
                        f"download it first (`{_pcmd(pdir, 'fetch URL --to uploads')}`) and give the file "
                        "(--ref uploads/FILE), or a plate candidate (--ref PLATE:K); nothing was run")
    return rs


def _job_refs(pdir: Path, j: dict, extra: list[dict]) -> list[dict]:
    """A job's own "refs" (project-relative, written by `slop plates book --anchor`) + the batch's --ref, resolved;
    errors name the job and the fix (as the OpenRouter batch does)."""
    try:
        own = ref_files(pdir, j.get("refs"), in_project=True)
    except SlopError as e:
        fix = (f"re-anchor with `{_pcmd(pdir, 'plates book --anchor PLATE:K')}` (or --no-anchor)" if j.get("anchor")
               else "fix the job's \"refs\" in the jobs file")
        raise SlopError(f"job {j['plate']}: {e}. Nothing was run; {fix}") from None
    seen = {r["id"] for r in own}
    return own + [r for r in extra if r["id"] not in seen]


def _ref_arg(pdir: Path, s: str) -> str:
    """A --ref as a background job (another working folder) must see it: an image file that exists here or in the
    project as its absolute path; a plate candidate (PLATE:K) or a link exactly as given."""
    p = util.input_path(pdir, s)
    return str(Path(p).resolve()) if p is not None and Path(p).is_file() else s


def generate_one(pdir: Path, *, prompt: str, aspect: str | None = "16:9", refs: list[str] | None = None,
                 out_dir: Path | None = None, out: Path | None = None, timeout: float = DEFAULT_TIMEOUT_S,
                 meta: dict | None = None) -> dict:
    """refs: image FILES (resolved by ref_files); the sidecar records them as project-relative ids."""
    from .images import ref_id, reserve
    if out is None and out_dir is None:
        raise SlopError("say where the image goes: --plate NAME (plates/cands/NAME/<k>.png) or --out FILE")
    refs = [str(r) for r in (refs or [])]
    try:
        r = run_codex(build_prompt(prompt, aspect, len(refs)), refs, timeout)
    except CodexImageError as e:
        ledger.record(pdir, provider=PROVIDER, model=MODEL, kind="image", est_usd=0.0, units={"n": 0, "plan": "chatgpt"},
                      status="failed", note=f"plan: {e.kind}: {str(e)[:120]}")
        raise
    side = {"model": MODEL, "provider": PROVIDER, "prompt": prompt.strip(), "aspect_ratio": aspect, "resolution": None,
            "quality": None, "seed": None, "refs": [ref_id(pdir, r) for r in refs], "cost_usd": 0.0, "est_usd": 0.0,
            "plan": "chatgpt",
            "thread_id": r["thread_id"], "revised_prompt": r["revised_prompt"], "secs": r["secs"], **(meta or {})}
    if out is not None:
        dst = Path(out)
        if not dst.suffix:
            dst = dst.with_suffix(r["ext"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(r["data"])
    else:
        dst = reserve(Path(out_dir), r["ext"], side)
        dst.write_bytes(r["data"])
    side["size"] = image_size(dst)
    dst.with_suffix(".json").write_text(json.dumps(side, indent=1), encoding="utf-8")
    if r.get("scratch"):                                 # the picture is saved: the run's scratch folder can go
        shutil.rmtree(r["scratch"], ignore_errors=True)
    row = ledger.record(pdir, provider=PROVIDER, model=MODEL, kind="image", est_usd=0.0,
                        units={"n": 1, "plan": "chatgpt", "secs": r["secs"], "size": side["size"]},
                        request_id=r["thread_id"], status="ok", note="plan")
    return {"file": str(dst), "secs": r["secs"], "size": side["size"], "thread_id": r["thread_id"], "ledger": row}


def generate(pdir: Path, *, prompt: str, n: int = 1, aspect: str | None = "16:9", refs: list[str] | None = None,
             out_dir: Path | None = None, out: Path | None = None, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    from ..job import write_progress
    refs = [r["src"] for r in ref_files(pdir, refs)]       # files or PLATE[:K]; refused before any run
    check_login()
    files, secs = [], []
    for i in range(n):
        write_progress(done=i, total=n, msg=f"codex image {i + 1}/{n}")
        dst = None
        if out is not None and n > 1:
            o = Path(out)
            dst = o.with_name(f"{o.stem}-{i + 1}{o.suffix}")
        g = generate_one(pdir, prompt=prompt, aspect=aspect, refs=refs, out_dir=out_dir,
                         out=dst if dst is not None else out, timeout=timeout)
        files.append(g["file"])
        secs.append(g["secs"])
    write_progress(done=n, total=n, msg="done", final=True)
    after = (f"next: {_pcmd(pdir, 'plates sheet')}, then the owner picks ({_pcmd(pdir, 'plates pick PLATE K')})"
             if out_dir is not None else "")
    return {"ok": True, "provider": PROVIDER, "files": files, "cost_usd": 0.0, "est_usd": 0.0, "secs": secs,
            "experimental": True,
            "text": f"{len(files)} image(s) on the ChatGPT plan via Codex ($0, {sum(secs):.0f} s; experimental): "
                    + ", ".join(files) + (f"\n{after}" if after else "")}


# ------------------------------------------------------------------------------------------------- batch
def plan_jobs(pdir: Path, jobs: list[dict], only: list[str] | None, missing: bool,
              refs: list[str] | None = None) -> list[dict]:
    """refs: the batch's --ref, added to every job's own "refs" (the lead anchor `slop plates book --anchor` writes);
    resume counts only images made from the same prompt with the same references."""
    from .images import any_candidates, job_prompt, made_for
    extra = ref_files(pdir, refs) if refs else []
    if only:
        known = {j["plate"] for j in jobs}
        bad = [o for o in only if o not in known]
        if bad:
            raise SlopError(f"--only: plate(s) not in the jobs file: {', '.join(bad)}")
    rows, taken = [], {}
    for i, j in enumerate(jobs):
        plate = j["plate"]
        asp = j.get("aspect") or "16:9"
        try:
            n = int(j.get("n") or 1)
        except (TypeError, ValueError):
            raise SlopError(f"job {plate}: n must be a whole number of images") from None
        row = {"job": i + 1, "plate": plate, "aspect": asp, "n": n, "done": 0, "need": 0, "skip": None}
        if only and plate not in only:
            row["skip"] = "not in --only"
        elif missing and any_candidates(pdir, plate):
            row["skip"] = "has candidates (--missing)"
        else:
            prompt = job_prompt(pdir, j)
            row["prompt"] = prompt
            rs = _job_refs(pdir, j, extra)
            ids = [r["id"] for r in rs]
            row["refs"], row["ref_src"] = ids, [r["src"] for r in rs]
            if j.get("anchor"):
                row["anchor"] = j["anchor"]
            key = (plate, prompt.strip(), asp, tuple(sorted(ids)))
            have = len(made_for(pdir, plate, prompt, MODEL, aspect=asp, refs=ids))
            row["done"] = min(n, max(0, have - taken.get(key, 0)))
            taken[key] = taken.get(key, 0) + row["done"]
            row["need"] = max(0, n - row["done"])
            if row["need"] == 0:
                row["skip"] = f"done ({row['done']}/{n} made on the plan from this prompt)"
        rows.append(row)
    return rows


def run_jobs(pdir: Path, jobs_file: Path, *, only: list[str] | None = None, missing: bool = False, yes: bool = False,
             refs: list[str] | None = None, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    from ..job import write_progress
    from .images import _public_row, _ref_arg as ref_flag, _refs_note, load_jobs
    rows = plan_jobs(pdir, load_jobs(pdir, jobs_file), only, missing, refs=refs)
    todo = [r for r in rows if not r["skip"]]
    n_img = sum(r["need"] for r in todo)
    try:
        rel = Path(jobs_file).resolve().relative_to(Path(pdir).resolve()).as_posix()
    except ValueError:
        rel = str(jobs_file)
    flags = (f" --only {','.join(only)}" if only else "") + (" --missing" if missing else "")         + "".join(f" --ref {shlex.quote(ref_flag(pdir, r))}" for r in refs or [])
    again = _pcmd(pdir, f"gen image --provider codex --jobs {rel}{flags}")
    head = [f"  {r['plate']:<24} " + (f"skip: {r['skip']}" if r["skip"] else f"{r['need']} image(s) {r['aspect']}"
                                      + _refs_note(r) + (f" ({r['done']} already made)" if r["done"] else ""))
            for r in rows]
    anchored = sorted({r["plate"] for r in todo if r.get("anchor")})
    if anchored:
        head.append(f"  lead anchor: {len(anchored)} plate(s) attach the approved lead image (codex exec -i) with the "
                    f"text canon: {', '.join(anchored[:10])}" + (" …" if len(anchored) > 10 else ""))
    base = {"provider": PROVIDER, "jobs_file": rel, "planned_images": n_img, "est_usd": 0.0,
            "jobs": [_public_row(r) for r in rows], **({"anchored": anchored} if anchored else {})}
    if not todo:
        return {**base, "ok": True, "dry_run": not yes, "made": [], "failed": [],
                "text": "nothing to do: every job already has its images on the plan.\n" + "\n".join(head)}
    if not yes:
        return {**base, "ok": True, "dry_run": True, "made": [], "failed": [],
                "text": f"DRY RUN - nothing was generated. {n_img} image(s) on the ChatGPT plan via Codex: $0, about "
                        f"{n_img}-{4 * n_img} min in all (1-4 min each), and they count against the plan's image "
                        "limits.\n" + "\n".join(head) + f"\nAfter the owner's OK, run: {again} --yes"}
    check_login()
    made, failed, stop, streak, k = [], [], None, 0, 0
    for r in todo:
        for _ in range(r["need"]):
            if stop:
                break
            write_progress(done=k, total=n_img, msg=f"codex image {k + 1}/{n_img}: {r['plate']}")
            try:
                g = generate_one(pdir, prompt=r["prompt"], aspect=r["aspect"], refs=r.get("ref_src") or None,
                                 out_dir=pdir / "plates" / "cands" / r["plate"], timeout=timeout,
                                 meta={"job": r["plate"], "jobs_file": rel})
                made.append(g["file"])
                streak = 0
            except CodexImageError as e:
                failed.append({"plate": r["plate"], "kind": e.kind, "error": str(e)[:300]})
                streak += 1
                if e.kind in ("limit", "auth") or streak >= 2:
                    stop = f"{r['plate']}: {e}"
            k += 1
    write_progress(done=k, total=n_img, msg="done", final=True)
    lines = [f"made {len(made)} of {n_img} image(s) on the ChatGPT plan ($0)"] + \
            [f"  {Path(f).parent.name}/{Path(f).name}" for f in made] + \
            [f"  {x['plate']}: {x['kind']}: {x['error'][:160]}" for x in failed]
    ok = not failed
    if stop:
        lines.append(f"STOPPED: {stop[:300]}. Fix that, then re-run (made images are skipped): {again} --yes")
    elif failed:
        lines.append(f"re-run to retry the failed ones (made images are skipped): {again} --yes")
    else:
        lines.append(f"next: {_pcmd(pdir, 'plates sheet')}, then the owner picks")
    out = {**base, "ok": ok, "dry_run": False, "made": made, "failed": failed, "stopped": stop, "cost_usd": 0.0,
           "text": "\n".join(lines)}
    if not ok:
        out["error"] = lines[0] + (f"; stopped: {stop[:200]}" if stop else f"; {len(failed)} failed")
    return out


# ------------------------------------------------------------------------------------------------- the CLI entry
def _abs(pdir: Path, s: str | None) -> str | None:
    """An input path as an absolute path (found from the current folder first, else inside the project), so the
    background job finds it whatever its working folder."""
    if not s:
        return s
    p = util.input_path(pdir, s)
    return str(Path(p).resolve()) if p is not None else s


def _job_words(a, pdir: Path) -> list[str]:
    w = ["gen", "image"]
    if a.prompt:
        if a.prompt.startswith("-"):
            raise SlopError("a prompt that starts with '-' cannot be passed on the command line: put it in a file and "
                            "use --prompt-file FILE")
        w.append(a.prompt)
    if a.prompt_file:
        w += ["--prompt-file", _abs(pdir, a.prompt_file)]
    if a.jobs:
        w += ["--jobs", _abs(pdir, a.jobs)]
    for o in a.only or []:
        w += ["--only", o]
    if a.missing:
        w.append("--missing")
    if a.plate:
        w += ["--plate", a.plate]
    if a.out:
        w += ["--out", a.out]
    w += ["--aspect-ratio", a.aspect_ratio or "16:9", "--n", str(a.n)]
    for r in a.ref or []:
        w += ["--ref", _ref_arg(pdir, r)]
    if a.yes:
        w.append("--yes")
    return w + ["--provider", "codex"]


def _csv(vals) -> list[str]:
    out: list[str] = []
    for v in vals or []:
        out += [x.strip() for x in str(v).split(",") if x.strip()]
    return out


def cmd_image(a) -> dict:
    pdir = resolve_project(a.project)
    bad = [f for f, v in (("--model", a.model), ("--res", a.res), ("--quality", a.quality), ("--seed", a.seed))
           if v not in (None, "")]
    if bad:
        raise SlopError(f"{', '.join(bad)} do not apply to --provider codex (the plan's image tool chooses them): drop "
                        f"{'it' if len(bad) == 1 else 'them'}")
    if not 1 <= int(a.n or 1) <= MAX_N:
        raise SlopError(f"--n must be 1..{MAX_N} with --provider codex (each image takes 1-4 minutes)")
    only = _csv(a.only)
    if a.jobs:
        if a.prompt or a.prompt_file or a.plate or a.out or a.n != 1:
            raise SlopError("--jobs runs every job of the jobs file (each job has its own plate, prompt and n): drop the "
                            "prompt / --plate / --out / --n, or run one plate without --jobs")
        jobs_file = Path(_abs(pdir, a.jobs))
        if not a.yes or os.environ.get("SLOP_JOB_ID") or os.environ.get("SLOP_CODEX_IMAGE_FOREGROUND"):
            return run_jobs(pdir, jobs_file, only=only or None, missing=a.missing, yes=a.yes,
                            refs=[_ref_arg(pdir, r) for r in a.ref or []])
        from .images import load_jobs
        plan_jobs(pdir, load_jobs(pdir, jobs_file), only or None, a.missing,   # a missing/broken jobs file or a bad
                  refs=[_ref_arg(pdir, r) for r in a.ref or []])               # reference fails now, not in the job
    elif only or a.missing:
        raise SlopError("--only / --missing pick jobs from a jobs file: add --jobs (default plates/jobs.json)")
    else:
        if not (a.plate or a.out):
            raise SlopError("say where the image goes: --plate NAME (plates/cands/NAME/<k>.png) or --out FILE")
        if not (a.prompt or a.prompt_file):
            raise SlopError("give the prompt: as text or with --prompt-file FILE")
        ref_files(pdir, [_ref_arg(pdir, r) for r in a.ref or []])   # a bad reference fails now, not in the job
    if not (os.environ.get("SLOP_JOB_ID") or os.environ.get("SLOP_CODEX_IMAGE_FOREGROUND")):
        check_login()                                   # fail now, not inside the job
        from .. import job
        r = job.start(_job_words(a, pdir), project=str(pdir))
        s = r["job"]
        n = "the batch" if a.jobs else f"{a.n} image(s)"
        return {"ok": True, "provider": PROVIDER, "job": s, "id": s["id"], "existing": r["existing"], "next": s["wait"],
                "experimental": True,
                "text": f"{'already running' if r['existing'] else 'started'} job {s['id']}: {n} on the ChatGPT plan "
                        f"via Codex ($0; 1-4 min per image; EXPERIMENTAL: not yet checked with a real plan - if it "
                        f"fails, --provider openrouter makes the stills). Next: {s['wait']}"}
    if a.jobs:
        return run_jobs(pdir, Path(_abs(pdir, a.jobs)), only=only or None, missing=a.missing, yes=True,
                        refs=[_ref_arg(pdir, r) for r in a.ref or []])
    pf = _abs(pdir, a.prompt_file) if a.prompt_file else None
    if pf and not Path(pf).is_file():
        raise SlopError(f"prompt file not found: {a.prompt_file}")
    prompt = Path(pf).read_text(encoding="utf-8") if pf else a.prompt
    out = None
    if a.out:
        out = Path(a.out) if Path(a.out).is_absolute() else pdir / a.out
    out_dir = (pdir / "plates" / "cands" / a.plate) if a.plate else None
    timeout = float(os.environ.get("SLOP_CODEX_IMAGE_TIMEOUT") or DEFAULT_TIMEOUT_S)
    return generate(pdir, prompt=prompt, n=int(a.n or 1), aspect=a.aspect_ratio,
                    refs=[_ref_arg(pdir, r) for r in a.ref or []], out_dir=out_dir, out=out, timeout=timeout)


def describe_cmd(pdir: Path, plate: str, prompt: str) -> str:
    """The command line a skill shows (one plate, one image)."""
    return _pcmd(pdir, f"gen image --provider codex --plate {shlex.quote(plate)} {shlex.quote(prompt)}")

