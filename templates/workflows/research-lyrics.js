export const meta = {
  name: 'slop-research-lyrics',
  description: 'Research and lyrics: parallel research sweeps, an adversarial fact-check of every candidate, one ranked bank of verified references, four lyric drafts from different angles, three judges with JSON scores, a head-writer merge and a critic pass that fixes the sheet against the bank and the scansion lint',
  phases: [
    { title: 'Research', detail: 'parallel sweeps of current events, culture, quotes and a fact-check of existing lyrics' },
    { title: 'Verify', detail: 'adversarial check of every candidate fact that could enter the lyrics' },
    { title: 'Bank', detail: 'one ranked bank of verified references + a digest for the writers' },
    { title: 'Write', detail: 'four complete lyric drafts from different angles' },
    { title: 'Judge', detail: 'three lenses score every draft (JSON schema)' },
    { title: 'Merge', detail: 'the head writer merges; a critic checks facts, bars, scansion and banned words and fixes the files' },
  ],
}
// Claudia research + lyrics (Claude Code Workflow script). Generalised from the reference video's research-and-lyrics
// workflow (researchers -> verifiers -> bank -> 4 writers -> 3 judges -> merge -> critic). Intentional changes: no
// topic, date or audience hard-codes (args.today is required: workflow scripts cannot read the clock); sweeps are
// built from args.topics unless args.sweeps is given; outputs go to the job outbox (research/bank.md,
// lyrics/LYRICS.md, lyrics/lyrics.txt, lyrics/display.txt) in the toolkit's lyric file contract; the critic runs the
// toolkit's scansion lint (`slop --json lyrics lint FILE --ban W`: --json is a root flag); a null agent is logged as a failure and
// the run returns ok:false when too little survives.
// Resume: Workflow({scriptPath: <this file>, resumeFromRunId: <run>, args: <same args>}); finished files are skipped.
//
// args (a JSON object; the delegation runner fills project_dir, out_dir, toolkit_dir, job_dir and slop):
//   out_dir         (required) the job's outbox                    project_dir  the project folder (optional)
//   today           (required) YYYY-MM-DD                          title        the song's working title
//   concept         (required) what the song and video are about, in the owner's words
//   audience        who must get every reference (default "the people the owner posts for")
//   topics          [string] research areas (default: from the concept) — or sweeps: [{key, p}] full prompts
//   owner, owner_notes (verbatim notes, string or list), likes (lines/phrases the owner likes; keep them)
//   existing_lyrics a path to the current lyric draft (adds a fact-check sweep of it)
//   struct          the song constraints: length, BPM, sections and bar counts, sung vs spoken parts (string)
//   banned_words    [string]                                       angles [{key, a}]   lenses [string]
//   min_recognisability 1-5 (default 3)                            verify_batch (10)   slop (CLI, default "slop")
const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const miss = ['out_dir', 'today', 'concept'].filter(k => !A[k])
if (miss.length) return { ok: false, error: `args missing: ${miss.join(', ')} (today must be YYYY-MM-DD: the script cannot read the clock)` }
const clean = p => String(p).replace(/\\/g, '/').replace(/\/+$/, '')
const OUT = clean(A.out_dir), P = A.project_dir ? clean(A.project_dir) : null, TK = A.toolkit_dir ? clean(A.toolkit_dir) : null
const SLOP = A.slop || 'slop'
const OWNER = A.owner || 'the owner'
const AUD = A.audience || `the people ${OWNER} posts for`
const NOTES = Array.isArray(A.owner_notes) ? A.owner_notes.map(q => `"${q}"`).join(' / ') : (A.owner_notes || '')
const LIKES = Array.isArray(A.likes) ? A.likes : (A.likes ? [A.likes] : [])
const BANNED = Array.isArray(A.banned_words) ? A.banned_words.filter(Boolean) : []
const MINREC = Number(A.min_recognisability ?? 3), BATCH = Number(A.verify_batch ?? 10)
const BANK = `${OUT}/research/bank.md`, LYR = `${OUT}/lyrics/LYRICS.md`, TXT = `${OUT}/lyrics/lyrics.txt`, DISP = `${OUT}/lyrics/display.txt`
const END_BANK = '<!-- END OF BANK -->'
const q = s => '`' + s + '`'   // every command is quoted in backticks (the toolkit's tests parse each one)
// --json belongs to the root parser: `slop --json lyrics lint FILE` (after the subcommand it is rejected)
const LINT = q(`${SLOP} --json lyrics lint ${TXT}${BANNED.map(b => ` --ban "${b}"`).join('')}`)

const CTX = `Project: ${OWNER}'s AI-made lyric music video${A.title ? ` "${A.title}"` : ''}. Today is ${A.today}. Audience: ${AUD}.
Concept: ${A.concept}
${NOTES ? `${OWNER}'s notes, verbatim (binding): ${NOTES}\n` : ''}${LIKES.length ? `${OWNER} likes these and they stay: ${LIKES.map(l => `"${l}"`).join(', ')}.\n` : ''}${P ? `Project files: ${P}/PRODUCTION.md if it exists (the binding plan), ${P}/project.json, ${P}/DECISIONS.md (binding decisions), ${P}/research/ (earlier research, if any).\n` : ''}${TK ? `Toolkit playbook: ${TK}/docs/10-song.md (lyric writing with scansion, the Suno pack).\n` : ''}${BANNED.length ? `HARD RULE: these words never appear anywhere: ${BANNED.join(', ')}.\n` : ''}Never invent events, dates, numbers or quotes. Refer to ${OWNER} only by that name.`

const ITEM = { type: 'object', properties: { items: { type: 'array', items: { type: 'object', properties: {
  name: { type: 'string' }, what: { type: 'string', description: 'one-line explanation' }, date: { type: 'string' },
  recognisability: { type: 'integer', description: `1-5 for ${AUD}` }, lyric_hook: { type: 'string', description: 'a phrase or fact that could sit in a lyric line' },
  visual: { type: 'string', description: 'a one-glance visual for a frame' }, sources: { type: 'array', items: { type: 'string' } },
  confidence: { type: 'string', enum: ['verified-2-sources', 'single-source', 'unverified'] }, risk: { type: 'string' } },
  required: ['name', 'what', 'date', 'recognisability', 'lyric_hook', 'visual', 'sources', 'confidence', 'risk'] } }, notes: { type: 'string' } }, required: ['items', 'notes'] }
const slug = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 30) || 'topic'
const TOPICS = Array.isArray(A.topics) && A.topics.length ? A.topics : [A.concept]
const SWEEPS = Array.isArray(A.sweeps) && A.sweeps.length ? A.sweeps : [
  ...TOPICS.map(t => ({ key: slug(t), p: `Find what ${AUD} is talking about RIGHT NOW (the 8 weeks before ${A.today}, weighted to the last 3) about: ${t}. Events, launches, incidents, memes, phrases, image macros, IRL culture, viral posts. Explain each fully (what happened, when, who, why it became a meme). 25-40 items.` })),
  { key: 'quotes', p: `Find the most-quoted short LINES of the last months that ${AUD} repeats, screenshots or parodies, around: ${TOPICS.join('; ')}. Lyric-sized lines (under ~12 words) with the exact wording, the speaker and a source. Exact quotes only, never invent or tidy wording. 20-35 items.` },
  ...(A.existing_lyrics ? [{ key: 'factcheck-old', p: `Fact-check every factual claim in the current lyrics ${clean(A.existing_lyrics)}. Read it; for each reference search for at least two independent sources. Return each as an item with confidence set honestly, and in "risk" state exactly what is wrong or uncertain in the lyric's wording.` }] : []),
]

phase('Research')
const research = await parallel(SWEEPS.map(s => () => agent(`${CTX}\n\nTASK (${s.key}): ${s.p}\n\nUse web search and fetch extensively (if WebSearch/WebFetch are not loaded, load them with ToolSearch "select:WebSearch,WebFetch"; curl in Bash for raw pages). Read-only: never log in, post, sign up or submit anything. Dates on everything (the event's date). If you cannot find a source, mark the item unverified. Also save your items as JSON to ${OUT}/research/sweep-${s.key}.json. Return structured items.`,
  { label: `research:${s.key}`, phase: 'Research', schema: ITEM })))
const all = []
SWEEPS.forEach((s, i) => {
  const r = research[i]
  if (!r || !Array.isArray(r.items)) { log(`research:${s.key} FAILED: returned nothing (usage limit?)`); return }
  for (const it of r.items) all.push({ ...it, bucket: s.key })
})
const okSweeps = SWEEPS.filter((s, i) => research[i] && Array.isArray(research[i].items)).length
log(`research: ${all.length} items from ${okSweeps}/${SWEEPS.length} sweeps`)
if (okSweeps * 2 < SWEEPS.length || !all.length) return { ok: false, error: `only ${okSweeps} of ${SWEEPS.length} research sweeps returned: resume after the cause (often a usage limit) is gone`, items: all.length }

phase('Verify')
const VERDICT = { type: 'object', properties: { results: { type: 'array', items: { type: 'object', properties: {
  name: { type: 'string' }, status: { type: 'string', enum: ['confirmed', 'wording-fix', 'refuted', 'unverifiable'] },
  correct_fact: { type: 'string' }, sources: { type: 'array', items: { type: 'string' } } }, required: ['name', 'status', 'correct_fact', 'sources'] } } }, required: ['results'] }
const top = all.filter(it => Number(it.recognisability) >= MINREC || it.bucket === 'factcheck-old')
const chunks = []
for (let i = 0; i < top.length; i += BATCH) chunks.push(top.slice(i, i + BATCH))
log(`verifying ${top.length} items in ${chunks.length} batches (items below recognisability ${MINREC} are not verified and never used)`)
const vres = await parallel(chunks.map((c, i) => () => agent(`${CTX}\n\nYou are an adversarial fact-checker. For each item below, try to REFUTE it: search independently (do not trust the listed sources alone), check the date, the numbers, the names and the exact wording of quotes. Default to "unverifiable" if you cannot find an independent source. "wording-fix" means the event is real but a detail (number, date, quote wording) is off — give the correct version.\n\nITEMS:\n${JSON.stringify(c.map(x => ({ name: x.name, what: x.what, date: x.date, lyric_hook: x.lyric_hook, sources: x.sources })), null, 1)}`,
  { label: `verify:${i + 1}`, phase: 'Verify', schema: VERDICT })))
const verdicts = []
vres.forEach((v, i) => { if (!v || !Array.isArray(v.results)) log(`verify:${i + 1} FAILED: returned nothing — its ${chunks[i].length} items stay unverified and are not used`); else verdicts.push(...v.results) })

phase('Bank')
const bank = await agent(`${CTX}\n\nIf ${BANK} already exists and its last line is ${END_BANK}, it is the finished bank from an interrupted run: do not rewrite it; return its digest (the sections described below).\n\nOtherwise merge this research into ONE reference bank file at ${BANK} (markdown). Sections: (1) status legend; (2) the 40 best lyric candidates ranked by fresh x recognisable x lyric-able x visual, each with the verified fact, the exact lyric hook, a one-glance visual, date, sources and verification status; (3) the tensions and through-lines the concept suggests, with the 10 best lines for them; (4) ${A.existing_lyrics ? 'the fact-check table for the existing lyrics (keep / fix wording / cut)' : 'what to avoid (stale, overused, risky)'}; (5) everything else, grouped, shorter. Drop anything refuted. Only items with status confirmed or wording-fix may appear in section 2; mark unverifiable items clearly. Put real deaths, minors, private people and legally risky claims in a "handle with care" list. End the file with the line ${END_BANK}.\n\nRAW ITEMS:\n${JSON.stringify(all)}\n\nVERDICTS:\n${JSON.stringify(verdicts)}\n\nReturn a compact plain-text digest (<= 1800 words) of sections 2, 3 and 4 that lyric writers can use directly.`,
  { label: 'bank', phase: 'Bank' })
if (!bank) return { ok: false, error: 'the bank agent returned nothing: resume the run (research replays from cache)', items: all.length, verdicts: verdicts.length }

phase('Write')
const STRUCT = `SONG CONSTRAINTS: ${A.struct || 'about 2:00–3:00; verse / pre-chorus / chorus / verse / chorus / bridge / final chorus / outro; dense verses (ideally two references per couplet), a short, singable chorus with clear vowels and a rhyme anchor'}. Spoken lines at the song's tempo hold about 6–10 syllables per bar; sung lines fewer. Suno formatting: section tags like [Verse 1 - spoken, deadpan] with bar counts; spell numbers, symbols and acronyms the way they are sung ("A G I", "eighteen", "plus twenty-five percent"). Only facts marked confirmed or wording-fix in the bank. Fully original lines: never quote or closely paraphrase an existing song.${BANNED.length ? ` Never: ${BANNED.join(', ')}.` : ''}`
const ANGLES = Array.isArray(A.angles) && A.angles.length ? A.angles : [
  { key: 'density', a: 'Maximum reference density: every line lands a fresh, current reference; the verses read like a timeline scroll.' },
  { key: 'tension', a: 'Tension: the concept\'s strongest opposing forces set against each other and resolved by the end; still reference-dense.' },
  { key: 'hook', a: 'Hook-first pop craft: the most singable, repeatable chorus and post-chorus chant possible; verses tight and funny.' },
  { key: 'format', a: 'Format purist: every line lives inside the video\'s central device or format (a show, a broadcast, a manual, a feed — whatever the concept implies); jokes come from the collision of that format and the references.' },
]
const DK = ANGLES.map(g => g.key)
const draftFile = k => `${OUT}/lyrics/drafts/${k}.md`
const wres = await parallel(ANGLES.map(g => () => agent(`${CTX}\n\nYou are a lyricist. Angle: ${g.a}\n\n${STRUCT}\n\nVERIFIED REFERENCE BANK DIGEST:\n${bank}\n${A.existing_lyrics ? `\nAlso read the current draft ${clean(A.existing_lyrics)}.` : ''}\nIf ${draftFile(g.key)} already exists and is complete, return it unchanged. Otherwise write a COMPLETE lyric sheet in Suno-ready format (section tags with bar counts; under each section a short italic line listing the references used) to ${draftFile(g.key)}, and return the sheet.`,
  { label: `write:${g.key}`, phase: 'Write' })))
const drafts = []
wres.forEach((t, i) => { if (t && String(t).trim()) drafts.push({ key: DK[i], text: String(t) }); else log(`write:${DK[i]} FAILED: returned nothing`) })
if (drafts.length < 2) return { ok: false, error: `only ${drafts.length} draft(s): resume the run`, bank: BANK }
const DRK = drafts.map(d => d.key)

phase('Judge')
const SCORE = { type: 'object', properties: { scores: { type: 'array', items: { type: 'object', properties: {
  draft: { type: 'string', enum: DRK }, total: { type: 'number', description: '0-100' }, density: { type: 'number' }, currency: { type: 'number' }, hook: { type: 'number' },
  wit: { type: 'number' }, arc: { type: 'number' }, singability: { type: 'number' },
  rules: { type: 'number', description: '0 if a banned word appears or a fact not confirmed/wording-fix in the bank is used' },
  best_lines: { type: 'array', items: { type: 'string' } }, worst_lines: { type: 'array', items: { type: 'string' } } },
  required: ['draft', 'total', 'density', 'currency', 'hook', 'wit', 'arc', 'singability', 'rules', 'best_lines', 'worst_lines'] } } }, required: ['scores'] }
const LENSES = Array.isArray(A.lenses) && A.lenses.length ? A.lenses : [
  `a power user of ${AUD}: does each line get an instant laugh or nod? is it current? would people screenshot lines?`,
  'a pop songwriter / topliner: will Suno sing it cleanly, is the chorus an earworm, do lines scan at the tempo, is the structure right for the length?',
  `a ruthless editor: clichés, filler, forced themes, weak rhymes, anything unverified or banned, ${OWNER}'s stated likes kept?`,
]
const jres = await parallel(LENSES.map((l, i) => () => agent(`${CTX}\n\nYou are a judge: ${l}\nScore each draft 0-10 on density, currency, hook, wit, arc, singability, rules, and a total 0-100. Quote the 5 best and 5 worst lines of each. Use exactly these draft names: ${DRK.join(', ')}; score every draft.\n\nBANK DIGEST (the only allowed facts):\n${bank}\n\nDRAFTS:\n${drafts.map(d => `=== DRAFT ${d.key} ===\n${d.text}`).join('\n\n')}`,
  { label: `judge:${i + 1}`, phase: 'Judge', schema: SCORE })))
const valid = []
jres.forEach((j, i) => {
  if (!j || !Array.isArray(j.scores)) { log(`judge:${i + 1} FAILED: returned nothing`); return }
  const by = {}; for (const s of j.scores) if (s && DRK.includes(s.draft) && typeof s.total === 'number') by[s.draft] = s
  const gap = DRK.filter(k => !by[k]); if (gap.length) { log(`judge:${i + 1} FAILED: no score for ${gap.join(', ')}`); return }
  valid.push(by)
})
const totals = {}; DRK.forEach(k => { totals[k] = valid.map(v => v[k].total) })
log(`judge totals ${JSON.stringify(totals)} (valid judges ${valid.length})`)

phase('Merge')
const merged = await agent(`${CTX}\n\n${STRUCT}\n\nYou are the head writer. ${valid.length ? 'Using the drafts and the judges\' scores and best/worst lines' : 'No judge returned a valid score: score the drafts yourself through these lenses first — ' + LENSES.join(' · ') + ' — then'}, write the final lyric sheet: start from the highest-scoring draft, graft in the best lines of the others, cut every worst line. Write THREE files:\n1) ${LYR}: a header with the title and date (${A.today}), a 5-line note on what changed and why, the Suno-ready sheet (section tags with bar counts) with an italic references line under each section (source and date of every fact), then a "Suno lyrics field" block (exactly what to paste: tags kept, notes removed, numbers spelled as sung), then a "Fact status" table (line -> fact -> status from the bank).\n2) ${TXT}: the sung words only, one lyric line per line, no tags, numbers and symbols spelled as sung.\n3) ${DISP}: the on-screen tokens, one line per lyric line, same line count as lyrics.txt; where a token stands for several sung words write TEXT|n (e.g. "+25%|4" for "plus twenty-five percent").\n\nBANK DIGEST:\n${bank}\n\nDRAFTS:\n${drafts.map(d => `=== DRAFT ${d.key} ===\n${d.text}`).join('\n\n')}\n\nJUDGES:\n${JSON.stringify(valid)}\n\nReturn the final Suno block as your answer.`,
  { label: 'merge', phase: 'Merge' })
if (!merged) return { ok: false, error: 'the merge returned nothing: resume the run', totals }
const CRIT = { type: 'object', properties: {
  pass: { type: 'boolean' }, lint: { type: 'string', description: 'the last lines the scansion lint printed' }, bars: { type: 'number' },
  changed: { type: 'array', items: { type: 'string' } }, risks: { type: 'array', items: { type: 'string' } } }, required: ['pass', 'lint', 'changed', 'risks'] }
let critic = await agent(`${CTX}\n\n${STRUCT}\n\nCritic pass on ${LYR}, ${TXT} and ${DISP} (read them and ${BANK}). Check, with code where you can: ${BANNED.length ? `none of ${BANNED.join(', ')} appears (case-insensitive);` : ''} every fact used has status confirmed or wording-fix in the bank; the bar total and section lengths match the constraints and each spoken line fits its bars (count syllables); run the toolkit's scansion lint: ${LINT} (if a flag is rejected, run ${q(`${SLOP} lyrics lint --help`)} and use what it offers) and fix what it flags; lyrics.txt and display.txt have the same number of lines and match the sheet; the chorus is singable; ${OWNER}'s likes are kept. FIX problems directly in the files (keep the formats), re-run the lint, then return pass, the lint's last lines, the bar count, what you changed and any remaining risks.`,
  { label: 'critic', phase: 'Merge', schema: CRIT })
if (!critic) { log('critic FAILED: returned nothing; retrying once'); critic = await agent(`${CTX}\n\nThe previous critic returned nothing. Do the critic pass on ${LYR}, ${TXT} and ${DISP} against ${BANK}: banned words, fact statuses, bars and syllables, the lint ${LINT}, line counts. Fix the files, then return pass, lint, changed, risks.`, { label: 'critic:2', phase: 'Merge', schema: CRIT }) }
const ok = !!(critic && critic.pass)
return { ok, error: ok ? null : (critic ? `the critic still sees problems: ${JSON.stringify(critic.risks).slice(0, 300)}` : 'no critic result (null twice)'),
  files: { bank: BANK, lyrics: LYR, lyrics_txt: TXT, display_txt: DISP }, counts: { items: all.length, verified: verdicts.length, sweeps_ok: okSweeps, sweeps: SWEEPS.length },
  totals, judges_valid: valid.length, critic, lyrics: merged }
