"""
UI/workspaces/analyse/inspector.py
===================================
Ticket 30 — the block inspector. One step of the chain under construction,
opened in isolation: the parameter controls auto-generated from its
`ParamSpec` list, the live `derive()` readout, one side-input picker per
declared `SideInputSpec`, and the step's cached `step_artifacts` row from
ticket 15 when one exists.

It is deliberately a *read/edit* surface, not a second run surface. It does
not launch runs; the Run surface (ticket 31) does that. It reads the chain
from `app.chain_builder.chain` (ticket 29) rather than keeping a duplicate
model, exactly like `RunSurface` (ticket 31).

Parameter widgets, recommended defaults, modified markers and derived
readouts are reused from ticket 17's split (`UI.analyse.param_widgets` and
`UI.analyse.derive.DeriveMixin`) — they are the same controls the run panel
uses, so an adapter's controls cannot drift between the two surfaces.
"""

import os

import numpy as np
import panel as pn

from Adapters.registry import discover_adapters, get_adapter
from Working.database import queries as q
from Working.database.runs import get_step_artifact
from Working.execution import _recipe_prefix_hash

from UI.analyse.derive import DeriveMixin
from UI.analyse.param_widgets import _widget_for_param

discover_adapters()  # idempotent; makes every adapter self-register


class BlockInspector(DeriveMixin):
    """Open one step of the chain under construction and inspect/edit it."""

    def __init__(self, app):
        self.app = app
        self.conn = app.conn
        builder = getattr(app, "chain_builder", None)
        self.chain = builder.chain if builder is not None else None

        # Step picker. The value is the step index; labels are human.
        self.step_select = pn.widgets.Select(name="Step", options={})
        self.status = pn.pane.Markdown("")
        self.param_column = pn.Column()
        self.reset_recommended_button = pn.widgets.Button(
            name="Reset to recommended", button_type="default"
        )
        self.span_changed_note = pn.pane.Markdown("")
        self.derived_pane = pn.pane.HTML("")
        self.side_inputs_column = pn.Column()
        self.cached_pane = pn.pane.Markdown("")

        # DeriveMixin reads/writes these; they are kept out of the visible
        # layout for this surface. `algorithm_select` mirrors the selected
        # step's registry name so the mixin needs no change.
        self.algorithm_select = pn.widgets.Select(value="")
        self.preprocess_window = pn.widgets.FloatInput(value=0.0)
        self.auto_preview_checkbox = pn.widgets.Checkbox(value=False)
        self._param_widgets = {}
        self._param_base_names = {}
        self._recommended_values = {}
        self._recommended_preprocess_window = None
        self._syncing_segment_controls = False
        self._suppress_param_watchers = False

        self._side_input_widgets = {}
        self._exemplar_rows = {}

        self.step_select.param.watch(self._on_step_changed, "value")
        self.reset_recommended_button.on_click(self._on_reset_recommended)
        self._refresh_step_options()
        self._on_step_changed(None)

    # ── layout ───────────────────────────────────────────────────────────

    def layout(self):
        return pn.Column(
            pn.pane.Markdown("### Block inspector"),
            self.step_select,
            self.status,
            pn.pane.Markdown("#### Parameters"),
            self.param_column,
            self.reset_recommended_button,
            self.span_changed_note,
            pn.pane.Markdown("#### Derived"),
            self.derived_pane,
            pn.pane.Markdown("#### Side inputs"),
            self.side_inputs_column,
            pn.pane.Markdown("#### Cached result"),
            self.cached_pane,
            sizing_mode="stretch_width",
        )

    # ── step selection ───────────────────────────────────────────────────

    def _refresh_step_options(self):
        old = self.step_select.value
        options = {}
        for i, step in enumerate(self.chain.steps if self.chain is not None else []):
            label = f"{i + 1}. {step['stage']}.{step['algorithm']}"
            options[label] = i
        self.step_select.options = options
        if options:
            self.step_select.value = old if old in options.values() else 0
        else:
            self.step_select.value = None

    def _selected_step_index(self):
        return self.step_select.value

    def _selected_step(self):
        if self.chain is None:
            return None
        idx = self._selected_step_index()
        if idx is None or not (0 <= idx < len(self.chain.steps)):
            return None
        return self.chain.steps[idx]

    def _selected_spec(self):
        step = self._selected_step()
        if step is None:
            return None
        try:
            return get_adapter(f"{step['stage']}.{step['algorithm']}")
        except KeyError:
            return None

    def _on_step_changed(self, _event):
        self.param_column.clear()
        self.derived_pane.object = ""
        self.side_inputs_column.clear()
        self.cached_pane.object = ""
        self._side_input_widgets = {}
        self._param_widgets = {}
        self._param_base_names = {}
        self._recommended_values = {}
        self._recommended_preprocess_window = None

        step = self._selected_step()
        spec = self._selected_spec()
        if step is None or spec is None:
            self.algorithm_select.value = ""
            self.status.object = ""
            return

        self.algorithm_select.value = f"{step['stage']}.{step['algorithm']}"
        self.status.object = f"**{spec.display_name}** — {spec.description}"

        # Parameter controls from the spec, exactly as the run panel builds them.
        for p in spec.params:
            widget = _widget_for_param(p)
            self._param_widgets[p.name] = widget
            self._param_base_names[p.name] = widget.name
            widget.param.watch(
                lambda event, n=p.name: self._on_param_widget_changed(n),
                "value",
            )
        if self._param_widgets:
            self.param_column.objects = list(self._param_widgets.values())

        # Recommended defaults for the current span, then live derived rows.
        self._apply_recommended_defaults(force=True)
        self._sync_trend_param_controls()
        self._render_side_inputs(spec)
        self._refresh_cached_result()

    def _on_reset_recommended(self, _event):
        self._apply_recommended_defaults(force=True)

    # ── span / params, the small contract DeriveMixin needs ──────────────

    def _current_span(self):
        """The currently selected span, read from the legacy run panel when
        present (the same surface that owns span selection today) and from
        the chain's span otherwise."""
        run_panel = getattr(self.app, "run_panel", None)
        if run_panel is not None:
            try:
                span = run_panel._current_span()
                if span is not None:
                    return span
            except (ValueError, AttributeError):
                pass
        if getattr(self.chain, "span", None):
            return tuple(self.chain.span)
        return None

    def _current_span_signal(self):
        app = self.app
        recording_id = getattr(app, "_recording_id", None)
        if recording_id is None:
            return None
        recording = q.get_recording_by_id(self.conn, recording_id)
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

    def _schedule_auto_preview(self):
        """The inspector does not auto-preview runs; this is the only
        DeriveMixin hook that assumes the run panel's preview machinery."""
        return None

    # ── side inputs: one picker per declared entry ───────────────────────

    def _render_side_inputs(self, spec):
        self.side_inputs_column.clear()
        self._side_input_widgets = {}
        if not spec.side_inputs:
            self.side_inputs_column.objects = [pn.pane.Markdown("*No side inputs.*")]
            return

        rows = [self._build_side_input_row(spec, si) for si in spec.side_inputs]
        self.side_inputs_column.objects = rows

    def _build_side_input_row(self, spec, side_input):
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
        existing = self._selected_step().get("side_inputs", {}).get(name)
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
        idx = self._selected_step_index()
        options = {}
        for i in range(0, idx):
            step = self.chain.steps[i]
            spec = get_adapter(f"{step['stage']}.{step['algorithm']}")
            if spec.output_kind == type_kind:
                options[f"{i + 1}. {step['stage']}.{step['algorithm']}"] = i
        return options

    def _library_exemplar_options(self):
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
        step = self._selected_step()
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

    # ── cached result (ticket 15) ────────────────────────────────────────

    def _recipe(self):
        """The recipe the run surface would execute, via the chain model's
        own `to_recipe` seam — the same recipe the executor hashes for its
        step cache, so the cache key below matches the executor's."""
        if self.chain is None or not self.chain.steps:
            return None
        try:
            return self.chain.to_recipe()
        except ValueError:
            return None

    def _refresh_cached_result(self):
        self.cached_pane.object = ""
        idx = self._selected_step_index()
        if idx is None:
            return
        recipe = self._recipe()
        if recipe is None:
            return
        try:
            prefix_hash = _recipe_prefix_hash(recipe, idx)
            row = get_step_artifact(self.conn, prefix_hash, idx)
        except Exception:
            return
        if row is None:
            return
        path = row["path"]
        missing = "" if os.path.isdir(path) else " *(missing on disk)*"
        self.cached_pane.object = f"**Cached result:** `{path}`{missing}"
