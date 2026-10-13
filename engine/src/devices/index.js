// devices/index.js — loads the device library in order (the engine page includes this one file; `slop render` lists it
// as the device file). Each file registers its devices with DEV (devices/_base.js) and, when the engine is loaded, with
// ENGINE.registerDevice, so ENGINE.drawDevice(spec, env) draws them too. Safe to load twice (every file guards itself).
'use strict';
(() => {
  if (window.DEV && window.DEV._base && window.DEV.treat) return;
  const FILES = ['_base.js', 'type.js', 'cv.js', 'ui.js', 'cards.js', 'flap.js', 'gauges.js', 'charts.js', 'voice.js', 'explain.js', 'flash.js', 'camera.js', 'hud.js', 'treat.js', 'trans.js'];
  const me = (document.currentScript && document.currentScript.src) || '', dir = me.replace(/[^/]*$/, '');
  window.DEVICE_FILES = FILES;
  if (document.readyState === 'loading') FILES.forEach(f => document.write(`<script src="${dir}${f}"><\/script>`));
  else window.DEV_LOADING = FILES.reduce((pr, f) => pr.then(() => new Promise(res => { const s = document.createElement('script'); s.src = dir + f; s.onload = s.onerror = res; document.head.appendChild(s); })), Promise.resolve());
})();
