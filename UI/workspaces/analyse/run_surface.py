"""
run_surface.py
===============
The run surface (ticket 31) — the decision surface before a run: what it
will cost, where it should execute, and the ability to stop it.

It reads the chain under construction (`app.chain_builder.chain`, a
`UI.analyse.chain_state.ChainState`), displays the summed per-step runtime
estimate multiplied by the fan-out width (PRD "Cluster routing"), reads
ticket 26's headless routing value (`Working.hpc.job_export.route_recipe`)
to promote "export cluster job" to the primary action above the configured
ceiling while demoting (never removing) local execution, feeds the ticket-25
scope selector (recordings/channels, span, bands) into the recipe's fan-out,
and wires launch/cancel to the ticket-24 background-run machinery
(`run_paired_recipe` / `fan_out_recipe` on a daemon thread with a cooperative
`should_cancel`).

Ticket 44 adds the surrogate toggle that defaults to on: every launch is
paired with a surrogate null run unless the researcher turns it off, and the
completion status shows detected-versus-surrogate counts rather than a bare
detection count. Ticket 32 adds the slow-run progress indicator (estimated
finish appears only above `MP_INTERACTIVE_BUDGET_S`) and the per-stage
results pane that accumulates each landed step.
"""

import datetime
import threading

import panel as pn

from Working.compare import compare_run_sets
from Working.config import CLUSTER_ROUTING_CEILING_S, MP_INTERACTIVE_BUDGET_S
from Working.database import queries as q
from Working.execution import RecipeCancelled, RecipeExecutionError
from Working.hpc.job_export import estimate_recipe_seconds, export_job, route_recipe
from Working.recipes import recipe_summary
from Working.run_groups import fan_out_recipe, run_paired_recipe

from UI.analyse.chain_state import ChainState
from UI.analyse.ui_thread import _run_on_ui_thread

#: Preset band targets for the band fan-out scope. These are UI options that
#: feed `Working.run_groups`' caller-supplied band target list — they are not
#: a replacement for the annotation-band vocabulary in `Working.database.bands`,
#: which answers a different question (classifying annotations, not fan-out).
_BAND_SCOPE_OPTIONS = (
    {"label": "delta", "low_hz": 0.5, "high_hz": 4.0},
    {"label": "theta", "low_hz": 4.0, "high_hz": 8.0},
    {"label": "alpha", "low_hz": 8.0, "high_hz": 13.0},
    {"label": "beta", "low_hz": 13.0, "high_hz": 30.0},
    {"label": "gamma", "low_hz": 30.0, "high_hz": 100.0},
)


def _fmt_seconds(seconds):
    """Compact human-readable duration; `None` renders as '?' (unknown)."""
    if seconds is None:
        return "?"
    seconds = float(seconds)
    if seconds < 60:
        return f"{seconds:g}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}min"
    return f"{seconds / 3600:.1f}h"


class RunSurface:
    """The run surface tab. `app` is read for its current recording id, fs,
    sample count, live database connection and (by default) the chain under
    construction; a `chain` may be passed explicitly instead."""

    def __init__(self, app, chain=None, ceiling_s=CLUSTER_ROUTING_CEILING_S,
                 progress_threshold_s=MP_INTERACTIVE_BUDGET_S):
        self.app = app
        if chain is None:
            builder = getattr(app, "chain_builder", None)
            chain = getattr(builder, "chain", None)
        self.chain = chain or ChainState(recording_id=getattr(app, "_recording_id", 1))
        self.ceiling_s = ceiling_s
        self.progress_threshold_s = progress_threshold_s

        self._cancel_event = threading.Event()
        self._thread = None
        # Latest computed values, exposed for tests and for the export action.
        self._estimate_seconds = None
        self._fanout_width = 1
        self._route = None
        self._current_target_label = None

        self.estimate_pane = pn.pane.Markdown("")
        self.routing_pane = pn.pane.Markdown("")

        self.channel_scope = pn.widgets.MultiSelect(name="Channels", size=6)
        self.band_scope = pn.widgets.MultiSelect(name="Bands", size=4)
        self.whole_channel = pn.widgets.Checkbox(name="Whole channel", value=True)
        self.span_start = pn.widgets.IntInput(name="Span start", value=0, start=0)
        self.span_end = pn.widgets.IntInput(name="Span end", value=0, start=0)

        self.surrogate_toggle = pn.widgets.Checkbox(
            name="Surrogate control", value=True,
        )
        self.local_button = pn.widgets.Button(name="Run locally", button_type="primary")
        self.export_button = pn.widgets.Button(name="Export cluster job", button_type="default")
        self.cancel_button = pn.widgets.Button(name="Cancel", button_type="danger", disabled=True)
        self.status = pn.pane.Markdown("")
        self.progress_pane = pn.pane.Markdown("")
        self.stage_results = pn.Column()

        self._load_scope_options()
        self._wire_handlers()
        self._refresh()

    # ── layout ─────────────────────────────────────────────────────────────

    def layout(self):
        return pn.Column(
            pn.pane.Markdown("### Run"),
            self.estimate_pane,
            self.routing_pane,
            pn.layout.Divider(),
            pn.pane.Markdown("### Scope"),
            pn.Row(self.whole_channel, self.span_start, self.span_end),
            self.channel_scope,
            self.band_scope,
            pn.layout.Divider(),
            pn.Row(self.surrogate_toggle),
            pn.Row(self.local_button, self.export_button, self.cancel_button),
            self.status,
            pn.layout.Divider(),
            pn.pane.Markdown("### Progress"),
            self.progress_pane,
            pn.pane.Markdown("### Stage results"),
            self.stage_results,
            sizing_mode="stretch_width",
        )

    # ── setup ──────────────────────────────────────────────────────────────

    def _load_scope_options(self):
        self._band_targets = {b["label"]: b for b in _BAND_SCOPE_OPTIONS}
        self.band_scope.options = list(self._band_targets)
        conn = getattr(self.app, "conn", None)
        if conn is not None:
            recordings = q.list_recordings(conn)
            self.channel_scope.options = {
                f"CH{r['channel']}": str(r["id"]) for r in recordings
            }
            n = getattr(self.app, "_n_samples", None)
            if n is None and recordings:
                n = recordings[0]["n_samples"]
            if n is not None:
                self.span_end.value = n
        # No channel is pre-selected: an empty channel scope means "run the
        # current recording once" (no fan-out), and only an explicit multi-
        # select creates a channel fan-out. Pre-selecting the current
        # recording here would silently turn every launch into a 1-target
        # fan-out.
        chain_span = getattr(self.chain, "span", None)
        if chain_span:
            self.whole_channel.value = False
            self.span_start.value = int(chain_span[0])
            self.span_end.value = int(chain_span[1])

    def _wire_handlers(self):
        self.local_button.on_click(self._on_run)
        self.export_button.on_click(self._on_export)
        self.cancel_button.on_click(self._on_cancel)
        self.channel_scope.param.watch(lambda _e: self._refresh(), "value")
        self.band_scope.param.watch(lambda _e: self._refresh(), "value")
        self.whole_channel.param.watch(lambda _e: self._refresh(), "value")
        self.span_start.param.watch(lambda _e: self._refresh(), "value")
        self.span_end.param.watch(lambda _e: self._refresh(), "value")
        self.surrogate_toggle.param.watch(lambda _e: self._refresh(), "value")

    # ── recipe / scope ─────────────────────────────────────────────────────

    def _current_recipe(self):
        """The chain's recipe with the scope selector's span and fan-out
        applied — the recipe a launch or export would actually run."""
        recipe = self.chain.to_recipe()
        fan = self._build_fan_out()
        if fan:
            recipe["fan_out"] = fan
        recipe["span"] = self._current_span()
        recipe["surrogate"] = bool(self.surrogate_toggle.value)
        return recipe

    def _build_fan_out(self):
        channels = [int(v) for v in self.channel_scope.value]
        if channels:
            return {"kind": "channels", "targets": channels}
        bands = list(self.band_scope.value)
        if bands:
            return {"kind": "bands", "targets": [self._band_targets[label] for label in bands]}
        return None

    def _current_span(self):
        if self.whole_channel.value:
            return None
        start = self.span_start.value
        end = self.span_end.value
        if end <= start:
            raise ValueError("Span end must be after span start.")
        return [start, end]

    def _recording_n_samples(self):
        n = getattr(self.app, "_n_samples", None)
        if n is not None:
            return n
        conn = getattr(self.app, "conn", None)
        if conn is not None and getattr(self.app, "_recording_id", None) is not None:
            rec = q.get_recording_by_id(conn, self.app._recording_id)
            if rec is not None:
                return rec["n_samples"]
        return 1

    def _recording_fs(self):
        return getattr(self.app, "_fs", None) or 1.0

    # ── estimate / routing display ─────────────────────────────────────────

    def _refresh(self):
        try:
            recipe = self._current_recipe()
        except ValueError as e:
            self.estimate_pane.object = f"**Chain not ready:** {e}"
            self.routing_pane.object = ""
            self._estimate_seconds = None
            self._fanout_width = 1
            self._route = None
            return

        n = self._recording_n_samples()
        fs = self._recording_fs()
        total = estimate_recipe_seconds(recipe, n, fs)
        route = route_recipe(recipe, n, fs, ceiling_s=self.ceiling_s)
        fan = recipe.get("fan_out")
        width = len(fan["targets"]) if fan else 1

        self._estimate_seconds = total
        self._fanout_width = width
        self._route = route

        if total:
            text = f"**Estimated runtime:** {_fmt_seconds(total)}"
            if width > 1:
                text += f"  (chain {_fmt_seconds(total / width)} × {width} targets)"
            self.estimate_pane.object = text
        elif route == "unknown":
            self.estimate_pane.object = "**Estimated runtime:** unknown (uncalibrated estimator)"
        else:
            self.estimate_pane.object = "**Estimated runtime:** < 1s (no calibrated estimator)"

        if route == "cluster":
            self.routing_pane.object = (
                "**Routing:** cluster job recommended — above the configured ceiling."
            )
            self.export_button.button_type = "primary"
            self.local_button.button_type = "default"
        elif route == "unknown":
            self.routing_pane.object = (
                "**Routing:** unknown — some blocks are uncalibrated; defaulting to local."
            )
            self.export_button.button_type = "default"
            self.local_button.button_type = "primary"
        else:
            self.routing_pane.object = "**Routing:** local — within the configured ceiling."
            self.export_button.button_type = "default"
            self.local_button.button_type = "primary"

    # ── progress / per-stage results (ticket 32) ──────────────────────────

    def _progress_visible(self):
        return (self._estimate_seconds is not None
                and self._estimate_seconds > self.progress_threshold_s)

    def _estimated_finish(self):
        if self._estimate_seconds is None:
            return "?"
        finish = datetime.datetime.now() + datetime.timedelta(seconds=self._estimate_seconds)
        return finish.strftime("%H:%M:%S")

    def _set_progress(self, detail):
        if self._progress_visible():
            self.progress_pane.object = (
                f"**Estimated finish:** {self._estimated_finish()} — {detail}"
            )
        else:
            self.progress_pane.object = ""

    def _update_step_progress(self, i, n_steps, stage, algorithm):
        self._set_progress(f"Step {i + 1}/{n_steps}: {stage}.{algorithm}")

    def _update_intra_step_progress(self, done, total, stage):
        self._set_progress(f"{stage}: {done}/{total}")

    def _update_target_progress(self, i, n_targets, label):
        self._set_progress(f"Target {i + 1}/{n_targets}: {label}")

    def _stage_label(self, recipe, step_index):
        fan = recipe.get("fan_out")
        if fan and fan["kind"] == "bands":
            if step_index == 0:
                return "preprocessing.bandpass"
            step = recipe["steps"][step_index - 1]
        else:
            step = recipe["steps"][step_index]
        return f"{step['stage']}.{step['algorithm']}"

    def _describe_result(self, result):
        kind = result.output_kind
        if kind == "spanset":
            return f"{len(getattr(result.value, 'starts', ()))} span(s)"
        if kind == "signal":
            shape = getattr(result.x, "shape", None)
            return f"signal {tuple(shape)}" if shape is not None else "signal"
        if kind == "encoding":
            try:
                n = len(result.encoding)
            except TypeError:
                n = None
            return f"encoding ({n} values)" if n is not None else "encoding"
        value = result.value
        if value is not None:
            for attr in ("n_windows", "n_timepoints", "starts"):
                if hasattr(value, attr):
                    try:
                        n = len(getattr(value, attr))
                    except TypeError:
                        continue
                    return f"{kind} ({n})"
        return kind

    def _clear_stage_results(self):
        self.stage_results.clear()

    def _append_stage_result(self, step_index, result, recipe, target_label=None):
        label = self._stage_label(recipe, step_index)
        heading = f"**Step {step_index + 1}** — {label}"
        if target_label is not None:
            heading += f" (target {target_label})"
        self.stage_results.append(
            pn.pane.Markdown(f"{heading}\n{self._describe_result(result)}")
        )

    # ── launch / cancel (ticket 24 background run) ─────────────────────────

    def _on_run(self, _event=None):
        self.status.object = ""
        if self._thread is not None and self._thread.is_alive():
            self.status.object = "**A run is already in progress.**"
            return

        try:
            recipe = self._current_recipe()
        except ValueError as e:
            self.status.object = f"**{e}**"
            return

        self._cancel_event.clear()
        self.local_button.disabled = True
        self.export_button.disabled = True
        self.cancel_button.disabled = False
        self.status.object = f"Running {recipe_summary(recipe)} ..."
        self._current_target_label = None
        self._clear_stage_results()
        self._set_progress("Starting ...")

        db_path = self.app.conn.execute("PRAGMA database_list").fetchone()[2] or None
        self._db_path = db_path
        doc = pn.state.curdoc  # captured here, on the serving thread

        def _worker():
            # A worker thread must never touch `self.app.conn` — SQLite
            # connections are thread-affined. `fan_out_recipe` /
            # `execute_recipe` open their own connection from `db_path`.
            def _show(status_text, progress_text):
                def _update():
                    self.status.object = status_text
                    self._set_progress(progress_text)
                _run_on_ui_thread(doc, _update)

            def on_step_progress(i, n, stage, algorithm):
                label = f"{stage}.{algorithm}"
                _show(
                    f"Running step {i + 1}/{n}: {label} ...",
                    f"Step {i + 1}/{n}: {label}",
                )

            def on_intra_progress(done, total, stage):
                _show(
                    f"Running {stage} {done}/{total} ...",
                    f"{stage}: {done}/{total}",
                )

            def on_target_progress(i, n, label):
                self._current_target_label = label
                _show(
                    f"Running target {i + 1}/{n}: {label} ...",
                    f"Target {i + 1}/{n}: {label}",
                )

            def on_step_result(i, result):
                target_label = self._current_target_label

                def _update():
                    self._append_stage_result(i, result, recipe, target_label=target_label)
                _run_on_ui_thread(doc, _update)

            run_kwargs = {"on_progress": on_intra_progress}
            try:
                if recipe.get("fan_out"):
                    out = fan_out_recipe(
                        recipe, db_path=db_path,
                        should_cancel=self._cancel_event.is_set,
                        on_progress=on_target_progress,
                        run_kwargs=run_kwargs,
                        on_step_result=on_step_result,
                        surrogate=recipe["surrogate"],
                    )
                else:
                    out = run_paired_recipe(
                        recipe, db_path=db_path,
                        should_cancel=self._cancel_event.is_set,
                        on_progress=on_step_progress,
                        run_kwargs=run_kwargs,
                        on_step_result=on_step_result,
                        surrogate=recipe["surrogate"],
                    )
                _run_on_ui_thread(doc, lambda: self._on_run_finished(out))
            except RecipeCancelled:
                _run_on_ui_thread(doc, lambda: self._on_run_cancelled())
            except RecipeExecutionError as e:
                _run_on_ui_thread(doc, lambda: self._on_run_failed(str(e)))

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def _on_cancel(self, _event=None):
        self._cancel_event.set()
        self.status.object = "Cancelling after the current step finishes ..."

    def _on_export(self, _event=None):
        try:
            recipe = self._current_recipe()
        except ValueError as e:
            self.status.object = f"**{e}**"
            return
        out_dir = getattr(self.app, "export_dir", "HPC/generated")
        try:
            result = export_job(
                recipe, out_dir=out_dir, base_name="chain_run", job_name="chain",
                est_seconds=self._estimate_seconds,
            )
        except Exception as e:
            self.status.object = f"**Export failed:** {e}"
            return
        self.status.object = f"**Exported cluster job:** {result['script_path']}"

    # ── completion handlers ────────────────────────────────────────────────

    def _paired_pairs(self, out):
        """(original_run_id, surrogate_run_id) pairs produced by a launch."""
        if "run_group_id" in out:
            return [(r["run_id"], r.get("surrogate_run_id"))
                    for r in out.get("runs", [])]
        return [(out["run_id"], out.get("surrogate_run_id"))]

    def _paired_summary(self, out):
        """Detected-versus-surrogate counts, computed through the one
        run-set overlap implementation in `Working.compare`.

        The completion handler runs on the background worker thread when
        there is no Bokeh session, so it must not reuse the app's live,
        thread-affined connection. When a launch supplied a database path,
        open a fresh connection for the comparison.
        """
        from Working.database.schema import init_db

        db_path = getattr(self, "_db_path", None)
        owns_conn = False
        if db_path:
            conn = init_db(db_path)
            owns_conn = True
        else:
            conn = getattr(self.app, "conn", None)
        if conn is None:
            return ""

        try:
            pairs = self._paired_pairs(out)
            if all(surrogate_run_id is None for _, surrogate_run_id in pairs):
                return "surrogate control off (no null run)"
            total_detected = 0
            total_surrogate = 0
            for run_id, surrogate_run_id in pairs:
                if surrogate_run_id is None:
                    continue
                comparison = compare_run_sets(conn, run_id, surrogate_run_id)
                total_detected += comparison.counts["a_total"]
                total_surrogate += comparison.counts["b_total"]
            return (f"{total_detected} detection(s) vs "
                    f"{total_surrogate} surrogate detection(s)")
        finally:
            if owns_conn:
                conn.close()

    def _on_run_finished(self, out):
        self.local_button.disabled = False
        self.export_button.disabled = False
        self.cancel_button.disabled = True
        self.progress_pane.object = ""
        if "run_group_id" in out:
            status = f"Done. run_group_id={out['run_group_id']}"
        else:
            status = f"Done. run_id={out['run_id']}"
        summary = self._paired_summary(out)
        if summary:
            status += f" — {summary}"
        self.status.object = status

    def _on_run_cancelled(self):
        self.local_button.disabled = False
        self.export_button.disabled = False
        self.cancel_button.disabled = True
        self.progress_pane.object = ""
        self.status.object = "**Cancelled.**"

    def _on_run_failed(self, message):
        self.local_button.disabled = False
        self.export_button.disabled = False
        self.cancel_button.disabled = True
        self.progress_pane.object = ""
        self.status.object = f"**Failed:** {message}"
