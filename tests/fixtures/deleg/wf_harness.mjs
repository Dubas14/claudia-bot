#!/usr/bin/env node
// Test harness for Claude Code Workflow scripts (templates/workflows/*.js): runs a script with stubbed
// agent()/parallel()/pipeline()/phase()/log(), canned agent answers from a scenario file, and the same determinism
// rules as the real runtime (Date.now(), new Date() and Math.random() throw). Prints one JSON object:
//   {meta, result, calls: [{label, phase, schema, effort, prompt}], logs, phases, issues, max_active}
// (max_active = the most agent() calls in flight at once: checks a script's own concurrency cap)
// usage: node wf_harness.mjs <script.js> <scenario.json>
// scenario: {"args": {...}, "responses": [{"match": "<regex on label>", "value": <any|null>, "times": n?}], "default": <any|null>}
import fs from 'node:fs';

const [, , scriptPath, scenarioPath] = process.argv;
const src = fs.readFileSync(scriptPath, 'utf8');
const sc = JSON.parse(fs.readFileSync(scenarioPath, 'utf8'));
const issues = [];
if (!src.startsWith('export const meta = {')) issues.push('script must begin with "export const meta = {"');
// meta must be a pure literal: evaluate it with nothing in scope
let i = src.indexOf('{'), depth = 0, end = -1, inStr = null;
for (let k = i; k < src.length; k++) {
  const ch = src[k];
  if (inStr) { if (ch === '\\') { k++; continue; } if (ch === inStr) inStr = null; continue; }
  if (ch === "'" || ch === '"' || ch === '`') { inStr = ch; continue; }
  if (ch === '{') depth++;
  else if (ch === '}') { depth--; if (depth === 0) { end = k; break; } }
}
let meta = null;
try { meta = Function('"use strict"; return (' + src.slice(i, end + 1) + ');')(); } catch (e) { issues.push('meta is not a pure literal: ' + e.message); }
const body = src.slice(end + 1);

const RealDate = Date;
globalThis.Date = class extends RealDate {
  constructor(...a) { if (!a.length) throw new Error('new Date() is not allowed in workflow scripts'); super(...a); }
  static now() { throw new Error('Date.now() is not allowed in workflow scripts'); }
};
Math.random = () => { throw new Error('Math.random() is not allowed in workflow scripts'); };

const calls = [], logs = [], phases = [];
let active = 0, maxActive = 0;
const responses = (sc.responses || []).map(r => ({ ...r, re: new RegExp(r.match), used: 0 }));
async function agent(prompt, opts = {}) {
  if (typeof prompt !== 'string') issues.push(`agent ${opts.label}: prompt is not a string`);
  const p = String(prompt);
  for (const bad of ['undefined', '[object Object]', 'NaN', '${']) if (p.includes(bad)) issues.push(`agent ${opts.label}: prompt contains "${bad}"`);
  if (!opts.label) issues.push('agent without a label');
  calls.push({ label: opts.label, phase: opts.phase, schema: opts.schema || null, effort: opts.effort || null, prompt: p });
  const r = responses.find(x => x.re.test(opts.label || '') && (x.times == null || x.used < x.times));
  active++; maxActive = Math.max(maxActive, active);
  await new Promise(res => setTimeout(res, 1 + (calls.length % 3)));   // uneven latencies, like real agents
  active--;
  if (r) { r.used++; return r.value === undefined ? null : JSON.parse(JSON.stringify(r.value)); }
  return sc.default === undefined ? null : JSON.parse(JSON.stringify(sc.default));
}
const parallel = async fns => Promise.all(fns.map(f => f()));
const pipeline = async (items, ...stages) => Promise.all(items.map(async (it, idx) => {
  let r = await stages[0](it, idx);
  for (const s of stages.slice(1)) r = await s(r, it, idx);
  return r;
}));
const phase = t => { phases.push(t); };
const log = m => { logs.push(String(m)); };

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
let result = null, error = null;
try {
  const fn = new AsyncFunction('args', 'phase', 'log', 'agent', 'parallel', 'pipeline', body);
  result = await fn(sc.args, phase, log, agent, parallel, pipeline);
} catch (e) { error = String(e && e.stack || e); }
if (meta && Array.isArray(meta.phases)) for (const ph of phases) if (!meta.phases.some(m => m.title === ph)) issues.push(`phase("${ph}") is not declared in meta.phases`);
for (const c of calls) if (c.phase && meta && !meta.phases.some(m => m.title === c.phase)) issues.push(`agent ${c.label} uses undeclared phase "${c.phase}"`);
process.stdout.write(JSON.stringify({ meta, result, error, calls, logs, phases, issues, max_active: maxActive }) + '\n');
