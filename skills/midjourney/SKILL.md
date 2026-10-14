---
name: midjourney
description: Use when relay read shows a midjourney job from Opus. You run each of Opus's prompts on midjourney.com in your own signed-in browser and save all four images of every prompt into the job's folder.
---

# Midjourney - your browser, Opus's prompts

You are the hands. Opus wrote every prompt; you never change a word, never pick among the images (save all four of every prompt) and never post or share anything. The hand-off: docs/96-relay.md.

## Each job
1. The job comes from `slop --json relay read` under `jobs`: its id (like J-0004), `text` (a list: one full prompt per item, parameters included), the `save` folder and `name`.
2. Open https://www.midjourney.com/imagine in your browser. Signed out: "Please sign in to Midjourney in my browser. I never type passwords." Wait for their "done".
3. For each prompt in `text`, in order: paste it exactly into the prompt box and press Enter. Each one runs as its own Midjourney job.
4. Wait until every prompt shows its four images (about a minute each). Check every 20 s; past ~2 min first post a status line and "Say continue" (the profile's turn rule).
5. Download each image's original file (open it, use its download button, never a screenshot) into the job's `save` folder as NAME-K-N.png: K = the prompt's number from 1, N = the image from 1 to 4.
6. `slop --json relay done JOB --file PATH` with one --file per image. Then one line to the person, e.g. "Midjourney: 6 prompts, 24 images, sent to Opus."

## When it goes wrong
- One prompt refused or moderated: never reword it. Finish the others, then `slop --json relay done JOB --file PATH ... --note 'prompt K refused: <the page words>'`.
- Every prompt refused: `slop --json relay fail JOB --reason '<the page words>' --declined`.
- Out of fast hours or another plan limit: `slop --json relay fail JOB --reason '<the page words>'`. Opus tells the person.
- The page looks different: find the same things by their labels (Imagine or Create, the prompt box, an image's download).

## Learned steps
After the first job that worked, write one memory paragraph: the exact buttons and labels that worked on midjourney.com, in order. Use it next time. If it stops working, learn the page again and replace that paragraph.

Rules: Claudia is a grown woman in her late twenties, never sexualised; no real person's likeness; never post or share the person's profile code.
