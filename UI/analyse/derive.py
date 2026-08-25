"""
`recommend()` / `derive()` bookkeeping: applying an adapter's recommended
defaults, tracking which of them the user has since edited, and re-rendering
the read-only derived-quantities table.
"""

from Adapters.registry import get_adapter
from Adapters._sax_common import segment_plan

from Working.config import AUTO_PREVIEW_SPAN_THRESHOLD

from UI.analyse.formatting import _rows_to_html


class DeriveMixin:
    """Recommended defaults and the derived-quantities readout."""

    def _apply_recommended_defaults(self, force=False):
        """Part 6, 4a: call `spec.recommend(x, t, fs)` for the CURRENT
        span and pre-fill the parameter widgets — UNLESS the user has
        already edited one of them away from the last recommendation, in
        which case leave every edit alone and just note that recommended
        values have changed (force=True, from the "Reset to recommended"
        button, always applies regardless).

        Never silently overwrites a deliberate choice on an incidental
        viewport pan — that would be maddening (the brief's own words).
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

        any_modified = any(
            self._recommended_values.get(pname) is not None
            and w.value != self._recommended_values[pname]
            for pname, w in self._param_widgets.items()
        )
        preprocess_modified = (
            self._recommended_preprocess_window is not None
            and self.preprocess_window.value != self._recommended_preprocess_window
        )

        # Update the "last recommendation" bookkeeping BEFORE setting any
        # widget value below — `_on_param_widget_changed` (fired by each
        # assignment) compares against `_recommended_values` to decide the
        # "(modified)" marker, and must see the NEW recommendation, not a
        # stale one, or a widget freshly set to its recommended value could
        # transiently (and permanently, since nothing re-checks it later)
        # get mismarked "(modified)".
        self._recommended_values = {k: v for k, v in rec.items() if k != "preprocess_window_s"}
        if "preprocess_window_s" in rec:
            self._recommended_preprocess_window = rec["preprocess_window_s"]

        if force or not (any_modified or preprocess_modified):
            for pname, value in rec.items():
                if pname in self._param_widgets:
                    self._param_widgets[pname].value = value
                    self._param_base_names.setdefault(pname, self._param_widgets[pname].name)
                    self._param_widgets[pname].name = self._param_base_names[pname]
                elif pname == "preprocess_window_s":
                    self.preprocess_window.value = value
            self.span_changed_note.object = ""
        else:
            self.span_changed_note.object = (
                "*Span changed; recommended values updated. Click "
                "'Reset to recommended' to apply them.*"
            )

        n = len(x)
        self.auto_preview_checkbox.value = n < AUTO_PREVIEW_SPAN_THRESHOLD
        self._sync_segment_mode_controls()
        self._refresh_derived()

    def _on_param_widget_changed(self, pname):
        """Part 6 4a's modified marker — appended to a widget's own label
        the moment its value differs from the last recommendation applied
        to it, cleared the moment it matches again (including right after
        Reset). Part 7, Part 3 item 6: a compact "•" rather than the word
        "(modified)", which was long enough on its own to push these
        already-long labels into mid-word truncation."""
        if self._syncing_segment_controls:
            # `_sync_segment_mode_controls` is assigning a RESOLVED display
            # value to an inactive, disabled control — not a user edit, so
            # it must not be marked "modified" or re-trigger a sync of
            # itself (this method is what it's called FROM).
            return
        if self._suppress_param_watchers:
            # A MEASURED value being written into a control by the panel
            # itself (currently only `min_same_halfwidth`, from the
            # noise-floor button). Not a user edit, and running the normal
            # chain from here is actively wrong twice over:
            #   - it would schedule an auto-preview, so a DIAGNOSTIC would
            #     silently recompute the encoding it just measured — the
            #     one thing the button promises not to do;
            #   - `_refresh_derived`/`_sync_segment_mode_controls` read
            #     `self.conn`, and this runs on the noise-floor WORKER
            #     thread whenever there is no live Bokeh document to defer
            #     to (`_run_on_ui_thread` falls back to calling directly),
            #     which sqlite3 rejects outright: "SQLite objects created
            #     in a thread can only be used in that same thread."
            #     Confirmed by exactly that traceback.
            # The status pane tells the user the value was set and that a
            # re-run is needed, which is the deliberate action this
            # replaces.
            return
        w = self._param_widgets.get(pname)
        if w is None:
            return
        base = self._param_base_names.get(pname, w.name)
        recommended = self._recommended_values.get(pname)
        modified = recommended is not None and w.value != recommended
        new_name = f"{base} •" if modified else base
        if w.name != new_name:
            w.name = new_name
        self._sync_segment_mode_controls()
        self._sync_trend_param_controls()
        self._refresh_derived()
        self._schedule_auto_preview()

    def _sync_trend_param_controls(self):
        """dSAX Phase E: `min_same_halfwidth` is a floor on the SAME band's
        half-width, and an EVEN alphabet size has no SAME band at all — the
        cutlines include one exactly AT zero rather than a band around it
        (IMPLEMENTATION_NOTES.md 7.7). The parameter is silently ignored by
        `dsax()` there, so the control is disabled and says why rather than
        accepting a number that will have no effect.

        Same principle as `_sync_segment_mode_controls`: a control that
        cannot affect the run must never look like one that can."""
        w = self._param_widgets.get("min_same_halfwidth")
        alphabet = self._param_widgets.get("alphabet_size")
        if w is None or alphabet is None:
            return  # not the dSAX adapter
        inert = int(alphabet.value) % 2 == 0
        w.disabled = inert
        base = self._param_base_names.get("min_same_halfwidth", w.name)
        w.description = (
            f"No effect at alphabet_size={int(alphabet.value)}: an even alphabet has a cutline "
            "exactly at zero and therefore no SAME band to widen. Use an odd alphabet size."
            if inert else
            "Floor on the SAME band half-width, in the working delta domain "
            "(use 'Estimate noise floor' to measure one). 0 = unset"
        )
        # Keep the "modified" marker logic in `_on_param_widget_changed`
        # authoritative over the name; only append the inert marker.
        if inert and not w.name.endswith("(n/a)"):
            w.name = f"{base} (n/a)"
        elif not inert and w.name.endswith("(n/a)"):
            w.name = base

    def _sync_segment_mode_controls(self):
        """Part 7, Part 4 item 1: the single most confusing thing on the
        page before this fix — with `segment_mode="seconds_per_symbol"`,
        the other three controls kept showing whatever stale value they
        last held, actively contradicting what would run. Now: only the
        ACTIVE control is enabled; the other three are disabled AND their
        displayed values are kept resolved to the SAME `samples_per_symbol`
        the active one means, via `segment_plan` — the identical function
        a real run uses — so all four can never disagree about what's
        about to happen."""
        widgets = self._param_widgets
        segment_param_names = ("seconds_per_symbol", "samples_per_symbol", "target_symbol_count", "dim_ratio")
        if "segment_mode" not in widgets or not all(p in widgets for p in segment_param_names):
            return  # not a SAX-style adapter (e.g. bandpass) -- nothing to sync
        signal = self._current_span_signal()
        if signal is None:
            return
        x, _t, fs, _rec = signal
        n = len(x)
        active_mode = widgets["segment_mode"].value
        params = {p: widgets[p].value for p in segment_param_names}
        try:
            plan = segment_plan(active_mode, params, fs, n)
        except (ValueError, ZeroDivisionError):
            return
        sps = max(1, plan["requested_sps"])
        resolved = {
            "seconds_per_symbol": sps / fs,
            "samples_per_symbol": sps,
            "target_symbol_count": max(2, round(n / sps)),  # matches that ParamSpec's own min=2
            "dim_ratio": 1.0 / sps,
        }
        self._syncing_segment_controls = True
        try:
            for pname in segment_param_names:
                w = widgets[pname]
                w.disabled = (pname != active_mode)
                if pname != active_mode:
                    w.value = resolved[pname]
        finally:
            self._syncing_segment_controls = False

    def _refresh_derived(self):
        """Part 6 4b: the read-only `derive()` table beneath the
        parameter controls — recomputed on every parameter change,
        without running anything."""
        name = self.algorithm_select.value
        spec = get_adapter(name) if name else None
        if spec is None or spec.derive is None:
            self.derived_pane.object = ""
            return
        signal = self._current_span_signal()
        if signal is None:
            self.derived_pane.object = ""
            return
        x, t, fs, _recording = signal
        try:
            rows = spec.derive(x, t, fs, self._current_params())
        except Exception as e:
            self.derived_pane.object = f"<i>Could not compute: {e}</i>"
            return
        self.derived_pane.object = _rows_to_html(rows)

    # ── Part 6, 4c: auto-preview on parameter change ─────────────────────

    @staticmethod
    def _is_sax_shaped_encoding(name):
        """Whether `name` ("stage.algorithm") is a SAX-family adapter — the
        only "encoding"-output-kind shape `_show_encoding` (the 4-panel
        PAA/quantisation/string view) knows how to render: an x/t pair plus
        a discrete symbol array plus a `meta["details"]` dict. Several other
        adapters are ALSO `output_kind == "encoding"` (matrix profile, the
        window matrix) but are structurally nothing like that — matrix
        profile is a continuous distance array with its own Motif browser
        tab, and the window matrix is a whole feature table with its own
        Run-panel section (`UI/workspaces/analyse/window_matrix.py`). `_gather_display_data`
        already draws this exact line via
        `last_step["algorithm"].startswith("sax_")` for the post-run path;
        this is the same test, reused for the pre-run auto-preview path."""
        if "." not in name:
            return False
        return name.split(".", 1)[1].startswith("sax_")
