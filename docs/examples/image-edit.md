# Image-edit instructions (verbatim, scrubbed)

How SP fixed canon breaks in picked plates without re-rolling them: an image-edit model through OpenRouter (the reference
used `google/gemini-3-pro-image`; see `51-plates-api.md` for the toolkit's current default). 16 calls on 15 images,
≈ $0.14 each, $2.22 in total; output 1376×768, then upscaled. The rule that created the tool: a hand-painted effect "shouldnt
have been done manually, it should have been in the midjourney prompt from the start or with the edit model."

## The form

The tool sends the plate with `"Edit this photograph. "` + the instruction, then appends this fixed clause (verbatim):

```
Keep everything else exactly as it is: the same framing and crop, the same light, colours, film grain and sharpness, the same people and objects except what this instruction changes. Photorealistic, the same photograph, same aspect ratio.
```

Instruction grammar: **"Change only X: <the precise target state, with negatives> … Keep Y."** Name forms exactly
("exactly eight points"), name what must *not* appear, and list what must stay the same when it is near the change.

**Why it worked:** edits preserved framing, faces and light remarkably well (a crew recast, a head shaved, hooded figures
turned into the lead's lookalikes). **Re-check canon after every edit**: the model can add a new error (a pink six-pointed
star instead of the eight-pointed clip). **Re-make depth and mattes** of every edited plate, and **re-make the clip** from
the fixed plate, then scan it again.

**Never** use an edit to get an image past a provider's safety filter (`62-moderation.md`).

---

## Examples

**chrome eyes** (the first edit; its full text):
```
Edit this photograph. Change only the man's eyes: make both of his eyes (the whole eyeball, iris and white) mirror-polished liquid chrome silver, like a chrome ball bearing, catching the white strobe light as hard specular highlights and reflecting a tiny dark figure of the woman. Keep everything else exactly as it is: the same framing and crop, the woman, her chrome glove on his cheek, her face, hair and orange streak, his beard, the lighting, the colours, the film grain and the sharpness. Photorealistic, the same photograph, same aspect ratio.
```
Why: an effect that continues across shots (his eyes stay silver) belongs in the image, so the video model animates it.

**a crew that looked like copies of the lead man:**
```
Change only the rowers on both sides of the ship: make them men of every age and build, some grey-haired and grey-bearded, some red-bearded, some with long curly hair tied back, some young and clean-shaven, with sun-dark weathered skin, all wearing plain undyed off-white linen tunics, each with a small bright orange foam earplug in his ear. None of them is bald, none has a thick dark beard like the man in the centre, and none wears black. The man sitting cross-legged in the centre with his phone stays exactly the same.
```
Why: positive variety + explicit negatives against the lead's features + "stays exactly the same" for the subject.

**hooded figures that read badly:**
```
Change only the standing figures on the rocks: make every one of them a young woman seen from behind or in profile with a glossy black jaw-length bob with heavy bangs, in a white structured high-necked couture gown with long sleeves, bare-headed (no hoods, no veils, no cones), all facing the same direction toward the horizon. Keep their number and their positions on the rocks.
```
Why: keeps the composition (number and positions) while fixing the read.

**one accessory too many:**
```
Remove the orange star hair clip on the left side of the image, so that exactly one small clay-orange eight-pointed star clip remains (the one on the right side of the image). …
```

**modern objects in an ancient scene + a stray prop:**
```
Replace every modern object behind them (metal railing posts, wire lifelines, the white fibreglass deck edge, the crumpled clear plastic object) with the dark wooden rail, thick hemp rigging and square sail of an ancient black Greek galley at twilight. Also remove the second small orange star on her cheek or temple, keeping only the star clip in her hair.
```

**her props on him:**
```
Remove the headset microphone from the man's face and jaw, and remove the small orange star from his brow. Replace any stainless-steel post or metal fitting and any modern synthetic rope with dark wood and thick natural hemp rope. Keep his face, his tears and the translucent glass hand on his cheek.
```

**a canon detail rendered wrong:**
```
make the orange streak a flat streak of clay-orange hair lying inside the black bangs, not a horn or spike sticking out.
```

**two passes on one plate** (check after each):
```
Make her hair clip a small flat clay-orange EIGHT-pointed star (exactly eight points), not a pink six-pointed star.
```
```
Remove the syringe and its needle completely; her lower chrome-gloved hand rests empty and relaxed against her chest. Replace the hoop-shaped wire and round disc hanging at her left jaw with a thin dark headset microphone: one slim boom running from her left ear along her cheek to just beside the corner of her mouth. …
```
Why the second pass: the safety scan flagged an uncapped needle; the fix went to the source image, not a crop.

**a continuity detail:**
```
Shave the man's head completely: a smooth, freshly shaved scalp with no hair at all. Keep his beard, his face, his eyes, his expression and the rope across his chest exactly the same. Keep the woman exactly as she is.
```
