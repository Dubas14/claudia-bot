# The lead - character bible

The lead is **Claudia** by default, the open character from claudia.gallery (the source of truth: re-read her canon
with the MCP tool `claudia_canon` at the start of the project; docs/05-claudia-gallery.md). Replace her with a new
character only when the owner asks for one, and record that with `slop decide`.

The lead's identity is TEXT, pinned in every prompt with the lead. Never use a face image as the identity reference:
image references of a face over-condition the model and drift. Test it on 4 plates and get the face approved (gate G3)
before any batch. Then store the prompt text in project.json:

    slop --project {{NAME}} lead --canon "..." --far "..." --possessive "..."

## Canon (every prompt and edit keeps these)
- Face / age / ethnicity / skin (pin them in the prompt - Midjourney drifts otherwise): a Caucasian American woman,
  28, in her late twenties; a grown-up angular face, defined cheekbones, a strong jaw; pale skin, light freckles
  across the nose, dark calm eyes. Never the word "young".
- Hair / marks: a glossy black blunt bob to the jaw, heavy straight bangs to the brows, ONE clay-orange streak
  (#D97757) through the bangs on her right side; a small flat clay-orange eight-pointed star hair clip on her left
  side above the ear; a thin headset microphone at her cheek.
- Outfit (base look): changes with every world (each look's wardrobe text is in the canon); her head never changes.
- Colour rules: everything on her is her look's own colour, plus the streak and the clip in clay. Clay is the one accent.
- Medium: photographic film stills with grain and cinematic light, never illustrated. Her avatar tier (a cel-shaded
  3D game heroine) is only for game or simulation worlds, with its own text, never mixed into a photographic prompt.

## Prompt text
- `lead.canon` (close and medium framings; the framing words come FIRST in the prompt, then this text):
  a 28-year-old Caucasian American woman with a grown-up angular face, defined cheekbones and a strong jawline, pale skin and light freckles, a glossy black blunt jaw-length bob with heavy straight bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone at her cheek
- `lead.far` (full-length and wide shots: a SHORT variant - face details pull the model into a close-up):
  a Caucasian American woman in her late twenties with pale skin and a glossy black blunt bob with heavy straight bangs and one clay-orange streak, a thin headset microphone
- `lead.possessive` (e.g. "the singer's"): a Caucasian American woman's

## Never
- a second streak, or orange anywhere else on her
- logos or text on her clothes
- an influencer smile for the camera
- anything that reads under-age; explicit or sexualised posing
- the word "young" in her prompts
- designer or celebrity names in prompts (describe the piece instead)
- generic mall Y2K (velour tracksuits, plain tees and jeans) when she goes Y2K
- Midjourney lettering, logos or UI: all type is drawn in code on top
