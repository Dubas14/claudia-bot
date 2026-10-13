# Seedance 2.5 prompts: sung, motion and screenplay (verbatim, scrubbed)

Video prompts from the reference videos, with what each was conditioned on and why it worked. The method (reference mode,
the exact song window as `@Audio1`, quoting exactly the words in the window, measuring sync by audio, covers) is in
`60-clips.md` and `61-lipsync.md`; moderation-safe wording is in `62-moderation.md`.

Two generations of prompt are shown. EV's were short and physical and suited a deadpan fashion show. SP's first round used
the same recipe for a narrative video and **failed** ("these prompts are really really bad and wasting money and need to
be 10x better and super context aware of the story"); its second round — the screenplay grammar — produced the cut the
user called "perfect". A later Studio-tier run measured what that cost the lips: long screenplays on sung windows
re-sang the line instead of copying the vocal. **The defaults: sung windows (lip sync) and their covers take the short
sung form (§1); motion clips and acting moments take the screenplay grammar (§3).** Screenplay for acting and motion,
short for copy.

---

## 1. Sung windows: the short sung form (`@Image1` = plate as reference, `@Audio1` = the vocal window)

**The template** (`60-clips.md` §4.0; `slop clip new SHOT --kind sung` drafts it):

```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "<every word in the window>".
<Framing> of the woman from @Image1 (<canon tags>), <how she sings the words>. <Light>. <Camera>.
[<a.aa s (the sound)>: <one small action>.]
[<b.bb s (the sound)>: <one small action>.]
One continuous shot, no cuts, no head turns. Only she sings. No text, letters or logos.
```

The head quotes every word; one line of framing and light; at most 2 timed beats (often none); the closer. About 90
words or fewer besides the lyric (`slop clip lock` warns past that, or past 2 beats). Her mouth fully visible on the
plate: no held microphone, hand or hair at her lips (a canon headset microphone stays at her cheek, clear of them).

**Measured** (share of the window's sung seconds in sync, long prompt → short retake): Studio run `c01` **0 % → 78 %**,
`c04` 13 % → 29 %, `c06` 26 % → 26 % (a microphone at her mouth on the plate); SP `W02` **28 % → 100 %** (§3's `W02`
is the long one). The chorus as a whole: 44 % → ≈ 62 % of its sung seconds. If a window still does not copy in the short
form: 2 OpenRouter non-copies → a Higgsfield draft → cut away (`61-lipsync.md` §8).

**A filled example** (the EV line in today's form; an illustration, not a measured take):
```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "Lock in, baby, foot down on the gas.".
Close-up of the woman from @Image1 (black bob, one orange streak, star clip), facing the lens, singing with her eyes closed, her head tilting back slightly on the long note. Warm light from the side. Locked camera, very slight push in.
1.62 s (downbeat): she opens her eyes on the lens.
One continuous shot, no cuts, no head turns. Only she sings. No text, letters or logos.
```

### EV's sung windows (the form the template grew from; `@Audio1` = the vocal-stem window)

The fixed head: `@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "<exact aligned words in
the window>".` — then one framing, one action, one camera. EV's short prompts copied on 41 % of its sung takes.

**SD05** · 4 s · plate `waymo-seat`:
```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "Our Waymo just drove into a firework. Are we on fire, dude?". Medium close-up of the woman from @Image1 sitting upright in the back seat of the car, facing the camera, saying the words flatly with no expression. Locked camera, no cuts, no head turns.
```
Why: a talking line delivered deadpan to the lens; "no head turns" keeps the mouth readable for the sync check.

**SD08** · 5 s:
```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "Lock in, baby, foot down on the gas. Feel the A G I, feel it". Close-up of the woman from @Image1 with her black bob, clay-orange streak and headset microphone, facing the camera, singing with her eyes closed, her head tilting back slightly on the long notes. Warm light from the side. Locked camera, very slight push in, no cuts, no head turns.
```
Why: the canon's performance rule ("when she sings, the mouth opens wide and the eyes close") written into the action.

**SD07** · 5 s · plate `hero-walk`:
```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "Eighteen months to escape the underclass. Lock in,". Full-length shot. The woman from @Image1 walks toward the camera down the middle of the huge hall, singing, with a confident model's walk; the flaps on the giant board behind her flicker in waves and bands of warm light cross the floor. Her skirt swings. The camera moves back at her walking speed so she ends at waist height. No cuts.
```
Why: the quoted words match the window exactly ("… Lock in,"); an earlier take quoted only up to "underclass", its window
also held "Lock in," and it diverged inside "underclass".

**SD06-c1** · 4 s · a **cover** (window starts in the word gap before its parent's divergence; start image = the parent's
frame at the cut):
```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "singularity. How's the temperature? Mild. No grades, no tests.". Medium close-up of the woman from @Image1 seated behind a large broadcast microphone, speaking the words calmly toward the camera like a podcast guest. One hard top light, black background. Locked camera, very slow push in, no cuts.
```
Why: same prompt pattern as the parent, new exact words; the chain (take + covers) holds the line where one take drifted.

## 2. EV: motion clips (`@Audio1` = the full mix)

**SD01** · 6 s · plate `waymo-cu` (the film's first shot):
```
The scene from @Image1, moving in time with @Audio1. Close-up. The woman from @Image1 sits still in the back seat of the moving car at night, eyes closed. A red light slides slowly across her face from left to right. At one second she opens her eyes and looks straight into the lens. At four seconds she turns her head slowly to the side window as a white light sweeps across the glass and her face. The car rocks slightly. Locked camera, very slow push in. No cuts. Her mouth stays closed, face expressionless.
```
Why: coarse timed beats inside the clip, one camera move, the mouth state stated for a non-singing clip.

**SD10** · plate end of the walkway:
```
The scene from @Image1, moving in time with @Audio1. Full-length shot. The woman from @Image1 stands completely still at the end of the walkway with her weight on one hip for two seconds, then turns sharply around on one heel so her short black hair swings out, the orange strand whips across her face and the tag on her belt flies out, and she stops facing the camera, still. Static camera. No cuts. Her mouth stays closed, face expressionless.
```
Why: one clear action with a named end state ("she stops facing the camera, still") and concrete physics on hair, streak
and tag.

---

## 3. SP: the screenplay grammar (the template for motion clips and acting moments)

> **Sung windows below are shown for their story and blocking, not as the sung template.** SP wrote its sung windows as
> screenplays too; measured since, the long form copies the vocal far less often than the short sung form (§1). Use §1 for
> a sung window; keep a screenplay on a sung shot only for an acting moment with a cut-away ready
> (`slop clip new SHOT --kind sung --style screenplay`).

> **Inputs warning: copy the prompt grammar, not SP's inputs.** Several entries below list a **first frame** (`first
> frame <plate>`). On **OpenRouter** a first frame (`frame_images`) overrides every reference: the `@Audio1` window is
> silently dropped (verified with paid probes: the take makes its own soundtrack, copy NCC ≈ 0.015). So:
>
> - **Sung windows and covers: reference mode only.** The plate as `@Image1` (a reference image), the window as
>   `@Audio1`, **no first frame**. `slop clip new` drafts them this way, and `slop clip lock` refuses a first frame on a
>   sung clip.
> - **Motion clips: reference mode by default** (`The scene from @Image1, moving in time with @Audio1. …`). A first
>   frame only when the exact opening composition matters more than moving on the music; on OpenRouter the clip then gets
>   **no audio conditioning**, so the timing lives only in the prompt's timestamps.
> - **A first frame together with `@Audio1` works only on Higgsfield** (SP's W07 below ran there). Do not copy that
>   combination to OpenRouter.
>
> Details: `60-clips.md` §2.2.

Written by the lead in one context (~25 minutes for 101 prompts) after reading the storyboard, contact sheets of every
first-frame plate, and the exact word and hit times inside each clip's window. Nothing spent until the user read the book.
Median 164 words.

**The book's header** (it travels with the prompts):

> **How to read a prompt.** Times are seconds from the clip's first frame; the clip's audio (@Audio1) is the song from the
> clip's start, so the times are the real word, kick, snare and impact times … Windows (W…) are her lip-sync clips: the
> head quotes only the words *she* sings on camera (crowd shouts and other voices are muted out of that clip's audio).
> Motion clips (M…) start from their plate as the first frame; nobody's mouth forms words in them unless noted.
>
> **Her, always:** doing something to him or reaching for him; warm, intimate, seductive, certain; never idle, never
> posing for a photo. **Him, always:** the body tells the story (the rope, the sweat, the breathing); he never speaks …
> **No earplugs on him, ever.** Orange on her only in the streak and the clip.

**The eight parts, in order:** (1) the singing head (sung acting moments only) · (2) place + light + blocking at 0.0 s, with canon tags
in parentheses · (3) the story beat in one sentence · (4) timestamped lines `a.aa–b.bb s ("<words>"): <her action>; <his
reaction>` on real word/kick/impact times, with the sound named · (5) the environment answering the music · (6) the camera
tied to the hits · (7) mouth rules · (8) the closer ("One continuous shot, no cuts. No text, letters or logos.") plus
constraint lines the code layer relies on.

**Entry format** (the toolkit's form; reference mode):
```
### <clip> · <storyboard shots> · <song time m:ss.ss> · <clip length>
- inputs: @Image1 `<plate>` (reference) · @Audio1 <the mix | her vocal (her words only)>
          [first frame `<plate>`: motion clips only; on OpenRouter it drops @Audio1]
- story: <one or two sentences: the beat, why it matters, the user's note if any>
<prompt as sent>
```

### W02 · s005 · 0:08.56 · 4 s · @Image1 `siren-sing-cu` · @Audio1 her vocal (her words only)
```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "Why would I deceive you?".
Night on her black sea rock, moonlight, faint spray. Close-up of the woman from @Image1 (black bob, one orange streak, star clip, thin headset mic, white ruffled gown). Someone has just asked her whether they can trust her; this is her answer, sung softly a cappella straight into the lens, as if to one person.
0.0–0.3 s: she draws a slow breath, lips parting, eyes on the lens, head tilted a little.
0.3–0.74 s ("Why would I"): she sings softly, her eyebrows lifting a fraction, as if the question has hurt her feelings a little.
0.88–1.34 s ("deceive"): she leans closer to the lens; her voice warms and her eyes soften.
1.44–1.56 s ("you?"): the word ends on a small, disarming smile; her eyes stay on ours.
1.6–2.16 s: silence; she holds the gaze, lips parted, completely sure of herself.
2.16 s (the beat drops): a wave bursts behind her and the wind whips her wet bob across her cheek; she does not flinch, and her smile deepens.
2.16–4.0 s: she keeps looking into the lens, lips closed, as the spray falls.
Camera: a very slow push in until 2.16 s, a small jolt on the drop, then still. One continuous shot, no cuts. No text, letters or logos.
```
Why (story): every word has its own action on its real time; the drop at 2.16 s moves the environment and the camera
together. Sync: this long form held only **28 %** of the line on Higgsfield (take 2); an earlier short prompt for the
same window (86 words, no timestamps) held **100 %** (take 1). That pair is one of the measurements behind §1.

### W07 · s026 · 0:42.90 · 5 s · first frame `mast-dusk-wide` · @Image1 `ghost-float` · @Audio1 her vocal: only "You don't have to die." (her shout and the crowd's shout muted)

> **Higgsfield only.** This take combined a first frame, a character reference and the vocal, and it copied the vocal
> (NCC 0.49) **on Higgsfield**. On OpenRouter the first frame would have dropped `@Audio1` and the lips could not sync.
> To send this window to OpenRouter: no first frame; the plate (or the cut frame) as `@Image1`, the vocal as `@Audio1`,
> and the opening composition described in words.

```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "You don't have to die.".
Dusk on the black galley, the first frame of this shot: a medium wide shot of the broad bearded man in a black t-shirt at the mast, a thick hemp rope around him and the mast, the sea and the Sirens' rocks behind him, rowers with orange earplugs pulling their oars below. The Sirens' song is pouring over the ship and it is pulling at him: he wants to go to them.
0.0–1.9 s: he strains toward the rocks with all his strength, pulling forward and twisting from side to side against the rope, the mast creaking, his jaw set and his eyes fixed on the rocks. The rowers keep rowing, eyes down, deaf to it.
1.2–1.9 s: from the left of the frame the woman from @Image1 glides in, floating level in the air like a diver, see-through like glass and seawater, her gown and black bob drifting as if underwater, the orange streak glowing faintly.
1.9–3.42 s ("You don't have to die."): she rests one hand on his shoulder, leans in close and whispers the words into his ear with a small, certain smile. He stops pulling mid-movement; his eyes widen and soften; he turns his head toward her voice as if he wants to believe her.
3.42–5.0 s: she stays close beside him, her cheek near his; he leans back against the mast and breathes out slowly, calmer now, still looking at the rocks.
Only she speaks, in a whisper; his mouth stays closed. Locked camera, drifting slowly toward them from 3.0 s. One continuous shot, no cuts. No text, letters or logos.
```
Why: action **and** reaction for everyone in frame; the audio window was built so the words start only after she has
arrived (take 1 had the words at 0.3–1.9 s while she was still in flight and did not copy the audio: NCC 0.04). On the
provider where a first frame counts as `@Image1`, the head was sent as `@Image2 sings @Audio1 …`.

### W15 · s072 · 2:15.38 · 4 s · @Image1 `chrome-ear` (re-made first with the image-edit model) · @Audio1 her vocal
```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "I said you don't have to die. The doctor said you could. Your P".
Inside a bathroom stall at the warehouse rave, one bare bulb, strobe light flickering under the door. The broad bearded man with a shaved head in a black tank top has just injected himself and it has gone wrong: he is slumped against the tiled wall, grey and slick with sweat, shaking, breathing in shallow gasps, his eyes mirror-chrome silver. The woman from @Image1 (black bob, orange streak, star clip, headset mic, mirrored chrome bodysuit and gloves) kneels astride his legs, close against him. She is not afraid for him: she is seducing him out of his fear.
0.0–0.3 s: his head lolls; she catches his face in her chrome-gloved hand.
0.3–1.8 s ("I said you don't have to die"): she turns his face toward hers and brings her lips to his ear, whispering slowly and tenderly, her other hand sliding flat over his racing heart; he grabs her wrist with a trembling hand and clings to it like a lifeline, his face crumpling, terrified and desperate to believe her.
1.88–3.48 s ("The doctor said you could"): she pulls back just enough to look into his silver eyes, wipes the sweat from his temple with her thumb and gives him a slow, confident, persuasive smile, as if the doctor were a joke; his head drops onto her shoulder, his body shaking, and she cradles the back of his head, rocking him gently.
3.48–4.0 s ("Your P"): she brings her lips back to his ear; his grip on her wrist loosens and his hand starts to slide away.
Camera: handheld close two-shot, breathing with them; a white strobe flash through the gap under the door on each kick (0.22, 0.68, 1.14, 1.59, 2.06, 2.5, 2.96, 3.43, 3.88 s). Only she speaks; his mouth stays closed. One continuous shot, no cuts. No text, letters or logos.
```
Why: the same words as the round-1 prompt the user called "awful prompt" (§5), rewritten as drama: a situation, a want,
blocking, and the strobe on every listed kick. (Ending a window mid-word, "Your P", is still a flaw: windows should end in
a word gap.)

### M-s001 · s001 · 0:00.00 · 4 s · first frame `eye-open` · @Audio1 the mix
```
Extreme macro close-up of the Siren's eye at night, filling the frame: pale freckled skin, lashes beaded with sea spray, the clay-orange streak of her bangs across the top of the frame. Reflected in the wet iris: a moonlit black sea, a ring of jagged sea rocks and, far off, the single white light of a ship. She is the Siren, watching a ship come toward her island.
0.0–0.4 s: the eye is still, looking just past the lens; the sea wind lifts a few strands of the orange streak.
0.4–1.0 s: a drop of spray lands on her lower lashes; she does not blink; the pupil slowly widens, as if she has spotted the ship.
1.0–2.1 s: the tiny ship light drifts across the reflection in her iris; her lower lid tightens very slightly with interest.
2.1–3.1 s: her gaze moves from past the lens straight into the lens and meets ours, calm and knowing.
2.3–4.0 s: the camera pushes in steadily, then faster as the synth swell rises, straight into the black pupil, until the pupil fills the whole frame with black.
The iris and pupil keep a crisp, perfect circle throughout. She never blinks. No cuts. No text, letters or logos.
```
Why: something happens in every interval, the camera move rides the synth swell, and the last frame (black pupil) is
designed as the transition into the next shot. The constraint line protects the shape the code layer uses.

### M-s025 · s025 · 0:43.10 · 4 s · first frame `tying` (edited) · @Audio1 the mix
```
Dusk on the deck of the black galley, the Sirens' song rolling across the water from the rocks. The broad bearded man with a shaved head in a black t-shirt stands with his back against the mast while two rowers in plain undyed linen tunics (one grey-haired, one young with long hair tied back), both with small orange foam earplugs, lash him to it with thick hemp rope. He asked for this: he wants to hear the song and be unable to act on it.
0.0–1.0 s: he presses his shoulders back against the mast and nods at them hard: tighter. They pass the rope around him fast, hand over hand.
1.0 s (the drums hit): they haul the rope tight across his chest in one hard jerk; the breath is knocked out of him and his head knocks back against the mast.
1.0–1.9 s: another loop whips around his chest and arms; the rope creaks; his fists clench at his sides.
1.9–2.84 s: his eyes go past the rowers to the singing rocks behind the camera, wide and hungry, his jaw set; the song is already reaching him.
2.84 s: the grey-haired rower yanks the knot tight with both hands, one foot braced against the mast.
2.9–4.0 s: the rowers go back to their oars without looking at him; he tests the rope, straining forward an inch; it holds.
Handheld camera, close, moving with the pulls. Nobody speaks. No cuts. No text, letters or logos.
```
Why: the hardest physical action lands on the drum hit at 1.0 s; the extras are described as distinct people.

### M-s037 · s037 · 1:09.44 · 5 s · first frame `benches` (passed only after rewording)
```
Twilight on the black galley. The woman (black bob, orange streak, star clip, headset mic, white high-necked ruffled gown) stands in the central aisle between the rowers' benches, facing the lens, the mast and sail behind her. She has walked onto their ship, and one by one the rowers stop blocking out her song.
0.0–3.0 s: she walks slowly toward the camera down the aisle, calm and confident, eyes on the lens, a small knowing smile, lips closed. As she passes each bench, the rowers on both sides pull the orange foam out of their ears, one bench on each beat (0.48, 0.94, 1.39, 1.86, 2.32, 2.77 s), a domino run following her down the ship; each rower's head turns to watch her go by, his oar trailing in the water.
1.42–1.72 s: she brushes one rower's shoulder with her fingertips as she passes; he looks up at her, entranced.
2.94–3.54 s: she stops and lifts both arms slowly from her sides, palms up, like a singer taking the applause; behind her, every rower is watching her.
3.54–5.0 s: she lowers her arms and tilts her head at the lens.
Camera: dollies backward at her walking pace, at eye level. She does not speak. One continuous shot, no cuts. No text, letters or logos.
```
Why: a domino on the beat (one bench per listed beat) — the picture plays the track. The blocked wording ("every man she
passes stops resisting", "pull the orange plugs out of their ears") became "one by one the rowers stop blocking out her
song", "pull the orange foam out of their ears".

### M-s009 · 4 s · @Audio1 the mix (the environment answers every kick)
```
Night, a moonlit black sea. The camera skims fast and low, a metre above the water, toward a single black galley with a white masthead light on the horizon: the Sirens' song is travelling across the sea to the ship.
0.0–4.0 s: one continuous forward skim, gently accelerating.
On every kick (0.45, 0.91, 1.37, 1.86, 2.35, 2.80, 3.24, 3.72 s): a fresh ring of ripples pulses outward across the surface from under the camera, as if the sea were a speaker cone, moonlight flashing along each ring.
1.86 s: the camera dips lower and spray flicks past the lens.
3.24–4.0 s: the galley grows larger; its oars rise and fall in rhythm.
No cuts. No text, letters or logos.
```
Why: with no people, the world itself keeps time. (QA: "the camera barely advances" — the push was added in 2.5D in the
comp.)

### M-s082-b · the flip pair (cut on quarter notes against M-s082)
```
Sunrise on the black galley, side view, the framing held exactly as in the first frame: on the left, the woman (black bob, orange streak, star clip, headset mic, white ruffled gown) is lashed to the mast with hemp rope; on the right, a step away, the broad bearded man with a shaved head in a black t-shirt faces her. Rowers with orange earplugs row below; sun flare and spray.
0.0–1.02 s: she strains toward him against the rope in one long scream, mouth wide open, eyes fierce, hair whipping.
0.85 s (the drums hit): spray bursts over the rail behind them.
1.02–1.98 s: she falls back against the mast, panting; he takes half a step closer, his hand rising toward the knot at her chest, then stopping in mid-air.
1.98–3.04 s: she looks at his hand, then up into his eyes, her face softening into a small, pleading smile; his fingers close on the rope.
3.04–4.0 s: he holds the rope without pulling it, jaw tight, torn.
Locked camera, the framing fixed exactly. His mouth stays closed. No cuts. No text, letters or logos.
```
Why: "the framing held exactly as in the first frame" + a locked camera keep the pair cuttable against each other.

### M-s073 · 7 s (moderation-safe rewording of a dark beat)
```
Straight down on a bathroom stall floor at the rave: the bearded man with a shaved head in a black tank top lies on his back on the tiles, eyes open and mirror-chrome silver, one bare bulb above. He has gone very still. A translucent, softly glowing copy of him, dressed exactly like him in the black tank top, dark trousers and thin silver chain, is rising out of his body toward the camera.
0.0–1.62 s: he lies still, breathing slowly, his fingers relaxing open on the tiles; the bulb above him flickers once.
1.62–2.5 s: the glowing copy of him, fully clothed like him, peels upward out of his body, arms hanging loose, head tipped back, rising toward the lens.
2.5 s (downbeat): the camera starts rising straight up with the glowing copy, keeping it in the centre of the frame while his body shrinks on the floor below.
2.5–4.33 s: the camera and the copy rise through the stall's ceiling, tiles and pipes sliding past.
4.33–6.15 s: they rise out through the warehouse roof into the night fog; below, the roof and the lights of San Francisco spread out; the copy opens its arms, at peace.
6.15–7.0 s: the fog swallows the city lights below.
One continuous vertical move, no cuts. No text, letters or logos.
```
Why: "He has gone very still" replaced "His heart is giving out" (blocked); "dressed exactly like him … fully clothed"
was added after the safety scan found a nude glowing figure in the first take.

### V-s002 · a 3D previz move (`@Video1` previz for the camera path only, `@Image1–3` plates for the look)
```
The camera follows the motion of @Video1 exactly. The look comes from the images: the moonlit white cloud deck seen from twelve kilometres up with one dark round gap in it (@Image1), and a ring of jagged black sea stacks in a black-teal night sea with white surf glowing around them (@Image2). We are falling toward the Sirens' island.
0.0–2.11 s: the camera dives toward the dark round gap in the clouds, accelerating with the rising synth swell, the cloud tops streaming past below.
2.11 s (the bar line): we drop through the gap; walls of cloud rush past on every side.
2.4–3.4 s: out through the cloud base: far below, the black sea and the ring of sea stacks, silver moonlight on the water; the camera corkscrews one full turn as it descends.
3.0–3.25 s: for a quarter of a second the moonlight catches something pale and enormous under the water beside the rocks: a calm woman's face with closed eyes (@Image3); then it is gone.
3.4–5.0 s: the rocks rush up and the camera settles low over them, on the same framing as the end of @Video1.
One continuous shot, no cuts. No text, letters or logos.
```
Why: a rough 3D render fixes the camera path; the plates fix the look. If proxies leak into the take, say "take only the
camera move from it, and film the scene itself in rich cinematic detail", or drop the video reference.

---

## 4. Moderation-safe rewording (keep the beat, change the words)

| Blocked | Passed |
|---|---|
| "the rope creaking and cutting into his chest"; "cups his bearded jaw" | "he strains toward the rocks … pulling forward and twisting from side to side against the rope"; "she rests one hand on his shoulder, leans in close" |
| "lashed to the mast with thick hemp rope across her chest"; "screams" | "held against the mast by a thick hemp rope"; "shouts" |
| "worn by a mountain of black-green tentacles" | "worn by an enormous dark sea creature" |
| "The drug is in his blood." | "The chrome is in his blood." |
| "a small orange foam plug pushed deep into each ear" | "small orange foam earplugs in their ears (no earmuffs)" |
| "(only as a guide for the camera path: everything on screen is photoreal …)" | "take only the camera move from it, and film the scene itself in rich cinematic detail" |

Rope across a chest was not a trigger alone; rope + chest + a hand or face on the body together was. Full table:
`62-moderation.md`. Never alter an *image* to pass a filter.

---

## 5. What bad looks like (round 1, agent-written; don't copy)

**W15, round 1** (the user pasted it back as "awful prompt"):
```
@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "I said you don't have to die. The doctor said you could. Your P". Extreme close-up in the dark: the woman with the black bob and one orange streak from @Image1 rests her chrome-gloved hand on the man's cheek and whispers the words at his ear. His eyes stay mirror-chrome silver and unblinking, and his mouth stays closed. Strobe light glints on the chrome; faint fog. Locked camera. No cuts. No text, letters or logos.
```
A pose, no story, no action and reaction, no timestamps, and a window that cuts a word. The user: "it should tell it to
him but he should be interacting with her in the scene somehow, she should be moving not just sittng there dead waiting,
she should be seductive and persuasive, he should be feeling awful given the context".
Note the other side: a take of this short window held 99 % of its sung seconds in sync (`61-lipsync.md` §9). Short is
right for the lips; the failure was the missing story. Today the drama of a sung shot goes in the book entry's `story:`
line, the plate and the motion clips around it, and the sung prompt stays short (§1).

**M-s001, round 1:**
```
Moving in time with @Audio1. Extreme close-up of her eye: it stays open, wet and still, the moonlit sea and the ring of rocks reflected in it shimmering; the clay-orange streak stirs in the wind. The camera pushes slowly and steadily into the black pupil until the pupil fills the frame. No cuts. No text, letters or logos.
```
"Nothing happens in the eye. There is no ship in the reflection, no look into the lens, and no reason to fall in."
Compare §3's M-s001.
