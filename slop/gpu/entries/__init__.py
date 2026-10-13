"""GPU entrypoints, one module per profile family (audio, matte, interp, lipsync). Each function has the signature
`fn(in_dir: Path, out_dir: Path, params: dict, ctx) -> dict` and writes only into out_dir. They run inside a profile
venv on the user's computer and import their heavy packages lazily."""
