"""
builder.py
===========
The chain builder surface (ticket 29) — the staged list a researcher
composes a chain in. It renders `UI.analyse.chain_state.ChainState`
(ticket 28); it does not compute type compatibility itself, and it does
not keep a second copy of the chain model.

A chain is a linear spine (PRD "Chain shape"): no node canvas, no fan-out.
The add-step control lists every registered block always — an incompatible
one is disabled with the reason `Working.chain_validation` (ticket 13)
gives, not filtered out of the list, so a researcher learns the type
system from the reason rather than wondering where a block went.
"""

import panel as pn

from Adapters.registry import list_adapters

from UI.analyse.chain_state import ChainState, ChainStateError

_EMPTY_STEPS_NOTICE = "*No steps staged yet — add one below.*"


class ChainBuilder:
    """The chain-builder tab. `app` is read for its current recording id
    only — this surface owns the chain under construction, not the
    recording, the same "read the app's live state, don't duplicate it"
    contract `RunPanel` uses for the staged-span basket."""

    def __init__(self, app):
        self.app = app
        self.chain = ChainState(recording_id=app._recording_id)

        self.status = pn.pane.Markdown("")
        self.steps_column = pn.Column(sizing_mode="stretch_width")
        self.add_column = pn.Column(sizing_mode="stretch_width")
        self._refresh()

    def layout(self):
        return pn.Column(
            pn.pane.Markdown("### Chain"),
            self.status,
            self.steps_column,
            pn.layout.Divider(),
            pn.pane.Markdown("### Add a step"),
            self.add_column,
            sizing_mode="stretch_width",
        )

    # ── editing: add, move, delete — each revalidates immediately ──────────

    def _add_step(self, block):
        algorithm = block.name.split(".", 1)[1]
        self.chain.add_step(block.stage, algorithm)
        self._refresh()

    def _move_step(self, index, delta):
        other = index + delta
        if not 0 <= other < len(self.chain.steps):
            return
        order = list(range(len(self.chain.steps)))
        order[index], order[other] = order[other], order[index]
        self.chain.reorder(order)
        self._refresh()

    def _delete_step(self, index):
        try:
            self.chain.remove_step(index)
        except ChainStateError as e:
            self.status.object = f"**Can't remove that step:** {e}"
            return
        self._refresh()

    # ── rendering ────────────────────────────────────────────────────────

    def _refresh(self):
        self._render_steps()
        self._render_add_controls()
        self.status.object = "" if self.chain.is_valid else f"**Invalid chain:** {self.chain.invalid_reason}"

    def _render_steps(self):
        n = len(self.chain.steps)
        if n == 0:
            self.steps_column.objects = [pn.pane.Markdown(_EMPTY_STEPS_NOTICE)]
            return

        rows = []
        for i, step in enumerate(self.chain.steps):
            label = pn.pane.Markdown(f"**{i + 1}.** {step['stage']}.{step['algorithm']}")
            up = pn.widgets.Button(name="\u2191", width=32, disabled=(i == 0))
            down = pn.widgets.Button(name="\u2193", width=32, disabled=(i == n - 1))
            delete = pn.widgets.Button(name="Delete", width=64, button_type="danger")
            up.on_click(lambda _e, idx=i: self._move_step(idx, -1))
            down.on_click(lambda _e, idx=i: self._move_step(idx, +1))
            delete.on_click(lambda _e, idx=i: self._delete_step(idx))
            rows.append(pn.Row(label, up, down, delete, sizing_mode="stretch_width"))
        self.steps_column.objects = rows

    def _render_add_controls(self):
        rows = []
        for block, ok, reason in self.chain.available_blocks():
            button = pn.widgets.Button(
                name=f"Add {block.display_name}",
                disabled=not ok,
                button_type="primary" if ok else "default",
            )
            button.on_click(lambda _e, b=block: self._add_step(b))
            rows.append(pn.Row(button, pn.pane.Markdown(reason), sizing_mode="stretch_width"))
        self.add_column.objects = rows
