# Changelog

Each release is a tag `vX.Y.Z`. A bot on an older release reminds its person once ("say update"); `slop update apply`
installs it and prints the newest entries below.

## 0.3.0
- Wake-ups: Grok hears the moment Opus (or Codex) posts, even after its own turn ended. Grok sets up a small wake-up routine once (its key goes in a secure card); the relay calls it when there is news and Grok is not already waiting.

## 0.2.9
- Always the newest: no model or version is hard-coded. The toolkit picks the newest model of each family, Midjourney prompts never carry `--v` (its default is its newest), and Grok uses the newest model each site offers.
- Midjourney's Raw, HD and personalization are your choices (Opus asks once per project; defaults Raw on, personalization on, HD off). Personalization goes on with the P button, never as a code in a prompt.
- Suno: Grok follows the page as it is today (the Advanced tab; an instrumental is an empty lyrics box).
- Effort: Claude Code and Codex now think at xhigh by default; say "effort" to pick another level (the levels come from the engine itself). A level the engine does not take falls back to its default instead of failing.
- Updating never stops at local edits on the bot's computer: they are set aside (kept in git's stash) and the release goes on.
- Grok's wait for Opus holds its full time (a blip no longer ends it early), and Opus keeps its turn open while its own long steps run.

## 0.2.8
- Every browser task is Grok's: Opus sends Midjourney prompts and Suno songs to Grok, which runs them in its own signed-in browser and hands back the files. You only decide; you never paste, press Create or download.

## 0.2.7
- The home-GPU link is parked until it works from every bot (a relay is in the works); analysis runs on the bot's computer meanwhile.

## 0.2.6
- Updates: a quiet reminder once per new release, and "update" installs it in one step (code, install, brief, skills).

## 0.2.5
- The home GPU's tunnel counts as up only once Cloudflare registers it; when the network blocks port 7844 you get the real reason and direct mode, never a dead pairing line.
- Sung-clip audio hosting and the taste app use the same check.

## 0.2.4
- Claude Code and Codex both get the claudia.gallery MCP; Opus's brief now covers the home GPU.

## 0.2.3
- The welcome says what each subscription gets you (Claude Max 20x recommended), asks "Set me up?", then what you have or will get.

## 0.2.2
- A welcome first: what the bot is, its skills and what to subscribe to, before any sign-in.

## 0.2.1
- The director's scansion and assonance scorer; Opus scores every lyric draft.

## 0.2.0
- Claudia: Grok relays, Opus produces, claudia.gallery is the source of truth; Grok Imagine in Grok's own browser.
