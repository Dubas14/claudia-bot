"""slop.board — storyboard (draft, write, audit, contact sheet) and plates (prompt book, ingest, pick, vary, boxes).

Commands: `slop board draft|set|fill|device add|rm|list|kinds|audit|sheet|approve` and
`slop plates book|ingest (files or --url)|sheet|pick|vary|status|box`.
The engine's vocabulary (devices, treatments, transitions, fonts) is read from the engine's own files by
`vocab.py` and `devices.py`, so the board tools never drift from what draws.
The edit side (EDL, engine export, look/LUT grade, fonts) lives in `slop.edit`.
"""
