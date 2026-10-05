"""Look of the teach pendant: calm surfaces, system font, large touch targets (iPad-like).

Colors follow the system colors of Apple's Human Interface Guidelines (blue, green, orange,
red; grouped background) in a light and a dark variant. Every interactive element is at least
44 px high, so it can be used with gloves on a tablet.
"""

from __future__ import annotations

COLORS = {
    "primary": "#007AFF",
    "secondary": "#8E8E93",
    "accent": "#5856D6",
    "positive": "#34C759",
    "negative": "#FF3B30",
    "warning": "#FF9500",
    "info": "#007AFF",
}

CSS = r"""
:root {
  --bg: #F2F2F7; --card: #FFFFFF; --card-2: #F2F2F7; --line: rgba(60,60,67,.12);
  --text: #1C1C1E; --text-2: #6E6E73; --text-3: #AEAEB2;
  --blue: #007AFF; --green: #34C759; --orange: #FF9500; --red: #FF3B30; --indigo: #5856D6;
  --glass: rgba(255,255,255,.72); --shadow: 0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.06);
  --radius: 18px;
}
body.body--dark {
  --bg: #000000; --card: #1C1C1E; --card-2: #2C2C2E; --line: rgba(84,84,88,.45);
  --text: #F2F2F7; --text-2: #98989F; --text-3: #636366;
  --blue: #0A84FF; --green: #30D158; --orange: #FF9F0A; --red: #FF453A; --indigo: #5E5CE6;
  --glass: rgba(28,28,30,.72); --shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.35);
}
html, body {
  background: var(--bg) !important; color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI Variable", "Segoe UI",
               Inter, Roboto, "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing: antialiased; letter-spacing: -.01em;
}
.nicegui-content { padding: 0 !important; }
.q-page { background: var(--bg); }

/* header with frosted glass */
.tp-header {
  background: var(--glass) !important; backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px); border-bottom: 1px solid var(--line);
  color: var(--text) !important; box-shadow: none !important;
}
.tp-title { font-weight: 650; font-size: 17px; }
.tp-sub { color: var(--text-2); font-size: 13px; }

/* sidebar */
.tp-drawer { background: var(--bg) !important; border-right: 1px solid var(--line); }
.q-btn.tp-nav { border-radius: 12px; min-height: 44px; padding: 0 12px; color: var(--text) !important;
          font-weight: 500; transition: background .15s ease; }
.q-btn.tp-nav:hover { background: var(--card-2); }
.q-btn.tp-nav.active { background: var(--blue) !important; color: #fff !important; }
.q-btn.tp-nav .q-btn__content { flex-wrap: nowrap; white-space: nowrap; }
.q-btn.tp-nav .q-icon { font-size: 20px; }

/* content */
.tp-page { max-width: 1180px; margin: 0 auto; padding: 28px 28px 48px; gap: 20px; width: 100%; }
.tp-h1 { font-size: 30px; font-weight: 700; letter-spacing: -.02em; line-height: 1.1; }
.tp-h1 input { font-weight: 700; letter-spacing: -.02em; }
.tp-lead { color: var(--text-2); font-size: 15px; margin-top: 4px; }
.tp-card { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow);
           padding: 20px; border: none; width: 100%; }
.tp-card-title { font-size: 13px; font-weight: 600; color: var(--text-2); text-transform: uppercase;
                 letter-spacing: .04em; margin-bottom: 6px; }
.tp-row { min-height: 44px; border-bottom: 1px solid var(--line); width: 100%;
          display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.tp-row:last-child { border-bottom: none; }
.tp-key { color: var(--text-2); }
.tp-val { font-weight: 500; text-align: right; }
.tp-muted { color: var(--text-2); font-size: 13px; }
.tp-mono, .tp-mono-in input { font-family: "SF Mono", ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace;
           font-variant-numeric: tabular-nums; }

/* status pill */
.tp-pill { border-radius: 999px; padding: 6px 12px 6px 10px; font-size: 13px; font-weight: 600;
           display: inline-flex; align-items: center; gap: 8px; background: var(--card-2); }
.tp-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-3); }
.tp-pill.ok .tp-dot { background: var(--green); box-shadow: 0 0 0 3px rgba(52,199,89,.2); }
.tp-pill.busy .tp-dot { background: var(--blue); animation: tp-pulse 1.2s ease-in-out infinite; }
.tp-pill.warn .tp-dot { background: var(--orange); }
.tp-pill.err .tp-dot { background: var(--red); }
@keyframes tp-pulse { 0%,100% { opacity: 1 } 50% { opacity: .35 } }

/* buttons */
.q-btn { border-radius: 12px; min-height: 44px; font-weight: 600; letter-spacing: -.01em; }
.q-btn.tp-btn-soft { background: var(--card-2) !important; color: var(--blue) !important; }
.q-btn.tp-btn-soft.danger { color: var(--red) !important; }
.q-btn.tp-stop { background: var(--red) !important; color: #fff !important; min-width: 120px;
           min-height: 44px; border-radius: 999px; font-weight: 800; letter-spacing: .06em;
           box-shadow: 0 4px 14px rgba(255,59,48,.35); }
.q-btn.tp-stop:active { transform: scale(.97); }

/* segmented control (ui.toggle) */
.tp-seg { background: var(--card-2); border-radius: 10px; padding: 2px; box-shadow: none !important; }
.tp-seg .q-btn { background: transparent !important; min-height: 32px; border-radius: 8px !important; color: var(--text) !important;
                 font-weight: 500; padding: 0 14px; }
.tp-seg .q-btn.bg-primary { background: var(--card) !important;
                 box-shadow: 0 1px 3px rgba(0,0,0,.12), 0 1px 1px rgba(0,0,0,.04); font-weight: 600; }
body.body--dark .tp-seg .q-btn.bg-primary { background: #636366 !important; }

/* inputs */
.q-field--outlined .q-field__control { border-radius: 12px; }
.q-field--filled .q-field__control { border-radius: 12px; background: var(--card-2); }
.q-field--filled .q-field__control:before, .q-field--filled .q-field__control:after { border: none !important; }
.q-toggle__inner--truthy .q-toggle__track { opacity: 1 !important; }
.q-toggle__inner { font-size: 52px !important; }
.q-slider__track { height: 6px !important; border-radius: 3px; }

/* jog keys */
.tp-axis { width: 100%; display: grid; grid-template-columns: 52px 1fr 64px 64px; align-items: center; gap: 12px;
           min-height: 64px; border-bottom: 1px solid var(--line); }
.tp-axis:last-child { border-bottom: none; }
.tp-axis-name { font-weight: 700; font-size: 17px; }
.tp-axis-val { font-size: 22px; font-weight: 600; text-align: right; }
.tp-bar { height: 6px; background: var(--card-2); border-radius: 3px; position: relative; overflow: hidden; }
.tp-bar > div { position: absolute; top: 0; bottom: 0; background: var(--blue); border-radius: 3px; }
.q-btn.tp-key-btn { width: 64px; height: 56px; min-height: 56px; border-radius: 14px !important;
              background: var(--card-2) !important; color: var(--text) !important; font-size: 24px;
              touch-action: none; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; }
.q-btn.tp-key-btn.held { background: var(--blue) !important; color: #fff !important; transform: scale(.96); }
.q-btn.tp-key-btn.disabled { opacity: .35; pointer-events: none; }
.tp-hold { touch-action: none; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; }
.tp-hold.held { filter: brightness(.9); transform: scale(.98); }

/* lists */
.tp-item { min-height: 56px; border-radius: 12px; padding: 8px 12px; gap: 12px; width: 100%;
           display: flex; align-items: center; transition: background .15s ease; }
.tp-item:hover { background: var(--card-2); }
.tp-item.current { background: rgba(0,122,255,.12); }
.tp-badge { min-width: 28px; height: 28px; border-radius: 8px; background: var(--card-2);
            display: inline-flex; align-items: center; justify-content: center; font-weight: 600;
            font-size: 13px; color: var(--text-2); }
.tp-item.current .tp-badge { background: var(--blue); color: #fff; }
.tp-chip { border-radius: 6px; padding: 2px 8px; font-size: 12px; font-weight: 600;
           background: var(--card-2); color: var(--text-2); }
.tp-chip.lin { color: var(--indigo); }
.tp-chip.ptp { color: var(--blue); }
.tp-chip.joint { color: var(--green); }
.tp-chip.blend { color: var(--orange); }
.tp-chip.unsupported { color: var(--red) !important; text-decoration: line-through; }
.tp-cap { display: inline-flex; align-items: center; gap: 4px; border-radius: 8px; padding: 3px 8px;
          font-size: 12px; font-weight: 500; background: rgba(52,199,89,.12); color: var(--text); }
.tp-cap .q-icon { color: var(--green); }
.tp-cap.missing { background: var(--card-2); color: var(--text-3); text-decoration: line-through; }
.tp-cap.missing .q-icon { color: var(--text-3); }

.tp-chip.circ { color: var(--orange); }
.tp-item.skipped { opacity: .45; }
/* compact jog pad in dialogs */
.tp-pad-compact .tp-axis { grid-template-columns: 36px 1fr 52px 52px; gap: 8px; min-height: 52px; }
.tp-pad-compact .tp-axis-name { font-size: 15px; }
.tp-pad-compact .tp-axis-val { font-size: 17px; }
.tp-pad-compact .q-btn.tp-key-btn { width: 52px; height: 44px; min-height: 44px; font-size: 20px; border-radius: 12px !important;
                                    background: var(--card) !important; }
.tp-card-2 .q-expansion-item__content { padding-top: 4px; }
.tp-card-2 .q-field--filled .q-field__control { background: var(--card); }
.q-btn.tp-free { background: var(--card) !important; color: var(--blue) !important; box-shadow: var(--shadow);
                 border-radius: var(--radius); }
.q-btn.tp-free.held { background: var(--blue) !important; color: #fff !important; }
.tp-item.skipped .font-semibold { text-decoration: line-through; }
.tp-card-2 { background: var(--card-2); border-radius: 14px; padding: 12px 14px; }

/* pause / continue next to STOP */
.q-btn.tp-pause { background: var(--orange) !important; color: #fff !important; border-radius: 999px;
           min-width: 120px; font-weight: 700; box-shadow: 0 4px 14px rgba(255,149,0,.3); }
.q-btn.tp-pause.go { background: var(--green) !important; box-shadow: 0 4px 14px rgba(52,199,89,.3); }

/* status tiles (drives, error, communication, sequence) */
.tp-tiles { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; width: 100%; }
.tp-tile { border-radius: 12px; padding: 10px 12px; font-size: 13px; font-weight: 600; text-align: center;
           background: var(--card-2); color: var(--text-3); transition: background .2s ease, color .2s ease; }
.tp-tile.ok { background: rgba(52,199,89,.14); color: var(--green); }
.tp-tile.warn { background: rgba(255,149,0,.14); color: var(--orange); }
.tp-tile.err { background: rgba(255,59,48,.14); color: var(--red); }

/* running program: status line and progress */
.tp-run { border-radius: 12px; padding: 8px 12px; margin: 8px 0 4px; background: rgba(0,122,255,.10); }
.tp-progress { border-radius: 3px; margin-bottom: 6px; color: var(--blue) !important; }
.tp-progress .q-linear-progress__track { background: var(--card-2); opacity: 1; }

/* digital I/O: one row per byte, one LED per signal */
.tp-io-row { display: grid; grid-template-columns: 40px repeat(8, 1fr); gap: 6px; align-items: center; width: 100%; }
.tp-led { height: 40px; border-radius: 10px; background: var(--card-2); display: flex; align-items: center;
          justify-content: center; position: relative; transition: background .15s ease, transform .1s ease;
          user-select: none; }
.tp-led-bit { font-size: 12px; font-weight: 600; color: var(--text-3); font-variant-numeric: tabular-nums; }
.tp-led.named::after { content: ""; position: absolute; top: 5px; right: 6px; width: 5px; height: 5px;
          border-radius: 50%; background: var(--text-3); }
.tp-led.on.di { background: var(--green); }
.tp-led.on.do { background: var(--blue); }
.tp-led.on .tp-led-bit, .tp-led.on.named::after { color: #fff; background-color: transparent; }
.tp-led.on.named::after { background: rgba(255,255,255,.8); }
.tp-led.unknown { opacity: .45; }
.tp-led.do { cursor: pointer; }
.tp-led.do:active { transform: scale(.94); }

/* software limits: joint range with the actual position */
.tp-limit-row { display: grid; grid-template-columns: 36px 64px 1fr 64px 64px; gap: 10px; align-items: center;
                min-height: 40px; width: 100%; }
.tp-limit { height: 8px; border-radius: 4px; background: linear-gradient(90deg, rgba(255,59,48,.35) 0 5%,
            var(--card-2) 5% 95%, rgba(255,59,48,.35) 95% 100%); position: relative; }
.tp-limit-marker { position: absolute; top: -4px; width: 4px; height: 16px; border-radius: 2px; background: var(--blue);
                   transition: left .15s linear; }
.tp-limit-marker.near { background: var(--red); }

.tp-empty { color: var(--text-2); text-align: center; padding: 28px 12px; }
.tp-banner { border-radius: 14px; padding: 12px 16px; background: rgba(255,149,0,.12); color: var(--text); }
.tp-banner.err { background: rgba(255,59,48,.12); }
.q-notification { border-radius: 14px !important; }
.q-dialog__inner > .q-card { border-radius: 20px !important; background: var(--card); padding: 8px; }

@media (max-width: 1000px) {
  /* the STOP key keeps its text; pause / continue shows only its icon */
  .tp-header .q-btn.tp-pause .block { display: none; }
  .tp-header .q-btn.tp-pause { min-width: 56px; padding: 0 10px; }
  .tp-header .q-btn.tp-pause .q-icon { margin: 0; }
  .tp-pill { max-width: 200px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
}
@media (max-width: 760px) {
  .tp-sub { display: none; }
  .tp-header .q-btn.tp-stop { min-width: 0; padding: 0 14px; }
  .tp-page { padding: 16px; }
  .tp-axis { grid-template-columns: 44px 1fr 56px 56px; gap: 8px; }
  .tp-io-row { grid-template-columns: 32px repeat(8, 1fr); gap: 4px; }
  .q-btn.tp-pause { min-width: 0; padding: 0 12px; }
  .tp-h1 { font-size: 26px; }
}
"""

# hold-to-run in the browser: while a key with the class tp-hold / tp-key-btn is pressed, the
# browser sends "hold_alive" every 100 ms; releasing it anywhere (or leaving the page) sends
# "hold_release". Without the heartbeat the robot service stops the motion after 0.5 s.
HOLD_JS = r"""
<script>
(function () {
  let timer = null, held = null;
  function release() {
    if (timer === null) return;
    clearInterval(timer); timer = null;
    if (held) { held.classList.remove('held'); held = null; }
    emitEvent('hold_release');
  }
  document.addEventListener('pointerdown', (e) => {
    const el = e.target.closest('.tp-hold, .tp-key-btn');
    if (!el || el.classList.contains('disabled') || el.hasAttribute('disabled')) return;
    release();
    held = el; el.classList.add('held');
    try { el.setPointerCapture(e.pointerId); } catch (_) {}
    timer = setInterval(() => emitEvent('hold_alive'), 100);
  }, true);
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(t => document.addEventListener(t, release, true));
  window.addEventListener('blur', release);
  document.addEventListener('visibilitychange', () => { if (document.hidden) release(); });
  document.addEventListener('contextmenu', (e) => { if (e.target.closest('.tp-hold, .tp-key-btn')) e.preventDefault(); });
})();
</script>
"""
