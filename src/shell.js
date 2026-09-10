// Desktop-only chrome. In a browser this file does nothing at all — roadmap.html is
// still the same page, so the version already sitting in someone's Downloads folder
// cannot break because of anything in here.
//
// Rust holds no state. Pin and opacity live in localStorage beside the app's other
// rm.* keys, and are re-applied on every launch.

const T = globalThis.__TAURI__;
if (T) {
  const read = (k, fallback) => {
    try {
      const v = localStorage.getItem(k);
      return v == null ? fallback : JSON.parse(v);
    } catch (_) { return fallback; }        // private window, cleared storage, corrupt value
  };


  // No pin strip here on purpose. The MAIN window is an ordinary window - making the
  // whole app always-on-top meant it sat over the game, over Discord, over everything,
  // which reads as broken rather than useful. The small overlay widget is the piece
  // that floats, and it owns the opacity setting too.


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
