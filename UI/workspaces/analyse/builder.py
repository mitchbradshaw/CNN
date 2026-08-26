"""
builder.py
===========
The chain builder surface (ticket 29, redrawn in ticket 57) — a horizontal
block canvas a researcher composes a chain in. It renders
`UI.analyse.chain_state.ChainState` (ticket 28); it does not compute type
compatibility itself, and it does not keep a second copy of the chain model.

A chain is a linear spine (PRD "Chain shape, revised"): no node canvas, no
fan-out. The canvas draws one fixed-width card per step, left to right in
execution order, with a connector between cards, and scrolls horizontally
rather than wrapping. The add-step control lists every registered block
always — an incompatible one is disabled with the reason
`Working.chain_validation` (ticket 13) gives, not filtered out of the list,
so a researcher learns the type system from the reason rather than wondering
where a block went.
"""

import panel as pn

from Adapters.registry import get_adapter, list_adapters
from Working.chain_validation import ROOT_SIGNAL_KIND, check_step_compatibility

from UI.analyse.chain_state import ChainState, ChainStateError

_EMPTY_STEPS_NOTICE = "*No steps staged yet — add one below.*"
_CARD_WIDTH = 220
_ARROW = "\u2192"


class ChainBuilder:
    """The chain-builder tab. `app` is read for its current recording id
    only — this surface owns the chain under construction, not the
    recording, the same "read the app's live state, don't duplicate it"
    contract `RunPanel` uses for the staged-span basket."""

    def __init__(self, app):
        self.app = app
        self.chain = ChainState(recording_id=app._recording_id)

        self.status = pn.pane.Markdown("")
        # `pn.Row(scroll=True)` is the horizontal non-wrapping scroll
        # container: a `pn.FlexBox` would wrap, and wrapping destroys the
        # left-to-right reading this ticket exists to create.
        self.steps_row = pn.Row(sizing_mode="stretch_width", scroll=True)
        self.add_column = pn.Column(sizing_mode="stretch_width")
        self.cards = []
        self.connectors = []
        self._refresh()

    def layout(self):
        return pn.Column(
            pn.pane.Markdown("### Chain"),
            self.status,
            self.steps_row,
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
        self.status.object = "" if self.chain.is_valid else self._invalid_status()

    def _render_steps(self):
        self.cards = []
        self.connectors = []
        if not self.chain.steps:
            self.steps_row.objects = [pn.pane.Markdown(_EMPTY_STEPS_NOTICE)]
            return

        objects = []
        for i, step in enumerate(self.chain.steps):
            if i > 0:
                connector = pn.pane.Markdown(
                    f"<div style='font-size: 20px; padding-top: 40px;'>{_ARROW}</div>"
                )
                self.connectors.append(connector)
                objects.append(connector)
            card = self._render_card(i, step)
            self.cards.append(card)
            objects.append(card)
        self.steps_row.objects = objects

    def _render_card(self, index, step):
        adapter = get_adapter(f"{step['stage']}.{step['algorithm']}")
        input_kind = adapter.input_kind or ROOT_SIGNAL_KIND
        output_kind = adapter.output_kind

        position = pn.pane.Markdown(f"**Step {index + 1}**")
        algorithm = pn.pane.Markdown(f"**{step['stage']}.{step['algorithm']}**")
        types = pn.pane.Markdown(
            f"in: `{input_kind}` {_ARROW} out: `{output_kind}`"
        )

        up = pn.widgets.Button(name="\u2191", width=32, disabled=(index == 0))
        down = pn.widgets.Button(
            name="\u2193", width=32, disabled=(index == len(self.chain.steps) - 1)
        )
        delete = pn.widgets.Button(name="Delete", width=64, button_type="danger")
        up.on_click(lambda _e, idx=index: self._move_step(idx, -1))
        down.on_click(lambda _e, idx=index: self._move_step(idx, +1))
        delete.on_click(lambda _e, idx=index: self._delete_step(idx))

        return pn.Column(
            position,
            algorithm,
            types,
            pn.Row(up, down, delete),
            width=_CARD_WIDTH,
            styles={
                "border": "1px solid #ccc",
                "border-radius": "6px",
                "padding": "10px",
                "background": "#fafafa",
            },
        )

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

    def _invalid_status(self):
        """The invalid-chain message with the *junction* named, not just the
        offending block. `self.chain.invalid_reason` stays the single source
        of the "why"; this only locates the first bad transition so the
        researcher knows which connection to fix."""
        junction = self._first_invalid_junction()
        if junction is None:
            return f"**Invalid chain:** {self.chain.invalid_reason}"

        index, producing_kind, block = junction
        expected_kind = block.input_kind or ROOT_SIGNAL_KIND
        if index == 0:
            source = f"the root signal (`{producing_kind}`)"
        else:
            previous = self.chain.steps[index - 1]
            source = (
                f"step {index} (`{previous['stage']}.{previous['algorithm']}`, "
                f"outputs `{producing_kind}`)"
            )
        return (
            f"**Invalid chain:** between {source} and step {index + 1} "
            f"(`{block.name}`, expects `{expected_kind}`). "
            f"{self.chain.invalid_reason}"
        )

    def _first_invalid_junction(self):
        """The first `(step_index, producing_kind, adapter)` whose primary
        input cannot be fed by the previous step, using the one
        compatibility function. Returns `None` when no typed junction is
        wrong (including when an adapter is no longer registered)."""
        producing_kind = ROOT_SIGNAL_KIND
        for index, step in enumerate(self.chain.steps):
            name = f"{step['stage']}.{step['algorithm']}"
            try:
                adapter = get_adapter(name)
            except KeyError:
                return None
            ok, _reason = check_step_compatibility(producing_kind, adapter)
            if not ok:
                return index, producing_kind, adapter
            producing_kind = adapter.output_kind
        return None
