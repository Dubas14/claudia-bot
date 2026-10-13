"""slop.taste — taste capture -> tokens (module owner: taste; ARCHITECTURE.md §5).

What it does
  pool.py / arena.py   the user's own reference pool (folders, URL lists, their own or followed Are.na channels —
                       never a crawl: <= 30 req/min, <= 600 blocks)
  starter.py / synth.py  the generated 320-image starter deck (CC0, OFL fonts, anti-modes included) for a user with
                       no references yet, and the shared deterministic drawing code
  embed.py             SigLIP 2 base on CPU (Apache-2.0) or OpenRouter multimodal embeddings; per-image cache
  model.py / feed.py   the retired feed's Bayesian logistic + Bradley–Terry model on PCA-k of the vectors, kNN modes
                       term, Thompson-sampled cards, nested-CV held-out meter; 40-card stratified cold start,
                       scheduled self-agreement repeats, 1 pair in 7, 15 % explore
  server.py / static/  phone-first tap app (like/pass + swipe, pairs, undo, progress + meter) and the font A/B page,
                       stdlib http.server under a random token path; tunnel.py = Cloudflare quick tunnel
  tokens.py            taste-tokens.json + look-bible.md (suggestions and owner questions, never imposed theses),
                       mood boards with text-free --sref references (textfree.py: a per-pool ridge probe, the
                       user's own images vs lettered copies of them; zero-shot fallback for pools under 40 images)
  fonts.py             counterbalanced font A/B with a position-corrected Bradley–Terry ranking
  profile.py / store.py  one taste profile per USER ($SLOP_HOME/taste): every project links to it by default, so the
                       second song starts with the first song's taps, model and meter; `slop taste use --profile
                       project [--fork]` gives a project its own (a copy with --fork); `--profile user --merge` adopts
                       an older project's own taps
  sheet.py             the no-tunnel fallback: numbered pair sheets (JPEG <= 2 MB) the bot sends in the chat and
                       `slop taste record --sheet ID "1a 2b ..."` to ingest the reply as pair taps (one open sheet at
                       a time: a retry shows it again; several open -> record refuses without --sheet)
  verdicts.py          `slop taste verdict RULE confirmed|rejected [--value]`: owner verdicts in taste/verdicts.jsonl
                       (+ the user profile's copy, + DECISIONS.md); `slop taste tokens` honours them (value-bound, own
                       > carried); yes/no rules (texture, faces) are confirmed = yes / rejected = no; every owner
                       question prints the exact command for each answer
  apply.py             `slop taste apply [--yes]`: the owner-confirmed look.mode / accent / fonts + a short MJ / API
                       style tail (palette + one warm note + grain + finish; no light — that is per chapter; never
                       "monochrome") into project.json
  threads.py           caps the BLAS thread pool for the model's small solves (sheet / record / meter / fit / server)

Ported from the author's retired taste system (feed/server.py, feed/taste.py, feed/analyze.py, feed/embed.py,
feed/words.py, studio/engine/inspo.py, canon.py, compose.font_ratings, tools/arena/crawl.py) per research 05 and
11-gap-5. Intentional changes are listed in each file's docstring; the main ones:
  * base-size SigLIP 2 on CPU instead of so400m on a GPU (-2..3 points, inside the ±5 margin);
  * the PCA basis is fitted on the user's own pool, not a 90k crawl (research: a few hundred images suffice);
  * a k-means-stratified 40-card cold start replaces the reel-still seed cards; repeats are scheduled (4-6 by
    ~tap 135) instead of 4 % random, so self-agreement is measured from the first session;
  * pairs log `shown` (which side was first) and `layout`; the font A/B is counterbalanced and fitted with a
    first-slot term (the original composed A/B had a +0.86 logit first-slot bias);
  * Are.na is read only from the user's own/followed channels at <= 30 req/min (the retired crawl ran ~109 req/min
    without a token, which the current AUP forbids);
  * text-free references are judged by the embedder instead of EasyOCR CRAFT boxes: a per-pool paired probe (on
    real Midjourney images the zero-shot calibration kept 0 of 509 text-free images; the probe: AUC 0.995);
  * the stop rule never fires before the recommended 150 taps and compares smoothed meter readings;
  * no references at all -> a generated starter deck instead of a shipped / downloaded public-domain set;
  * tokens never choose the accent or the footage grade (the EV audit's "mono + red" thesis was overridden by the
    owner); they propose and ask.
Licences: SigLIP 2 weights Apache-2.0; fonts used by the A/B are OFL only (Nimbus Sans, Junicode, Pilcrow Rounded and
Alchimia are excluded by name); Are.na images are the user's references, kept privately, never re-hosted publicly.
Heavy imports (torch, transformers) are lazy: `slop --help` stays fast.
"""
