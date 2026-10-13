"""slop.taste.pool + slop.taste.arena: normalisation, dedupe, URL lists, Are.na compliance (all HTTP mocked)."""
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "taste"))
import taste_synth as S  # noqa: E402

from slop.config import SlopError  # noqa: E402
from slop.taste import arena as A  # noqa: E402
from slop.taste import net  # noqa: E402
from slop.taste import pool as P  # noqa: E402


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    return S.make_project(tmp_path)


def jpeg(kind="grey", seed=0, size=(1600, 900)) -> bytes:
    b = io.BytesIO()
    S.image(kind, seed, size).save(b, "JPEG")
    return b.getvalue()


def test_normalize_resizes_and_rejects_small():
    im, data = P.normalize(jpeg(size=(2000, 1000)))
    assert max(im.size) == 1024 and im.mode == "RGB"
    assert Image.open(io.BytesIO(data)).format == "JPEG"
    with pytest.raises(ValueError):
        P.normalize(jpeg(size=(200, 150)))
    with pytest.raises(ValueError):
        P.normalize(b"not an image")


def test_add_dir_is_idempotent_and_dedupes(proj, tmp_path):
    d = tmp_path / "refs"
    S.write_images(d, {"grey": 4, "red": 3, "colour": 3})
    Image.open(d / "grey-000.png").save(d / "copy-of-grey.jpg", quality=95)     # a re-encode: near-duplicate
    w = P.PoolWriter(proj)
    P.add_dir(w, d)
    assert w.stats["added"] == 10 and w.stats["duplicate"] + w.stats["near_duplicate"] == 1
    items = P.load_pool(proj)
    assert len(items) == 10
    it = next(iter(items.values()))
    assert set(it) >= {"id", "kind", "src", "w", "h", "sha1", "dhash"} and it["kind"] == "human"
    assert P.image_path(proj, it).exists()
    w2 = P.PoolWriter(proj)
    P.add_dir(w2, d)
    assert w2.stats["added"] == 0 and len(P.load_pool(proj)) == 10
    with pytest.raises(SlopError):
        P.add_dir(w2, tmp_path / "missing")


def test_add_urls_with_mocked_http(proj, tmp_path, monkeypatch):
    f = tmp_path / "links.txt"
    f.write_text("# my saves\nhttps://example.org/a.jpg\nhttps://example.org/b.jpg\nftp://nope\nhttps://example.org/404.jpg\n")
    bodies = {"https://example.org/a.jpg": jpeg("red", 1), "https://example.org/b.jpg": jpeg("blue", 2)}

    def fake_get(url, headers=None, timeout=30):
        return (200, {}, bodies[url]) if url in bodies else (404, {}, b"")
    monkeypatch.setattr(net, "http_get", fake_get)
    w = P.PoolWriter(proj, "generated")
    P.add_urls(w, f, sleep=lambda s: None)
    assert w.stats["added"] == 2 and w.stats["skipped"] == 1
    assert any("not an http" in e for e in w.stats["errors"])
    assert {it["kind"] for it in P.load_pool(proj).values()} == {"generated"}


def test_project_keys():
    assert P.project_keys("https://www.behance.net/gallery/12345/Some-Project") [0] == "behance:12345"
    assert "ig:AbC_1" in P.project_keys("https://instagram.com/p/AbC_1/")
    assert P.project_keys(None) == []


# ---------------------------------------------------------------- Are.na (mocked)

class FakeArena:
    """routes api.are.na v3 paths; records every call and the clock at which it happened"""

    def __init__(self, owner_id=7, me_id=7, followed=("followed-chan",), n_blocks=250, token_ok=True, can=None):
        self.can = can or {}
        self.calls = []
        self.t = 0.0
        self.owner_id, self.me_id, self.followed, self.n_blocks, self.token_ok = owner_id, me_id, followed, n_blocks, token_ok
        self.img = jpeg("grey", 5, (800, 600))

    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def get(self, url, headers=None, timeout=30):
        if "cloudfront" in url or "images.are.na" in url:
            bid = int(url.rsplit("/", 1)[-1].split(".")[0])
            return 200, {}, jpeg("grey" if bid % 2 else "dark", bid, (400, 320))
        self.calls.append((self.t, url))
        path = url.split("api.are.na", 1)[1]
        if path.startswith("/v3/me"):
            return (200, {}, json.dumps({"id": self.me_id, "slug": "me"}).encode()) if self.token_ok else (401, {}, b"{}")
        if "/following" in path:
            data = [{"type": "Channel", "slug": s} for s in self.followed] + [{"type": "User", "slug": "someone"}]
            return 200, {}, json.dumps({"data": data, "meta": {"has_more_pages": False}}).encode()
        if "/contents" in path:
            page = int(path.split("page=")[1].split("&")[0])
            per = 100
            ids = list(range((page - 1) * per, min(page * per, self.n_blocks)))
            data = [{"id": 1000 + i, "type": "Image", "title": f"b{i}",
                     "image": {"src": f"https://d.cloudfront.net/{1000 + i}.jpg",
                               "medium": {"src": f"https://images.are.na/{1000 + i}.jpg"}},
                     "source": {"url": f"https://example.org/p/{i}"}} for i in ids]
            data.append({"id": 9, "type": "Text", "title": "a note"})
            return 200, {}, json.dumps({"data": data, "meta": {"has_more_pages": page * per < self.n_blocks}}).encode()
        if path.startswith("/v3/channels/"):
            slug = path.split("/v3/channels/")[1].split("?")[0]
            return 200, {}, json.dumps({"id": 1, "slug": slug, "owner": {"id": self.owner_id, "type": "User"},
                                        "collaborators": [], "can": self.can}).encode()
        return 404, {}, b"{}"


def client(fa, token):
    return A.ArenaClient(token=token, sleep=fa.sleep, clock=fa.clock)


def test_arena_own_channel_with_token_paced_at_30_per_minute(proj, monkeypatch):
    fa = FakeArena(owner_id=7, me_id=7, n_blocks=250)
    monkeypatch.setattr(net, "http_get", fa.get)
    w = P.PoolWriter(proj)
    rep = A.add_arena(w, ["https://www.are.na/me/my-chan"], client=client(fa, "tok"), sleep=fa.sleep, limit=600)
    assert rep["channels"][0]["allowed_as"] == "owner" and rep["channels"][0]["added"] == 250
    times = [t for t, _ in fa.calls]
    assert all(b - a >= A.MIN_INTERVAL - 1e-9 for a, b in zip(times, times[1:]))   # <= 30 API calls / minute
    assert all("/v3/" in u for _, u in fa.calls)
    items = P.load_pool(proj)
    it = items["arena-1000"]
    assert it["src"] == "arena" and it["block_id"] == "1000" and it["channel"] == "my-chan"
    assert it["image_url"].startswith("https://images.are.na/")                     # the medium (1200 px) variant


def test_arena_cap_600_blocks(proj, monkeypatch):
    fa = FakeArena(n_blocks=900)
    monkeypatch.setattr(net, "http_get", fa.get)
    w = P.PoolWriter(proj)
    rep = A.add_arena(w, ["big-chan"], client=client(fa, "tok"), sleep=fa.sleep, limit=5000)
    assert sum(c["added"] for c in rep["channels"]) == 600
    rep2 = A.add_arena(P.PoolWriter(proj), ["big-chan"], client=client(fa, "tok"), sleep=fa.sleep)
    assert "cap" in rep2.get("note", "")


def test_arena_refuses_other_peoples_channels(proj, monkeypatch):
    fa = FakeArena(owner_id=99, me_id=7, followed=("followed-chan",))
    monkeypatch.setattr(net, "http_get", fa.get)
    with pytest.raises(SlopError, match="neither yours nor one you follow"):
        A.add_arena(P.PoolWriter(proj), ["someone-elses"], client=client(fa, "tok"), sleep=fa.sleep)
    rep = A.add_arena(P.PoolWriter(proj), ["followed-chan"], client=client(fa, "tok"), sleep=fa.sleep, limit=5)
    assert rep["channels"][0]["allowed_as"] == "followed"


def test_arena_without_token_needs_user_confirmation(proj, monkeypatch):
    fa = FakeArena()
    monkeypatch.setattr(net, "http_get", fa.get)
    monkeypatch.delenv("ARENA_TOKEN", raising=False)
    with pytest.raises(SlopError, match="--mine"):
        A.add_arena(P.PoolWriter(proj), ["my-chan"], client=client(fa, None), sleep=fa.sleep)
    rep = A.add_arena(P.PoolWriter(proj), ["my-chan"], confirm_own=True, client=client(fa, None), sleep=fa.sleep, limit=3)
    assert rep["channels"][0]["allowed_as"] == "user-confirmed" and rep["channels"][0]["added"] == 3
    with pytest.raises(SlopError, match="ARENA_TOKEN"):
        A.add_arena(P.PoolWriter(proj), ["@following"], client=client(fa, None), sleep=fa.sleep)


def test_arena_429_retry_after_and_bad_token(monkeypatch):
    seq = [(429, {"retry-after": "7"}, b"{}"), (200, {"x-ratelimit-remaining": "5"}, b'{"ok": 1}')]
    slept = []
    monkeypatch.setattr(net, "http_get", lambda url, headers=None, timeout=30: seq.pop(0))
    cl = A.ArenaClient(token="t", sleep=slept.append, clock=lambda: 0.0)
    st, d = cl.get("/v3/channels/x")
    assert st == 200 and d == {"ok": 1} and 7.0 in slept
    fa = FakeArena(token_ok=False)
    monkeypatch.setattr(net, "http_get", fa.get)
    with pytest.raises(SlopError, match="rejected"):
        client(fa, "bad").me()


def test_normalize_block_v2_and_v3():
    v3 = {"id": 1, "type": "Image", "image": {"src": "o.jpg", "medium": {"src": "m.jpg"}}, "source": {"url": "s"}}
    v2 = {"id": 2, "class": "Image", "image": {"display": {"url": "d.jpg"}, "original": {"url": "o.jpg"}}}
    assert A.normalize_block(v3, "c")["image_url"] == "m.jpg"
    assert A.normalize_block(v2, "c")["image_url"] == "d.jpg"
    assert A.normalize_block({"id": 3, "type": "Link"}, "c") is None


def test_arena_open_channel_permissions_are_not_ownership(proj, monkeypatch):
    # an open public channel: any signed-in user "can add_to" (and the API may say "update") — still not theirs
    fa = FakeArena(owner_id=99, me_id=7, followed=(), can={"add_to": True, "update": True})
    monkeypatch.setattr(net, "http_get", fa.get)
    with pytest.raises(SlopError, match="neither yours nor one you follow"):
        A.add_arena(P.PoolWriter(proj), ["open-chan"], client=client(fa, "tok"), sleep=fa.sleep)
    rep = A.add_arena(P.PoolWriter(proj), ["open-chan"], confirm_own=True, client=client(fa, "tok"), sleep=fa.sleep,
                      limit=2)
    assert rep["channels"][0]["allowed_as"] == "user-confirmed"


def test_arena_long_retry_after_stops_with_wait_and_rerun(monkeypatch):
    monkeypatch.setattr(net, "http_get", lambda url, headers=None, timeout=30: (429, {"retry-after": "3600"}, b"{}"))
    slept = []
    cl = A.ArenaClient(token="t", sleep=slept.append, clock=lambda: 0.0)
    with pytest.raises(SlopError, match="wait.*re-run"):
        cl.get("/v3/channels/x")
    assert not any(x >= 3600 for x in slept)


def test_dir_and_url_items_record_their_source_group(proj, tmp_path, monkeypatch):
    S.write_images(tmp_path / "refs" / "neon", {"colour": 2})
    S.write_images(tmp_path / "refs", {"grey": 1})
    P.add_dir(P.PoolWriter(proj), tmp_path / "refs")
    groups = sorted(it["group"] for it in P.load_pool(proj).values())
    assert groups == ["dir:refs", "dir:refs/neon", "dir:refs/neon"]
    f = tmp_path / "links.txt"
    f.write_text("https://cdn.example.org/a.jpg\n", encoding="utf-8")
    monkeypatch.setattr(net, "http_get", lambda url, headers=None, timeout=45: (200, {}, jpeg("red", 3)))
    P.add_urls(P.PoolWriter(proj), f, sleep=lambda s: None)
    assert any(it.get("group") == "url:cdn.example.org" for it in P.load_pool(proj).values())


def test_starter_deck_is_stratified_idempotent_and_composed(proj, monkeypatch):
    from slop.taste import starter as ST
    assert len(ST.TEMPLATES) * ST.PER_TEMPLATE == 320
    monkeypatch.setattr(ST, "PER_TEMPLATE", 2)                       # a 32-image deck keeps the test fast
    w = P.PoolWriter(proj)
    rep = ST.add_starter(w, limit=len(ST.TEMPLATES))                  # a --max prefix is stratified: 1 per template
    items = P.load_pool(proj)
    assert {it["group"] for it in items.values()} == {f"starter:{n}" for n, _ in ST.TEMPLATES}
    assert all(it["kind"] == "composed" and it["src"] == "starter" for it in items.values())
    assert set(ST.ANTI_MODES) <= {n for n, _ in ST.TEMPLATES} and rep["deck_size"] == 32
    ST.add_starter(P.PoolWriter(proj))                                # the rest of the deck
    n_full = len(P.load_pool(proj))
    assert n_full >= 30                                               # (a near-duplicate swatch may be dropped)
    w3 = P.PoolWriter(proj)
    ST.add_starter(w3)                                                # re-run: nothing new
    assert w3.stats["added"] == 0 and len(P.load_pool(proj)) == n_full
    assert ST.render("neon-flyer", 3).tobytes() == ST.render("neon-flyer", 3).tobytes()   # deterministic
