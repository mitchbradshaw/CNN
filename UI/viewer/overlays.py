"""
The two ribbon panes stacked around the main plot, and the toggles that
show, hide and threshold them.
"""

import panel as pn


class OverlaysMixin:
    """Annotation/reviewed ribbons and the overlay toggles. Mixed into `ViewerApp`."""

    def _build_ribbon_panes(self):
        # Part A (2026-08 restructure): the reviewed-coverage and
        # annotation-density ribbons are separate, thin panes stacked
        # directly above/below the main plot (`layout()`), not overlays
        # inside it — see UI/plots.py's module docstring for why. `.object`
        # is set in `_rebuild_plot`; `.visible` is bound to the existing
        # show/hide toggles below so switching a ribbon off collapses its
        # pane entirely instead of leaving an empty strip (Part A4).
        self.reviewed_ribbon_pane = pn.pane.HoloViews(sizing_mode="stretch_width", linked_axes=False)
        self.annotation_ribbon_pane = pn.pane.HoloViews(sizing_mode="stretch_width", linked_axes=False)

    def _build_overlay_toggles(self):
        # Independent show/hide toggles for the two overlay families — so
        # you can tell at a glance where an algorithm's detections agree or
        # disagree with your own annotations by looking at either alone.
        # `show_annotations_toggle` is ALSO the annotation ribbon pane's
        # show/hide (Part A4, 2026-08) -- there's nothing left to
        # separately show/hide on the main plot now that ribbons live in
        # their own panes, so "show annotations" and "show the annotation
        # pane" are the same question.
        self.show_annotations_toggle = pn.widgets.Checkbox(name="Show annotations", value=True)
        self.show_detections_toggle = pn.widgets.Checkbox(name="Show detections", value=True)
        self.show_annotations_toggle.param.watch(self._on_overlay_toggle_changed, "value")
        self.show_detections_toggle.param.watch(self._on_overlay_toggle_changed, "value")

        # Independent per-ribbon toggles (Part B), on by default.
        # `show_annotation_ribbon_toggle` does NOT show/hide the pane --
        # it controls the density THRESHOLD within it (off = always render
        # individual rectangles, even above the threshold, a deliberate
        # choice for precise inspection at the cost of possible
        # slowness); `show_annotations_toggle` above is what shows/hides
        # the pane itself. `show_reviewed_ribbon_toggle` has no such
        # sub-mode, so it directly shows/hides its own pane (Part A4).
        self.show_annotation_ribbon_toggle = pn.widgets.Checkbox(
            name="Show annotation density ribbon", value=True,
        )
        self.show_reviewed_ribbon_toggle = pn.widgets.Checkbox(
            name="Show reviewed-coverage ribbon", value=True,
        )
        self.show_annotation_ribbon_toggle.param.watch(self._on_overlay_toggle_changed, "value")
        self.show_reviewed_ribbon_toggle.param.watch(self._on_overlay_toggle_changed, "value")

        # Part A4: collapsing (not just emptying) a hidden ribbon pane --
        # `.visible = False` on a Panel pane removes it from the rendered
        # layout's flow entirely, unlike feeding it empty data (which used
        # to still reserve the overlay's full-height footprint).
        self.show_annotations_toggle.param.watch(self._update_ribbon_pane_visibility, "value")
        self.show_reviewed_ribbon_toggle.param.watch(self._update_ribbon_pane_visibility, "value")
        self._update_ribbon_pane_visibility()

    def _on_overlay_toggle_changed(self, _event=None):
        self._refresh_view()
        self._save_session_state()

    def _update_ribbon_pane_visibility(self, _event=None):
        """Part A4 (2026-08): a hidden ribbon pane COLLAPSES (no visible
        footprint at all), it doesn't just go blank — `show_annotations`
        is the annotation pane's show/hide (there's nothing else left on
        the main plot to separately toggle now that ribbons live in their
        own panes; see the toggle construction comment), `show_reviewed_
        ribbon` is the reviewed pane's."""
        self.annotation_ribbon_pane.visible = self.show_annotations_toggle.value
        self.reviewed_ribbon_pane.visible = self.show_reviewed_ribbon_toggle.value
