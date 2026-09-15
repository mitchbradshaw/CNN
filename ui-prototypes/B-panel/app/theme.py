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

# ---- B builder additions: Panel/Bokeh widgets live in shadow roots. raw_css is injected into every
# component's shadow root, so a class set with css_classes=[...] on the widget is only reachable from
# inside that root as :host(.cls). Every styled control below needed that trick.
THEME_CSS += r"""
:host(.seg) .bk-btn-group { background: var(--grey-100); border-radius: 8px; padding: 2px; gap: 2px; }
:host(.seg) .bk-btn { border: none !important; background: transparent !important; color: var(--text-2) !important; font-size: 11.5px !important; height: 26px; padding: 0 11px; border-radius: 6px !important; box-shadow: none !important; }
:host(.seg) .bk-btn.bk-active { background: #fff !important; color: var(--text) !important; box-shadow: 0 1px 2px rgba(17,24,39,.10) !important; }
:host(.btn) .bk-btn { background: #fff !important; border: 1px solid var(--border-strong) !important; color: var(--text) !important; height: 30px; padding: 0 12px; font-size: 12px !important; box-shadow: none !important; }
:host(.btn) .bk-btn:hover { background: var(--grey-100) !important; }
:host(.btn-primary) .bk-btn { background: var(--blue) !important; border: 1px solid var(--blue) !important; color: #fff !important; height: 30px; padding: 0 14px; font-size: 12px !important; box-shadow: none !important; }
:host(.btn-primary) .bk-btn:hover { background: var(--blue-600) !important; }
:host(.btn-danger) .bk-btn { background: #fff !important; border: 1px solid #f7c1c3 !important; color: #b3262b !important; height: 30px; font-size: 12px !important; }
:host(.btn-link) .bk-btn { background: transparent !important; border: none !important; color: var(--blue) !important; font-size: 12px !important; box-shadow: none !important; padding: 0 4px; }
:host(.btn) .bk-btn[disabled], :host(.btn-primary) .bk-btn[disabled] { opacity: .45 !important; cursor: not-allowed; }
:host(.icon-btn) .bk-btn { width: 24px; min-width: 24px; height: 22px; padding: 0 !important; font-size: 12px !important; background: var(--grey-100) !important; border: none !important; color: var(--muted) !important; border-radius: 5px !important; box-shadow: none !important; }
:host(.icon-btn.on) .bk-btn { background: var(--blue-100) !important; color: var(--blue) !important; }
:host(.icon-btn) .bk-btn:hover { background: var(--grey-200) !important; color: var(--text) !important; }
:host(.pill-insert) .bk-btn { border-radius: 999px !important; height: 22px; font-size: 11px !important; padding: 0 12px; background: #fff !important; color: var(--muted) !important; border: 1px solid var(--border) !important; box-shadow: none !important; }
:host(.pill-insert) .bk-btn:hover { color: var(--blue) !important; border-color: var(--blue-200) !important; }
:host(.card-btn) .bk-btn { white-space: pre-line !important; overflow-wrap: anywhere; text-align: left !important; min-height: 96px; height: auto !important; width: 100%; display: flex; flex-direction: row; align-items: flex-start !important; justify-content: flex-start !important; line-height: 1.5; padding: 10px 10px !important; background: #fff !important; border: 1px solid var(--border) !important; border-radius: 10px !important; color: var(--text) !important; font-size: 11px !important; box-shadow: none !important; overflow: visible; }
:host(.card-btn) { height: auto !important; min-height: 100px; }
:host(.card-btn) .bk-btn:hover { border-color: var(--blue-200) !important; }
:host(.card-btn.sel) .bk-btn { border: 1.5px solid var(--blue) !important; background: #f3f8ff !important; }
:host(.card-btn) .bk-btn[disabled] { opacity: .55; background: #fafafa !important; color: var(--muted) !important; cursor: not-allowed; }
:host(.card-btn) .bk-btn .bk-TablerIcon, :host(.card-btn) .bk-btn svg { flex: none; margin-right: 8px; }
:host(.chk) .bk-input-group label, :host(.chk) label { font-family: var(--font-mono); font-size: 12px; color: var(--text-2); }
:host(.chk) input[type=checkbox] { accent-color: var(--blue); }
:host(.sel-mono) select, :host(.sel-mono) input { font-family: var(--font-mono) !important; font-size: 12px !important; height: 30px; border-radius: 8px !important; border: 1px solid var(--border-strong) !important; }
:host(.sel-mono) label { font-family: var(--font-mono); font-size: 10.5px; color: var(--muted); }
.pb-toolbar { display: flex; align-items: center; gap: 8px; }
.row-left h4 { margin: 0; font-size: 13.5px; font-weight: 600; } .row-left .num { font-family: var(--font-mono); color: var(--muted); font-size: 11px; margin-right: 4px; font-weight: 400; }
.row-left .sig { font-family: var(--font-mono); font-size: 11px; color: var(--muted); margin-left: 6px; }
.row-left .cap { font-family: var(--font-mono); font-size: 11px; color: var(--text-2); margin-top: 4px; line-height: 1.4; }
.junction { border: 1px solid #f7c1c3; background: var(--red-100); color: #b3262b; border-radius: 999px; padding: 4px 12px; font-family: var(--font-mono); font-size: 11.5px; display: inline-block; }
.runbar { height: 3px; background: var(--blue-100); overflow: hidden; border-radius: 2px; position: relative; }
.runbar::after { content: ''; position: absolute; left: -40%; width: 40%; height: 100%; background: var(--blue); animation: pbslide 1.1s infinite linear; }
@keyframes pbslide { from { left: -40%; } to { left: 100%; } }
.waits { height: 100%; display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 11.5px; color: var(--muted); background: repeating-linear-gradient(135deg, #fafbfc, #fafbfc 8px, #f3f4f6 8px, #f3f4f6 16px); border-radius: 6px; border: 1px dashed var(--border); }
.legend-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }
.kv { display: grid; grid-template-columns: auto 1fr; gap: 3px 12px; font-family: var(--font-mono); font-size: 11.5px; }
.kv .k { color: var(--muted); }
.popover { background: #fff; border: 1px solid var(--border); border-radius: 10px; box-shadow: 0 8px 28px rgba(17,24,39,.14); }
.tile { background: var(--grey-100); border-radius: 8px; padding: 8px 10px; } .tile .k { font-family: var(--font-mono); font-size: 10px; color: var(--muted); } .tile .v { font-size: 17px; font-weight: 600; }
/* ---- critique round 1 fixes ---- */
/* Inter never applied: Bokeh's :host stylesheet sets font-family: var(--bokeh-base-font, Helvetica, Arial, sans-serif) on
   every shadow host, which beats body{}. Set the variable (inherits into shadow roots) and the :host rule itself. */
:root { --bokeh-base-font: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif; }
:host { font-family: var(--font-ui); }
.card.axis-row { background: transparent !important; border-color: transparent !important; box-shadow: none !important; }
.badge.computed { background: #ffffff; color: #15794f; box-shadow: inset 0 0 0 1px #9fd8bb; }
:host(.btn) .bk-btn:focus-visible, :host(.btn-primary) .bk-btn:focus-visible, :host(.icon-btn) .bk-btn:focus-visible,
:host(.pill-insert) .bk-btn:focus-visible, :host(.card-btn) .bk-btn:focus-visible { outline: 2px solid var(--blue) !important; outline-offset: 2px; }
"""
