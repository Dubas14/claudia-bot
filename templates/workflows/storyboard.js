export const meta = {
  name: 'slop-storyboard',
  description: 'Storyboard panel: three directors board the whole song from different angles, three judges score every board with a JSON schema, a head director merges the best into STORYBOARD.md + shots.json, and a checker runs the board audit as code and fixes until it passes',
  phases: [
    { title: 'Direct', detail: 'three independent full storyboards, each written to its own file' },
    { title: 'Judge', detail: 'three lenses score every board (JSON schema; a missing or partial score is a failed judge)' },
    { title: 'Merge', detail: 'the head director merges the best into board/STORYBOARD.md + board/shots.json' },
    { title: 'Check', detail: 'the board audit runs as code; the board is fixed until it passes' },
  ],
}
// Claudia storyboard panel (Claude Code Workflow script). Generalised from the panel that boarded the two reference
// videos: 3 directors (angles) -> 3 judges (lenses, JSON scores) -> head director merge -> code CHECK until it passes.
// Intentional changes from the original: no project hard-codes (everything comes from args and the project files);
// boards are written to files (a resumed or restarted run skips finished boards); judge keys are an enum and a judge
// with a missing board score counts as FAILED (a past run logged empty totals when names did not match); a null agent
// is never treated as success; the audit is its own agent, retried while it fails (user interrupts killed the merge
// three times when the audit lived inside it); the clip budget uses the toolkit's motion tiers (still | plate3d |
// motion | sung). Resume: Workflow({scriptPath: <this file>, resumeFromRunId: <run>, args: <same args>}).
//
// args (a JSON object; the delegation runner fills project_dir, out_dir, toolkit_dir, job_dir and slop):
//   project_dir     (required) absolute path of the project folder on this machine
//   out_dir         (required) the job's outbox: boards/, judges.json, check.json and the summary go here
//   toolkit_dir     the Claudia toolkit checkout (docs/ and engine/ are read from it)
//   slop            how to run the toolkit CLI (default "slop")
//   title           song title                                   duration   song length in s (else analysis/beats.json)
//   owner           what the prompts call the owner (default "the owner")
//   owner_quotes    the owner's verbatim notes for the board (string or list), quoted to every agent
//   banned_words    words that must never appear on screen or in prompts (list)
//   lead_min        share of runtime the lead is on screen (default 0.7)
//   motion_s        planned generated-motion seconds, sung + motion clips (default 200)
//   motion_clips    planned clip count (default 45)
//   shot_s          target mean shot length in s (default 2.25)
//   angles          [{k, a}] director angles (default purist / density / narrative)
//   lenses          [string] judge lenses (default viewer / owner taste / producer)
//   judges          false = no judge panel, the head director scores the boards itself (saves ~20 min)
//   board_dir       where the merged board is written (default <project_dir>/board)
//   audit_cmd       the board audit command (default "<slop> --project <project_dir> board audit")
//   check_rounds    how many audit agents may run while the board still fails (default 2)
//   extra           extra text appended to the shared context
const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const miss = ['project_dir', 'out_dir'].filter(k => !A[k])
if (miss.length) return { ok: false, error: `args missing: ${miss.join(', ')} (pass args as a JSON object; the delegation runner sets these)` }
const clean = p => String(p).replace(/\\/g, '/').replace(/\/+$/, '')
const P = clean(A.project_dir), OUT = clean(A.out_dir), TK = A.toolkit_dir ? clean(A.toolkit_dir) : null
const SLOP = A.slop || 'slop'
const BOARD = A.board_dir ? clean(A.board_dir) : `${P}/board`
const TITLE = A.title || 'the song'
const DUR = Number(A.duration) > 0 ? Number(A.duration) : null
const DURTXT = DUR ? `${DUR} s` : 'the full length in analysis/beats.json "duration"'
const OWNER = A.owner || 'the owner'
const QUOTES = Array.isArray(A.owner_quotes) ? A.owner_quotes.map(q => `"${q}"`).join(' · ') : (A.owner_quotes || '')
const BANNED = Array.isArray(A.banned_words) ? A.banned_words.filter(Boolean) : []
const LEAD_MIN = Number(A.lead_min ?? 0.7)
const MOTION_S = Number(A.motion_s ?? 200), CLIPS = Number(A.motion_clips ?? 45), SHOT_S = Number(A.shot_s ?? 2.25)
const AUDIT = A.audit_cmd || `${SLOP} --project "${P}" board audit`
const q = s => '`' + s + '`'   // every command is quoted in backticks (the toolkit's tests parse each one)
const AUDIT_RUN = q(`${AUDIT} --json${A.board_dir ? ` --shots "${BOARD}/shots.json"` : ''}`)
const ROUNDS = Math.max(1, Number(A.check_rounds ?? 2))
const DOCS = TK ? `${TK}/docs/40-storyboard.md, ${TK}/docs/50-plates-midjourney.md (or 51-plates-api.md for API plates), ${TK}/docs/60-clips.md, ${TK}/docs/61-lipsync.md and ${TK}/docs/70-motion-design.md (the toolkit playbook; read the parts about boards, plates, clips and motion design)` : 'the toolkit docs if you can find them'
const END_BOARD = '<!-- END OF BOARD -->'

const CTX = `You are boarding the lyric music video "${TITLE}" (the song is ${DURTXT}, locked). ${OWNER} owns it.
READ FIRST, fully: ${P}/PRODUCTION.md if it exists (the binding plan), ${P}/project.json (title, tier, lead canon, look, models, budget), ${P}/DECISIONS.md (${OWNER}'s decisions — binding; a later "UPDATE … supersedes" block wins), ${P}/lyrics/lyrics.txt and ${P}/lyrics/display.txt (the sung words and the on-screen tokens), ${P}/analysis/words.json (every sung word with its aligned t0/t1 and line), ${P}/analysis/beats.json (beats, downbeats, local tempo, sections), ${P}/analysis/hits.json (kicks, snares, hits, risers, vocal entries), ${P}/analysis/report.md, ${P}/taste/taste-tokens.json if it exists (${OWNER}'s measured taste), every file in ${P}/research/ if it exists (the references the lyrics make — the jokes the visuals must land), and ${DOCS}. Look at any images in ${P}/taste/ and ${P}/plates/ with the Read tool.
${QUOTES ? `${OWNER}'s words, verbatim (binding): ${QUOTES}\n` : ''}
PRODUCTION REALITY (design within it):
- PLATES: one still per shot (Midjourney or an image model, per project.json tier) — never the same image on two shots unless they are one continuous moment. Every prompt with the lead starts with its framing (extreme close-up / close-up / medium close-up / medium shot / full-length / wide / extreme wide) and where the lead stands, then the lead's pinned canon text from project.json "lead" (the "far" variant for full-length and wider) — identity comes from text, never from face reference images. Upright editorial poses (seated or reclining frontal poses get refused downstream). Every prompt ends "no text, no letters, no logos". Generation inputs stay in colour; the grade happens in post.
- MOTION TIERS per shot: "still" (a plate with code motion) · "plate3d" (2.5D: the still + its depth map animated in code — never a still with a slow zoom) · "motion" (an image-to-video clip from the shot's plate, 4–12 s, audio-conditioned on the song window so motion lands on the beat) · "sung" (a lip-synced clip: a 4–8 s window that starts in a gap between words and quotes exactly the words sung inside it; plan every sung passage the lead is on camera for as a chain of such windows with alternating framings — CU / MCU / MS / profile / over-shoulder — so a cover cut after a sync divergence lands as a designed cut). Two clips never start from the same frame. Planned motion + sung total <= ${MOTION_S} s across <= ${CLIPS} clips. Pure motion design (full-frame code-drawn diagram, UI, typographic poster, data-viz, split-flap wall) where a plate would repeat its neighbours or the idea reads clearer as a graphic.
- IT IS A LYRIC VIDEO: every sung word on screen at its aligned time (type modes: subtitle · coverline · masthead · stack · mass), AND every lyric line gets one explaining graphic that shows what the line means (chart, UI, diagram, label, counter, map) — a device in the shot's "devices" list. At least three ordered layers per frame (footage, lyric, chrome, graphic). 2.5D treatments never repeat on consecutive shots.
- Cuts land on beats or declared hits (analysis/beats.json, analysis/hits.json); mean shot about ${SHOT_S} s, faster where the song is dense, slower where it breathes; the first 3 s are a hook, not a wait. The lead is on screen >= ${Math.round(LEAD_MIN * 100)} % of the runtime.
${BANNED.length ? `- These words never appear anywhere (type, prompts, file names): ${BANNED.join(', ')}.\n` : ''}${A.extra || ''}`

const SHOT_FIELDS = `Each shot: id (s001…), t0, t1 (seconds, on beats), section, lines (lyric line numbers it covers), set, lead_on_screen (bool: the lead is recognisably in frame), framing (ECU|CU|MCU|MS|MWS|WS|FS|EWS), action (concrete: who does what), camera (move, tied to a hit if it moves), motion_tier (still|plate3d|motion|sung), plate (plate key), clip (clip id or null; several shots may cut from one clip), mj_prompt or img_prompt (the plate prompt per the rules), type (list of {line, mode: subtitle|coverline|masthead|stack|mass, text, placement: which empty field of the frame}), devices (list of {kind, anchor, params, key: W|B|H|F|T} — the explaining graphic first), treatment (the 2.5D family for plate3d shots), transition_in (cut, or a motivated device), chrome (what the always-on devices show), accent (hex), notes.`

const ANGLES = Array.isArray(A.angles) && A.angles.length ? A.angles : [
  { k: 'purist', a: 'Purist: restraint and gravity, long deadpan passes, few but perfect cuts; the jokes land in the type, tags and graphics, not in slapstick.' },
  { k: 'density', a: 'Density: timeline-scroll energy — every line its own one-glance visual joke, inserts on the beat, graphics between the lead\'s shots; maximum rewatch value.' },
  { k: 'narrative', a: 'Narrative: a journey — every chapter a place, motivated transitions (a door opens onto the next set, a board flips into the next scene), an ending that is earned.' },
]
const KEYS = ANGLES.map(g => g.k)

phase('Direct')
const DONE_SCHEMA = { type: 'object', properties: {
  file: { type: 'string' }, complete: { type: 'boolean' }, shots: { type: 'number' }, mean_shot_s: { type: 'number' },
  lead_fraction: { type: 'number' }, motion_s: { type: 'number' }, clips: { type: 'number' }, hook: { type: 'string' } },
  required: ['file', 'complete', 'shots', 'mean_shot_s', 'lead_fraction', 'motion_s', 'clips', 'hook'] }
const boardFile = k => `${OUT}/boards/${k}.md`
const directed = await parallel(ANGLES.map(g => () => agent(
  `${CTX}\n\nYOUR ANGLE: ${g.a}\n\nIf ${boardFile(g.k)} already exists and its last line is ${END_BOARD}, it is your finished board from an interrupted run: do not rewrite it, just read it and return its numbers.\n\nOtherwise write a COMPLETE storyboard for the whole song (0 to ${DURTXT}), no gaps, every lyric line covered, to ${boardFile(g.k)} (markdown): (1) a one-paragraph treatment; (2) the chapter map (chapter, time range, sections, grade, accent, sets); (3) the shot list with these fields: ${SHOT_FIELDS} (4) the clip list: clip id, tier (motion|sung), duration, plate, song_t0, for sung clips the exact words sung in the window (from words.json), the prompt idea in plain physical language (subject, action and reaction, camera tied to hits), which shots cut from it, and the running total seconds; (5) the hook design for the first 3 seconds. Be concrete; aim for one shot per ${SHOT_S} s of song. Write the file early and extend it (a cut at any moment must leave a valid file); end it with the line ${END_BOARD}.\nReturn the file path, complete (true only if every second and every lyric line is covered), and its numbers.`,
  { label: `director:${g.k}`, phase: 'Direct', schema: DONE_SCHEMA })))
const boards = []
directed.forEach((d, i) => {
  if (d && d.complete) boards.push({ k: ANGLES[i].k, file: boardFile(ANGLES[i].k), ...d })
  else log(`director:${ANGLES[i].k} FAILED: ${d ? 'board incomplete' : 'returned nothing (usage limit?)'}`)
})
if (boards.length < 2) return { ok: false, error: `only ${boards.length} complete board(s): the panel needs at least two. Resume this run after the cause (often a usage limit) is gone; finished boards are skipped.`, boards }
const BK = boards.map(b => b.k)
const boardList = boards.map(b => `- ${b.k}: ${b.file}`).join('\n')

phase('Judge')
const SCORE = { type: 'object', properties: { scores: { type: 'array', items: { type: 'object', properties: {
  board: { type: 'string', enum: BK }, total: { type: 'number' }, hook: { type: 'number' }, lead_coverage: { type: 'number' }, lyric_video: { type: 'number' },
  jokes: { type: 'number' }, taste_fit: { type: 'number' }, feasibility: { type: 'number' }, arc: { type: 'number' },
  best: { type: 'array', items: { type: 'string' } }, fixes: { type: 'array', items: { type: 'string' } } },
  required: ['board', 'total', 'hook', 'lead_coverage', 'lyric_video', 'jokes', 'taste_fit', 'feasibility', 'arc', 'best', 'fixes'] } } }, required: ['scores'] }
const LENSES = Array.isArray(A.lenses) && A.lenses.length ? A.lenses : [
  'a music-video director and a viewer of the target audience: is the first 3 s a hook, would people rewatch and screenshot, does every reference land in one glance, is the lead the star?',
  `${OWNER}'s taste (read DECISIONS.md, taste/ and the quotes): the look and type rules, editorial reduction, no slop; and the lyric-video rules: every line on time, type in empty fields, modes used with rhythm, one explaining graphic per line.`,
  `a producer: is it buildable with the pipeline (plates, audio-conditioned clips within ${MOTION_S} s / ${CLIPS} clips, 2.5D, code), are clip prompts physically simple, are sung windows in word gaps with their exact words, is cutting on the beat map, is 0 to the end covered with no holes?`,
]
let valid = [], judgeFailures = 0
if (A.judges !== false) {
  const judged = await parallel(LENSES.map((l, i) => () => agent(
    `${CTX}\n\nYou are a judge: ${l}\nRead every board below in full. Score each board 0–10 per field and a total 0–100; list its 6 best ideas (concrete shots, with ids) and its 6 most important fixes. Use exactly these board names: ${BK.join(', ')}. Score every board; a missing board makes your whole verdict void.\n\nBOARDS:\n${boardList}`,
    { label: `judge:${i + 1}`, phase: 'Judge', schema: SCORE })))
  judged.forEach((j, i) => {
    if (!j || !Array.isArray(j.scores)) { judgeFailures++; log(`judge:${i + 1} FAILED: returned nothing (usage limit?)`); return }
    const byKey = {}
    for (const s of j.scores) if (s && BK.includes(s.board) && typeof s.total === 'number') byKey[s.board] = s
    const gap = BK.filter(k => !byKey[k])
    if (gap.length) { judgeFailures++; log(`judge:${i + 1} FAILED: no score for ${gap.join(', ')}`); return }
    valid.push({ lens: i + 1, scores: byKey })
  })
}
const totals = {}
BK.forEach(k => { totals[k] = valid.map(v => v.scores[k].total) })
const mean = k => totals[k].length ? totals[k].reduce((a, b) => a + b, 0) / totals[k].length : 0
const ranked = BK.slice().sort((a, b) => mean(b) - mean(a))
log(`judge totals ${JSON.stringify(totals)} (valid judges ${valid.length}, failed ${judgeFailures})`)

phase('Merge')
const SELF_SCORE = valid.length ? '' : `\nNO VALID JUDGE SCORES (${A.judges === false ? 'the judge panel is off' : 'the judges failed'}): first score every board yourself 0–10 through three lenses — ${LENSES.join(' · ')} — list each board's 6 best concrete ideas and its 6 most important fixes, write that to ${OUT}/self-scores.md, then merge.`
const MERGED = '<!-- MERGED -->'
const MERGE_SCHEMA = { type: 'object', properties: {
  storyboard: { type: 'string' }, shots_json: { type: 'string' }, shots: { type: 'number' }, mean_shot_s: { type: 'number' }, lead_fraction: { type: 'number' },
  motion_s: { type: 'number' }, clips: { type: 'number' }, plates: { type: 'number' }, summary: { type: 'string' } },
  required: ['storyboard', 'shots_json', 'shots', 'mean_shot_s', 'lead_fraction', 'motion_s', 'clips', 'plates', 'summary'] }
const merged = await agent(`${CTX}\n\nYou are the head director. If ${BOARD}/STORYBOARD.md already ends with the line ${MERGED} and ${BOARD}/shots.json parses, you are resuming a finished merge: check both files, fix only what is broken, and return their numbers.\n\nOtherwise merge the boards using the scores: start from the best-scoring board (ranking: ${ranked.join(' > ')}), graft in every judge-listed best idea that fits, apply every fix.${SELF_SCORE}\nWRITE TWO FILES:\n1) ${BOARD}/STORYBOARD.md — treatment, chapter map, hook design, the full shot list (readable), the clip list with prompt ideas and the running total, the plate list (every plate, grouped by set, with its prompt; mark the ones with the lead), and a section "How this board was merged" (each grafted idea with its source board; each judge fix and how it was applied). End the file with the line ${MERGED}.\n2) ${BOARD}/shots.json — {"version": 1, "duration": <song length>, "chapters": [{id, name, t0, t1, sections, grade, accent, sets}], "shots": [...], "seedance": [...], "plates": [...]} (the toolkit's shots.json contract; "seedance" is the clip list whatever the video model). Shots use exactly these fields: ${SHOT_FIELDS} seedance items: {clip, kind: "motion"|"sung", duration, plate, song_t0, words (sung: the exact aligned words in the window), sing (bool), prompt, shots: [ids]}; plates: {plate, set, mj_prompt (or img_prompt), lead (bool: the lead is in it), aspect: "16:9", used_by: [shot ids]}. Keep the file valid JSON at every save.\nTarget numbers: lead_on_screen fraction >= ${LEAD_MIN}; motion + sung clip seconds <= ${MOTION_S} over <= ${CLIPS} clips; every cut on a beat or hit.\n\nBOARDS:\n${boardList}\n\nJUDGES:\n${JSON.stringify(valid)}\n\nReturn the two file paths, the numbers, and a 15-line summary of the final video.`,
  { label: 'head-director', phase: 'Merge', schema: MERGE_SCHEMA })
if (!merged) return { ok: false, error: 'the head director returned nothing (usage limit?): resume this run — finished boards and judges replay from cache', totals, ranked, boards }

phase('Check')
const CHECK_SCHEMA = { type: 'object', properties: {
  pass: { type: 'boolean' }, audit_output: { type: 'string', description: 'the last lines the audit printed' },
  numbers: { type: 'object', properties: { shots: { type: 'number' }, mean_shot_s: { type: 'number' }, lead_fraction: { type: 'number' }, motion_s: { type: 'number' }, clips: { type: 'number' }, plates: { type: 'number' } } },
  fixed: { type: 'array', items: { type: 'string' } }, remaining: { type: 'array', items: { type: 'string' } } },
  required: ['pass', 'audit_output', 'numbers', 'fixed', 'remaining'] }
const CHECKS = `(a) shots tile 0 to the song's end exactly, no gaps or overlaps; (b) every cut within 0.03 s of a beat in analysis/beats.json or a declared hit in analysis/hits.json (snap it if not); (c) every sung word in analysis/words.json appears in the type list of a shot whose time range contains the word's t0, and every lyric line index appears in some shot's type list; (d) lead_on_screen fraction >= ${LEAD_MIN}; (e) in "seedance": motion + sung clip seconds <= ${MOTION_S} over <= ${CLIPS} clips, each motion clip 4–12 s, each sung clip 4–8 s with song_t0 inside a word gap (no word spans it) and words equal to the aligned words inside [song_t0, song_t0 + duration], every sung prompt quoting them exactly; two clips never start from the same plate frame; (f) ${BANNED.length ? `none of these words appear (case-insensitive) in either file: ${BANNED.join(', ')}` : 'no banned words from DECISIONS.md appear'}; (g) every plate referenced exists in "plates" and every plate is used; no plate on two non-continuous shots; (h) the 2.5D treatment never repeats on consecutive plate3d shots.`
let check = null
for (let round = 1; round <= ROUNDS && !(check && check.pass); round++) {
  const prev = check ? `\nAn earlier check round left these problems: ${JSON.stringify(check.remaining)}. Its last audit output: ${check.audit_output}` : ''
  const res = await agent(`${CTX}\n\nYou check the merged board with CODE, then fix it. Files: ${BOARD}/shots.json and ${BOARD}/STORYBOARD.md.\n1. Run the toolkit's audit: ${AUDIT_RUN} (it audits ${BOARD}/shots.json; if a flag is rejected, run ${q(`${AUDIT} --help`)} and use what it offers).\n2. Also check these with a python script you write and run (the audit may already cover some): ${CHECKS}\n3. FIX every violation directly in both files (keep them consistent), re-run the audit and your script, and repeat until everything passes or you have made 6 fix passes.\nNever edit analysis/*.json, lyrics/*, the audit code or project.json to make a check pass — that is cheating and the board is discarded (the bot re-runs the same audit on its own copy).${prev}\nWrite the final audit output and your script's output to ${OUT}/check-${round}.md. Return pass (true only if the audit and every check above pass), the last audit output lines, the final numbers, what you fixed, and what remains.`,
    { label: `audit:${round}`, phase: 'Check', schema: CHECK_SCHEMA })
  if (!res) log(`audit:${round} FAILED: returned nothing (usage limit?)`)
  else { check = res; log(`audit:${round} pass=${res.pass} remaining=${(res.remaining || []).length}`) }
}
const ok = !!(check && check.pass)
return { ok, error: ok ? null : (check ? `the board still fails the audit: ${JSON.stringify(check.remaining).slice(0, 400)}` : 'no audit result (every audit agent returned nothing)'),
  totals, ranked, judges_valid: valid.length, judge_failures: judgeFailures, boards: boards.map(b => ({ k: b.k, file: b.file, shots: b.shots, lead_fraction: b.lead_fraction, motion_s: b.motion_s })),
  merged, check }
