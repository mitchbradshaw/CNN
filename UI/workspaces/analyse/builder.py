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

Ticket 59: each card is also the block's edit surface. The generated
parameter controls, recommended-default bookkeeping, live derived readout
and side-input pickers are the same shared code the run panel and block
inspector use (`UI.analyse.param_widgets` / `UI.analyse.derive`), imported
here rather than forked, so an adapter's controls cannot drift between the
three surfaces.
"""

import numpy as np
import panel as pn

from Adapters.registry import get_adapter, list_adapters
from Working.chain_validation import ROOT_SIGNAL_KIND, check_step_compatibility
from Working.database import queries as q

from UI.analyse.chain_state import ChainState, ChainStateError
from UI.analyse.derive import DeriveMixin
from UI.analyse.param_widgets import _widget_for_param

_EMPTY_STEPS_NOTICE = "*No steps staged yet — use the + to add one.*"
_CARD_WIDTH = 320
_ARROW = "\u2192"


class _BlockCard(DeriveMixin):
    """The edit half of one block card — the generated parameter controls,
    the recommended-default bookkeeping, the live derived readout, and one
    side-input picker per declared side input. One instance per step on the
    canvas, created by `ChainBuilder._render_card` and embedded in the card.

    Parameter widgets and the derived-readout mixin are imported from the
    same shared modules the run panel and block inspector use, so an
    adapter's controls cannot drift between the three surfaces.
    """

    def __init__(self, app, chain, index, spec):
        self.app = app
        self.chain = chain
        self.index = index
        self.spec = spec
        self.conn = getattr(app, "conn", None)

        # The small attribute surface `DeriveMixin` reads and writes — the
        # same one the run panel and block inspector set up, so the shared
        # mixin needs no change.
        self.algorithm_select = pn.widgets.Select(value=spec.name)
        self.preprocess_window = pn.widgets.FloatInput(value=0.0)
        self.auto_preview_checkbox = pn.widgets.Checkbox(value=False)
        self.span_changed_note = pn.pane.Markdown("")
        self.derived_pane = pn.pane.HTML("", sizing_mode="stretch_width")
        self.reset_recommended_button = pn.widgets.Button(
            name="Reset to recommended", button_type="default"
        )
        self.side_inputs_column = pn.Column()
        self._param_widgets = {}
        self._param_base_names = {}
        self._recommended_values = {}
        self._recommended_preprocess_window = None
        self._syncing_segment_controls = False
        self._suppress_param_watchers = False
        self._side_input_widgets = {}
        self._exemplar_rows = {}

        self._build_param_widgets()
        self._wire_param_watchers()
        # A fresh step (params empty) gets the span-aware recommendations;
        # a step that already carries params (a user edit, or one restored
        # from a recipe) keeps those values when the card is re-rendered
        # after a reorder/add — only the explicit "Reset to recommended"
        # button force-applies over an edit.
        if self._step() and self._step().get("params"):
            self._record_recommended_preserving_edits()
        else:
            self._apply_recommended_defaults(force=True)
        self._sync_params_to_step()
        self._render_side_inputs()
        self.reset_recommended_button.on_click(self._on_reset_recommended)

    # ── the step this card edits ──────────────────────────────────────────

    def _step(self):
        if not 0 <= self.index < len(self.chain.steps):
            return None
        return self.chain.steps[self.index]

    # ── parameter widgets ────────────────────────────────────────────────

    def _build_param_widgets(self):
        step = self._step()
        existing = step.get("params", {}) if step else {}
        for p in self.spec.params:
            widget = _widget_for_param(p)
            if p.name in existing:
                widget.value = existing[p.name]
            self._param_widgets[p.name] = widget
            self._param_base_names[p.name] = widget.name

    def _wire_param_watchers(self):
        for pname, widget in self._param_widgets.items():
            widget.param.watch(
                lambda event, n=pname: self._on_param_changed(n), "value"
            )

    def _on_param_changed(self, pname):
        # Editing a parameter on the card edits the chain model, and the
        # shared mixin refreshes the modified marker + derived readout.
        self._write_param_to_step(pname)
        self._on_param_widget_changed(pname)

    def _write_param_to_step(self, pname):
        step = self._step()
        if step is None:
            return
        widget = self._param_widgets.get(pname)
        if widget is not None:
            step["params"][pname] = widget.value

    def _sync_params_to_step(self):
        step = self._step()
        if step is None:
            return
        for pname, widget in self._param_widgets.items():
            step["params"][pname] = widget.value

    def _on_reset_recommended(self, _event):
        self._apply_recommended_defaults(force=True)
        self._sync_params_to_step()

    # ── the small contract `DeriveMixin` needs ───────────────────────────

    def _current_span(self):
        if getattr(self.chain, "span", None):
            return tuple(self.chain.span)
        return None

    def _current_span_signal(self):
        conn = self.conn
        recording_id = getattr(self.app, "_recording_id", None)
        if recording_id is None or conn is None:
            return None
        recording = q.get_recording_by_id(conn, recording_id)
        if recording is None:
            return None
        span = self._current_span()
        if span is None:
            start, end = 0, recording["n_samples"]
        else:
            start, end = span
        x_full = np.load(recording["npy_path"], mmap_mode="r")
        x = np.asarray(x_full[start:end])
        t = np.arange(start, end) / recording["fs"]
        return x, t, recording["fs"], recording

    def _current_params(self):
        return {name: w.value for name, w in self._param_widgets.items()}

    def _record_recommended_preserving_edits(self):
        """Record the span-aware recommendations for the modified marker
        WITHOUT overwriting widget values that came from the step's existing
        params (a user edit or a restored recipe).

        `DeriveMixin._apply_recommended_defaults` decides whether to apply
        by comparing against the last-applied recommendation, which a fresh
        card instance does not have — so on re-render it cannot tell a prior
        edit from a default. The step's non-empty `params` dict is that
        signal, so this path only records the bookkeeping the marker reads.
        """
        name = self.algorithm_select.value
        spec = get_adapter(name) if name else None
        if spec is None or spec.recommend is None:
            self.span_changed_note.object = ""
            return
        signal = self._current_span_signal()
        if signal is None:
            return
        x, t, fs, _recording = signal
        rec = spec.recommend(x, t, fs)
        self._recommended_values = {k: v for k, v in rec.items() if k != "preprocess_window_s"}
        if "preprocess_window_s" in rec:
            self._recommended_preprocess_window = rec["preprocess_window_s"]
        for pname, widget in self._param_widgets.items():
            base = self._param_base_names.get(pname, widget.name)
            recommended = self._recommended_values.get(pname)
            modified = recommended is not None and widget.value != recommended
            new_name = f"{base} •" if modified else base
            if widget.name != new_name:
                widget.name = new_name
        self._sync_segment_mode_controls()
        self._refresh_derived()

    def _schedule_auto_preview(self):
        # Cards do not auto-preview runs; this is the only `DeriveMixin`
        # hook that assumes the run panel's preview machinery.
        return None

    # ── side inputs: one picker per declared entry ───────────────────────
    # Adapted from the block inspector (the PRD relocates this content onto
    # the card and the inspector ceases to exist), parameterised to the
    # card's fixed step index instead of a step select. The parameter-widget
    # and derived-readout halves come from the shared modules; this half has
    # no shared module yet, so it lives on the destination surface.

    def _render_side_inputs(self):
        self.side_inputs_column.clear()
        self._side_input_widgets = {}
        if not self.spec.side_inputs:
            self.side_inputs_column.objects = []
            return
        rows = [self._build_side_input_row(si) for si in self.spec.side_inputs]
        self.side_inputs_column.objects = rows

    def _build_side_input_row(self, side_input):
        name = side_input.name
        source_options = self._source_options(side_input)

        source_select = pn.widgets.Select(
            name="Source", options=source_options, value=None,
        )
        earlier_options = self._earlier_step_options(side_input.type_kind)
        target_select = pn.widgets.Select(
            name="Earlier step", options=earlier_options,
            value=next(iter(earlier_options.values()), None),
        )
        exemplar_options = self._library_exemplar_options()
        exemplar_select = pn.widgets.Select(
            name="Library exemplar", options=exemplar_options,
            value=next(iter(exemplar_options.values()), None),
        )

        self._side_input_widgets[name] = {
            "source": source_select,
            "target": target_select,
            "exemplar": exemplar_select,
        }

        # Reflect any binding already on the step before wiring watchers, so
        # the initial restore doesn't read as a user edit.
        step = self._step()
        existing = step.get("side_inputs", {}).get(name) if step else None
        if existing:
            if existing["source_kind"] in source_options.values():
                source_select.value = existing["source_kind"]
            if existing["source_kind"] == "earlier_step" and existing["step_index"] in earlier_options.values():
                target_select.value = existing["step_index"]
            if existing["source_kind"] == "library_exemplar" and existing["entry_id"] in exemplar_options.values():
                exemplar_select.value = existing["entry_id"]

        source_select.param.watch(
            lambda event, n=name: self._on_side_input_source_changed(n), "value"
        )
        target_select.param.watch(
            lambda event, n=name: self._on_side_input_target_changed(n), "value"
        )
        exemplar_select.param.watch(
            lambda event, n=name: self._on_side_input_exemplar_changed(n), "value"
        )

        target_select.visible = source_select.value == "earlier_step"
        exemplar_select.visible = source_select.value == "library_exemplar"

        # Panel auto-selects the first option when a Select has a None value,
        # so record that default binding rather than showing a picker whose
        # chosen source isn't actually on the step.
        self._write_side_input_binding(name)

        return pn.Column(
            pn.pane.Markdown(f"**{name}** (*{side_input.type_kind}*)"),
            source_select,
            target_select,
            exemplar_select,
            sizing_mode="stretch_width",
        )

    def _source_options(self, side_input):
        """Only sources the side input *declares* and that can produce its
        declared `type_kind` are offered."""
        options = {}
        if "root_signal" in side_input.sources and side_input.type_kind == "signal":
            options["Root signal"] = "root_signal"
        if "earlier_step" in side_input.sources and self._earlier_step_options(side_input.type_kind):
            options["Earlier step"] = "earlier_step"
        if "library_exemplar" in side_input.sources and side_input.type_kind == "signal" \
                and self._library_exemplar_options():
            options["Library exemplar"] = "library_exemplar"
        return options

    def _earlier_step_options(self, type_kind):
        options = {}
        for i in range(0, self.index):
            step = self.chain.steps[i]
            spec = get_adapter(f"{step['stage']}.{step['algorithm']}")
            if spec.output_kind == type_kind:
                options[f"{i + 1}. {step['stage']}.{step['algorithm']}"] = i
        return options

    def _library_exemplar_options(self):
        if self.conn is None:
            return {}
        rows = self.conn.execute(
            """SELECT e.id AS entry_id, e.recording_id, e.start_idx, e.end_idx,
                      r.source_file, r.channel
               FROM motif_entry e
               JOIN recordings r ON r.id = e.recording_id
               ORDER BY e.id"""
        ).fetchall()
        self._exemplar_rows = {int(row["entry_id"]): row for row in rows}
        return {
            f"Entry {row['entry_id']}: {row['source_file']} ch{row['channel']} "
            f"[{row['start_idx']},{row['end_idx']})": int(row["entry_id"])
            for row in rows
        }

    def _on_side_input_source_changed(self, name):
        widgets = self._side_input_widgets[name]
        source = widgets["source"].value
        widgets["target"].visible = source == "earlier_step"
        widgets["exemplar"].visible = source == "library_exemplar"
        self._write_side_input_binding(name)

    def _on_side_input_target_changed(self, name):
        if self._side_input_widgets[name]["source"].value == "earlier_step":
            self._write_side_input_binding(name)

    def _on_side_input_exemplar_changed(self, name):
        if self._side_input_widgets[name]["source"].value == "library_exemplar":
            self._write_side_input_binding(name)

    def _write_side_input_binding(self, name):
        step = self._step()
        if step is None:
            return
        widgets = self._side_input_widgets[name]
        source = widgets["source"].value

        if source == "root_signal":
            step["side_inputs"][name] = {"source_kind": "root_signal"}
        elif source == "earlier_step":
            target = widgets["target"].value
            if target is None:
                step["side_inputs"].pop(name, None)
            else:
                step["side_inputs"][name] = {
                    "source_kind": "earlier_step",
                    "step_index": int(target),
                }
        elif source == "library_exemplar":
            entry_id = widgets["exemplar"].value
            if entry_id is None:
                step["side_inputs"].pop(name, None)
            else:
                row = self._exemplar_rows[int(entry_id)]
                step["side_inputs"][name] = {
                    "source_kind": "library_exemplar",
                    "entry_id": int(row["entry_id"]),
                    "source_file": row["source_file"],
                    "channel": int(row["channel"]),
                    "start_idx": int(row["start_idx"]),
                    "end_idx": int(row["end_idx"]),
                }
        else:
            step["side_inputs"].pop(name, None)

    # ── what the card embeds ──────────────────────────────────────────────

    def panes(self):
        """The panes to embed in the card, in reading order."""
        parts = []
        if self._param_widgets:
            parts.append(pn.pane.Markdown("**Parameters**"))
            parts.extend(self._param_widgets.values())
            parts.append(self.reset_recommended_button)
            parts.append(self.span_changed_note)
        if self.spec.derive is not None:
            parts.append(pn.pane.Markdown("**Derived**"))
            parts.append(self.derived_pane)
        if self.spec.side_inputs:
            parts.append(pn.pane.Markdown("**Side inputs**"))
            parts.append(self.side_inputs_column)
        return parts


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
        self._active_insert_index = None
        self._refresh()

    def layout(self):
        return pn.Column(
            pn.pane.Markdown("### Chain"),
            self.status,
            self.steps_row,
            pn.layout.Divider(),
            pn.pane.Markdown("### Insert a block"),
            self.add_column,
            sizing_mode="stretch_width",
        )

    # ── editing: add, move, delete — each revalidates immediately ──────────

    def _add_step(self, block):
        algorithm = block.name.split(".", 1)[1]
        self.chain.add_step(block.stage, algorithm)
        self._refresh()

    def _insert_step(self, block, position):
        """Insert `block` at `position` (0-based) rather than appending.

        The chain model's `add_step` already accepts an insertion index; the
        surface has simply never offered one. Inserting mid-chain shifts every
        step at index >= `position` up by one, so any `earlier_step` side-input
        bound to a shifted step must follow it or it silently points at the
        wrong (or the newly inserted) step — `_rebind_after_insertion` keeps
        those bindings honest without changing the model.
        """
        algorithm = block.name.split(".", 1)[1]
        self.chain.add_step(block.stage, algorithm, index=position)
        self._rebind_after_insertion(position)
        self._refresh()

    def _rebind_after_insertion(self, position):
        """Follow `earlier_step` side-inputs that pointed at a step shifted
        by an insertion at `position`."""
        for step in self.chain.steps:
            for binding in step["side_inputs"].values():
                if binding.get("source_kind") == "earlier_step" \
                        and binding["step_index"] >= position:
                    binding["step_index"] += 1

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
        # Any edit closes an open + picker: the position it was bound to may
        # have moved or gone away, and re-opening it for the new layout is
        # less surprising than keeping a stale picker open.
        self._active_insert_index = None
        self._render_steps()
        self._render_add_controls()
        self.status.object = "" if self.chain.is_valid else self._invalid_status()

    def _render_steps(self):
        self.cards = []
        self.connectors = []
        if not self.chain.steps:
            self.steps_row.objects = [
                pn.pane.Markdown(_EMPTY_STEPS_NOTICE),
                self._render_insert_button(0),
            ]
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
            # A + after each card: between this card and the next (position
            # i + 1), or after the last card (the chain's end).
            objects.append(self._render_insert_button(i + 1))
        self.steps_row.objects = objects

    def _render_insert_button(self, position):
        """The `+` between cards / at the chain's end. Clicking it opens the
        picker for that insertion position."""
        button = pn.widgets.Button(name="+", width=32, button_type="default")
        button.on_click(lambda _e, pos=position: self._open_picker(pos))
        return button

    def _render_card(self, index, step):
        adapter = get_adapter(f"{step['stage']}.{step['algorithm']}")
        input_kind = adapter.input_kind or ROOT_SIGNAL_KIND
        output_kind = adapter.output_kind

        position = pn.pane.Markdown(f"**Step {index + 1}**")
        algorithm = pn.pane.Markdown(f"**{step['stage']}.{step['algorithm']}**")
        types = pn.pane.Markdown(
            f"in: `{input_kind}` {_ARROW} out: `{output_kind}`"
        )

        editor = _BlockCard(self.app, self.chain, index, adapter)

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
            *editor.panes(),
            pn.Row(up, down, delete),
            width=_CARD_WIDTH,
            styles={
                "border": "1px solid #ccc",
                "border-radius": "6px",
                "padding": "10px",
                "background": "#fafafa",
            },
        )

    def _open_picker(self, position):
        """Open the block picker for `position` — the `+` was clicked. The
        picker lives in `add_column` (the same container the old permanent
        add-step list used) rather than permanently on the surface."""
        self._active_insert_index = position
        self._render_add_controls()

    def _render_add_controls(self):
        """The picker rows for the open `+`, or nothing when no `+` is open.
        Every registered block is listed; an incompatible one is disabled with
        the reason `Working.chain_validation` gives, never filtered out."""
        if self._active_insert_index is None:
            self.add_column.objects = []
            return
        self.add_column.objects = self._picker_rows(self._active_insert_index)

    def _picker_rows(self, position):
        """The `(button, reason)` rows for inserting at `position`.

        A block is compatible at `position` when it can be fed by the previous
        step's output (or the root signal at position 0) AND its own output can
        feed the next step. Both halves go through the one chain-validation
        function, so the reason text is the same text the rest of the system
        uses — this surface doesn't invent wording.
        """
        producing_kind = self._producing_kind_at(position)
        next_block = self._next_block_at(position)
        rows = []
        for block in list_adapters():
            ok, reason = check_step_compatibility(producing_kind, block)
            if ok and next_block is not None:
                ok_down, reason_down = check_step_compatibility(block.output_kind, next_block)
                if not ok_down:
                    ok, reason = False, reason_down
            button = pn.widgets.Button(
                name=f"Add {block.display_name}",
                disabled=not ok,
                button_type="primary" if ok else "default",
            )
            button.on_click(lambda _e, b=block, pos=position: self._insert_step(b, pos))
            rows.append(pn.Row(button, pn.pane.Markdown(reason), sizing_mode="stretch_width"))
        return rows

    def _producing_kind_at(self, position):
        """What feeds a block inserted at `position` — the previous step's
        output, or the root signal for the chain's start."""
        if position <= 0:
            return ROOT_SIGNAL_KIND
        step = self.chain.steps[position - 1]
        try:
            return get_adapter(f"{step['stage']}.{step['algorithm']}").output_kind
        except KeyError:
            return ROOT_SIGNAL_KIND

    def _next_block_at(self, position):
        """The step that will sit after an insertion at `position`, or None
        when inserting at the chain's end."""
        if position >= len(self.chain.steps):
            return None
        step = self.chain.steps[position]
        try:
            return get_adapter(f"{step['stage']}.{step['algorithm']}")
        except KeyError:
            return None

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
