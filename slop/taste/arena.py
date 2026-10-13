"""Are.na reader for the reference pool — the user's OWN or FOLLOWED channels only.

Compliance (research 11-gap-5 §6.4-6.5, 09 §3.11): Are.na's Acceptable Use Policy and Terms forbid scraping,
crawling and mass downloading. The retired 90k-image crawl (v2, no token, ~109 req/min) must not be repeated. This
module therefore:
  * reads only channels the user owns, collaborates on, or follows (verified through `GET /v3/me` +
    `/v3/users/{id}/following` when ARENA_TOKEN is set: owner id, the `collaborators` list or the followed set —
    `can.add_to` / `can.update` are not enough, since anyone signed in can add to an open channel; without a
    token, or for a channel the checks cannot see, the user must confirm with --mine);
  * keeps API calls at <= 30 requests/minute whatever the tier (the guest limit; a quarter of the Free limit),
    honours X-RateLimit-Remaining/Reset and 429 Retry-After (a Retry-After over 120 s stops with "wait and re-run");
  * stops at 600 image blocks per pool (a ~600-block pool is ~6 API pages at per=100);
  * stores {block id, channel, title, source URL, image URL} plus a <= 1024 px copy for embedding and the
    private tap app; it never re-hosts images publicly. Re-sync happens only when the user asks.
API: v3 (current; `GET /v3/channels/{slug}/contents?per=100&page=N` -> {data[], meta.has_more_pages}); falls back to
stable v2 (`/v2/channels/{slug}/contents`) when v3 errors. Image URL: v3 image.medium.src (1200 px) else image.src;
v2 image.large.url / display.url / original.url. Only Image blocks are kept (as the crawler did).
`ARENA_TOKEN` = an Are.na personal access token (read scope), entered via the bot's secure secret card.
"""
from __future__ import annotations

import json
import os
import time

from ..config import SlopError
from . import net

API = "https://api.are.na"
MAX_BLOCKS = 600
REQ_PER_MIN = 30
MIN_INTERVAL = 60.0 / REQ_PER_MIN   # 2.0 s between API calls
PER = 100
MAX_RETRIES = 4
MAX_RETRY_AFTER = 120.0             # a longer Retry-After is reported (wait and re-run), never slept through silently


class ArenaClient:
    def __init__(self, token: str | None = None, sleep=time.sleep, clock=time.monotonic):
        self.token = (token if token is not None else os.environ.get("ARENA_TOKEN", "")).strip() or None
        self.sleep = sleep
        self.clock = clock
        self._last = None
        self.calls = 0

    # ---------------------------------------------------------------- transport
    def _pace(self) -> None:
        if self._last is not None:
            wait = self._last + MIN_INTERVAL - self.clock()
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()

    def get(self, path: str, params: dict | None = None) -> tuple[int, dict]:
        """-> (status, json). Retries 429/5xx with backoff; never more than REQ_PER_MIN calls a minute."""
        q = "&".join(f"{k}={v}" for k, v in (params or {}).items())
        url = API + path + (("?" + q) if q else "")
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        for attempt in range(MAX_RETRIES):
            self._pace()
            self.calls += 1
            try:
                status, h, body = net.http_get(url, headers=headers, timeout=30)
            except OSError as e:
                if attempt == MAX_RETRIES - 1:
                    raise SlopError(f"cannot reach api.are.na ({e}); check the network and re-run") from e
                self.sleep(min(60, 2 ** (attempt + 1)))
                continue
            remaining = h.get("x-ratelimit-remaining")
            if remaining is not None and str(remaining).strip() == "0":
                self.sleep(self._reset_wait(h))
            if status == 429:
                ra = h.get("retry-after")
                wait = float(ra) if ra and str(ra).replace(".", "", 1).isdigit() else self._reset_wait(h)
                if wait > MAX_RETRY_AFTER:
                    raise SlopError(f"Are.na asked to wait {wait:.0f} s before the next request (rate limit). Wait "
                                    "that long, then re-run the same command (it resumes; images already added are "
                                    "kept)")
                self.sleep(wait)
                continue
            if status >= 500:
                self.sleep(min(60, 2 ** (attempt + 1)))
                continue
            try:
                data = json.loads(body.decode("utf-8")) if body else {}
            except ValueError:
                data = {}
            return status, data
        raise SlopError(f"Are.na kept refusing {path} (rate limit or server error); wait a minute and re-run")

    def _reset_wait(self, h: dict) -> float:
        reset = h.get("x-ratelimit-reset")
        try:
            r = float(reset)
            wait = r - time.time() if r > 1e9 else r      # epoch seconds or seconds-from-now
        except (TypeError, ValueError):
            wait = 60.0
        return max(1.0, min(65.0, wait))

    # ---------------------------------------------------------------- identity / permission
    def me(self) -> dict:
        if not self.token:
            raise SlopError("this needs ARENA_TOKEN (an Are.na personal access token, read scope): ask the user "
                            "for it with the secure secret card, then re-run")
        st, d = self.get("/v3/me")
        if st in (401, 403):
            raise SlopError("ARENA_TOKEN was rejected by Are.na (401/403): ask the user for a fresh personal "
                            "access token from are.na/settings/personal-access-tokens")
        if st != 200 or not d.get("id"):
            raise SlopError(f"Are.na /v3/me answered HTTP {st}; re-run later")
        return d

    def followed_channels(self, me_id, max_pages: int = 6) -> set[str]:
        out: set[str] = set()
        for page in range(1, max_pages + 1):
            st, d = self.get(f"/v3/users/{me_id}/following", {"per": PER, "page": page})
            if st != 200:
                break
            for x in d.get("data") or d.get("following") or []:
                if (x.get("type") or x.get("base_class") or x.get("class")) == "Channel" and x.get("slug"):
                    out.add(x["slug"])
            if not (d.get("meta") or {}).get("has_more_pages"):
                break
        return out

    def channel(self, slug: str) -> dict:
        st, d = self.get(f"/v3/channels/{slug}")
        if st == 200 and d:
            return d
        if st in (401, 403, 404):
            raise SlopError(f"Are.na channel '{slug}' was not found or is private (HTTP {st}). Use the slug from "
                            "the channel URL (are.na/<user>/<slug>); private channels need ARENA_TOKEN")
        st2, d2 = self.get(f"/v2/channels/{slug}")
        if st2 == 200 and d2:
            return d2
        raise SlopError(f"Are.na channel '{slug}' could not be read (HTTP {st}/{st2}); re-run later")

    def check_allowed(self, ch: dict, me: dict | None, followed: set[str] | None, confirm_own: bool) -> str:
        """-> why it is allowed ("owner" | "collaborator" | "followed" | "user-confirmed"), or raise"""
        slug = ch.get("slug", "?")
        if me is not None:
            owner = ch.get("owner") or ch.get("user") or {}
            if owner.get("id") == me.get("id") and (owner.get("type") in (None, "User")):
                return "owner"
            if ch.get("user_id") is not None and ch.get("user_id") == me.get("id"):
                return "owner"
            if any(c.get("id") == me.get("id") for c in (ch.get("collaborators") or []) if isinstance(c, dict)):
                return "collaborator"
            # `can.add_to` / `can.update` are NOT ownership: any signed-in user may add to an open channel
            if followed is not None and slug in followed:
                return "followed"
            if confirm_own:
                return "user-confirmed"
            raise SlopError(f"Are.na channel '{slug}' is neither yours nor one you follow. Are.na's terms forbid "
                            "crawling other people's channels: follow it on are.na first if you want it in your "
                            "taste pool, or add your own channels")
        if confirm_own:
            return "user-confirmed"
        raise SlopError(f"cannot verify that '{slug}' is the user's own or followed channel without ARENA_TOKEN. "
                        "Ask the user: if it is theirs (or one they follow), re-run with --mine; or set ARENA_TOKEN")

    # ---------------------------------------------------------------- contents
    def channel_blocks(self, slug: str, limit: int):
        """yield normalised image blocks {id, title, image_url, source_url, channel} in channel order"""
        n = 0
        page = 1
        use_v2 = False
        while n < limit:
            if not use_v2:
                st, d = self.get(f"/v3/channels/{slug}/contents", {"per": PER, "page": page})
                if st != 200:
                    if page == 1:
                        use_v2 = True
                        continue
                    break
                blocks = d.get("data") or []
                more = bool((d.get("meta") or {}).get("has_more_pages"))
            else:
                st, d = self.get(f"/v2/channels/{slug}/contents", {"per": PER, "page": page})
                if st != 200:
                    raise SlopError(f"Are.na channel '{slug}' contents answered HTTP {st}; re-run later")
                blocks = d.get("contents") or []
                more = len(blocks) >= PER
            for b in blocks:
                nb = normalize_block(b, slug)
                if nb is None:
                    continue
                yield nb
                n += 1
                if n >= limit:
                    return
            if not blocks or not more:
                return
            page += 1

    def user_blocks(self, me_id, limit: int):
        """the user's own image blocks (all their channels), newest first"""
        n, page = 0, 1
        while n < limit:
            st, d = self.get(f"/v3/users/{me_id}/contents", {"per": PER, "page": page, "type": "Image"})
            if st != 200:
                raise SlopError(f"Are.na /v3/users/{me_id}/contents answered HTTP {st}; re-run later")
            blocks = d.get("data") or []
            for b in blocks:
                nb = normalize_block(b, "@me")
                if nb:
                    yield nb
                    n += 1
                    if n >= limit:
                        return
            if not blocks or not (d.get("meta") or {}).get("has_more_pages"):
                return
            page += 1


def normalize_block(b: dict, channel: str) -> dict | None:
    kind = b.get("type") or b.get("class") or b.get("base_class")
    if kind != "Image":
        return None
    img = b.get("image") or {}
    url = None
    for key in ("medium", "large"):                       # v3 resized variants (medium = 1200 px)
        e = img.get(key) or {}
        if isinstance(e, dict) and (e.get("src") or e.get("url")):
            url = e.get("src") or e.get("url")
            break
    if not url:
        url = img.get("src")                              # v3 original
    if not url:
        for key in ("display", "original"):               # v2
            e = img.get(key) or {}
            if isinstance(e, dict) and e.get("url"):
                url = e["url"]
                break
    if not url or b.get("id") is None:
        return None
    src = b.get("source") or {}
    return {"id": b["id"], "title": (b.get("title") or b.get("generated_title") or "")[:200],
            "image_url": url, "source_url": src.get("url") if isinstance(src, dict) else None, "channel": channel}


def add_arena(writer, targets: list[str], confirm_own: bool = False, limit: int = MAX_BLOCKS,
              client: ArenaClient | None = None, sleep=time.sleep) -> dict:
    """pull image blocks from the given channels into the pool (PoolWriter). targets: channel slugs, '@me' (the
    user's own blocks) or '@following' (every channel they follow); the last two need ARENA_TOKEN"""
    from .pool import DOWNLOAD_INTERVAL, download
    cl = client or ArenaClient(sleep=sleep)
    have = sum(1 for it in writer.items.values() if it.get("src") == "arena")
    budget = max(0, min(limit, MAX_BLOCKS) - have)
    report = {"channels": [], "api_calls": 0, "cap": MAX_BLOCKS, "arena_in_pool_before": have}
    if budget <= 0:
        report["note"] = f"the pool already holds {have} Are.na blocks (cap {MAX_BLOCKS}); nothing fetched"
        return report
    me = cl.me() if cl.token else None
    followed = cl.followed_channels(me["id"]) if me is not None else None
    expanded: list[str] = []
    for t in targets:
        t = t.strip().strip("/")
        if "are.na/" in t:                                # a pasted URL: are.na/<user>/<slug>
            t = t.rstrip("/").split("/")[-1]
        if t == "@following":
            if me is None:
                cl.me()                                   # raises the "needs ARENA_TOKEN" error
            expanded += sorted(followed or [])
        elif t:
            expanded.append(t)
    first_dl = True
    for t in expanded:
        if budget <= 0:
            break
        if t == "@me":
            if me is None:
                cl.me()
            blocks, why, slug = cl.user_blocks(me["id"], budget), "owner", "@me"
        else:
            ch = cl.channel(t)
            why = cl.check_allowed(ch, me, followed, confirm_own)
            slug = ch.get("slug") or t
            blocks = cl.channel_blocks(slug, budget)
        got = 0
        for b in blocks:
            iid = f"arena-{b['id']}"
            if writer.known_id(iid):
                writer.stats["duplicate"] += 1
                continue
            if not first_dl:
                sleep(DOWNLOAD_INTERVAL)
            first_dl = False
            data = download(b["image_url"], writer.stats)
            if data is None:
                continue
            if writer.add(data, {"src": "arena", "origin": f"are.na/block/{b['id']}", "title": b["title"],
                                 "source_url": b.get("source_url"), "channel": b["channel"], "block_id": b["id"],
                                 "image_url": b["image_url"]}, iid=iid):
                got += 1
                budget -= 1
                if budget <= 0:
                    break
        report["channels"].append({"channel": slug, "allowed_as": why, "added": got})
    report["api_calls"] = cl.calls
    return report
