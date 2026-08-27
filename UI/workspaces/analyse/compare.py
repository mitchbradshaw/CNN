"""
compare.py
==========
The Compare view (tickets 33, 69) — two run selectors, the per-step chain
comparison with the difference highlighted, the span-set overlap result, and
a route from each exclusive remainder into the Review queue.

The overlap half renders what `Working.compare.compare_run_sets` computes;
the chain half renders `Working.compare.diff_recipes` with the builder's own
card renderer, so a compared chain cannot drift from the chain a researcher
composes. The surface keeps no second copy of either computation.

The Review routing reuses the existing `ReviewQueue` filters rather than
building a parallel candidate path: an exclusive remainder belongs to one
run, so routing it means "open the Review workspace filtered to that run,
unadjudicated only".
"""

import panel as pn

from Working.compare import MISSING, compare_run_sets, diff_recipes
from Working.database import runs as run_db

from UI.analyse.chain_state import ChainState
from UI.workspaces.analyse.builder import ChainBuilder, _ARROW, _CARD_WIDTH


class _ReadOnlyCardApp:
    """The minimal app shape the builder's card renderer reads when a chain
    is being drawn read-only. `_recording_id`/`conn` stay None so the card
    renderer never tries to load signal data or derive live readouts."""

    _recording_id = None
    conn = None


class CompareSurface:
    """Pick two completed runs and see their chains and span-set overlap."""

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
        self.diff_summary_pane = pn.pane.Markdown("")
        self.chain_a_label = pn.pane.Markdown("")
        self.chain_b_label = pn.pane.Markdown("")
        self.chain_a_pane = pn.Row(sizing_mode="stretch_width", scroll=True)
        self.chain_b_pane = pn.Row(sizing_mode="stretch_width", scroll=True)
        self.chain_comparison_pane = pn.Column(
            pn.pane.Markdown("### Chain comparison"),
            self.diff_summary_pane,
            self.chain_a_label,
            self.chain_a_pane,
            self.chain_b_label,
            self.chain_b_pane,
            sizing_mode="stretch_width",
        )
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
            self.chain_comparison_pane,
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
        name = row["name"] or "unnamed"
        return (
            f"#{row['id']} — {name} — recording {row['recording_id']} "
            f"[{row['span_start']}, {row['span_end']})"
        )

    # ── actions ────────────────────────────────────────────────────────────

    def _on_compare(self, _event=None):
        self.status.object = ""
        self._clear_chain_comparison()
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

    def _clear_chain_comparison(self):
        """Empty the chain-comparison panes so a failed/cleared compare never
        leaves the previous run pair's canvases on screen."""
        self.diff_summary_pane.object = ""
        self.chain_a_label.object = ""
        self.chain_b_label.object = ""
        self.chain_a_pane.objects = []
        self.chain_b_pane.objects = []

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
        self._render_chain_comparison()

    def _render_chain_comparison(self):
        """Draw the two runs' chains as stacked block canvases, with the
        per-step difference highlighted and a one-line summary above them."""
        comparison = self._comparison
        if comparison is None:
            self._clear_chain_comparison()
            return

        run_a = run_db.get_run(self.conn, comparison.run_a_id)
        run_b = run_db.get_run(self.conn, comparison.run_b_id)
        recipe_a = run_db.load_recipe(self.conn, run_a["config_id"])
        recipe_b = run_db.load_recipe(self.conn, run_b["config_id"])
        diff = diff_recipes(recipe_a, recipe_b)

        self.diff_summary_pane.object = self._format_diff_summary(diff)
        self.chain_a_label.object = f"**Run A:** {self._run_label(run_a)}"
        self.chain_b_label.object = f"**Run B:** {self._run_label(run_b)}"

        max_len = max(
            len(recipe_a.get("steps") or []),
            len(recipe_b.get("steps") or []),
        )
        self.chain_a_pane.objects = self._chain_canvas_objects(recipe_a, diff, max_len)
        self.chain_b_pane.objects = self._chain_canvas_objects(recipe_b, diff, max_len)

    @staticmethod
    def _format_diff_summary(diff):
        """One pasteable line, or a single 'identical' sentence when no diff."""
        if not diff:
            return "Chains are identical."
        return " · ".join(CompareSurface._format_step_diff(d) for d in diff)

    @staticmethod
    def _format_step_diff(step_diff):
        index = step_diff.index + 1
        if step_diff.a_step is None:
            step = step_diff.b_step
            return f"Step {index} only in Run B (`{step['stage']}.{step['algorithm']}`)"
        if step_diff.b_step is None:
            step = step_diff.a_step
            return f"Step {index} only in Run A (`{step['stage']}.{step['algorithm']}`)"
        if step_diff.changed_params:
            changes = ", ".join(
                f"{p.name}: {CompareSurface._format_value(p.a_value)} → "
                f"{CompareSurface._format_value(p.b_value)}"
                for p in step_diff.changed_params
            )
            return f"Step {index} {changes}"
        return (
            f"Step {index} algorithm: "
            f"`{step_diff.a_step['stage']}.{step_diff.a_step['algorithm']}` → "
            f"`{step_diff.b_step['stage']}.{step_diff.b_step['algorithm']}`"
        )

    @staticmethod
    def _format_value(value):
        if value is MISSING:
            return "absent"
        return repr(value)

    @staticmethod
    def _builder_for_recipe(recipe):
        """A throwaway builder whose card renderer draws `recipe` read-only."""
        builder = ChainBuilder(_ReadOnlyCardApp())
        builder.chain = ChainState.from_recipe(recipe)
        return builder

    @staticmethod
    def _chain_connector():
        return pn.pane.Markdown(
            f"<div style='font-size: 20px; padding-top: 40px;'>{_ARROW}</div>"
        )

    @staticmethod
    def _highlight_card(card):
        """The T69 visual marker for a step that differs between the runs."""
        styles = dict(getattr(card, "styles", {}) or {})
        styles.update({"border": "2px solid #d97706", "background": "#fff7e6"})
        card.styles = styles

    @staticmethod
    def _placeholder_card(index):
        """A card-shaped gap where one chain has no step at this position."""
        return pn.Column(
            pn.pane.Markdown(f"**Step {index + 1}**"),
            pn.pane.Markdown("*Not in this chain*"),
            width=_CARD_WIDTH,
            styles={
                "border": "1px dashed #ccc",
                "border-radius": "6px",
                "padding": "10px",
                "background": "#fafafa",
            },
        )

    def _chain_canvas_objects(self, recipe, diff, max_len):
        """The ordered cards/connectors for one chain, with diff positions
        highlighted. Missing positions become placeholders so an added/removed
        step stays visually aligned across the two stacked canvases."""
        diff_by_index = {d.index: d for d in diff}
        steps = recipe.get("steps") or []
        objects = []
        builder = None
        for index in range(max_len):
            if objects:
                objects.append(self._chain_connector())
            step = steps[index] if index < len(steps) else None
            if step is None:
                card = self._placeholder_card(index)
            else:
                if builder is None:
                    builder = self._builder_for_recipe(recipe)
                card = builder._render_card(index, step)
            if index in diff_by_index:
                self._highlight_card(card)
            objects.append(card)
        return objects

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
