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
(`execute_recipe` / `fan_out_recipe` on a daemon thread with a cooperative
`should_cancel`).

The surrogate toggle is deliberately NOT here — ticket 44 owns that control
(merge risk MEDIUM vs 44), and ticket 32 owns progress/per-stage-result
rendering on this same file (merge risk HIGH vs 32). This surface only
decides, launches and cancels.
"""

import threading

import panel as pn

from Working.config import CLUSTER_ROUTING_CEILING_S
from Working.database import queries as q
from Working.execution import RecipeCancelled, RecipeExecutionError, execute_recipe
from Working.hpc.job_export import estimate_recipe_seconds, export_job, route_recipe
from Working.recipes import recipe_summary
from Working.run_groups import fan_out_recipe

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

    def __init__(self, app, chain=None, ceiling_s=CLUSTER_ROUTING_CEILING_S):
        self.app = app
        if chain is None:
            builder = getattr(app, "chain_builder", None)
            chain = getattr(builder, "chain", None)
        self.chain = chain or ChainState(recording_id=getattr(app, "_recording_id", 1))
        self.ceiling_s = ceiling_s

        self._cancel_event = threading.Event()
        self._thread = None
        # Latest computed values, exposed for tests and for the export action.
        self._estimate_seconds = None
        self._fanout_width = 1
        self._route = None

        self.estimate_pane = pn.pane.Markdown("")
        self.routing_pane = pn.pane.Markdown("")

        self.channel_scope = pn.widgets.MultiSelect(name="Channels", size=6)
        self.band_scope = pn.widgets.MultiSelect(name="Bands", size=4)
        self.whole_channel = pn.widgets.Checkbox(name="Whole channel", value=True)
        self.span_start = pn.widgets.IntInput(name="Span start", value=0, start=0)
        self.span_end = pn.widgets.IntInput(name="Span end", value=0, start=0)

        self.local_button = pn.widgets.Button(name="Run locally", button_type="primary")
        self.export_button = pn.widgets.Button(name="Export cluster job", button_type="default")
        self.cancel_button = pn.widgets.Button(name="Cancel", button_type="danger", disabled=True)
        self.status = pn.pane.Markdown("")

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
            pn.Row(self.local_button, self.export_button, self.cancel_button),
            self.status,
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

    # ── recipe / scope ─────────────────────────────────────────────────────

    def _current_recipe(self):
        """The chain's recipe with the scope selector's span and fan-out
        applied — the recipe a launch or export would actually run."""
        recipe = self.chain.to_recipe()
        fan = self._build_fan_out()
        if fan:
            recipe["fan_out"] = fan
        recipe["span"] = self._current_span()
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

        db_path = self.app.conn.execute("PRAGMA database_list").fetchone()[2] or None
        doc = pn.state.curdoc  # captured here, on the serving thread

        def _worker():
            # A worker thread must never touch `self.app.conn` — SQLite
            # connections are thread-affined. `fan_out_recipe` /
            # `execute_recipe` open their own connection from `db_path`.
            def on_progress(i, n, label):
                def _update():
                    self.status.object = f"Running target {i + 1}/{n}: {label} ..."
                _run_on_ui_thread(doc, _update)

            try:
                if recipe.get("fan_out"):
                    out = fan_out_recipe(
                        recipe, db_path=db_path,
                        should_cancel=self._cancel_event.is_set,
                        on_progress=on_progress,
                    )
                else:
                    out = execute_recipe(
                        recipe, db_path=db_path,
                        should_cancel=self._cancel_event.is_set,
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

    def _on_run_finished(self, out):
        self.local_button.disabled = False
        self.export_button.disabled = False
        self.cancel_button.disabled = True
        if "run_group_id" in out:
            self.status.object = f"Done. run_group_id={out['run_group_id']}"
        else:
            self.status.object = f"Done. run_id={out['run_id']}"

    def _on_run_cancelled(self):
        self.local_button.disabled = False
        self.export_button.disabled = False
        self.cancel_button.disabled = True
        self.status.object = "**Cancelled.**"

    def _on_run_failed(self, message):
        self.local_button.disabled = False
        self.export_button.disabled = False
        self.cancel_button.disabled = True
        self.status.object = f"**Failed:** {message}"
