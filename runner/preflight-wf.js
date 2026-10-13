export const meta = {
  name: 'slop-preflight',
  description: 'Preflight of the Workflow path: one subagent writes one file with Bash and one with Write, proving headless workflow subagents get those tools under the runner permission flags',
  phases: [{ title: 'Probe', detail: 'one agent, two tiny files' }],
}
// Used by `node runner/deleg.mjs preflight claude --workflow` (not a production template). The runner checks the two
// files afterwards: <dir>/probe-bash.txt = "bash-ok" and <dir>/probe-write.txt = "write-ok".
// args (a JSON object): dir (required) — the folder for the probe files (the runner passes the job's outbox).
const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
if (!A.dir) return { ok: false, error: 'args missing: dir (the folder for the probe files)' }
const D = String(A.dir).replace(/\\/g, '/').replace(/\/+$/, '')
phase('Probe')
const r = await agent(`Do exactly these two things, nothing else, then reply with the single word DONE.
1. With the Bash tool (use the PowerShell tool only if there is no Bash tool), run this command exactly: node -e "require('fs').writeFileSync('${D}/probe-bash.txt', 'bash-ok')"
2. With the Write tool, create the file ${D}/probe-write.txt containing exactly: write-ok`,
  { label: 'probe', phase: 'Probe', effort: 'low' })
log(r == null ? 'probe FAILED: the subagent returned nothing' : 'probe returned')
return { ok: r != null, reply: r == null ? null : String(r).slice(0, 200) }
