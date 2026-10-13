---
name: taste
description: Use when capturing or updating the owner's taste (the 7-minute tap session on their phone, pair sheets in chat, style frames, font A/B), when choosing a project's look, accent or fonts, or when the owner reacts to a look ("too gray", "more colour").
---

# Taste - taps, model, tokens, then a look the owner confirms

Read docs/30-taste.md §0 (the ten lessons) and §2 first. Taste is evidence, not orders: never impose a colour thesis or a grade on the footage; ask (§4). The taste profile belongs to the user and follows them to every project.

1. Interview (§2.1): one message, the must-ask questions first (accent colour; keep the generator's colour or one grade; faces shown or hidden), then texture, density, type, taboos. Record: `slop --json -p NAME decide '<their answers>' --by owner`.
2. Pool (§2.4), pick one:
   - their Are.na channel: `slop --json -p NAME taste pool add --arena SLUG --mine` (only channels they own or follow; ARENA_TOKEN only through the secure card);
   - their own images: `slop --json -p NAME taste pool add --dir DIR` (DIR = a full path);
   - nothing yet: `slop --json -p NAME taste pool add --starter`.
   Never crawl other people's channels.
3. Embed: `bash /workspace/claudia/bin/setup.sh --check --full --json` must say ok. Not yet: other work, then check again (the profile's turn rule); never serve or embed before it is ok (the fallback embedder would stick to the profile). Then `slop --json -p NAME job start -- taste embed --provider local` (wait: the profile's turn rule). `slop --json -p NAME taste status` shows an embed_model that is not siglip2: `slop --json -p NAME job start -- taste embed --provider local --reembed`.
4. Tap app, after step 3: `slop --json -p NAME taste serve --tunnel`. Send the https link: "About 7 minutes on your phone: tap like or pass, pick the better of each pair, about 150 taps. Tell me when you're done."
5. Done: `slop --json -p NAME taste status` (taps, the meter, the stop rule: at least 150, stop at 200).
   No tunnel (§2.4b): `slop --json -p NAME taste sheet`, send the sheets with the message it prints; the owner answers in one line; run the record command it printed, e.g. `slop --json -p NAME taste record --sheet ID '1a 2b 3t 4x'`.
6. Model: `slop --json -p NAME taste fit`, then `slop --json -p NAME taste meter`, then `slop --json -p NAME taste tokens`. Read taste/look-bible.md and ask its owner questions in one message (the evidence on both sides, a default).
7. Each answer: `slop --json -p NAME taste verdict RULE confirmed --note '<their words>'` (or rejected).
8. Style frames (§2.5, once plates exist): 3 frames that differ on the riskiest axes. "Rank 1-3 and say what's wrong with the others." Record: `slop --json -p NAME taste verdict style_frame confirmed --value 2 --note '<their words>'`.
9. Look: `slop --json -p NAME taste apply` (a preview), the owner's yes, then `slop --json -p NAME taste apply --yes`.
10. Fonts (§2.6, after a style frame): `slop --json -p NAME taste fonts --tunnel`, send the link, then `slop --json -p NAME taste fonts rank`. Only fonts the engine ships (OFL).
11. `slop --json -p NAME taste stop` closes the app and its tunnel.

Mood board for a shot or chapter: `slop --json -p NAME taste board '<what it should feel like>'`.
A look complaint later ("too gray"): stop spending first, ask which frame shows the problem, record a verdict, change the look only with taste apply after their yes.
