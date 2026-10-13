export const meta = {
  name: 'slop-safety-scan',
  description: 'Safety and canon scan of every final generated take before release: N agents each take a slice of a list file, look at six frames of every take, and report block / fix / note findings; a slice that returns nothing or skips takes is a failure',
  phases: [{ title: 'Scan', detail: 'each agent looks at six frames of every take in its slice' }],
}
// Claudia safety + canon scan (Claude Code Workflow script). Generalised from the reference video's release scan
// (96 takes, 6 agents, 8 minutes: 12 blocks found). Intentional changes: the video's world, the lead's canon and the
// cast rules come from args/project.json instead of being hard-coded; the take list is ALWAYS a file each agent
// slices itself (passing 96 paths inline once let a placeholder through and the run was killed); a slice that returns
// nothing, or checks fewer takes than it was given, makes the run fail (ok:false + "unchecked") instead of passing.
//
// args (a JSON object; the delegation runner fills project_dir, out_dir, toolkit_dir, job_dir and slop):
//   list         (required) path (absolute, or relative to project_dir) of a JSON list of takes: [{clip, file, shots?, song_t0?, dur?}] (file is relative to
//                project_dir unless absolute, so one list works on the bot's box and on the user's computer)
//   total        (required) number of entries in the list (the script cannot read files: it is checked by the agents)
//   out_dir      (required) the job's outbox                          project_dir   the project folder
//   slices       number of agents (default 6, max 16)                 scratch_dir   default <project_dir>/render/scratch/scan
//   world        one paragraph: who is who, the places and the era of the video (default: read project.json/DECISIONS.md)
//   canon        the lead's canon text (also accepted as lead_canon, the brief's LEAD_CANON; default: project.json lead.canon)
//   fix_rules    [string] extra "fix" findings for this video (cast look-alikes, props that must not appear, …)
//   block_rules  [string] extra "block" findings for this video (e.g. a modern object in a period scene)
const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const miss = ['list', 'total', 'out_dir'].filter(k => !A[k])
if (miss.length) return { ok: false, error: `args missing: ${miss.join(', ')} (write the take list to a JSON file and pass its path; never inline the takes)` }
const clean = p => String(p).replace(/\\/g, '/').replace(/\/+$/, '')
const OUT = clean(A.out_dir), P = A.project_dir ? clean(A.project_dir) : null, TOTAL = Number(A.total)
const LIST = /^([a-zA-Z]:)?\//.test(clean(A.list)) || !P ? clean(A.list) : `${P}/${clean(A.list)}`
if (!(TOTAL > 0)) return { ok: false, error: 'total must be the number of takes in the list (> 0)' }
const per = Math.ceil(TOTAL / Math.max(1, Math.min(16, Number(A.slices || 6), TOTAL)))
const N = Math.ceil(TOTAL / per)   // never an agent with an empty slice (7 takes over 6 asked slices = 4 slices of 2,2,2,1)
const SCR = A.scratch_dir ? clean(A.scratch_dir) : (P ? `${P}/render/scratch/scan` : `${OUT}/scan-scratch`)
const WORLD = A.world || (P ? `read ${P}/PRODUCTION.md if it exists, ${P}/project.json and ${P}/DECISIONS.md for who is who, the places and the era` : 'a lyric music video')
const CANON = A.canon || A.lead_canon || (P ? `the lead's canon text in ${P}/project.json "lead"` : 'the lead as described in the brief')
const BLOCK = ['any nudity or visible genitals/nipples (even glowing, translucent or statue-like figures)', 'sexual content', 'gore', 'a minor', 'text, logos or watermarks readable in frame', 'a real, recognisable person', ...(A.block_rules || [])]
const FIX = ['the lead is off-canon (compare with the canon: hair, colour accents, outfit, accessories)', 'obvious generation glitches (melting or doubled faces, extra limbs or fingers, a face morphing into another person, objects warping)', 'background people who look like copies of a lead character', ...(A.fix_rules || [])]
const SCHEMA = { type: 'object', properties: {
  findings: { type: 'array', items: { type: 'object', properties: { clip: { type: 'string' }, time: { type: 'number' }, severity: { type: 'string', enum: ['block', 'fix', 'note'] }, kind: { type: 'string' }, what: { type: 'string' } }, required: ['clip', 'severity', 'kind', 'what'] } },
  checked: { type: 'array', items: { type: 'string' } }, given: { type: 'number', description: 'how many takes your slice contained' } },
  required: ['findings', 'checked', 'given'] }

phase('Scan')
const res = await parallel(Array.from({ length: N }, (_, i) => () => agent(`You are checking finished AI-generated video takes for a PUBLIC music video before release. The video: ${WORLD}. The lead's canon: ${CANON}.
Your takes: read the JSON list ${LIST} with a short python command (python3 -c "import json;print(json.dumps(json.load(open('${LIST}'))[${i * per}:${(i + 1) * per}]))", or python on Windows) — entries ${i * per} to ${Math.min(TOTAL, (i + 1) * per) - 1}, each {clip, file, ...}; a relative "file" is relative to ${P || 'the project folder'}.
For EACH take: get its duration with ffprobe, extract 6 frames at 8%, 25%, 42%, 58%, 75% and 92% of it with ffmpeg at 640 px wide into ${SCR}/${i}/ (give ffmpeg < /dev/null so it cannot eat a loop's input), tile them into one 3x2 contact sheet per take with Python PIL (label each tile with its time), and Read every sheet. Look carefully.
Report every problem with the clip name, the time in the clip, a severity and a kind:
- severity "block" (must not ship): ${BLOCK.join('; ')}.
- severity "fix": ${FIX.join('; ')}.
- severity "note": small things worth knowing (soft focus, a brief oddity).
Do not report the grade or colour. Do not edit, move or delete any file except your own sheets in ${SCR}/${i}/.
Return the findings (empty if every take is clean), the list of clips you checked, and how many takes your slice contained.`,
  { label: `scan:${i}`, phase: 'Scan', schema: SCHEMA, effort: 'high' })))
const unchecked = []
let checked = 0
res.forEach((r, i) => {
  const want = Math.max(0, Math.min(TOTAL, (i + 1) * per) - i * per)
  if (!r || !Array.isArray(r.checked)) { unchecked.push({ slice: i, missing: want, why: 'returned nothing (usage limit?)' }); log(`scan:${i} FAILED: returned nothing`); return }
  checked += r.checked.length
  if (r.checked.length < want) { unchecked.push({ slice: i, missing: want - r.checked.length, why: 'checked fewer takes than its slice' }); log(`scan:${i} FAILED: checked ${r.checked.length} of ${want}`) }
})
const findings = res.filter(Boolean).flatMap(r => r.findings || [])
const count = s => findings.filter(f => f.severity === s).length
log(`scan: ${checked}/${TOTAL} takes checked; block ${count('block')} fix ${count('fix')} note ${count('note')}`)
return { ok: unchecked.length === 0 && checked >= TOTAL, error: unchecked.length ? `unchecked takes in ${unchecked.length} slice(s): resume the run` : null,
  checked, of: TOTAL, counts: { block: count('block'), fix: count('fix'), note: count('note') }, unchecked, findings }
