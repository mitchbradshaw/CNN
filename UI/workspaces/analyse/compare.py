"""
compare.py
==========
The Compare view (ticket 33) — two run selectors, the overlap result, and a
route from each exclusive remainder into the Review queue.

This surface renders what `Working.compare.compare_run_sets` computes; it
keeps no second copy of the overlap logic. It reads the live app connection
the same way the other Analyse surfaces do.

The Review routing reuses the existing `ReviewQueue` filters rather than
building a parallel candidate path: an exclusive remainder belongs to one
run, so routing it means "open the Review workspace filtered to that run,
unadjudicated only".
"""

import panel as pn

from Working.compare import compare_run_sets
from Working.database import runs as run_db


class CompareSurface:
    """Pick two completed runs and see their span-set overlap."""

    def __init__(self, app):
        self.app = app
        self.conn = app.conn

        self.run_a_select = pn.widgets.Select(name="Run A", options={})
        self.run_b_select = pn.widgets.Select(name="Run B", options={})
        self.compare_button = pn.widgets.Button(name="Compare runs", button_type="primary")
        self.review_a_button = pn.widgets.Button(
            name="Review A-only", button_type="warning", disabled=True,
        )
        self.review_b_button = pn.widgets.Button(
            name="Review B-only", button_type="warning", disabled=True,
        )
        self.status = pn.pane.Markdown("")
        self.summary_pane = pn.pane.Markdown("*Select two completed runs and compare.*")
        self.detail_pane = pn.pane.Markdown("")

        self._comparison = None

        self._load_runs()
        self._wire_handlers()

    # ── layout ─────────────────────────────────────────────────────────────

    def layout(self):
        return pn.Column(
            pn.pane.Markdown("### Compare runs"),
            pn.Row(self.run_a_select, self.run_b_select),
            pn.Row(self.compare_button, self.review_a_button, self.review_b_button),
            self.status,
            self.summary_pane,
            self.detail_pane,
            sizing_mode="stretch_width",
        )

    # ── setup ──────────────────────────────────────────────────────────────

    def _load_runs(self):
        rows = run_db.list_runs(self.conn, status="completed")
        options = {self._run_label(row): row["id"] for row in rows}
        self.run_a_select.options = options
        self.run_b_select.options = options

        values = list(options.values())
        if values:
            self.run_a_select.value = values[0]
            self.run_b_select.value = values[1] if len(values) > 1 else values[0]

    def _wire_handlers(self):
        self.compare_button.on_click(self._on_compare)
        self.review_a_button.on_click(lambda _event: self._route_to_review("a"))
        self.review_b_button.on_click(lambda _event: self._route_to_review("b"))

    @staticmethod
    def _run_label(row):
        return (
            f"#{row['id']} — recording {row['recording_id']} "
            f"[{row['span_start']}, {row['span_end']})"
        )

    # ── actions ────────────────────────────────────────────────────────────

    def _on_compare(self, _event=None):
        self.status.object = ""
        run_a = self.run_a_select.value
        run_b = self.run_b_select.value

        if run_a is None or run_b is None:
            self._comparison = None
            self.status.object = "**Select two completed runs.**"
            return
        run_a, run_b = int(run_a), int(run_b)
        if run_a == run_b:
            self._comparison = None
            self.status.object = "**Pick two different runs.**"
            return

        try:
            self._comparison = compare_run_sets(self.conn, run_a, run_b)
        except ValueError as e:
            self._comparison = None
            self.status.object = f"**{e}**"
            return

        self.review_a_button.disabled = not bool(self._comparison.a_only)
        self.review_b_button.disabled = not bool(self._comparison.b_only)
        self._render_comparison()

    def _route_to_review(self, side):
        """Open Review filtered to the run whose exclusive remainder was asked for."""
        if self._comparison is None:
            return
        run_id = self._comparison.run_a_id if side == "a" else self._comparison.run_b_id

        review = getattr(self.app, "review_surface", None)
        if review is not None:
            review.queue.set_filters(run_id=run_id, adjudication_status="unadjudicated")
            if hasattr(review, "on_tab_activated"):
                review.on_tab_activated()

        activate = getattr(self.app, "activate_workspace", None)
        if activate is not None:
            activate("Review", "Candidate queue")

    # ── rendering ──────────────────────────────────────────────────────────

    def _render_comparison(self):
        comparison = self._comparison
        if comparison is None:
            return
        counts = comparison.counts
        self.summary_pane.object = (
            f"### Overlap: run {comparison.run_a_id} vs run {comparison.run_b_id}\n\n"
            f"- Run A detections: **{counts['a_total']}**\n"
            f"- Run B detections: **{counts['b_total']}**\n"
            f"- Intersection: **{counts['intersection']}**\n"
            f"- A-only: **{counts['a_only']}**\n"
            f"- B-only: **{counts['b_only']}**\n\n"
            f"*Criterion: {comparison.overlap_criterion}, "
            f"IoU ≥ {comparison.iou_threshold:g}.*"
        )
        self.detail_pane.object = self._format_details(comparison)

    @staticmethod
    def _format_details(comparison):
        lines = ["**A-only detections**"]
        if comparison.a_only:
            for row in comparison.a_only:
                lines.append(f"- #{row['id']}: [{row['start_idx']}, {row['end_idx']})")
        else:
            lines.append("*None*")

        lines.append("")
        lines.append("**B-only detections**")
        if comparison.b_only:
            for row in comparison.b_only:
                lines.append(f"- #{row['id']}: [{row['start_idx']}, {row['end_idx']})")
        else:
            lines.append("*None*")

        lines.append("")
        lines.append("**Intersection**")
        if comparison.intersection:
            for pair in comparison.intersection:
                lines.append(
                    f"- A #{pair.a_detection_id} ↔ B #{pair.b_detection_id} "
                    f"(IoU {pair.iou:.3f})"
                )
        else:
            lines.append("*None*")

        return "\n".join(lines)
