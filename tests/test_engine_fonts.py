"""engine/fonts: OFL faces only, every face listed in the manifest exists and has its licence text alongside."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1] / "engine"
FONTS = ENGINE / "fonts"
# families that must never be shipped (AGPL / GPL / Fontshare EULA / no licence)
BANNED = re.compile(r"nimbus|junicode|pilcrow|alchimia", re.I)


def manifest() -> dict:
    s = (FONTS / "fonts.js").read_text(encoding="utf-8")
    i = s.index("window.ENGINE_FONTS")
    return json.loads(s[s.index("=", i) + 1:].strip().rstrip(";"))


def test_manifest_faces_exist_with_ofl_licence():
    m = manifest()
    assert m["faces"], "no faces in fonts.js"
    for f in m["faces"]:
        assert (FONTS / f["file"]).is_file(), f"missing font file {f['file']}"
        lic = FONTS / "licenses" / f["licence"]
        assert lic.is_file(), f"missing licence text {lic.name} for {f['file']}"
        txt = lic.read_text(encoding="utf-8")
        assert "SIL Open Font License" in txt and "Version 1.1" in txt, f"{lic.name} is not the OFL 1.1 text"


def test_roles_point_at_bundled_families():
    m = manifest()
    fams = {f["family"] for f in m["faces"]}
    for role, fam in m["roles"].items():
        assert fam in fams, f"role {role} uses {fam!r}, which is not bundled"
    assert m["roles"]["grotesk"] in ("Space Grotesk", "Geist", "Inter Tight"), "the lyric face must be an OFL grotesk"


def test_every_font_file_is_listed_and_none_is_banned():
    files = [p for p in FONTS.rglob("*") if p.suffix.lower() in (".ttf", ".otf", ".woff", ".woff2")]
    listed = {f["file"] for f in manifest()["faces"]}
    for p in files:
        assert not BANNED.search(p.name), f"banned font shipped: {p.name}"
        assert p.name in listed, f"{p.name} is not in fonts.js (unlisted fonts are not licence-checked)"
    for p in (ENGINE / "src").rglob("*.js"):
        txt = p.read_text(encoding="utf-8")
        hits = [m.group(0) for m in re.finditer(r'"(Nimbus Sans|Junicode|Pilcrow Rounded|Alchimia)"', txt)]
        assert not hits, f"{p.name} still references a banned face: {hits}"


def test_name_tables_say_ofl():
    fontTools = pytest.importorskip("fontTools.ttLib")
    for f in manifest()["faces"]:
        t = fontTools.TTFont(str(FONTS / f["file"]), lazy=True)
        name = t["name"]
        lic = " ".join(filter(None, [name.getDebugName(13), name.getDebugName(14)])) or ""
        assert re.search(r"open font licen[cs]e|\bOFL\b|scripts\.sil\.org|openfontlicense", lic, re.I), f"{f['file']}: licence field {lic[:80]!r}"
