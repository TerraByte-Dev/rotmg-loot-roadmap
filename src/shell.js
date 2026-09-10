// Desktop-only chrome. In a browser this file does nothing at all — roadmap.html is
// still the same page, so the version already sitting in someone's Downloads folder
// cannot break because of anything in here.
//
// Rust holds no state. Pin and opacity live in localStorage beside the app's other
// rm.* keys, and are re-applied on every launch.

const T = globalThis.__TAURI__;
if (T) {
  const w = T.window.getCurrentWindow();

  const read = (k, fallback) => {
    try {
      const v = localStorage.getItem(k);
      return v == null ? fallback : JSON.parse(v);
    } catch (_) { return fallback; }        // private window, cleared storage, corrupt value
  };
  const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) {} };

  let pinned = read("rm.pin", true) !== false;   // on top by default: that is the point of it
  let alpha = Math.min(1, Math.max(0.35, Number(read("rm.opacity", 1)) || 1));

  const applyPin = () => w.setAlwaysOnTop(pinned).catch(() => {});
  const applyAlpha = () =>
    T.core.invoke("set_window_opacity", { alpha }).catch(() => {});

  // --- the strip -----------------------------------------------------------
  // Deliberately tiny and bottom-left, out of the way of the class rail's top.
  const bar = document.createElement("div");
  bar.className = "shellbar";
  bar.innerHTML =
    `<button id="shell-pin" type="button" title="keep this window above the game"></button>` +
    `<input id="shell-op" type="range" min="35" max="100" step="5" title="window opacity">`;
  document.body.appendChild(bar);

  const css = document.createElement("style");
  css.textContent = `
    .shellbar{position:fixed;left:9px;bottom:9px;z-index:99;display:flex;gap:7px;
      align-items:center;background:var(--bg-panel);border:1px solid var(--line);
      border-radius:var(--radius);padding:4px 7px;opacity:.55;transition:opacity .12s}
    .shellbar:hover{opacity:1}
    .shellbar button{background:none;border:0;color:var(--ink-faint);cursor:pointer;
      font:inherit;font-size:13px;line-height:1;padding:0}
    .shellbar button.on{color:var(--accent)}
    .shellbar input[type=range]{width:74px;accent-color:var(--accent)}`;
  document.head.appendChild(css);

  const pinBtn = bar.querySelector("#shell-pin");
  const opIn = bar.querySelector("#shell-op");
  const paint = () => {
    pinBtn.textContent = pinned ? "◉ on top" : "○ floating";
    pinBtn.classList.toggle("on", pinned);
  };

  pinBtn.addEventListener("click", () => {
    pinned = !pinned; write("rm.pin", pinned); paint(); applyPin();
  });
  opIn.addEventListener("input", () => {
    alpha = opIn.value / 100; write("rm.opacity", alpha); applyAlpha();
  });

  opIn.value = Math.round(alpha * 100);
  paint(); applyPin(); applyAlpha();


  // TEMP DIAGNOSTIC - reports computed sprite geometry through the window title, which
  // is readable from outside without attaching a debugger to the webview.
  setTimeout(() => {
    try {
      const el = document.querySelector('table.items .ico') || document.querySelector('.ico');
      const cs = el ? getComputedStyle(el) : null;
      const root = getComputedStyle(document.documentElement);
      const img = new Image();
      img.onload = () => report(img.naturalWidth + 'x' + img.naturalHeight);
      img.onerror = () => report('ATLAS-FAIL');
      img.src = 'sprite-atlas.png';
      function report(atlas) {
        const D2 = window.D || {};
        w.setTitle([
          'cols=' + ((D2.sprites || {}).cols),
          'dpr=' + window.devicePixelRatio,
          'bgSize=' + (cs ? cs.backgroundSize : 'no-el'),
          'bgPos=' + (cs ? cs.backgroundPosition : '-'),
          'ico=' + root.getPropertyValue('--ico').trim(),
          'atlas=' + atlas,
          'url=' + (cs ? cs.backgroundImage.slice(0, 46) : '-'),
        ].join(' | '));
      }
    } catch (e) { w.setTitle('DIAG-ERR ' + String(e).slice(0, 90)); }
  }, 2500);

  // --- updates -------------------------------------------------------------
  // A non-modal strip, and it never installs on its own. A window that vanishes
  // mid-run is worse than a version that is a week stale.
  (async () => {
    try {
      const { check } = T.updater || {};
      if (!check) return;
      const up = await check();
      if (!up) return;
      const note = document.createElement("div");
      note.className = "shellupd";
      note.innerHTML =
        `<span>Version <b>${up.version}</b> is out.</span>` +
        `<button id="upd-go" type="button">install &amp; restart</button>` +
        `<button id="upd-no" type="button">later</button>`;
      document.body.appendChild(note);
      const s2 = document.createElement("style");
      s2.textContent = `
        .shellupd{position:fixed;right:11px;bottom:11px;z-index:99;display:flex;gap:9px;
          align-items:center;background:var(--bg-panel);border:1px solid var(--accent-dim);
          border-radius:var(--radius);padding:7px 11px;font-size:12px;color:var(--ink)}
        .shellupd button{background:none;border:1px solid var(--line);color:var(--ink-dim);
          border-radius:var(--radius);padding:2px 8px;cursor:pointer;font:inherit;font-size:11.5px}
        .shellupd button#upd-go{border-color:var(--accent-dim);color:var(--accent)}`;
      document.head.appendChild(s2);
      note.querySelector("#upd-no").onclick = () => note.remove();
      note.querySelector("#upd-go").onclick = async () => {
        note.querySelector("#upd-go").textContent = "downloading…";
        try {
          // NSIS installMode "passive" restarts the app itself (/R), so there is no
          // tauri-plugin-process dependency and nothing to call after this resolves.
          await up.downloadAndInstall();
        } catch (e) {
          note.innerHTML = `<span>Update failed: ${String(e).slice(0, 120)}</span>`;
        }
      };
    } catch (_) { /* offline, or no updater configured — never block the app */ }
  })();
}
