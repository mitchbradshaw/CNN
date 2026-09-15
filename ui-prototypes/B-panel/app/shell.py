"""Shell: 64 px nav rail + header, as Panel HTML panes (frames shell-nav-rail, shell-header).
Workspace switching is driven by the URL hash (#explore/corpus, #analyse/chain, …) through
``pn.state.location``, so every page is deep-linkable and a reload lands where it was."""
from __future__ import annotations

import panel as pn

WORKSPACES = [
    ("explore", "Explore", "explore/corpus"), ("analyse", "Analyse", "analyse/chain"),
    ("discovery", "Discovery", "discovery"), ("models", "Models", "models"),
    ("review", "Review", "review"), ("library", "Library", "library"),
]
_ICON = {
    "explore": '<path d="M3 12h3l2-6 3 12 3-9 2 6 2-3h3" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',
    "analyse": '<g fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/><path d="M10.5 7h4a2 2 0 0 1 2 2v4.5"/></g>',
    "discovery": '<g fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/></g>',
    "models": '<g fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M9 4.5a3.5 3.5 0 0 0-3.5 3.5v8A3.5 3.5 0 0 0 9 19.5M15 4.5a3.5 3.5 0 0 1 3.5 3.5v8a3.5 3.5 0 0 1-3.5 3.5M12 4v16"/></g>',
    "review": '<g fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M4 7l2 2 3-3M4 15l2 2 3-3M12 7h8M12 15h8"/></g>',
    "library": '<g fill="none" stroke="currentColor" stroke-width="1.7"><rect x="4" y="4" width="4" height="16" rx="1"/><rect x="10" y="4" width="4" height="16" rx="1"/><path d="M16.5 5l3.5 14.5"/></g>',
    "jobs": '<g fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3.5" y="5.5" width="17" height="13" rx="2"/><circle cx="12" cy="12" r="2.5"/></g>',
    "settings": '<g fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21"/></g>',
}


def _item(key, label, target, active):
    return (f'<a href="#{target}" class="{"on" if active else ""}" data-testid="nav-{key}">'
            f'<svg width="22" height="22" viewBox="0 0 24 24">{_ICON[key]}</svg><span>{label}</span></a>')


def rail_html(active: str, live_jobs: int = 0) -> str:
    items = "".join(_item(k, lbl, tgt, active == k) for k, lbl, tgt in WORKSPACES)
    foot = _item("jobs", f"Jobs · {live_jobs}" if live_jobs else "Jobs", "jobs", active == "jobs") + \
        '<div class="sep"></div>' + _item("settings", "Settings", "settings", active == "settings")
    return (f'<nav class="pb-rail" data-testid="nav-rail"><div class="pb-logo"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" '
            f'stroke="#fff" stroke-width="1.8" stroke-linecap="round"><path d="M12 20V10M12 10c0-4 3-6 7-6 0 4-3 6-7 6zM12 13c0-3-2.5-5-6-5 0 3 2.5 5 6 5z"/></svg></div>'
            f'{items}<div class="foot">{foot}</div></nav>')


def header_html(workspace: str, page: str, subtitle: str = "", need_you: int = 0, bridge_note: str = "") -> str:
    return (f'<header class="pb-hdr" data-testid="header"><div><span class="ws">{workspace}</span><span class="pg">{page}</span>'
            f'<span class="sub">{subtitle}</span></div><div class="right">'
            f'<div class="pb-search" title="global search · out of slice scope">🔍 Search spans, runs, families <kbd style="margin-left:auto;font-size:10px;opacity:.7">Ctrl K</kbd></div>'
            f'{bridge_note}<span class="chip {"blue" if need_you else "grey"}" title="runs started in this session that failed">● {need_you} need you</span>'
            f'<span class="chip grey" title="M4_aug_concat_fs1.mat is held out (D6): every workspace refuses it">🔒 M4 held out</span></div></header>')


def rail_pane(active: str, live_jobs: int = 0) -> pn.pane.HTML:
    return pn.pane.HTML(rail_html(active, live_jobs), sizing_mode="fixed", width=64, margin=0)


def header_pane(workspace: str, page: str, subtitle: str = "", need_you: int = 0) -> pn.pane.HTML:
    return pn.pane.HTML(header_html(workspace, page, subtitle, need_you), sizing_mode="stretch_width", margin=0)


def inert_page(ws: str) -> pn.Column:
    spec = {"discovery": ("Runs", "apply finished recipes at scale · out of slice scope"), "models": ("Launch", "train from Analyse templates · out of slice scope"),
            "review": ("Queue", "named queues, one source each · out of slice scope"), "library": ("Atlas", "motifs · window sets · templates · out of slice scope"),
            "jobs": ("All jobs", "every job across workspaces · out of slice scope"), "settings": ("Datasets", "project and personal settings · out of slice scope")}.get(ws, ("", ""))
    return pn.Column(header_pane(ws.capitalize(), spec[0], spec[1]),
                     pn.pane.HTML(f'<div class="pb-page"><div class="card card-pad" style="max-width:640px"><div class="card-title">{ws} — visible, inert</div>'
                                  f'<p class="muted" style="margin:8px 0 0">This workspace is outside the vertical slice. Its concept pages live in prototyping/imgs/{ws}/.</p></div></div>'),
                     sizing_mode="stretch_width", margin=0)
