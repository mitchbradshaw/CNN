"""The same design tokens as A's theme.css, as raw CSS for Panel. Panel/Bokeh render into
shadow DOM, so page-level classes only style Panel's HTML panes and our own markup; Bokeh
figure styling is done on the figure objects (see charts.py). Light grounds, thin lines,
Geist Mono / Inter, 64 px rail, cards white with 1 px #E5E7EB borders and 10 px radius."""

THEME_CSS = r"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap');
:root {
  --font-ui: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
  --font-mono: 'Geist Mono', ui-monospace, 'Cascadia Mono', 'Consolas', monospace;
  --bg: #f5f6f8; --card: #ffffff; --border: #e5e7eb; --border-strong: #d1d5db;
  --text: #111827; --text-2: #374151; --muted: #6b7280; --muted-2: #9ca3af;
  --blue: #0a84ff; --blue-600: #0066d6; --blue-100: #e6f1ff; --blue-200: #bfdcff;
  --green: #22a06b; --green-100: #e6f6ee; --amber: #e8900c; --amber-100: #fff3e0;
  --red: #e5484d; --red-100: #fdeaea; --purple: #8e5cf7; --purple-100: #f1eaff;
  --grey-100: #eef0f3; --grey-200: #dfe3e8; --radius: 10px;
}
body { font-family: var(--font-ui); font-size: 13px; color: var(--text); background: var(--bg); margin: 0; min-width: 1200px; }
.pb-app { display: grid; grid-template-columns: 64px 1fr; min-height: 100vh; }
.pb-rail { width: 64px; background: var(--card); border-right: 1px solid var(--border); display: flex; flex-direction: column; align-items: center; padding: 10px 0 12px; position: sticky; top: 0; height: 100vh; box-sizing: border-box; }
.pb-logo { width: 38px; height: 38px; border-radius: 10px; background: var(--blue); display: flex; align-items: center; justify-content: center; margin-bottom: 18px; }
.pb-rail a { width: 54px; height: 50px; border-radius: 9px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px; color: var(--muted); text-decoration: none; font-size: 10px; margin-bottom: 6px; }
.pb-rail a:hover { background: var(--grey-100); color: var(--text); }
.pb-rail a.on { background: var(--blue-100); color: var(--blue); }
.pb-rail .foot { margin-top: auto; display: flex; flex-direction: column; align-items: center; }
.pb-rail .sep { width: 36px; height: 1px; background: var(--border); margin: 4px 0 10px; }
.pb-hdr { height: 44px; display: flex; align-items: center; justify-content: space-between; padding: 0 20px; border-bottom: 1px solid var(--border); background: var(--bg); }
.pb-hdr .ws { font-weight: 700; font-size: 15px; } .pb-hdr .pg { font-size: 13.5px; color: var(--text-2); margin-left: 12px; padding-left: 12px; border-left: 1px solid var(--border); }
.pb-hdr .sub { font-family: var(--font-mono); font-size: 11px; color: var(--muted); margin-left: 10px; }
.pb-hdr .right { display: flex; gap: 8px; align-items: center; }
.pb-search { display: flex; align-items: center; gap: 8px; height: 28px; padding: 0 12px; border-radius: 999px; background: var(--card); border: 1px solid var(--border); color: var(--muted); font-family: var(--font-mono); font-size: 11.5px; min-width: 280px; opacity: .7; }
.pb-page { padding: 12px 20px 24px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: 0 1px 2px rgba(17,24,39,.04); }
.card-pad { padding: 12px 14px; }
.card-title { font-family: var(--font-mono); font-size: 11px; letter-spacing: .04em; color: var(--muted); text-transform: uppercase; }
.chip { display: inline-flex; align-items: center; gap: 6px; height: 26px; padding: 0 10px; border-radius: 999px; font-family: var(--font-mono); font-size: 11.5px; border: 1px solid var(--border); background: var(--card); color: var(--text-2); white-space: nowrap; }
.chip.blue { background: var(--blue-100); border-color: var(--blue-200); color: var(--blue-600); }
.chip.grey { background: var(--grey-100); border-color: var(--grey-200); }
.chip.green { background: var(--green-100); border-color: #bfe8d2; color: #15794f; }
.chip.amber { background: var(--amber-100); border-color: #ffd9a8; color: #a05e00; }
.chip.red { background: var(--red-100); border-color: #f7c1c3; color: #b3262b; }
.badge { display: inline-flex; align-items: center; height: 18px; padding: 0 7px; border-radius: 5px; font-family: var(--font-mono); font-size: 10.5px; }
.badge.cached { background: var(--green-100); color: #15794f; } .badge.stale { background: var(--amber-100); color: #a05e00; }
.badge.new { background: var(--grey-100); color: var(--text-2); } .badge.running { background: var(--blue-100); color: var(--blue-600); }
.badge.failed, .badge.invalid { background: var(--red-100); color: #b3262b; } .badge.cancelled, .badge.blocked { background: var(--grey-100); color: var(--muted); }
.mono { font-family: var(--font-mono); } .muted { color: var(--muted); } .small { font-size: 11px; }
.error-card { border: 1.5px solid var(--red); background: #fff7f7; border-radius: var(--radius); padding: 12px 14px; }
.error-card h3 { margin: 0 0 4px; font-size: 13px; color: #b3262b; }
.error-card pre { margin: 6px 0 0; font-family: var(--font-mono); font-size: 10.5px; white-space: pre-wrap; max-height: 220px; overflow: auto; color: #7f1d1d; }
/* Panel widget overrides: mono buttons/selects, flat inputs */
.bk-btn, .bk-input, select.bk-input { font-family: var(--font-mono) !important; font-size: 12px !important; border-radius: 8px !important; }
.bk-btn-primary { background: var(--blue) !important; border-color: var(--blue) !important; }
"""
