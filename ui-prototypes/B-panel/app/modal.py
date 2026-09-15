"""Insert-stage modal (frame chain-2) built from ``chain.compatible_at``: the type contract as three
pills, "N of 22 fit", search, category tabs, show-incompatible toggle, a grid of block cards
(incompatible ones disabled, each with its reason), a detail panel, Insert / Insert and open settings.

Panel has no clickable rich card, so each card is a ``Button`` whose label is multi-line text styled
with ``white-space: pre-line`` through a ``:host(.card-btn)`` rule, with the algorithm glyph passed as
the button's SVG ``icon``. Per-card estimates are computed in-process from a hypothetical recipe (A
could not do this without a new endpoint)."""
from __future__ import annotations

import copy
import html

import panel as pn

from server import chain as chain_mod

from . import runstate as RS

esc = html.escape
CATS = ["all", "preprocess", "encode", "detect", "cluster", "model", "control"]

_GLYPH = {  # 44×26 algorithm glyphs, colour key per spec §6.8 (grey context · blue emits · amber cut · red discord)
    "preprocess": '<path d="M2 16 C8 4 12 22 18 12 S30 6 34 14 40 18 42 12" stroke="#9ca3af" fill="none"/><path d="M2 13 C10 11 20 15 30 12 S40 13 42 12" stroke="#0a84ff" fill="none" stroke-width="1.6"/>',
    "encode": '<rect x="3" y="8" width="7" height="10" fill="#9db9e8"/><rect x="12" y="8" width="7" height="10" fill="#e8900c"/><rect x="21" y="8" width="7" height="10" fill="#2f5fb3"/><rect x="30" y="8" width="7" height="10" fill="#9db9e8"/>',
    "detect": '<path d="M2 18 L10 16 L14 6 L18 17 L28 15 L32 9 L36 17 L42 16" stroke="#0a84ff" fill="none" stroke-width="1.4"/><line x1="2" y1="11" x2="42" y2="11" stroke="#e8900c" stroke-dasharray="2 2"/>',
    "cluster": '<circle cx="10" cy="10" r="3" fill="#0a84ff"/><circle cx="15" cy="16" r="3" fill="#0a84ff"/><circle cx="30" cy="9" r="3" fill="#22a06b"/><circle cx="34" cy="16" r="3" fill="#22a06b"/>',
    "model": '<rect x="6" y="5" width="32" height="16" rx="3" fill="none" stroke="#0a84ff"/><line x1="11" y1="10" x2="30" y2="10" stroke="#9ca3af"/><line x1="11" y1="15" x2="24" y2="15" stroke="#9ca3af"/>',
    "control": '<path d="M2 13 C8 5 14 21 20 13 S32 5 42 13" stroke="#8e5cf7" fill="none" stroke-width="1.4"/>',
}


def glyph(cat: str, w=44, h=26) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 44 26">{_GLYPH.get(cat, _GLYPH["control"])}</svg>'


def insert_modal(view, position: int):
    steps = view.steps
    comp = chain_mod.compatible_at(steps, position)
    cat = RS.catalog()
    rows = {r["name"]: r for r in comp["rows"]}
    prev_label = f"{position:02d} {RS.page_name(steps[position - 1])}" if position > 0 else "Source"
    next_label = f"{position + 1:02d} {comp['next_name']}" if comp.get("next_name") else None

    # per-card estimate for fitting blocks: hypothetical recipe with the block inserted
    est: dict[str, str] = {}
    src = view.src
    for name, r in rows.items():
        if not r["ok"]:
            continue
        try:
            hyp = copy.deepcopy(steps)
            hyp.insert(position, {"stage": cat[name]["stage"], "algorithm": cat[name]["algorithm"], "params": {}})
            recipe = chain_mod.build_recipe(src["recording_id"], (src["start_idx"], src["end_idx"]), hyp)
            e = chain_mod.estimate(recipe, src["end_idx"] - src["start_idx"], float(src.get("fs") or 1))
            est[name] = "≈ " + (RS.fmt_timing(e["per_step_s"][position]) or "0 s") if cat[name]["has_estimate"] else "≈ – (no estimator)"
        except Exception:
            est[name] = "≈ –"

    search = pn.widgets.TextInput(placeholder="search blocks", width=260, css_classes=["sel-mono"], margin=(0, 6))
    tabs = pn.widgets.RadioButtonGroup(options=CATS, value="all", css_classes=["seg"], margin=(0, 6))
    show_inc = pn.widgets.Checkbox(name="show incompatible", value=True, css_classes=["chk"], margin=(8, 6))
    # FRICTION: GridBox(height=…, scroll=True) still painted its last row over the footer; a scrolling Column around it clips
    grid = pn.GridBox(ncols=4, sizing_mode="stretch_width", margin=0)
    grid_scroll = pn.Column(grid, height=500, scroll=True, sizing_mode="stretch_width", margin=0)
    detail = pn.pane.HTML("", width=300, margin=(0, 0, 0, 12), styles={"border": "1px solid #e5e7eb", "border-radius": "10px", "padding": "12px",
                                                                       "background": "#fafbfc", "min-height": "420px"})
    selected = {"name": next((n for n, r in rows.items() if r["ok"]), None)}
    insert = pn.widgets.Button(name="+ Insert", css_classes=["btn"], width=100, margin=(0, 4))
    insert_open = pn.widgets.Button(name="→ Insert and open settings", css_classes=["btn-primary"], width=220, margin=(0, 4))
    cancel = pn.widgets.Button(name="Cancel", css_classes=["btn"], width=90, margin=(0, 4))
    card_btns: dict[str, pn.widgets.Button] = {}

    def card_label(name):
        c = cat[name]
        r = rows[name]
        fit = ("✓ fits here" + (" · " + r["reason"][7:] if r["reason"].startswith("fits · ") else "")) if r["ok"] else f"⊘ {r['reason']}"
        return f"{c['page_name']}\n{c['signature']}\n{est.get(name, '≈ –')} · no null declared\n{fit}"

    def paint_detail():
        name = selected["name"]
        if not name:
            detail.object = '<div class="mono small muted">no block fits at this point</div>'
            insert.disabled = insert_open.disabled = True
            return
        c = cat[name]
        r = rows[name]
        defaults = "".join(f'<span class="k">{esc(p["name"])}</span><span>{esc(str(p["default"]))}</span>' for p in c["params"][:8]) or '<span class="k">no parameters</span><span></span>'
        stale = f"{position + 1:02d}–{len(steps):02d} go stale · 00–{position:02d} stay cached" if position < len(steps) else "inserting at the end changes the terminal type"
        detail.object = (f'<div data-testid="modal-detail"><div style="font-size:15px;font-weight:600">{esc(c["page_name"])}</div>'
                         f'<div class="mono small" style="color:var(--blue)">{esc(c["signature"])}</div>'
                         f'<div style="margin:10px 0;background:#fff;border:1px solid var(--border);border-radius:8px;display:flex;justify-content:center">{glyph(c["category"], 272, 96)}</div>'
                         f'<div class="small" style="line-height:1.45">{esc(c["description"][:260])}</div>'
                         f'<div class="card-title" style="margin-top:10px">defaults</div><div class="kv" style="margin-top:4px">{defaults}</div>'
                         f'<div style="display:flex;gap:6px;margin-top:10px"><div class="tile"><div class="k">est. cost</div><div class="v">{esc(est.get(name, "–"))}</div></div>'
                         f'<div class="tile"><div class="k">null</div><div class="v" style="font-size:13px">not declared</div></div>'
                         f'<div class="tile"><div class="k">side-inputs</div><div class="v" style="font-size:13px">{len(c["side_inputs"]) or "none"}</div></div></div>'
                         f'<div class="chip amber" style="margin-top:10px;height:auto;white-space:normal;padding:4px 10px">◷ {esc(stale)}</div>'
                         + (f'<div class="mono small" style="color:#b3262b;margin-top:8px">{esc(r["reason"])}</div>' if not r["ok"] else "")
                         + (f'<div class="mono small" style="color:#a05e00;margin-top:8px">{esc(c["known_broken"])}</div>' if c.get("known_broken") else "")
                         + '</div>')
        insert.disabled = insert_open.disabled = not r["ok"]
        for n, b in card_btns.items():
            want = ["card-btn", f"t-modal-card-{n.replace('.', '-')}"] + (["sel"] if n == name else [])
            if b.css_classes != want:
                b.css_classes = want

    def select(name):
        selected["name"] = name
        paint_detail()

    def paint_grid(*_):
        q = (search.value or "").lower().strip()
        names = sorted(cat, key=lambda n: (not rows[n]["ok"], cat[n]["page_name"]))
        out = []
        for n in names:
            c = cat[n]
            if tabs.value != "all" and c["category"] != tabs.value:
                continue
            if q and q not in (c["page_name"] + " " + n + " " + c["signature"]).lower():
                continue
            if not rows[n]["ok"] and not show_inc.value:
                continue
            if n not in card_btns:
                b = pn.widgets.Button(name=card_label(n), icon=glyph(c["category"]), icon_size="26px", disabled=not rows[n]["ok"],
                                      css_classes=["card-btn", f"t-modal-card-{n.replace('.', '-')}"], height=100, sizing_mode="stretch_width",
                                      margin=(4, 4), description=None if rows[n]["ok"] else rows[n]["reason"])
                b.on_click(lambda e, n=n: select(n))
                card_btns[n] = b
            out.append(card_btns[n])
        grid.objects = out

    for w in (search, tabs, show_inc):
        w.param.watch(paint_grid, "value")

    def do_insert(open_settings):
        if selected["name"] and rows[selected["name"]]["ok"]:
            modal.open = False
            view.insert_step(position, selected["name"], open_settings=open_settings)
    insert.on_click(lambda e: do_insert(False))
    insert_open.on_click(lambda e: do_insert(True))
    cancel.on_click(lambda e: setattr(modal, "open", False))

    ribbon = " › ".join(["● Source"] + [f"{k + 1:02d} {RS.page_name(s)}" for k, s in enumerate(steps[:position])] +
                        ['<b style="color:var(--blue)">+ new stage</b>'] + [f"{position + k + 1:02d} {RS.page_name(s)}" for k, s in enumerate(steps[position:])])
    accepts = comp["producing_label"]
    emits = comp.get("next_requires_label") or "any type"
    head = pn.pane.HTML(
        f'<div data-testid="insert-modal"><div style="font-size:17px;font-weight:600">⊞ Insert a stage <span class="mono small muted" style="font-weight:400">between '
        f'{esc(prev_label)} and {esc(next_label or "the end of the chain")}</span></div>'
        f'<div class="mono small" style="background:var(--grey-100);border-radius:8px;padding:6px 10px;margin:10px 0">chain &nbsp; {ribbon}'
        f'{"<span style=float:right;color:#a05e00>inserting makes " + f"{position + 1:02d} stale</span>" if position < len(steps) else ""}</div>'
        f'<div style="display:flex;gap:10px;align-items:center;margin-bottom:6px">'
        f'<span class="chip grey">{esc(prev_label)} outputs <b style="color:var(--blue);margin-left:4px">{esc(accepts)}</b></span> →'
        f'<span class="chip amber">new stage accepts {esc(accepts)} → emits {esc(emits)}</span> →'
        f'<span class="chip grey">{esc(next_label + " requires " + emits) if next_label else "end · changes the terminal type"}</span>'
        f'<span style="margin-left:auto;font-weight:600" data-testid="modal-fit-count">{comp["n_fit"]} of {comp["n_total"]} blocks fit</span></div></div>',
        sizing_mode="stretch_width", margin=0)
    body = pn.Row(pn.Column(pn.Row(search, tabs, show_inc, margin=(0, 0, 6, 0)), grid_scroll, sizing_mode="stretch_width", margin=0), detail,
                  sizing_mode="stretch_width", margin=0)
    foot = pn.Row(pn.pane.HTML(f'<div class="mono small muted" style="padding-top:8px">{comp["n_total"]} blocks in the registry · a new technique is one adapter file</div>'),
                  pn.layout.HSpacer(), cancel, insert, insert_open, sizing_mode="stretch_width", margin=(10, 0, 0, 0))
    paint_grid()
    paint_detail()
    modal = pn.Modal(pn.Column(head, body, foot, width=1180, margin=10), open=True, width=1220, background_close=True)
    view._modal = modal
    return modal
