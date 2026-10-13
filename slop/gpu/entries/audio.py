"""audio profile: stems (htdemucs), align (wav2vec2 CTC emissions), whisper (faster-whisper large-v3 word times).

The methods are the CPU modules' own (slop/audio/stems.py, slop/audio/align.py), moved to the GPU: the same
normalisation and apply_model(shifts=1, split=True, overlap=0.25) with the same seed for stems; the same 20 s chunks
with 0.1 s of right context for the emissions (the Viterbi and everything after it stay on the box). Only fp32 maths
(TF32 off), so GPU and CPU results agree to rounding.
The song arrives as FLAC (lossless, about half the bytes of the WAV) or WAV.
Stems go back as 24-bit FLAC (lossless to -144 dB, about half the bytes of float WAV over a home uplink) with a gain
per stem: a stem that peaks above full scale is scaled down before encoding and the box multiplies it back
(result.json "gains"), so nothing clips. `format: f32` sends float WAV instead.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

W2V_MODEL = "facebook/wav2vec2-large-960h-lv60-self"
DEMUCS_MODEL = "htdemucs"
WHISPER_REPO = "Systran/faster-whisper-large-v3"


def _read(path: Path, want_sr: int):
    import soundfile as sf
    y, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if sr != want_sr:
        raise RuntimeError(f"{path.name} is {sr} Hz; the box sends {want_sr} Hz")
    return y


def stems(in_dir: Path, out_dir: Path, params: dict, ctx) -> dict:
    import numpy as np
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    dev = ctx.torch_device()
    t = time.monotonic()
    model = ctx.model("htdemucs", lambda: get_model(DEMUCS_MODEL).eval())
    sr = int(model.samplerate)
    song = next(p for p in (in_dir / "song.flac", in_dir / "song.wav") if p.is_file())
    y = _read(song, sr)                                   # (n, ch)
    if y.shape[1] == 1:
        y = np.repeat(y, 2, axis=1)
    wav = torch.from_numpy(np.ascontiguousarray(y[:, :2].T))
    ref = wav.mean(0)
    mu, sd = ref.mean(), ref.std() + 1e-9
    wn = (wav - mu) / sd
    t_load = time.monotonic() - t
    random.seed(params["seed"])
    torch.manual_seed(params["seed"])
    with torch.no_grad():
        src = apply_model(model, wn[None], shifts=params["shifts"], split=True, overlap=params["overlap"],
                          progress=False, device=dev)[0]
    if ctx.device == "cuda":
        torch.cuda.synchronize()
    src = (src * sd + mu).cpu().numpy().astype(np.float32)
    t_sep = time.monotonic() - t - t_load
    gains, files = {}, {}
    for name, s in zip(model.sources, src):
        if params["format"] == "f32":
            fn = f"{name}.wav"
            sf.write(str(out_dir / fn), s.T, sr, subtype="FLOAT")
            gains[name] = 1.0
        else:
            peak = float(np.max(np.abs(s))) if s.size else 0.0
            g = 1.0 if peak <= 0.999 else 0.999 / peak
            fn = f"{name}.flac"
            sf.write(str(out_dir / fn), (s * g).T, sr, subtype="PCM_24", format="FLAC")
            gains[name] = g
        files[name] = fn
    return {"model": DEMUCS_MODEL, "sources": list(model.sources), "samplerate": sr, "format": params["format"],
            "files": files, "gains": gains, "load_s": round(t_load, 2), "separate_s": round(t_sep, 2),
            "frames": int(src.shape[-1])}


def align(in_dir: Path, out_dir: Path, params: dict, ctx) -> dict:
    import numpy as np
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    dev = ctx.torch_device()
    t = time.monotonic()
    proc = ctx.model("w2v-proc", lambda: Wav2Vec2Processor.from_pretrained(W2V_MODEL), to_device=False)
    am = ctx.model("w2v", lambda: Wav2Vec2ForCTC.from_pretrained(W2V_MODEL).eval())
    t_load = time.monotonic() - t
    voc = _read(in_dir / "vocals16k.wav", 16000)[:, 0]
    step = 16000 * int(params["chunk_s"])
    ctx_n = int(round(16000 * float(params["context_s"])))
    emis = []
    with torch.inference_mode():
        for i in range(0, len(voc), step):
            chunk = voc[i:i + step + ctx_n]
            if len(chunk) < 800:
                chunk = np.pad(chunk, (0, 800 - len(chunk)))
            iv = proc(chunk, sampling_rate=16000, return_tensors="pt").input_values.to(dev)
            lp = torch.log_softmax(am(iv).logits[0].float(), -1).cpu().numpy()
            keep = int(round(len(voc[i:i + step]) / 16000 * 50))
            emis.append(lp[:keep])
    E = np.concatenate(emis).astype(np.float32) if emis else np.zeros((0, 32), np.float32)
    np.savez_compressed(str(out_dir / "w2v.npz"), E=E)
    vocab = dict(proc.tokenizer.get_vocab())
    (out_dir / "vocab.json").write_text(json.dumps(vocab), encoding="utf-8")
    return {"model": W2V_MODEL, "frames": int(len(E)), "load_s": round(t_load, 2),
            "emissions_s": round(time.monotonic() - t - t_load, 2)}


def _cuda_dlls_on_path() -> None:
    """Windows: CTranslate2 loads cuBLAS/cuDNN by name; torch's wheel ships both - put its lib folder on PATH."""
    if os.name != "nt":
        return
    try:
        import torch
        lib = Path(torch.__file__).parent / "lib"
        if lib.is_dir():
            os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(lib))
    except ImportError:
        pass


def _whisper_dir() -> str:
    from huggingface_hub import snapshot_download
    rev = None
    try:
        from slop.gpu.profiles import HF_REVISIONS
        rev = HF_REVISIONS.get(WHISPER_REPO)
    except ImportError:
        pass
    return snapshot_download(WHISPER_REPO, revision=rev)


def whisper(in_dir: Path, out_dir: Path, params: dict, ctx) -> dict:
    _cuda_dlls_on_path()
    import torch
    from faster_whisper import WhisperModel
    t = time.monotonic()
    if torch.cuda.is_available():
        ctx.device, device, compute = "cuda", "cuda", "float16"
    else:                                      # CTranslate2 has no MPS backend: Apple runs it on the CPU
        ctx.device, device, compute = "cpu", "cpu", "int8"
    model = WhisperModel(_whisper_dir(), device=device, compute_type=compute)
    t_load = time.monotonic() - t
    audio = _read(in_dir / "audio.wav", 16000)[:, 0]
    segs, info = model.transcribe(audio, language=params["language"] or None, beam_size=params["beam_size"],
                                  word_timestamps=True, vad_filter=params["vad"])
    words, segments = [], []
    for s in segs:
        segments.append({"t0": round(s.start, 3), "t1": round(s.end, 3), "text": s.text.strip()})
        for w in s.words or []:
            words.append({"w": w.word.strip(), "t0": round(w.start, 3), "t1": round(w.end, 3),
                          "p": round(float(w.probability), 3)})
    (out_dir / "words.json").write_text(json.dumps({"model": "faster-whisper-large-v3", "language": info.language,
                                                    "words": words, "segments": segments}, ensure_ascii=False),
                                        encoding="utf-8")
    return {"model": "faster-whisper-large-v3", "compute_type": compute, "language": info.language,
            "words": len(words), "load_s": round(t_load, 2), "transcribe_s": round(time.monotonic() - t - t_load, 2)}


def prewarm_after(name: str, ctx) -> None:
    """After stems, `slop analyze` aligns next: import transformers and load wav2vec2 (CPU memory) meanwhile."""
    if name == "stems":
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        ctx.model("w2v-proc", lambda: Wav2Vec2Processor.from_pretrained(W2V_MODEL), to_device=False)
        ctx.model("w2v", lambda: Wav2Vec2ForCTC.from_pretrained(W2V_MODEL).eval(), to_device=False)


def prefetch(ctx) -> None:
    """The weights analyze uses (htdemucs 84 MB, wav2vec2 1.26 GB); Whisper (3 GB) downloads on its first job."""
    from demucs.pretrained import get_model
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    get_model(DEMUCS_MODEL)
    Wav2Vec2Processor.from_pretrained(W2V_MODEL)
    Wav2Vec2ForCTC.from_pretrained(W2V_MODEL)
    print("[prefetch] audio weights ready", file=sys.stderr, flush=True)
