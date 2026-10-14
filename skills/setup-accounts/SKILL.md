---
name: setup-accounts
description: Use when setting up or fixing an account the videos use - the OpenRouter key and its spend limit, the Higgsfield or Google Drive connector, the Suno plan and sign-in, the Midjourney plan, personal profile code and sign-in, an Are.na token - or when a key is rejected or expired.
---

# Accounts - keys, connectors, Suno, Midjourney, Are.na

Each account is one item of `slop --json onboard next` (skill claudia-setup); run it again after each step. You never see, type or store a secret: keys only through the masked secure secret card (it reaches new shells as an environment variable), sign-ins only by the person, in their browser or on the connector's card. Never write an account address, a key or a sign-in code into a note or a file.

## OpenRouter key (item openrouter; API stills, clips, Lyria; docs/51-plates-api.md §2.1)
1. Say: "Make a NEW key at openrouter.ai/settings/keys with its own credit limit a little above one video's budget (Quick $25, Studio $110, Director $160). That limit is your hard cap, whatever happens here. Credits: openrouter.ai/settings/credits."
2. Ask with the masked secure secret card named OPENROUTER_API_KEY.
3. `slop --json onboard next` checks it for free. Still "not set" right after the card: a new shell sees it: `bash -lc '/workspace/claudia/bin/slop --json onboard next'`. Rejected or expired: a new key on the card; a key pasted in chat: ask the person to revoke it and make a new one.
4. Later: `slop --json -p NAME spend` shows the usage and the key's limit.
5. No key and no Higgsfield wanted: `slop --json onboard mark openrouter --skip`; Opus then makes stills and motion clips with Grok Imagine and the person's own song file (no sung lip-sync clips, no Lyria).

## Higgsfield connector (item higgsfield; sung clips, images and video on their credits)
1. SearchPlugins for Higgsfield. Connected: call its `balance`. It answers: `slop --json onboard mark higgsfield --connected`.
2. Missing and wanted: a question widget "Add the Higgsfield connector? (video and images with your Higgsfield credits)". Install it only after a yes, in the next turn; the person signs in on its card; then `balance` and the mark command.
3. An auth error later: ask the person to reconnect it. Their spend: `balance` and `transactions`.

## Google Drive (item drive; optional, bulk import)
SearchPlugins for Google Drive; missing and wanted: the same widget rule. List one folder; it answers: `slop --json onboard mark drive --connected`. Drive moves one file per call: for many files ask for one zip share link, then `slop --json -p NAME fetch 'LINK' --to uploads`.

## Suno (items suno, suno-signin; docs/10-song.md §8)
1. The plan: `slop --json onboard set suno-plan pro` (free, pro, premier or none). Free: songs are non-commercial; offer Lyria (needs OpenRouter) or an upgrade. None: Lyria, or their own song file.
2. Suno has no API and its terms forbid bots: the person presses Create and downloads the WAV themselves (a paid plan is what allows commercial use). Opus writes the lyric and the style fields; you show them as copy blocks (a relay job of kind person). So: `slop --json onboard mark suno-signin --skip`.

## Midjourney (items midjourney, mj-profile, mj-signin; docs/50-plates-midjourney.md §2.1 and §2.2)
1. The plan: `slop --json onboard set mj-plan standard` (basic, standard, pro, mega or none); it sizes each paste.
2. Their personal profile code (their look; never anyone else's): they make a profile as §2.2 says (Personalize, a V8 profile, one test prompt; the code shows on the job). Record it: `slop --json onboard set mj-profile CODE`. It stays in their user settings; never post it. Per project: `slop --json -p NAME onboard apply`. No profile yet: plates look generic; say so once and offer to wait.
3. The person pastes Opus's prompt blocks into Midjourney and downloads the picks; you never automate it: `slop --json onboard mark mj-signin --skip`.

## Are.na (item arena; optional; docs/30-taste.md §2.4)
Only if they keep their own channels there (for the taste pool). They create a personal access token on Are.na's developer page (dev.are.na); ask with the masked secure secret card named ARENA_TOKEN; `slop --json onboard next` sees it.

## Agents, skipping
- Claude Code, Codex (ChatGPT plan), Muse Code, Gemini CLI, ChatGPT-plan images: skill setup-agents.
- Not now: `slop --json onboard mark ID --skip`; later `slop --json onboard mark ID --todo`. Every account can come later: the person says "setup".
- What is left: `slop --json onboard status`.
