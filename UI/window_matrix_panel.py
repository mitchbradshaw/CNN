"""
window_matrix_panel.py
========================
Stage 3 UI for the window matrix (WINDOW_MATRIX_UI_PROMPT.md §8): the
timescale ladder, cost/routing, and run controls. Composed INTO the Run
panel rather than given its own tab — `UI/run_panel.py` is already 2,100+
lines and must not grow by another 500 for this.

Structured like `UI/motif_browser.py`'s scale switcher (the same ladder
idea at a different pipeline stage): a small component class with a
`layout()` and a `refresh(recording, span)` the owning `RunPanel` calls
whenever the algorithm selection, span, or recording changes.

Visibility (§3.1): the WHOLE component is hidden — not disabled, not shown
empty — unless `run_panel.algorithm_select.value ==
"preprocessing.window_matrix"`, the same convention `run_panel.
encoding_section` already follows for its own conditional section.

Selecting a ladder scale writes `window_min` straight into the
auto-generated parameter form (`run_panel._param_widgets["window_min"]`) —
`motif_browser.py` does exactly this for the MP adapter's scale switcher —
so the recipe that would actually run and the ladder shown here can never
disagree about what "this scale" means.

Progress plumbing
------------------
`Working.execution.execute_recipe`'s own `on_progress(step_index, n_steps,
stage, algorithm)` fires once per RECIPE STEP — useless as a progress bar
for a single window-matrix step that may run 27,000+ windows. The adapter's
`_run` (`Adapters/preprocessing_window_matrix.py`) now accepts
`on_progress(done, total, stage)`/`should_cancel()` directly and forwards
them into `build_window_matrix`'s own per-window loop; `execute_recipe`
threads them through via its `run_kwargs=` argument (matched against the
adapter's `run` signature, so every other adapter is unaffected). The two
callbacks are NOT the same thing and must not be conflated — this module
only ever uses the per-window one for its progress bar.

`build_window_matrix`'s cancellation is NOT an exception (unlike
`execute_recipe`'s own between-step `RecipeCancelled`): the adapter returns
normally with `meta["cancelled"] = True` and a valid partial artifact — see
WINDOW_MATRIX_UI_PROMPT.md §6.3 ("the runs row is genuinely completed... do
not mark the run failed to signal partiality"). `_on_run_finished` below
reads that flag rather than expecting an exception.
"""

import threading

import numpy as np
import panel as pn

from Adapters.preprocessing_window_matrix import default_artifact_path
from Working.config import WM_SCALE_LADDER_MIN
from Working.database import window_matrix_store as store
from Working.execution import RecipeCancelled, RecipeExecutionError, execute_recipe
from Working.hpc.job_export import export_wm_job
from Working.Preprocessing.window_matrix import cost
from Working.recipes import make_recipe
from UI.plots import build_window_matrix_ribbon

_STAGE_NAMES = ("catch22", "fast_entropy", "slow_entropy", "cnn", "rf")
_STAGE_LABELS = {
    "catch22": "Catch22", "fast_entropy": "fast entropy", "slow_entropy": "slow entropy",
    "cnn": "CNN", "rf": "random forest",
}
# verb -> per-tier button text. "Compute"/"Recompute"/"Resume" match the
# per-state affordance table (§3.2); the tier-specific wording (plain /
# "in background" / "Export HPC ... job") matches §3.3's "the primary
# button's label is the tier".
_TIER_VERB_LABELS = {
    "interactive": "{verb}",
    "background": "{verb} in background",
    "hpc": "Export HPC {verb_lower} job",
    "unknown": "{verb} (not calibrated)",
}


def _run_on_ui_thread(doc, fn):
    """Same bounce-to-the-Bokeh-document's-thread pattern as
    `run_panel._run_on_ui_thread` — a private copy, not an import, since
    each is three lines and importing would couple this module to
    run_panel's whole namespace for no benefit."""
    if doc is not None:
        doc.add_next_tick_callback(fn)
    else:
        fn()


def _fmt_seconds(seconds):
    if seconds is None:
        return "?"
    if seconds < 60:
        return f"{seconds:.0f} s"
    if seconds < 3600:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"


class WindowMatrixPanel:
    def __init__(self, run_panel):
        # Owned by RunPanel (not `app` directly, unlike `MotifBrowser`) —
        # this component reaches into `run_panel._param_widgets` and
        # `run_panel._build_steps()`/`_current_span()` directly, since it
        # exists specifically to stay in lockstep with the auto-generated
        # parameter form beside it.
        self.run_panel = run_panel
        self.app = run_panel.app
        self.conn = run_panel.conn

        self._recording = None
        self._span = None
        self._ladder_rows = {}
        self._label_to_window_min = {}
        self._selected_window_min = None
        self._last_describe = None
        self._thread = None
        self._cancel_event = threading.Event()
        self._calibrating = False

        self.scale_radio = pn.widgets.RadioButtonGroup(name="Timescale", options=[], button_type="default")
        self.scale_status = pn.pane.Markdown("*Pick a channel/span to see the timescale ladder.*")
        self.cost_status = pn.pane.Markdown("")
        self.calibrate_button = pn.widgets.Button(name="Calibrate", button_type="default", visible=False, width=120)
        self.calibrating_indicator = pn.pane.Markdown("", visible=False)
        self.action_button = pn.widgets.Button(name="Compute", button_type="primary", visible=False)
        self.cancel_button = pn.widgets.Button(name="Cancel", button_type="danger", visible=False, disabled=True)
        self.progress = pn.indicators.Progress(
            visible=False, active=False, bar_color="primary", value=0, max=100, sizing_mode="stretch_width",
        )
        self.run_status = pn.pane.Markdown("")
        self.hpc_status = pn.pane.Markdown("", visible=False)

        # Coverage ribbons (§4/§8.3) — a separate Column below the ladder
        # controls, one thin pane per ladder scale that has any coverage,
        # stacked under the staged-span preview per the layout spec; this
        # class only builds/holds them, `RunPanel.layout()` places the
        # Column where the preview lives.
        self.ribbon_column = pn.Column(visible=False, sizing_mode="stretch_width")

        self.card = pn.Card(
            pn.pane.Markdown("**Window matrix — timescale**"),
            self.scale_radio, self.scale_status,
            self.cost_status,
            pn.Row(self.calibrate_button, self.calibrating_indicator),
            pn.Row(self.action_button, self.cancel_button),
            self.progress, self.run_status, self.hpc_status,
            title="Window matrix", collapsed=False, visible=False, sizing_mode="stretch_width",
        )

        self.scale_radio.param.watch(self._on_scale_changed, "value")
        self.calibrate_button.on_click(self._on_calibrate)
        self.action_button.on_click(self._on_action)
        self.cancel_button.on_click(self._on_cancel)

    # ── Visibility (§3.1) ────────────────────────────────────────────────

    def set_visible(self, visible):
        """Hidden, not disabled, not shown empty — same convention
        `run_panel.encoding_section` follows."""
        self.card.visible = visible
        self.ribbon_column.visible = visible and bool(self.ribbon_column.objects)

    @property
    def visible(self):
        return self.card.visible

    # ── refresh(recording, span) — RunPanel calls this ──────────────────

    def refresh(self, recording, span):
        """`recording`: a `queries.get_recording_by_id` row, or None.
        `span`: whatever `RunPanel._current_span()` currently resolves to
        (None = whole channel) — the SAME span a real run would use, so the
        ladder's `n_windows`/cost estimates can never disagree with what
        Compute would actually do."""
        self._recording = recording
        self._span = span
        if not self.card.visible:
            return
        if recording is None:
            self._ladder_rows = {}
            self.scale_radio.options = []
            self.scale_status.object = "*No recording loaded.*"
            self.cost_status.object = ""
            self.action_button.visible = False
            self.ribbon_column.objects = []
            self.ribbon_column.visible = False
            return
        if self._calibrating:
            return  # the calibration worker refreshes again when it finishes

        self._maybe_auto_calibrate()

        step_frac = self._current_step_frac()
        rows = store.ladder_status(
            self.conn, recording["id"], recording["fs"], recording["n_samples"],
            step_frac=step_frac, span=span, estimate=cost.estimate_seconds,
        )
        self._ladder_rows = {r["window_min"]: r for r in rows}
        options = [self._label_for(r) for r in rows]
        self._label_to_window_min = {opt: r["window_min"] for opt, r in zip(options, rows)}
        self.scale_radio.options = options

        current_wm = self._current_window_min_param()
        matching = next(
            (opt for opt, wm in self._label_to_window_min.items() if np.isclose(wm, current_wm)),
            None,
        )
        if matching is not None and matching == self.scale_radio.value:
            # Same option string already selected — `.value` assignment
            # below would be a no-op and skip `_on_scale_changed`, so the
            # per-row status/cost text (which DOES need to refresh, e.g.
            # after a run just completed) is rendered here directly.
            self._render_state(self._ladder_rows[current_wm])
        elif matching is not None:
            self.scale_radio.value = matching
        elif options:
            self.scale_radio.value = options[0]
        else:
            self._selected_window_min = None
            self.scale_status.object = "*No valid timescale for this span at this sample rate.*"
            self.cost_status.object = ""
            self.action_button.visible = False

        self._refresh_ribbons()

    # ── Ladder labels ────────────────────────────────────────────────────

    def _measure_counts(self, row):
        total = len(store.measure_columns())
        unavail = len(store.measure_columns(row["unavailable_stages"])) if row["unavailable_stages"] else 0
        return total - unavail, total

    def _excluded_label(self, row):
        return ", ".join(_STAGE_LABELS[s] for s in row["unavailable_stages"])

    def _label_for(self, row):
        wm = row["window_min"]
        state = row["state"]
        if state == "invalid":
            return f"{wm:g} min (invalid)"
        if state == "missing":
            return f"{wm:g} min (missing)"
        if state == "stale":
            return f"{wm:g} min (stale)"
        if state == "partial":
            return f"{wm:g} min ({row['n_windows']:,} windows, partial)"
        # available
        avail, total = self._measure_counts(row)
        suffix = f", {avail}/{total} measures" if avail < total else ""
        return f"{wm:g} min ({row['n_windows']:,} windows{suffix})"

    # ── Selecting a scale ────────────────────────────────────────────────

    def _on_scale_changed(self, event):
        if event.new is None:
            return
        wm = self._label_to_window_min.get(event.new)
        if wm is None:
            return
        self._selected_window_min = wm
        row = self._ladder_rows[wm]

        # §3.2: writes window_min into the auto-generated form so the
        # recipe and the ladder can never disagree about what will run —
        # `motif_browser.py` does exactly this for the MP adapter.
        w = self.run_panel._param_widgets.get("window_min")
        if w is not None:
            w.value = wm

        self._render_state(row)

    def _render_state(self, row):
        state = row["state"]
        self.calibrate_button.visible = False
        self.calibrating_indicator.visible = self._calibrating
        self.action_button.visible = False
        self.cancel_button.visible = False
        self.hpc_status.visible = False
        self.cost_status.object = ""

        if state == "invalid":
            # Greyed (no Compute button) is expressed by simply never
            # showing one — Panel's RadioButtonGroup has no per-option
            # disable, so the option label itself already carries
            # "(invalid)" (see `_label_for`), matching `motif_browser.py`'s
            # existing treatment of the same limitation.
            self.scale_status.object = f"**Not valid here:** {row['reason']}"
            return

        if state == "stale":
            self.scale_status.object = f"**Stale:** {row['reason']}"
            self._render_cost(row, verb="Recompute")
            return

        if state == "partial":
            done, total = self._partial_progress(row)
            self.scale_status.object = (
                f"**Partial** — {done:,} / {total:,} windows computed "
                f"(run_id={row['run_id']})."
            )
            self._render_cost(row, verb="Resume")
            return

        if state == "missing":
            self.scale_status.object = "**Not computed yet.**"
            self._render_cost(row, verb="Compute")
            return

        # available
        avail, total = self._measure_counts(row)
        note = "" if avail == total else f" — {avail}/{total} measures (excludes {self._excluded_label(row)})"
        self.scale_status.object = f"**Available** — {row['n_windows']:,} windows{note} (run_id={row['run_id']})."

    def _render_cost(self, row, verb):
        """§3.3: estimate + tier shown BEFORE the user commits, via
        `cost.describe(n_windows, m, stages)` over the CURRENTLY SELECTED
        stages (the auto-generated form's catch22/fast_entropy/... boolean
        params) intersected with what's actually available at this scale —
        not `ladder_status`'s own generic "every available stage" estimate,
        since that wouldn't match what Compute is actually about to run."""
        selected = self._selected_stages()
        stages = tuple(s for s in selected if s in row["available_stages"])
        excluded_by_scale = tuple(s for s in selected if s in row["unavailable_stages"])

        if not stages:
            self.cost_status.object = "**No selected stage can run at this scale.**"
            self._last_describe = None
            self.action_button.visible = False
            return

        desc = cost.describe(row["n_windows"], row["m"], stages)
        self._last_describe = desc
        lines = []
        if desc["estimated_seconds"] is not None:
            lines.append(
                f"≈ {_fmt_seconds(desc['estimated_seconds'])} for "
                + ", ".join(_STAGE_LABELS[s] for s in stages)
            )
        if desc["unbudgeted_stages"]:
            names = ", ".join(_STAGE_LABELS[s] for s in desc["unbudgeted_stages"])
            lines.append(f"*not cost-calibrated:* {names}")
        if excluded_by_scale:
            names = ", ".join(_STAGE_LABELS[s] for s in excluded_by_scale)
            lines.append(f"*unavailable at this scale:* {names}")
        self.cost_status.object = "  \n".join(lines)

        if desc["tier"] == "unknown":
            self.calibrate_button.visible = True

        self.action_button.name = self._tier_label(desc["tier"], verb)
        self.action_button.visible = True

    def _tier_label(self, tier, verb):
        template = _TIER_VERB_LABELS[tier]
        text = template.format(verb=verb, verb_lower=verb.lower())
        if tier in ("interactive", "background") and self._last_describe:
            est = self._last_describe["estimated_seconds"]
            text += f" (≈ {_fmt_seconds(est)})"
        elif tier == "hpc" and self._last_describe:
            est = self._last_describe["estimated_seconds"]
            text += f" (≈ {_fmt_seconds(est)})" if est is not None else ""
        return text

    def _partial_progress(self, row):
        """(windows done, total windows) for a partial artifact. A window
        counts as "done" when every column belonging to a stage that's
        AVAILABLE at this scale is computed for that row — columns from a
        stage unavailable at this scale (§3.3) are excluded from the
        requirement, the same per-row logic `build.py`'s `_only_skipped_missing`
        already applies matrix-wide. Loads only the `computed` mask of the
        ONE selected artifact (not every ladder row — `ladder_status` stays
        cheap on purpose), so this is called only for the currently
        selected scale."""
        try:
            loaded = store.load_wm(row["artifact_path"], mmap=True)
        except Exception:
            return 0, row["n_windows"]
        computed = np.asarray(loaded["computed"], dtype=bool)
        columns = [str(c) for c in loaded["columns"]]
        skip_cols = set()
        for s in row["unavailable_stages"]:
            skip_cols.update(store.STAGE_COLUMNS[s]())
        keep = [i for i, c in enumerate(columns) if c not in skip_cols]
        done = int(computed.shape[0]) if not keep else int(computed[:, keep].all(axis=1).sum())
        return done, int(computed.shape[0])

    # ── Reading the auto-generated form ─────────────────────────────────

    def _selected_stages(self):
        widgets = self.run_panel._param_widgets
        return tuple(s for s in _STAGE_NAMES if s in widgets and bool(widgets[s].value))

    def _current_step_frac(self):
        w = self.run_panel._param_widgets.get("step_frac")
        return float(w.value) if w is not None else 1.0

    def _current_window_min_param(self):
        w = self.run_panel._param_widgets.get("window_min")
        return float(w.value) if w is not None else WM_SCALE_LADDER_MIN[1]

    # ── Calibration (§3.3) ───────────────────────────────────────────────

    def _maybe_auto_calibrate(self):
        """On first use, if any calibratable stage is uncalibrated on this
        machine, run `cost.calibrate()` automatically in the background —
        it takes a few seconds, and the alternative is a UI that says
        "unknown" until someone finds the Calibrate button. Decision
        recorded in WINDOW_MATRIX_STAGE3_SUMMARY.md's DECISIONS section."""
        if self._calibrating:
            return
        status = cost.calibration_status()
        if all(v != "uncalibrated" for v in status.values()):
            return
        self._start_calibration()

    def _on_calibrate(self, _event=None):
        self._start_calibration()

    def _start_calibration(self):
        if self._calibrating:
            return
        self._calibrating = True
        self.calibrating_indicator.object = "*calibrating…*"
        self.calibrating_indicator.visible = True
        self.calibrate_button.visible = False
        doc = pn.state.curdoc

        def _worker():
            try:
                cost.calibrate()
            except Exception:
                pass  # a failed calibration just leaves stages "unknown" — cost.describe already handles that honestly

            def _done():
                self._calibrating = False
                self.calibrating_indicator.visible = False
                if self._recording is not None:
                    self.refresh(self._recording, self._span)
            _run_on_ui_thread(doc, _done)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Running (§3.4) ───────────────────────────────────────────────────

    def _on_action(self, _event=None):
        if self._selected_window_min is None or self._recording is None:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        row = self._ladder_rows.get(self._selected_window_min)
        if row is None or self._last_describe is None:
            return

        recording = self._recording
        window_min = self._selected_window_min
        step_frac = self._current_step_frac()

        # Resume path set on EVERY run, not only resumes (§3.4): it's
        # deterministic from (recording, window_min, step_frac), so putting
        # it in from the start is what keeps the recipe/config hash stable
        # across a whole resubmit chain — filling it in only on the SECOND
        # job would make job 1 and job 2 different recipes.
        resume_path = default_artifact_path(recording, window_min, step_frac)
        resume_widget = self.run_panel._param_widgets.get("resume_path")
        if resume_widget is not None:
            resume_widget.value = resume_path

        if self._last_describe["tier"] == "hpc":
            self._export_hpc(recording, window_min, step_frac, row)
            return

        self._run_inline_or_background(recording, row)

    def _run_inline_or_background(self, recording, row):
        """Both the "interactive" and "background" tiers execute on a
        background `threading.Thread` — Panel/Bokeh serve one document per
        session on a shared server process, so a genuinely blocking call on
        the serving thread (even for <=WM_INTERACTIVE_BUDGET_S) would freeze
        every OTHER session's UI too, not just this tab, which is worse than
        the tiers' UX difference is meant to convey. The only observable
        difference between the two tiers is the estimate/label shown before
        committing (§3.3) — this mirrors `RunPanel._on_run`, which already
        always threads regardless of estimated duration. Recorded in
        WINDOW_MATRIX_STAGE3_SUMMARY.md's DECISIONS section.
        """
        steps = self.run_panel._build_steps()
        recipe = make_recipe(recording["id"], steps, span=self._span)

        # A partial/stale run's artifact belongs to a `runs` row that's
        # already `status='completed'` (§6.3) — without `force=True`,
        # `execute_recipe` would short-circuit on it and never actually
        # resume/recompute.
        force = row["state"] in ("partial", "stale")

        self._cancel_event.clear()
        self.action_button.disabled = True
        self.cancel_button.visible = True
        self.cancel_button.disabled = False
        self.progress.visible = True
        self.progress.active = True
        self.progress.value = 0
        self.progress.max = max(1, row["n_windows"])
        self.run_status.object = "Starting…"

        db_path = self.conn.execute("PRAGMA database_list").fetchone()[2] or None
        doc = pn.state.curdoc  # captured on the serving thread, before spawning

        def on_progress(done, total, stage):
            def _update():
                self.progress.max = max(1, int(total))
                self.progress.value = min(int(done), self.progress.max)
                self.run_status.object = f"{stage}: {done:,} / {total:,} windows"
            _run_on_ui_thread(doc, _update)

        def _worker():
            try:
                out = execute_recipe(
                    recipe, db_path=db_path, force=force,
                    should_cancel=self._cancel_event.is_set,
                    run_kwargs={"on_progress": on_progress, "should_cancel": self._cancel_event.is_set},
                )
                cancelled = bool(out["result"] is not None and out["result"].meta.get("cancelled"))
                _run_on_ui_thread(doc, lambda: self._on_run_finished(cancelled))
            except RecipeCancelled:
                _run_on_ui_thread(doc, lambda: self._on_run_finished(True))
            except RecipeExecutionError as e:
                _run_on_ui_thread(doc, lambda: self._on_run_failed(str(e)))

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def _on_cancel(self, _event=None):
        self._cancel_event.set()
        self.cancel_button.disabled = True
        self.run_status.object = "Cancelling…"

    def _on_run_finished(self, cancelled):
        self.action_button.disabled = False
        self.cancel_button.visible = False
        self.progress.active = False
        self.run_status.object = (
            "**Cancelled** — partial progress was saved and can be resumed."
            if cancelled else "**Done.**"
        )
        self._thread = None
        if self._recording is not None:
            self.refresh(self._recording, self._span)

    def _on_run_failed(self, message):
        self.action_button.disabled = False
        self.cancel_button.visible = False
        self.progress.active = False
        self.run_status.object = f"**Failed:** {message}"
        self._thread = None

    # ── HPC export (§3.4, §7) ────────────────────────────────────────────

    def _export_hpc(self, recording, window_min, step_frac, row):
        stages = tuple(s for s in self._selected_stages() if s in row["available_stages"])
        est = self._last_describe["estimated_seconds"] if self._last_describe else None

        widgets = self.run_panel._param_widgets
        cnn_model_dir = widgets["cnn_model_dir"].value if "cnn_model_dir" in widgets else "models"
        rf_model_path = widgets["rf_model_path"].value if "rf_model_path" in widgets else ""

        result = export_wm_job(
            self.conn, recording["id"], window_min, span=self._span, step_frac=step_frac,
            stages=stages, est_seconds=est,
            cnn_model_dir=cnn_model_dir, rf_model_path=rf_model_path,
        )
        # Explicit, not implied: this only writes into the local working
        # tree. A confirmation that reads like the job was submitted would
        # be a lie (§3.4).
        self.hpc_status.object = (
            "**HPC job generated — NOT submitted.**  \n"
            f"Script: `{result['script_path']}`  \n"
            f"Recipe: `{result['recipe_path']}`  \n"
            f"Run on the cluster once synced: `{result['sbatch_command']}`  \n\n"
            "*These files exist only in this local working tree. They still need "
            "to reach rangpur (git sync / scp / etc.) before `sbatch` can run them — "
            "nothing has been submitted anywhere.*"
        )
        self.hpc_status.visible = True

    # ── Coverage ribbons (§4, §8.3) ──────────────────────────────────────

    def _refresh_ribbons(self):
        self.ribbon_column.objects = []
        if self._recording is None:
            self.ribbon_column.visible = False
            return

        step_frac = self._current_step_frac()
        # WHOLE-CHANNEL coverage (span=None), not `self._span` — which scale
        # gets a pane at all is a question about the recording as a whole
        # ("has any coverage" per §4), separate from what that pane's
        # bucketing shows for the current viewport. Clipping this to
        # `self._span` first would drop a scale's pane entirely the moment
        # its coverage doesn't overlap the current viewport — exactly the
        # "scale with no coverage [in view] must still show the lane
        # background, not a blank/missing pane" case §8 verifies, since
        # `build_window_matrix_ribbon` already does its own per-viewport
        # clipping below.
        coverage = store.coverage_by_completeness(
            self.conn, self._recording["id"], span=None, step_frac=step_frac,
        )
        if not coverage:
            self.ribbon_column.visible = False
            return

        lo, hi = self._span if self._span is not None else (0, self._recording["n_samples"])
        fs = self._recording["fs"]
        panes = []
        for window_min in WM_SCALE_LADDER_MIN:
            cov = coverage.get(window_min)
            if not cov:
                continue
            panes.append(pn.pane.Markdown(f"*{window_min:g} min coverage*", margin=(0, 0, 0, 4)))
            panes.append(pn.pane.HoloViews(
                build_window_matrix_ribbon(cov, fs, (lo, hi)), sizing_mode="stretch_width",
            ))
        self.ribbon_column.objects = panes
        self.ribbon_column.visible = self.card.visible and bool(panes)

    # ── Layout ───────────────────────────────────────────────────────────

    def layout(self):
        """Just the sidebar card — `RunPanel.layout()` places `ribbon_column`
        separately, under the staged-span preview (§4), since the two live
        in different columns of the Run panel's layout."""
        return self.card
