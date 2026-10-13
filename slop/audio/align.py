"""Forced alignment of the lyric sheet to the vocal stem on CPU: wav2vec2 CTC posteriors + our own Viterbi.

Port of the GPU analyze script's alignment part, same method and constants:
  - model facebook/wav2vec2-large-960h-lv60-self (Apache-2.0; pytorch_model.bin 1.26 GB, loaded by transformers with
    torch weights_only; downloaded once into $HF_HOME);
  - vocal stem at 16 kHz mono, emissions in 20 s chunks with 0.1 s right context, 20 ms frames;
  - greedy CTC transcript ("what was actually sung") -> analysis/transcript.json (ad-lib hunting);
  - CTC Viterbi over the expanded sequence (blank, c1, blank, c2, ...): stay / advance / skip-blank transitions, the path
    ends in the last char or the final blank; per word t0 = first owned frame x 0.02, t1 = (last + 1) x 0.02,
    confidence = exp(mean log-posterior over its frames).
Changes: the sheet is linted first - digits, symbols and letter-less lines are an ERROR (the aligner can only spell A-Z
and ', so "01" or "+25%" silently vanish and their audio gets absorbed by the neighbouring words: EV's CPU replay put
three words 3.2-3.6 s early that way); accents are folded (é -> e) and curly apostrophes straightened; emissions are
cached per vocal stem (analysis/cache/w2v.npz) so re-aligning an edited sheet takes seconds; an impossible fit (sheet
longer than the audio can hold) is an explicit error instead of garbage times.
CPU cost for a 306 s song (T 15k frames x L 4.2k states; first run downloads the 1.26 GB model):
  - this module's benchmark (tests/bench_audio_ev.py, 32 threads shared with other jobs): emissions 29 s + Viterbi 1.3 s,
    2.65 GB peak RSS for the whole analyze;
  - research 11-gap-3 section 3 (8 pinned desktop threads): 7.9 s of emissions per 60 s excerpt (~40 s for the song);
  - the 8-vCPU box: estimated 1-2 min (1.5-2.5x the 8-thread figure).
GPU route: `slop analyze --gpu auto|require` computes the emissions on the user's paired home GPU when `slop gpu
status` is healthy (_emissions_on_gpu); the Viterbi stays here. Otherwise the CPU, with a note.
"""
from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path

import numpy as np

from slop.config import SlopError

from .common import Paths, fingerprint, hf_home_default, load_mono, need_module, read_json, write_json
from .pron import SYMBOL_WORDS, num_words, spell_numbers

MODEL_ID = "facebook/wav2vec2-large-960h-lv60-self"
FRAME = 0.02                      # 20 ms per CTC frame
_WORD = re.compile(r"[A-Za-z0-9']+")


# ---------------------------------------------------------------- the sheet
def fold(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def read_sheet(path: Path) -> list[str]:
    """Lyric lines: every non-empty line not starting with '[' (section tags such as [Verse 1: spoken] are skipped)."""
    if not Path(path).exists():
        raise SlopError(f"no {path}. Write the sung lyrics there: one line per lyric line, section tags in [brackets], "
                        "every number/symbol spelled the way it is sung (\"twenty five percent\", \"A G I\").")
    from slop.util import read_lyric_lines
    return read_lyric_lines(path)


def split_words(line: str) -> list[str]:
    """The sung words of a line as the aligner counts them (display tokens' n counts these)."""
    out = []
    for w in _WORD.findall(fold(line)):
        if re.search(r"[A-Za-z]", w):
            out.append(w)
    return out


def sheet_words(lines: list[str]) -> list[dict]:
    words = []
    for li, ln in enumerate(lines):
        for w in split_words(ln):
            words.append({"w": w, "line": li})
    return words


def lint_sheet(lines: list[str]) -> list[dict]:
    """Problems that break alignment (level 'error') or often do ('warn'). Each has a suggested fix."""
    out = []
    for li, ln in enumerate(lines):
        f = fold(ln)
        if not re.search(r"[A-Za-z]", f):
            out.append({"line": li, "level": "error", "text": ln,
                        "msg": "line has no letters - the aligner cannot place it; write it as sung",
                        "fix": spell_numbers(f)})
            continue
        if re.search(r"\d", f):
            nums = re.findall(r"\d+(?:[.,]\d+)?", f)
            out.append({"line": li, "level": "error", "text": ln,
                        "msg": "digits are not aligned: write numbers as sung (" +
                               ", ".join(f"{d} -> {num_words(d.replace(',', ''))}" for d in nums) + ")",
                        "fix": spell_numbers(f)})
        syms = sorted({c for c in f if c in SYMBOL_WORDS})
        if syms:
            out.append({"line": li, "level": "error", "text": ln,
                        "msg": "symbols are not aligned: write them as sung (" +
                               ", ".join(f"{c} -> {SYMBOL_WORDS[c]}" for c in syms) + ")",
                        "fix": spell_numbers(f)})
        for a in re.findall(r"\b[A-Z]{2,6}\b", f):
            if a not in ("I", "OK") and not _is_shout(f):
                out.append({"line": li, "level": "warn", "text": ln,
                            "msg": f"'{a}': if it is sung letter by letter, write '{' '.join(a)}'; "
                                   "if sung as a word, write it in lower case", "fix": None})
    return out


def _is_shout(line: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", line)
    return len(letters) > 8 and letters.upper() == letters


def check_sheet(lines: list[str], allow_digits: bool = False) -> list[dict]:
    problems = lint_sheet(lines)
    errs = [p for p in problems if p["level"] == "error"]
    if errs and not allow_digits:
        msg = "; ".join(f"line {p['line'] + 1} \"{p['text']}\": {p['msg']}" + (f" -> try \"{p['fix']}\"" if p["fix"] else "")
                        for p in errs[:8])
        more = f" (+{len(errs) - 8} more)" if len(errs) > 8 else ""
        raise SlopError(f"lyrics/lyrics.txt must be spelled as sung before alignment: {msg}{more}. Fix the sheet "
                        "(the on-screen spelling goes in lyrics/display.txt as 'TEXT|n' tokens) and re-run.")
    return problems


# ---------------------------------------------------------------- emissions (wav2vec2, CPU)
_MODEL_CACHE: dict = {}


def load_model():
    if "m" not in _MODEL_CACHE:
        hf_home_default()
        need_module("torch", "alignment runs wav2vec2 on torch (CPU)")
        need_module("transformers", "alignment uses transformers' Wav2Vec2ForCTC")
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        try:
            proc = Wav2Vec2Processor.from_pretrained(MODEL_ID)
            am = Wav2Vec2ForCTC.from_pretrained(MODEL_ID).eval()
        except Exception as e:
            raise SlopError(f"could not load {MODEL_ID} ({type(e).__name__}: {e}). It downloads once (1.26 GB) from "
                            "huggingface.co into $HF_HOME; check the network and disk space, then re-run.")
        _MODEL_CACHE["m"] = (proc, am)
    return _MODEL_CACHE["m"]


def compute_emissions(vocals: Path) -> tuple[np.ndarray, dict]:
    """(E [T, V] log-posteriors at 50 fps, vocab {char: id})."""
    gpu = _emissions_on_gpu(vocals)        # routing hook (--gpu auto|require): the user's paired home GPU
    if gpu is not None:
        return gpu
    import torch
    proc, am = load_model()
    voc = load_mono(vocals, 16000)
    emis = []
    step = 16000 * 20
    with torch.inference_mode():
        for i in range(0, len(voc), step):
            chunk = voc[i:i + step + 1600]
            if len(chunk) < 800:
                chunk = np.pad(chunk, (0, 800 - len(chunk)))
            iv = proc(chunk, sampling_rate=16000, return_tensors="pt").input_values
            lp = torch.log_softmax(am(iv).logits[0], -1).cpu().numpy()
            keep = int(round(len(voc[i:i + step]) / 16000 * 50))
            emis.append(lp[:keep])
    E = np.concatenate(emis).astype(np.float32) if emis else np.zeros((0, 32), np.float32)
    return E, dict(proc.tokenizer.get_vocab())


def _emissions_on_gpu(vocals: Path) -> tuple[np.ndarray, dict] | None:
    """The same emissions on the user's paired home GPU (slop/gpu: the vocal stem is resampled to 16 kHz HERE, with
    the CPU path's own loader, and the GPU runs the same 20 s chunks with 0.1 s of context in fp32). The Viterbi and
    everything after it stay on the box. None = the CPU path runs (--gpu off, or no healthy GPU / a failed GPU job in
    auto mode; the router adds a note)."""
    from slop.gpu import route
    if not route.plan("audio.align", "align"):
        return None
    import json
    import tempfile
    from .common import write_audio
    with tempfile.TemporaryDirectory(prefix="slop-w2v-") as td:
        p = Path(td) / "vocals16k.wav"
        write_audio(p, load_mono(vocals, 16000), 16000, codec="pcm_f32le")
        r = route.execute("audio.align", {"vocals16k.wav": p}, {}, label="align")
    if r is None:
        return None
    try:
        with np.load(r.file("w2v.npz")) as z:
            E = z["E"].astype(np.float32)
        vocab = json.loads(r.file("vocab.json").read_text(encoding="utf-8"))
    except (SlopError, OSError, ValueError, KeyError) as e:
        if route.mode() == "require":
            raise SlopError(f"align: the GPU result was unusable ({e})") from None
        route.note(f"align: the GPU result was unusable ({e}) - ran on the CPU instead")
        return None
    return E, vocab


def emissions(paths: Paths, force: bool = False) -> tuple[np.ndarray, dict, bool]:
    """Cached emissions for the current vocal stem -> (E, vocab, from_cache)."""
    voc = paths.stem("vocals")
    if not voc.exists():
        raise SlopError("no audio/stems/vocals.wav - run `slop analyze --steps stems` first")
    key = f"{MODEL_ID}|{fingerprint(voc)}"
    cp = paths.cache / "w2v.npz"
    meta = read_json(paths.cache / "w2v.json", {}) or {}
    if not force and cp.exists() and meta.get("key") == key:
        with np.load(cp) as z:
            return z["E"], meta["vocab"], True
    E, vocab = compute_emissions(voc)
    paths.cache.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cp, E=E)
    write_json(paths.cache / "w2v.json", {"key": key, "model": MODEL_ID, "frames": int(len(E)), "vocab": vocab})
    return E, vocab, False


# ---------------------------------------------------------------- greedy transcript
def greedy_transcript(E: np.ndarray, vocab: dict) -> list[dict]:
    inv = {v: k for k, v in vocab.items()}
    blank = vocab.get("<pad>", 0)
    am_ = E.argmax(1)
    tw, cur, t0w, prev = [], "", None, -1
    for t, k in enumerate(am_):
        if k != prev and k != blank:
            ch = inv.get(int(k), "")
            if ch == "|":
                if cur:
                    tw.append({"w": cur, "t0": round(t0w * FRAME, 2), "t1": round(t * FRAME, 2)})
                    cur, t0w = "", None
            elif len(ch) == 1:
                if not cur:
                    t0w = t
                cur += ch
        prev = k
    if cur:
        tw.append({"w": cur, "t0": round(t0w * FRAME, 2), "t1": round(len(am_) * FRAME, 2)})
    return tw


# ---------------------------------------------------------------- CTC Viterbi (own, no compiled aligner)
def viterbi_align(E: np.ndarray, vocab: dict, lines: list[str]) -> list[dict]:
    """-> [{w, line, t0, t1, score}] (t0/t1 None when a word owns no frame)."""
    blank = vocab.get("<pad>", 0)
    space = vocab.get("|")
    words, toks, owner = [], [], []
    for li, ln in enumerate(lines):
        for w in split_words(ln):
            wc = re.sub(r"[^A-Z']", "", fold(w).upper())
            if not re.search("[A-Z]", wc):
                continue
            if toks and space is not None:
                toks.append(space)
                owner.append(-1)
            words.append({"w": w, "line": li})
            for ch in wc:
                if ch in vocab:
                    toks.append(vocab[ch])
                    owner.append(len(words) - 1)
    T = len(E)
    if not words:
        raise SlopError("the lyric sheet has no words to align: write the sung lyrics in lyrics/lyrics.txt (one line per "
                        "lyric line, words as sung; [section] lines and notes are ignored), then run "
                        "`slop analyze --steps align`")
    ext, eo = [blank], [-1]
    for t_, o_ in zip(toks, owner):
        ext += [t_, blank]
        eo += [o_, -1]
    L = len(ext)
    if T < (L - 1) // 2 + 1:
        raise SlopError(f"the lyric sheet has more characters ({len(toks)}) than the vocal stem can hold ({T} frames): "
                        "wrong lyrics file, or wrong song?")
    NEG = np.float32(-1e9)
    ext_a = np.array(ext)
    dp = np.full((T, L), NEG, np.float32)
    bp = np.zeros((T, L), np.int8)
    dp[0, 0] = E[0, ext[0]]
    if L > 1:
        dp[0, 1] = E[0, ext[1]]
    allow = np.array([ext[s] != blank and s >= 2 and ext[s] != ext[s - 2] for s in range(L)])
    cols = np.arange(L)
    for t in range(1, T):
        prev = dp[t - 1]
        b = np.concatenate([[NEG], prev[:-1]])
        c = np.concatenate([[NEG, NEG], prev[:-2]])
        c = np.where(allow, c, NEG)
        stack = np.vstack([prev, b, c])
        arg = stack.argmax(0)
        dp[t] = stack[arg, cols] + E[t, ext_a]
        bp[t] = arg
    s = L - 1 if L < 2 or dp[-1, L - 1] > dp[-1, L - 2] else L - 2
    if dp[-1, s] < NEG / 2:
        raise SlopError("alignment failed: no path through the sheet fits the audio (is this the right song?)")
    path = np.zeros(T, int)
    for t in range(T - 1, -1, -1):
        path[t] = s
        s -= int(bp[t, s])
    first, last, sc = {}, {}, {}
    for t in range(T):
        o = eo[path[t]]
        if o >= 0:
            first.setdefault(o, t)
            last[o] = t
            sc.setdefault(o, []).append(float(E[t, ext[path[t]]]))
    for i, w in enumerate(words):
        if i in first:
            w["t0"] = round(first[i] * FRAME, 3)
            w["t1"] = round((last[i] + 1) * FRAME, 3)
            w["score"] = round(float(np.exp(np.mean(sc[i]))), 3)
        else:
            w["t0"] = w["t1"] = None
            w["score"] = 0.0
    return words


def align(paths: Paths, lines: list[str], force: bool = False) -> dict:
    t = time.monotonic()
    E, vocab, cached = emissions(paths, force=force)
    t_em = time.monotonic() - t
    tw = greedy_transcript(E, vocab)
    write_json(paths.analysis / "transcript.json", tw)
    t = time.monotonic()
    words = viterbi_align(E, vocab, lines)
    t_vit = time.monotonic() - t
    write_json(paths.cache / "words-w2v.json", {"lines": lines, "words": words})
    sc = [w["score"] for w in words]
    return {"words": words, "transcript_words": len(tw), "emissions_s": round(t_em, 2), "emissions_cached": cached,
            "viterbi_s": round(t_vit, 2), "mean_conf": round(float(np.mean(sc)), 3) if sc else 0.0,
            "conf_ge_05": round(float(np.mean([s >= 0.5 for s in sc])), 3) if sc else 0.0}
