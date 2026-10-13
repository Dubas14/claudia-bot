// fonts.js — the engine's bundled faces. Every file here is SIL Open Font License 1.1; the licence texts are in
// fonts/licenses/ (one per family, kept next to the fonts wherever they are copied). Never add Nimbus Sans (AGPL),
// Junicode 0.6 (GPL), Pilcrow Rounded (Fontshare EULA) or Alchimia (no licence): tests/test_engine_fonts.py fails on them.
// "roles" are the type tokens the engine draws with (chrome.js F.*); project.json look.fonts {lyric, micro, display}
// overrides lyric (F.grotesk), micro (F.mono) and display (F.display). The body after "=" is strict JSON (Python reads it).
window.ENGINE_FONTS = {
 "roles": {
  "display": "Barlow Condensed", "grotesk": "Space Grotesk", "mono": "IBM Plex Mono", "tech": "Share Tech Mono",
  "serif": "Instrument Serif", "serif2": "Instrument Serif", "wide": "Audiowide", "lava": "Pilowlava",
  "sign": "DINish Condensed", "signW": "DINish", "code": "JetBrains Mono", "alt": "Geist"
 },
 "faces": [
  {"family": "Barlow Condensed", "file": "BarlowCondensed-Light.ttf", "weight": "300", "style": "normal", "licence": "BarlowCondensed-OFL.txt"},
  {"family": "Barlow Condensed", "file": "BarlowCondensed-Regular.ttf", "weight": "400", "style": "normal", "licence": "BarlowCondensed-OFL.txt"},
  {"family": "Barlow Condensed", "file": "BarlowCondensed-Medium.ttf", "weight": "500", "style": "normal", "licence": "BarlowCondensed-OFL.txt"},
  {"family": "Barlow Condensed", "file": "BarlowCondensed-SemiBold.ttf", "weight": "600", "style": "normal", "licence": "BarlowCondensed-OFL.txt"},
  {"family": "Space Grotesk", "file": "SpaceGrotesk-Variable.ttf", "weight": "300 700", "style": "normal", "licence": "SpaceGrotesk-OFL.txt"},
  {"family": "Geist", "file": "Geist-Variable.ttf", "weight": "100 900", "style": "normal", "licence": "Geist-OFL.txt"},
  {"family": "IBM Plex Mono", "file": "IBMPlexMono-Regular.ttf", "weight": "400", "style": "normal", "licence": "IBMPlexMono-OFL.txt"},
  {"family": "IBM Plex Mono", "file": "IBMPlexMono-Medium.ttf", "weight": "500", "style": "normal", "licence": "IBMPlexMono-OFL.txt"},
  {"family": "Share Tech Mono", "file": "ShareTechMono-Regular.ttf", "weight": "400", "style": "normal", "licence": "ShareTechMono-OFL.txt"},
  {"family": "Instrument Serif", "file": "InstrumentSerif-Regular.ttf", "weight": "400", "style": "normal", "licence": "InstrumentSerif-OFL.txt"},
  {"family": "Instrument Serif", "file": "InstrumentSerif-Italic.ttf", "weight": "400", "style": "italic", "licence": "InstrumentSerif-OFL.txt"},
  {"family": "Audiowide", "file": "Audiowide-Regular.ttf", "weight": "400", "style": "normal", "licence": "Audiowide-OFL.txt"},
  {"family": "Pilowlava", "file": "Pilowlava-Regular.otf", "weight": "400", "style": "normal", "licence": "Pilowlava-OFL.txt"},
  {"family": "DINish", "file": "DINish-Bold.ttf", "weight": "700", "style": "normal", "licence": "DINish-OFL.txt"},
  {"family": "DINish Condensed", "file": "DINishCondensed-Medium.ttf", "weight": "500", "style": "normal", "licence": "DINish-OFL.txt"},
  {"family": "DINish Condensed", "file": "DINishCondensed-Bold.ttf", "weight": "700", "style": "normal", "licence": "DINish-OFL.txt"},
  {"family": "DINish Condensed", "file": "DINishCondensed-Black.ttf", "weight": "900", "style": "normal", "licence": "DINish-OFL.txt"},
  {"family": "JetBrains Mono", "file": "JetBrainsMono-Regular.ttf", "weight": "400", "style": "normal", "licence": "JetBrainsMono-OFL.txt"},
  {"family": "JetBrains Mono", "file": "JetBrainsMono-Medium.ttf", "weight": "500", "style": "normal", "licence": "JetBrainsMono-OFL.txt"},
  {"family": "JetBrains Mono", "file": "JetBrainsMono-Bold.ttf", "weight": "700", "style": "normal", "licence": "JetBrainsMono-OFL.txt"}
 ]
};
