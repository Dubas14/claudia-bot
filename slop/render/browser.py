"""Headless Chromium (Playwright) for the engine page: launch with SwiftShader, boot the page, grab frames.

Playwright is imported lazily (inside functions) so `slop --help` stays fast. apply_env() must run before
sync_playwright() starts the driver (PLAYWRIGHT_BROWSERS_PATH from $SLOP_HOME/env.sh is read by the driver, not by
launch()); frames._sync_playwright() does that for every command.
"""
from __future__ import annotations

import base64
import os
import re
import sys

from ..config import SlopError, slop_home

# software GL (no GPU on the box): ANGLE on SwiftShader; file access for the project's media
# --js-flags=--expose-gc: the engine's image cache (core.js dropCache) runs a GC after it drops images, so decoded plates
# are freed at once (V8 does not count Blink's image memory and would otherwise wait).
LAUNCH_ARGS = ["--no-sandbox", "--allow-file-access-from-files", "--use-gl=angle", "--use-angle=swiftshader",
               "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--js-flags=--expose-gc"]
BOOT_TIMEOUT_MS = 120_000
FRAME_TIMEOUT_MS = 180_000
_ENV_KEYS = re.compile(r"^(PLAYWRIGHT_[A-Z0-9_]+|SLOP_[A-Z0-9_]+)$")


def load_env_sh() -> None:
    """Pick up PLAYWRIGHT_* / SLOP_* exports from $SLOP_HOME/env.sh (written by bin/setup.sh); never overrides the env."""
    f = slop_home() / "env.sh"
    try:
        lines = f.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if not m or not _ENV_KEYS.match(m.group(1)):
            continue
        val = m.group(2).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        val = os.path.expandvars(val.replace("${HOME}", os.environ.get("HOME", "")))
        os.environ.setdefault(m.group(1), val)


def apply_env() -> None:
    """Make the browser settings visible to the Playwright DRIVER: it reads PLAYWRIGHT_BROWSERS_PATH when
    sync_playwright() starts, so this must run before that (frames._sync_playwright calls it). Reads $SLOP_HOME/env.sh,
    then defaults PLAYWRIGHT_BROWSERS_PATH to $SLOP_HOME/ms-playwright when bin/setup.sh installed Chromium there."""
    load_env_sh()
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        d = slop_home() / "ms-playwright"
        if d.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(d)


def launch(p):
    """Bundled Chromium first; then $SLOP_CHROME_PATH / $SLOP_BROWSER_CHANNEL; then the system Chrome.
    (The driver was started by sync_playwright(): PLAYWRIGHT_BROWSERS_PATH must already be set — apply_env().)"""
    load_env_sh()
    attempts: list[dict] = []
    if os.environ.get("SLOP_CHROME_PATH"):
        attempts.append({"executable_path": os.environ["SLOP_CHROME_PATH"]})
    if os.environ.get("SLOP_BROWSER_CHANNEL"):
        attempts.append({"channel": os.environ["SLOP_BROWSER_CHANNEL"]})
    attempts += [{}, {"channel": "chrome"}]
    errors = []
    for kw in attempts:
        try:
            return p.chromium.launch(args=LAUNCH_ARGS, **kw)
        except Exception as e:  # noqa: BLE001 — try the next browser
            errors.append(f"{kw or 'bundled chromium'}: {str(e).strip().splitlines()[0][:200]}")
    raise SlopError("could not start a browser — " + " | ".join(errors) +
                    ". Fix: run `python -m playwright install chromium` (or install google-chrome), then retry.")


def _race(expr: str, ms: int) -> str:
    """Wrap a page expression returning a promise with a timeout (evaluate itself never times out)."""
    return (f"(args) => Promise.race([({expr})(args), new Promise((_, rej) => setTimeout(() => "
            f"rej(new Error('timed out after {ms} ms')), {ms}))])")


class EnginePage:
    """One browser + one booted engine page. Use as a context manager, or call close()."""

    def __init__(self, p, spec: dict, verbose: bool = False):
        self.p, self.spec, self.verbose = p, spec, verbose
        self.errors: list[str] = []      # uncaught page exceptions
        self.console: list[str] = []     # console errors / warnings (bounded)
        self.browser = None
        self.page = None
        self._open()

    def _open(self) -> None:
        self.browser = launch(self.p)
        pg = self.browser.new_page(viewport={"width": int(self.spec["w"]), "height": int(self.spec["h"])})
        pg.on("console", self._on_console)
        pg.on("pageerror", lambda e: self.errors.append(str(e)[:500]))
        pg.add_init_script(self.spec["init"])
        pg.goto(self.spec["url"], wait_until="load", timeout=BOOT_TIMEOUT_MS)
        pg.evaluate(_race("() => window.booted || Promise.reject(new Error('the engine page did not boot (window.booted missing)'))",
                          BOOT_TIMEOUT_MS), None)
        self.page = pg

    def _on_console(self, m) -> None:
        if m.type in ("error", "warning") and len(self.console) < 200:
            txt = m.text[:400]
            self.console.append(f"{m.type}: {txt}")
            if self.verbose:
                print(f"[page] {txt}", file=sys.stderr)

    def reopen(self) -> None:
        self.close()
        self._open()

    def close(self) -> None:
        try:
            if self.browser:
                self.browser.close()
        except Exception:  # noqa: BLE001 — a crashed browser is already gone
            pass
        self.browser = self.page = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def info(self) -> dict:
        d = self.page.evaluate("() => Object.assign(ENGINE.info(), {missing: (window.SLOP || {}).missing || []})")
        d["page_errors"] = list(self.errors)
        d["console"] = list(self.console[:30])
        return d

    def frame_jpeg(self, t: float, q: float = .95) -> bytes:
        return self.frame_checked(t, q)[0]

    def frame_checked(self, t: float, q: float = .95) -> tuple[bytes, list[str]]:
        """(JPEG bytes, the required media this frame asked for and could not load — ENGINE.frameMissing)."""
        r = self.page.evaluate(_race("async ([t, q]) => { const u = await window.frame(t, q); "
                                     "return [u, (window.ENGINE && ENGINE.frameMissing) || []]; }", FRAME_TIMEOUT_MS),
                               [float(t), float(q)])
        url, missing = (r if isinstance(r, list) and len(r) == 2 else [None, []])
        if not isinstance(url, str) or "," not in url:
            raise RuntimeError(f"frame({t}) returned no image")
        return base64.b64decode(url.split(",", 1)[1]), list(missing or [])

    def check_media(self) -> list[dict]:
        """Decode every media file the film declares (ENGINE.checkMedia): [{src, why}] for the ones that fail."""
        return self.page.evaluate(_race("() => (window.ENGINE && ENGINE.checkMedia) ? ENGINE.checkMedia() : []",
                                        BOOT_TIMEOUT_MS), None) or []

    def drawn(self, t: float) -> list[str]:
        return self.page.evaluate(_race("([t]) => window.drawn(t)", FRAME_TIMEOUT_MS), [float(t)])

    def layers(self, t: float) -> dict | None:
        """Draw the frame at t (no JPEG) and return its information layers (ENGINE.frameLayers, core.js):
        {count, layers, rule, ok, shot, treatment, missingMedia}; None when the engine has no layer probe."""
        return self.page.evaluate(_race("async ([t]) => { if (window.DRAWN) window.DRAWN.clear(); await window.renderAt(t); "
                                        "return (window.ENGINE && ENGINE.frameLayers) ? ENGINE.frameLayers() : null; }",
                                        FRAME_TIMEOUT_MS), [float(t)])

    def scenes(self) -> list[dict]:
        """The page's scenes in time order: [{name, t0, t1, bespoke}] (storyboard shots, chapter scenes, gap fillers).
        bespoke: drawn by the project's own chapter code (the default renderer marks its scenes isDefault)."""
        return self.page.evaluate("() => { const E = window.ENGINE || {}, dflt = E.shotsRenderer === 'devices-v1'; "
                                  "return (E.scenes || []).map(s => ({name: s.name, t0: +s.t0, t1: +s.t1, "
                                  "bespoke: dflt && !s.isDefault})); }") or []

    def lyric_tokens(self) -> list[dict]:
        """Every sung token with the time the gate checks it at and its mark key (computed in JS: toFixed rounding)."""
        return self.page.evaluate("""() => (window.LYR || []).filter(l => (l.kind || 'lyric') === 'lyric').flatMap(l =>
            l.tokens.map((tk, i) => ({line: l.line, i, txt: tk.txt, t0: tk.t0, t1: tk.t1,
              t: tk.t0 + Math.min(.12, Math.max(.03, (tk.t1 - tk.t0) / 2)), key: (+tk.t0).toFixed(2)})))""")


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """(w, h) of a JPEG from its SOF marker (no decode)."""
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return w, h
        seg = int.from_bytes(data[i + 2:i + 4], "big")
        i += 2 + seg
    return None
