# Midjourney prompts by framing (verbatim, scrubbed)

Plate prompts that shipped in the reference videos, grouped by framing, each with a one-line note on why it worked. All
ran on Midjourney v8.2 with `--ar 16:9 --v 8.2 --raw --hd` plus the creator's own personal profile (`--profile <your own
code>`; never use or ship someone else's code; never bare `--p`). No style references. The grammar is in
`50-plates-midjourney.md`:

```
<framing + vantage first> of <canon identity block> [wearing <look>], <pose/action>, <placement in frame + the declared
empty field for type>, <set + props (the meme as an object)>, <the chapter's light/style tail, verbatim>, no text, no letters, no logos
```

Replace the canon blocks with **today's Claudia identity text** (the canon on claudia.gallery, `claudia_canon`: "a
28-year-old …" close, "… in her late twenties …" far), or a new character's canon only when the owner asked for one.
The EV and SP blocks below are records: their "young" and "in her mid-twenties" are retired, never written again.
Keep the clause order.

---

## 0. Canon blocks (the identity lives in text)

EV lead (the descriptor that ended the ethnicity drift; drop garments that are not visible in the framing):

```
a young Caucasian American woman with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone, a white cropped puff-sleeve shirt, a black pleated skirt with a harness belt and a hanging white garment tag, black knee boots
```

SP lead, close (`HER`) and far (`HER_FAR` — for full-length and wide shots; the face details pull the frame in):

```
a Caucasian American woman in her mid-twenties with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy straight bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone at her cheek
```
```
a young Caucasian American woman with pale skin and a glossy black blunt bob with heavy straight bangs and one clay-orange streak
```

SP second lead (pinning "shaved head, thick short dark beard, pale blue eyes" made him consistent), and fixed props:

```
a broad-shouldered Caucasian man in his early thirties with a shaved head, a thick short dark beard, a square jaw, heavy brows and pale blue eyes, the build of a man who lifts
```
```
a long black ancient Greek galley with a single mast, a square sail and two banks of oars
```

**Why:** "Midjourney turns her Asian" until ethnicity, skin and age are pinned in every prompt; face image references
over-condition (big heads on far figures). Text canon, framing first, worked for 300+ plates.

## 1. Style tails (append verbatim per chapter)

| Chapter light | Tail |
|---|---|
| EV night | `blue-black #0f1216 and steel blue, one small red lamp as the only warm note, fine silver-gelatin grain, cinematic stillness` |
| EV board | `blue-black night turning to first light, clay-orange #D97757 light as the only colour, fine grain, cinematic stillness` |
| EV pre-dawn | `pre-dawn slate grey, one small ember-orange #db5c34 light as the only warm note, fine silver-gelatin grain` |
| EV fog | `pale grey-white fog, pure monochrome, no colour at all, soft diffuse light, fine grain` |
| EV white | `high-key white paper, soft shadowless light, monochrome except her clay-orange streak and hair clip, fine grain` |
| SP night | `night, moonlight on a black-teal sea, silver spray, cinematic 35mm film still, anamorphic, fine grain` |
| SP dusk | `dusk, low gold light on a glassy sea, violet sky, cinematic 35mm film still, anamorphic, fine grain` |
| SP bedroom | `a dark bedroom at 3am lit only by a phone screen, blue-white glow on the face, cinematic 35mm film still, grain` |
| SP rave | `a San Francisco warehouse rave, fog, white strobe, chrome reflections, deep black, flash photography` |
| SP insert | `macro product photograph, hard rim light, razor-thin focus` |

**Why:** one light state per chapter makes 100+ plates read as one film; "one small … light as the only warm note" is the
creator's recurring taste signature. Night prompts still come back in rich colour (the grade is decided in post).

---

## 2. Extreme close-up (ECU)

**SP `eye-open`** (the first frame of the film):
```
extreme close-up of the right eye of a Caucasian American woman in her mid-twenties with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy straight bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone at her cheek, wearing a structured high-neck pearl-white couture gown with long sleeves, its sculpted ruffles rising around her like breaking sea foam, hair damp from the spray, composed and deadpan, the clay-orange streak falling across the frame, the pupil wide and black, a moonlit sea and a ring of black rocks reflected in the eye, night, moonlight on a black-teal sea, silver spray, cinematic 35mm film still, anamorphic, fine grain, no text, no letters, no logos
```
Why: the reflection *is* the story (the sea and the rocks in her eye), and it gave the film's first transition (push
into the pupil = the hole in the clouds). It came back with two star clips; the image-edit model removed one.

**EV `n-P24`** (an insert without the lead):
```
extreme close-up of a slim glass thermometer pendant on a long steel chain resting on a white cropped shirt, the mercury halfway, dark background, the right half empty, blue-black #0f1216 and steel blue, one small red lamp as the only warm note, fine silver-gelatin grain, cinematic stillness, no text, no letters, no logos
```
Why: the meme as an object ("How's the temperature? Mild."), with a declared empty half for the graphic.

## 3. Close-up (CU)

**EV `waymo-cu`** (shot 1 of the film):
```
close-up of a young Caucasian American woman with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone, sitting upright alone in the back seat of a driverless robotaxi at night, her face in the centre of the frame, eyes closed, a single red lamp sliding across one cheek through the side window, dark leather seat, the lower third of the frame dark and empty, blue-black night, fog, one small red lamp as the only warm note, fine silver-gelatin grain, cinematic 35mm film still, no text, no letters, no logos
```
Why: framing first, placement stated ("in the centre"), a declared empty field (the lower third) for the split-flap board,
and only the garments a close-up shows.

**SP `siren-sing-cu`** (a lip-sync window's reference):
```
close-up of a Caucasian American woman in her mid-twenties with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy straight bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone at her cheek, wearing a structured high-neck pearl-white couture gown with long sleeves, its sculpted ruffles rising around her like breaking sea foam, hair damp from the spray, composed and deadpan, singing with her eyes open, looking straight into the lens, the dark sea empty on the right, night, moonlight on a black-teal sea, silver spray, cinematic 35mm film still, anamorphic, fine grain, no text, no letters, no logos
```
Why: a singing pose and the lens look give the video model a clean lip-sync start; the empty right side holds the lyric.

## 4. Medium close-up (MCU)

**SP `siren-mcu`** (sp-02, after the canon change):
```
medium close-up of a Caucasian American woman in her mid-twenties with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy straight bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone at her cheek, wearing a structured high-neck pearl-white couture gown with long sleeves, its sculpted ruffles rising around her like breaking sea foam, hair damp from the spray, composed and deadpan, sitting on a black wet rock, turning her face to the lens, sea spray behind her, empty dark sea on the left, night, moonlight on a black-teal sea, silver spray, cinematic 35mm film still, anamorphic, fine grain, no text, no letters, no logos
```
Why: the same shot one batch earlier said "a sculptural sheer … gown … bare shoulders, bare feet" and came back as
nude-reading "plastic wrap" and reclining; "structured high-neck … long sleeves … composed and deadpan" fixed taste and
safety at once.

**EV `n-P12`**:
```
medium close-up of a young Caucasian American woman with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone, … holding a pair of narrow rectangular black sunglasses at chest height, deadpan, dark data hall behind, red lamp glint, the right third dark, blue-black #0f1216 and steel blue, one small red lamp as the only warm note, fine silver-gelatin grain, cinematic stillness, no text, no letters, no logos
```
Why: one prop held at chest height carries the line's joke; the dark right third is the type field. (The garments a
medium close-up cannot show are cut here: "…".)

## 5. Medium shot (MS) — a group that must not look alike

**SP `rowers-plugs`** (sp-09, the third attempt):
```
medium shot along a rowing bench of a long black ancient Greek galley with a single mast, a square sail and two banks of oars at night, four oarsmen of different ages and builds pulling their oars together, a grey-haired old sailor, a lanky young man with long curly hair tied back, a heavyset man with a red beard and a wiry dark-haired man, none of them bald, each with a small bright orange foam earplug pushed deep into his ear canal so only its round orange end shows, eyes down on the oar handles, sweat and moonlight, night, moonlight on a black-teal sea, silver spray, cinematic 35mm film still, anamorphic, fine grain, no text, no letters, no logos
```
Why: listing each extra by age, build and hair, plus the explicit negative "none of them bald", ended "three copies of
him". (The ear phrase passed the image model but later tripped a video provider's input filter; for video prompts say
"small orange foam earplugs in their ears".)

## 6. Full-length (FS)

**EV `s045` hero walk** (a sung window):
```
full-length shot of a young Caucasian American woman with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone, a white cropped puff-sleeve shirt, a black pleated skirt with a harness belt and a hanging white garment tag, black knee boots, walking hard toward the camera down the centre of a narrow wet catwalk in a vast hall, a colossal split-flap board filling the wall behind her, bands of warm light from the flaps across the floor, symmetrical, singing, the upper third the board, blue-black night turning to first light, warm clay-orange light spilling from the giant board as the only colour, fine grain, cinematic 35mm film still, no text, no letters, no logos
```
Why: a walk toward camera is what video models do best; the giant board behind her is the through-line device in frame.

**SP `chrome-full-b`** (sp-07, the fix for "full-length gives close-ups"):
```
full-body fashion editorial photograph taken from far away with a long lens: a young Caucasian American woman with pale skin and a glossy black blunt bob with heavy straight bangs and one clay-orange streak, in a mirrored liquid-chrome couture bodysuit, chrome opera gloves and chrome thigh-high boots, standing tall and still on a wet mirror-black floor that reflects her whole figure, head to toe in frame with empty fog above her head and floor below her boots, a warehouse rave lit by white strobes, deep black, flash photography, no text, no letters, no logos
```
Why: the camera distance comes first and the identity is cut to the short FAR form; three earlier batches with the full
face canon gave face crops "whatever the wording". "Repeating the instruction louder doesn't help; removing what competes
with it does."

## 7. Wide (WS) — a series for stills in rhythm

**SP `inst-1` … `inst-8`** (only the copy count changes):
```
wide shot of a Caucasian American woman in her mid-twenties with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy straight bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone at her cheek, wearing a structured high-neck pearl-white couture gown with long sleeves, its sculpted ruffles rising around her like breaking sea foam, hair damp from the spray, composed and deadpan, standing on a black sea rock, behind her one identical copy of the same woman rising out of the sea foam onto the rocks, night, moonlight on a black-teal sea, silver spray, cinematic 35mm film still, anamorphic, fine grain, no text, no letters, no logos
```
("… behind her two / four / eight identical copies …" in the others.) Why: four plates with one variable become a
stills-in-rhythm sequence swapped on the beats of the drop (×1, ×2, ×4, ×8) under a counter.

**EV `dist-ws`** (a distance reference):
```
wide shot: a young woman with a glossy black blunt jaw-length bob with heavy bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone, a white cropped puff-sleeve shirt with a small spark pin on the collar, a black pleated coated-nylon skirt with a harness belt and a hanging white garment tag, black knee-high boots, standing small in the middle of the frame, her whole figure about one third of the frame height, lots of empty studio floor and wall around her, in an empty seamless light-grey photo studio, plain backdrop and floor, soft even light, nothing else in the frame, deadpan expression, cinematic 35mm film still, fine silver grain, no text, no letters, no logos
```
Why: stating her size as a fraction of the frame height ("about one third"; "about one tenth" for extreme wide) teaches
scale without image references.

## 8. Extreme wide (EWS) — the world without the lead

**EV `n-P05`** (the README's "typical plate"):
```
a vast low datacenter on a black plain at night, steam plumes rising from its roof, a row of loading bays lit white, one red aviation lamp, a small white robotaxi turning into the nearest bay, a passenger silhouette in its rear window, the top half empty night sky, blue-black #0f1216 and steel blue, one small red lamp as the only warm note, fine silver-gelatin grain, cinematic stillness, no text, no letters, no logos
```
Why: scale carries the genre (no neon needed), a tiny story detail (the passenger silhouette), and half the frame
declared empty for type.

## 9. Two people, staged for a video clip

**SP `mast-dusk-wide`** (the first frame of a clip where a ghost arrives at his ear):
```
medium wide shot of a broad-shouldered Caucasian man in his early thirties with a shaved head, a thick short dark beard, a square jaw, heavy brows and pale blue eyes, the build of a man who lifts, in a plain black t-shirt and black trousers, barefoot, tied to the mast of a long black ancient Greek galley with a single mast, a square sail and two banks of oars with thick hemp rope wrapped around his chest, looking out to sea toward distant rocks glowing gold, empty air beside his head, rowers with orange earplugs at the oars behind him, dusk, low gold light on a glassy sea, violet sky, cinematic 35mm film still, anamorphic, fine grain, no text, no letters, no logos
```
Why: "empty air beside his head" reserves the space the second character flies into in the video clip.

**SP `flip-a` / `flip-b`** (a matched pair for a flicker edit): both start "side view at sunrise on the deck of [the
ship]: …"; `flip-a` has him "tied to the mast with thick hemp rope around his chest, and facing him a step away [her canon]
… standing calmly, looking at him"; `flip-b` swaps the roles ("[her canon] … tied to the mast with thick hemp rope around
her chest, screaming, and facing her a step away [his canon] … standing calmly, looking at her"); both end "the mast in
the centre of the frame, rowers with orange earplugs rowing below, sun flare, sunrise, warm gold light and long shadows,
spray lit gold, cinematic 35mm film still, anamorphic, fine grain, no text, no letters, no logos".
Why: identical framing language with only the roles swapped gives two plates that cut against each other on quarter
notes.

## 10. A character reference on a plain backdrop

**SP `ghost-float`** (made only to be a video model's `@Image` reference):
```
full-body side view of a Caucasian American woman in her mid-twenties with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy straight bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone at her cheek, wearing the same structured high-neck pearl-white couture gown, all of her translucent as if made of glass and seawater, faintly lit at the edges, hair drifting as if underwater, floating horizontally in mid-air like a diver gliding, chest toward the floor, her head and neck reaching forward as if about to whisper into someone's ear, the long gown trailing behind her like smoke, arms soft at her sides, elegant and poised, the composure of a high-fashion model, against a plain dark grey backdrop, no text, no letters, no logos
```
Why: when the image model can't compose a pose into the scene, make the pose alone on a plain backdrop and give it to
the video model next to the scene's first frame.

## 11. Make the feature the subject

**SP `eyes-flank-a`**:
```
extreme close-up of the wet black-green hide of a colossal sea monster rising out of the sea, the hide studded with dozens of large glossy human eyes of different sizes, some wide open and some half-closed, each eye reflecting a tiny pale figure, sea spray streaming off the skin, overcast grey light, cinematic 35mm film still, fine grain, no text, no letters, no logos
```
Why: "a flank covered in eyes" gave four bare flanks; making the eyes the subject of the sentence gave eyes.

---

## 12. What bad looks like (don't copy)

- **Broken substitution** (EV `n-P04`): `close-up of a young Caucasian American woman with pale skin and light freckles,'s
  hand pulling a black utility harness strap tight …` — the canon was pasted into a body-part shot. Use the possessive form
  and drop the canon: `close-up of a young woman's hand pulling …`.
- **Doubled garments** (EV `shoes-off`): `… black knee-high boots's black knee-high boots stepping past the pile …`.
- **Lookalike crowd** (SP `rowers-plugs`, sp-02b): `close-up of the heads of three rowers in profile … bright orange foam
  earplugs in their ears …` → three near-identical men. Fixed by §5.
- **A full face canon on a wide shot** → a face crop. Fixed by §6 `chrome-full-b`.
- **"Dithered", "xerox", "1-bit"** in the prompt → a grainy photo, not real 1-bit. Texture is made in code.
