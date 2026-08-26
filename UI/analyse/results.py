"""
What the run produced: the pre-run span preview and the post-run
Before/After pair (one pane, never both), the preprocessing banner, the
detections table, and saving the current plot as an artifact.
"""

import holoviews as hv
import numpy as np
import pandas as pd
import panel as pn

from Adapters.registry import get_adapter

from Working.database import queries as q
from Working.database import runs as R
from Working.artifacts import save_plot
from Working.config import RUN_PREVIEW_HEIGHT

from UI.plots import (
    build_peek_curve, compute_display_y_range, style_main_plot_frame, CURVE_COLOR,
    PLOT_FONTSIZE,
)
from UI.analyse.formatting import _format_duration_human


class ResultsMixin:
    """The preview/Before-After pane, preprocessing banner and detections table."""

    def _build_result_widgets(self):
        # Part 5, Section A: a single pane that holds EITHER the pre-run
        # "staged span" preview OR the post-run Before/After pair, never
        # both — see `_refresh_preview`/`_show_before_after`, the only two
        # places that assign `result_pane.object`.
        self.result_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.preview_info = pn.pane.Markdown("")
        self.yaxis_mode = pn.widgets.RadioButtonGroup(
            name="Y-axis", options=["Independent y-axis", "Shared y-axis"],
            value="Independent y-axis",
        )
        self.scale_note = pn.pane.Markdown("")
        self._last_before_after = None  # (recording, result_x, result_t) for the y-axis toggle to re-render without re-running

    def _build_detection_widgets(self):
        self.save_plot_button = pn.widgets.Button(
            name="Save plot", button_type="default", disabled=True,
        )
        self.save_plot_status = pn.pane.Markdown("")
        self.detections_placeholder = pn.pane.Markdown("*No run yet.*")
        # What these rows actually ARE. `execute_recipe` writes a detections
        # row for every span of ANY step whose output_kind is 'spanset', so
        # the answer is per-run and cannot be a static label: it names the
        # block, and the units start_idx/end_idx are counted in.
        self.detections_caption = pn.pane.Markdown("")
        self.detections_table = pn.widgets.Tabulator(
            pd.DataFrame(columns=["id", "start_idx", "end_idx", "score"]),
            page_size=8, disabled=True, selectable=1,
            show_index=False, sizing_mode="stretch_width", visible=False,
        )

    def _refresh_preview(self):
        """Render whatever `_current_span()` would actually run on, using
        the exact same decimated-curve rendering path as the Viewer tab
        (`UI.plots.build_peek_curve`, also used for the cross-channel peek)
        — never a second, independent renderer (A5), so this tab and the
        Viewer can never visually disagree about the same samples.

        `result_pane.object` has exactly two writers: this method (the
        pre-run preview) and `_show_before_after` (the post-run pair) —
        whichever ran most recently is what's on screen, so a stale
        single-plot and a Before/After pair can never both be showing
        (A2). Called on init, whenever the span mode or staged-row
        selection changes, and whenever the staged basket itself changes
        (`refresh_staged_list`) — i.e. every event that could change what
        `_current_span()` returns.
        """
        app = self.app
        if app._recording_id is None or app._fs is None:
            self.result_pane.object = None
            self.preview_info.object = "*No recording loaded.*"
            return
        try:
            span = self._current_span()
        except ValueError as e:
            self.result_pane.object = None
            self.preview_info.object = f"*{e}*"
            return

        start, end = (0, app._n_samples) if span is None else span
        recording = q.get_recording_by_id(self.conn, app._recording_id)
        # Part A4: "Whole channel" is just `(0, n_samples)` through this
        # SAME call — `build_peek_curve` already decimates via
        # `_minmax_decimate`, so a multi-million-sample channel is never
        # rendered raw, with no special-casing needed here.
        curve = build_peek_curve(
            recording["npy_path"], recording["fs"], (start, end), height=RUN_PREVIEW_HEIGHT,
        ).opts(color=CURVE_COLOR, title="Staged span — not yet processed")
        if self.window_matrix_panel.visible:
            # The coverage ribbons (§4) sit directly under this preview and
            # share its x-range only, the same relationship the Viewer's own
            # ribbon panes have to its main curve — which requires matching
            # `min_border_left`/`right` (`style_main_plot_frame`, the same
            # hook the Viewer curve uses), or a wider/narrower left margin
            # here shifts every ribbon bucket sideways relative to what it's
            # meant to annotate. Scoped to when the window-matrix panel is
            # actually visible so every other algorithm's preview (nothing
            # stacks ribbons under those) keeps its default framing.
            curve = style_main_plot_frame(curve)
        self.result_pane.object = curve
        self._last_before_after = None  # this preview IS "before" now; no stale pair left to re-toggle

        n = end - start
        duration_label = _format_duration_human(n / recording["fs"])
        which = ""
        if self.span_mode.value == "Selected span":
            idx = self._staged_row_index()
            n_staged = len(app._staged_spans)
            if idx is not None and n_staged > 1:
                which = f" (staged row {idx + 1}/{n_staged})"
            elif idx is not None:
                which = " (staged span)"
        self.preview_info.object = f"**{n:,} samples** ({duration_label}){which}"

    def _has_valid_manual_span(self):
        """Whether `_current_span()` resolves to an actual bounded span —
        NOT `None`/"Whole channel", which 'Save current selection as
        motif' has always explicitly rejected (see `_on_save_viewport_as_motif`)."""
        if self.span_mode.value == "Whole channel":
            return False
        try:
            return self._current_span() is not None
        except ValueError:
            return False

    def _on_yaxis_mode_changed(self, _event=None):
        """Part 5 B2: re-render the last Before/After pair (if any) under
        the newly chosen y-axis mode without re-running anything — the
        toggle is purely a display choice over data already in hand."""
        if self._last_before_after is not None:
            recording, result_x, result_t = self._last_before_after
            self._show_before_after(recording, result_x, result_t)

    # ── 5b: before/after comparison ─────────────────────────────────────

    def _show_before_after(self, recording, result_x, result_t):
        """Part 5, Section B: independent-by-default y-axes, because most
        of what runs here (anything removing a DC offset or changing
        scale — e.g. the bandpass filter's After output, which can be
        orders of magnitude smaller than Before's raw DC-offset range)
        renders as a flat line near zero if forced onto a shared/
        normalized range. `self.yaxis_mode` lets the user opt back into a
        shared range for the (rarer) amplitude-preserving transform where
        that's the more informative comparison.
        """
        x_full = np.load(recording["npy_path"], mmap_mode="r")
        start = int(round(result_t[0] * recording["fs"]))
        end = start + len(result_x)
        x_before = np.asarray(x_full[start:end])
        t = np.arange(start, end) / recording["fs"]
        x_after = np.asarray(result_x)

        self._last_before_after = (recording, result_x, result_t)

        # `compute_display_y_range` is the exact per-frame autoscale the
        # Viewer's main curve uses (10% padding) — reused here (A5's reuse
        # principle applies just as much to a y-range computation as to a
        # curve's decimation) so "auto-scaled" means the same thing in
        # both tabs.
        before_lo, before_hi = compute_display_y_range(x_before, (0.0, 1.0), y_autoscale=True)
        after_lo, after_hi = compute_display_y_range(x_after, (0.0, 1.0), y_autoscale=True)

        shared = self.yaxis_mode.value == "Shared y-axis"
        if shared:
            lo = min(before_lo, after_lo)
            hi = max(before_hi, after_hi)
            before_range, after_range = (lo, hi), (lo, hi)
        else:
            before_range, after_range = (before_lo, before_hi), (after_lo, after_hi)

        # Part B3: the actual numeric range in each title, so the two
        # panels' scales are never just inferred from eyeballing the axes.
        before = hv.Curve((t, x_before), "time_s", "amplitude").opts(
            color="#999999", title=f"Before  [y: {before_lo:.4g} to {before_hi:.4g}]",
            height=RUN_PREVIEW_HEIGHT, responsive=True, fontsize=PLOT_FONTSIZE,
            ylim=before_range, framewise=True, axiswise=True,
        )
        after = hv.Curve((result_t, result_x), "time_s", "amplitude").opts(
            color="steelblue", title=f"After  [y: {after_lo:.4g} to {after_hi:.4g}]",
            height=RUN_PREVIEW_HEIGHT, responsive=True, fontsize=PLOT_FONTSIZE,
            ylim=after_range, framewise=True, axiswise=True,
        )
        # Stacked with a shared/linked x-axis: combining same-dimension
        # Curves in a Layout shares axes by default, so zooming one pans/
        # zooms the other in lockstep. `axiswise=True` on each curve (Part
        # B1) stops HoloViews' separate per-Layout normalization of shared
        # value dimensions from silently re-merging the two y-ranges back
        # together regardless of the explicit `ylim`s above — without it,
        # "independent" mode rendered identically to "shared" because both
        # curves carry the "amplitude" dimension.
        self.result_pane.object = (before + after).cols(1).opts(shared_axes=True)

        # Part B4: make an amplitude-scale change visible rather than
        # requiring it to be inferred from the two titles.
        before_span = before_hi - before_lo
        after_span = after_hi - after_lo
        if before_span > 0:
            ratio = after_span / before_span
            self.scale_note.object = (
                f"*Output range is {ratio:.3g}x the input range "
                f"({after_span:.4g} vs {before_span:.4g}).*"
            )
        else:
            self.scale_note.object = ""

    # ── Encoding inspection view (Part 6, Section 3) ─────────────────────

    def _preprocessing_active(self):
        return self.preprocess_select.value != "none"

    def _preprocessing_description(self):
        return f"{self.preprocess_select.value}, window {self.preprocess_window.value:g} s"

    def _update_preprocessing_banner(self):
        """Part 7, Part 2 item 6 — the same loud-banner treatment the
        Viewer uses for its own "DISPLAY TRANSFORM ACTIVE" state (Part
        E3): the only way to know the encoding ran on a transformed
        signal, not the raw trace, used to be remembering the dropdown."""
        if self._preprocessing_active():
            self.enc_preprocessing_banner.object = (
                f"**⚠ PREPROCESSED — {self._preprocessing_description()} — "
                "panels below show the preprocessed signal, not the raw trace.**"
            )
            self.enc_preprocessing_banner.styles = {
                "display": "block", "background": "#fff3cd", "border": "2px solid #f0ad4e",
                "padding": "8px", "border-radius": "4px",
            }
        else:
            self.enc_preprocessing_banner.object = ""
            self.enc_preprocessing_banner.styles = {"display": "none"}

    # ── 5d: save as motif ────────────────────────────────────────────────

    def _spanset_step_name(self):
        """`"<stage>.<algorithm>"` of the step in the last recipe whose
        output is a SpanSet -- the one whose spans became these rows.

        Returns None if the recipe is unavailable or no step claims a
        spanset output, in which case the caption stays generic rather
        than asserting a block that may be the wrong one.
        """
        recipe = getattr(self, "_last_recipe", None)
        if not recipe:
            return None
        for step in reversed(recipe.get("steps", [])):
            name = f"{step['stage']}.{step['algorithm']}"
            try:
                if get_adapter(name).output_kind == "spanset":
                    return name
            except KeyError:
                continue
        return None

    def _show_detections(self, detection_rows):
        producer = self._spanset_step_name()
        block = f"`{producer}`" if producer else "the chain's detection block"
        self.detections_caption.object = (
            f"*The {len(detection_rows)} span(s) {block} emitted, as sample indices "
            "into the whole recording (not into the staged span). `score` is the "
            "block's own confidence, and is blank for blocks that do not report "
            "one. These are machine detections; a human verdict on them is "
            "recorded in Review, never here.*"
        )
        records = [{"id": d["id"], "start_idx": d["start_idx"], "end_idx": d["end_idx"],
                    "score": d["score"]} for d in detection_rows]
        self.detections_table.value = pd.DataFrame(
            records, columns=["id", "start_idx", "end_idx", "score"]
        )
        # Part 5 C3: an empty Tabulator still renders its header row, which
        # reads as "something's broken", not "zero detections" — a plain
        # sentence is unambiguous either way (no run yet vs. a completed
        # run that just found nothing).
        if records:
            self.detections_table.visible = True
            self.detections_placeholder.visible = False
        else:
            self.detections_table.visible = False
            self.detections_placeholder.visible = True
            self.detections_placeholder.object = "*No detections in this run.*"

    # ── Save plot (explicit only — never automatic) ─────────────────────

    def _on_save_plot(self, _event=None):
        self.save_plot_status.object = ""
        if self._last_recipe is None:
            self.save_plot_status.object = "**Run something first.**"
            return

        recipe = self._last_recipe
        last_step = recipe["steps"][-1]
        spec = get_adapter(f"{last_step['stage']}.{last_step['algorithm']}")
        if spec.plot is None:
            self.save_plot_status.object = "**This algorithm has no plotting hook.**"
            return

        recording = q.get_recording_by_id(self.conn, recipe["recording_id"])
        span = recipe["span"]
        start, end = (0, recording["n_samples"]) if span is None else span
        x_full = np.load(recording["npy_path"], mmap_mode="r")
        x = np.asarray(x_full[start:end])
        t = np.arange(start, end) / recording["fs"]

        params = spec.validate_params(last_step["params"])
        # Recomputed here rather than reusing the run's result: the run
        # panel only ever passes plain data across the worker-thread
        # boundary (see `_gather_display_data`), and re-running a single
        # step on a bounded span for a plot is cheap relative to the run
        # itself.
        result = spec.run(x, t, recording["fs"], **params)
        fig = spec.plot(x, t, result, **params)

        config_id, hash8 = R.get_or_create_config(self.conn, recipe)
        path = save_plot(
            fig, recording["source_file"], recording["channel"],
            last_step["stage"], f"{last_step['stage']}.{last_step['algorithm']}",
            params, hash8,
        )
        run_row = R.find_completed_run(self.conn, config_id, recipe["recording_id"], start, end)
        run_id = run_row["id"] if run_row is not None else R.insert_run(
            self.conn, config_id, recipe["recording_id"], start, end, status="completed",
        )
        R.insert_artifact(self.conn, run_id, "plot", path)
        self.save_plot_status.object = f"Saved: `{path}`"
