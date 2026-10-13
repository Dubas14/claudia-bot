// devices/camera.js — the camera plays the track: punch (a zoom kick on kicks), shake (handheld energy scaled by the drum
// envelope), ride (a push that rides a riser into its hit), impact (a real hit: a big zoom kick + a shake burst), whip (a
// pan through a cut or a fill), snap (snap zooms on beats with a two-frame overshoot). These devices draw nothing: the
// default renderer folds every camera device active at t into one move (DEV.camFx) and draws the footage through it
// (CAM.through: the zoom covers any shake, so no frame edge shows; m.map / m.box stay aligned).
// Rules carried from the source: a move answers a sound you can hear (punch is gated by the drum envelope; no shake in UI
// shots); hold still where the song breathes. With window.HITS the moves read the real events (H); without it they fall
// back to the beat map (B) so a draft still moves on the beat.
// Port of the engine's hits.js CAM.* parameters (defaults kept: punch .02/τ .13, shake 6 px/7 Hz/γ 1.6, ride .06/2.2/.09,
// impact .06/14 px/τ .3, whip 520 px/180 px/.24 s) and the second video's snap zoom (.09 · e^(−age/.045)) with its
// alternating 18 px lateral jag (dx = ±18 · e^(−age/.045), the sign flipping on every snap).
'use strict';
(() => {
  const D = window.DEV; if (!D || D.REG['cam.punch']) return;
  const noop = () => {};
  const CAMS = {
    'cam.punch': { amp: .02, kind: 'kick', every: null, phase: 0, tau: .13, atk: .03, gate: true, minS: 0 },
    'cam.shake': { amp: 6, rot: .002, freq: 7, gamma: 1.6, stem: 'drums', seed: 3 },
    'cam.ride': { amp: .06, curve: 2.2, release: .09, hold: false },
    'cam.impact': { amp: .06, shake: 14, rot: .006, burst: .22, tau: .3, atk: .035, minS: .6 },
    'cam.whip': { at: null, dir: 0, dist: 520, blur: 180, dur: .24, fill: false },
    'cam.snap': { amp: .09, every: 1, kind: 'beat', tau: .045, jag: 18 },
  };
  const DOC = {
    'cam.punch': 'A zoom kick on the kicks (or vocal entries with kind: "vox"): the footage feels the beat.',
    'cam.shake': 'Handheld energy scaled by the drum envelope: tension, chaos, a crowd.',
    'cam.ride': 'A push that rides a riser into its hit and snaps back on it: anticipation landing.',
    'cam.impact': 'The real hits (drops, section starts): a big zoom kick plus a shake burst.',
    'cam.whip': 'A whip pan through a cut or a drum fill: motion carried across the edit.',
    'cam.snap': 'Snap zooms on the beats with a two-frame overshoot: stills that cut in rhythm.',
  };
  Object.entries(CAMS).forEach(([kind, defaults]) => D.register(kind, { role: 'camera', keys: 'BHFW', defaults, draw: noop, doc: DOC[kind],
    alias: [kind.replace('cam.', 'camera.')], example: { kind, key: 'B', params: kind === 'cam.whip' ? { at: 'shot.t1' } : {} } }));

  // every camera instance active at t → {fx (for CAM.through / CAM.fx), base: {zoom add, dx, dy, rot} for the no-hits path}
  D.camFx = (insts, t, sh) => {
    const fx = {}, hits = D.has.HIT(); let zoom = 0, dx = 0, dy = 0, rot = 0;
    for (const inst of insts) {
      if (inst.role !== 'camera' || t < inst.t0 - .3 || t >= inst.t1 + .3) continue;
      const p = Object.assign({}, inst.p), k = inst.kind;
      if (k === 'cam.snap') { const e = p.kind === 'beat' || !hits ? { t: D.tAtBeat(Math.floor(bpOf(t) / (p.every || 1)) * (p.every || 1)) } : HIT.last(t, p.kind, { within: 1 });
        if (e && e.t >= inst.t0 - 1e-6 && t >= e.t) { const j = Math.exp(-(t - e.t) / p.tau), k = Math.round((bpOf(e.t) - bpOf(inst.t0)) / (p.every || 1));
          zoom += p.amp * j; dx += (((k % 2) + 2) % 2 ? -1 : 1) * (p.jag ?? 18) * j; } continue; }
      if (k === 'cam.whip') { const at = p.at != null ? D.time(p.at, sh || inst.sh, inst.t1) : (p.fill ? null : inst.t1); fx.whip = Object.assign({}, p, { at }); continue; }
      if (hits) { fx[k.slice(4)] = p; continue; }
      // the beat map stands in for the track's events
      if (k === 'cam.punch') { const ev = p.every > 1 ? (((Math.floor(bpOf(t)) % p.every) + p.every) % p.every === (p.phase || 0)) : true; if (ev) zoom += p.amp * D.kick(t); }
      if (k === 'cam.shake' && typeof shake === 'function') { const [sx, sy] = shake(t, p.amp / W * 2.5); dx += sx * W; dy += sy * H; }
      if (k === 'cam.ride') { const db = (SONG.downbeats || []).find(v => v > t); if (db && db - t < 2 * D.bl(t)) zoom += p.amp * Math.pow(1 - (db - t) / (2 * D.bl(t)), p.curve); }
      if (k === 'cam.impact') { const db = (SONG.downbeats || []).filter(v => v <= t).pop(); if (db != null && t - db < 1) zoom += p.amp * Math.exp(-(t - db) / p.tau); }
    }
    if (zoom) fx.zoom = (fx.zoom || 0) + zoom; if (dx) fx.dx = dx; if (dy) fx.dy = dy; if (rot) fx.rot = rot;
    return fx;
  };
  D.hasCamFx = fx => Object.keys(fx).length > 0;
})();
