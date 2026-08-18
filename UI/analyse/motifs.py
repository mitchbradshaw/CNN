"""
Saving a span as a motif -- from a selected detection, from the current
viewport/selection directly, or from the encoding as a seed.
"""

import panel as pn

from Working.database import vocabulary as v
from Working.database import runs as R
from Working.encoding_cache import read_encoding_file
from Working.recipes import make_recipe

from UI.plots import symbol_letters, symbols_to_string


class MotifsMixin:
    """The save-as-motif form and its three entry points. Mixed into `RunPanel`."""

    def _build_motif_widgets(self):
        # Save-as-motif controls
        self.motif_label = pn.widgets.TextInput(name="Label")
        self.motif_elements = pn.widgets.MultiChoice(name="element tags", options=[])
        self.motif_rating = pn.widgets.IntSlider(name="Rating", start=0, end=5, value=0)
        self.motif_notes = pn.widgets.TextAreaInput(name="Notes")
        self.save_motif_button = pn.widgets.Button(
            name="Save selected detection as motif", button_type="success", disabled=True,
        )
        self.save_viewport_motif_button = pn.widgets.Button(
            name="Save current selection as motif (no detection needed)", button_type="default",
            disabled=True,
        )
        self.motif_gate_note = pn.pane.Markdown(
            "*Run something (to save a detection) or pick a span above "
            "via 'Selected span'/'Current viewport' (to save it directly) "
            "before saving a motif.*"
        )
        self.motif_status = pn.pane.Markdown("")

    # ── Adapter/param wiring ─────────────────────────────────────────────

    def _refresh_element_options(self):
        self.motif_elements.options = [r["value"] for r in v.list_terms(self.conn, category="element")]

    def _update_motif_button_states(self):
        """Part 5 C4: 'Save selected detection' only means anything once a
        run has actually produced detections to pick from; 'Save current
        selection' only means anything once `_current_span` resolves to a
        real span. Re-evaluated on every span/staged-selection change and
        after every run so neither button is ever clickable in a
        meaningless state."""
        self.save_motif_button.disabled = len(self.detections_table.value) == 0
        self.save_viewport_motif_button.disabled = not self._has_valid_manual_span()

    def _on_save_encoding_as_motif(self, _event=None):
        """Part 4e: save the current span + string + full recipe as a
        motif in one click, without requiring a detection first — the
        exact workflow this whole view exists to support."""
        self.enc_seed_motif_status.object = ""
        if self._last_encoding is None or self._last_recipe is None:
            self.enc_seed_motif_status.object = "**Run an encoding first.**"
            return
        _x, _t, symbols, details, recording = self._last_encoding
        span = self._last_recipe["span"]
        start, end = (0, recording["n_samples"]) if span is None else span

        config_id, _hash8 = R.get_or_create_config(self.conn, self._last_recipe)
        run_row = R.find_completed_run(self.conn, config_id, recording["id"], start, end)
        run_id = run_row["id"] if run_row is not None else R.insert_run(
            self.conn, config_id, recording["id"], start, end, status="completed",
        )
        detection_id = R.insert_detection(self.conn, run_id, start, end)
        # A morphology pattern that currently MATCHES this encoding is the
        # most useful thing to record alongside the seed string: the string
        # says what this span looks like, the pattern says what class of
        # shape it was recognised as. Appended to the free-text notes
        # rather than given a column — `motifs` has no pattern field, and
        # inventing one is a schema change this work order does not cover.
        notes = self.motif_notes.value or None
        if self._search_matches:
            pattern_note = (f"morphology pattern: {self.enc_search_input.value} "
                            f"({len(self._search_matches)} matches in this span)")
            notes = f"{notes}\n{pattern_note}" if notes else pattern_note
        motif_id = R.insert_motif(
            self.conn, detection_id,
            label=self.motif_label.value or None, rating=self.motif_rating.value or None,
            notes=notes,
            sax_string=symbols_to_string(symbols, symbol_letters(details)),
        )
        if self.motif_elements.value:
            v.set_motif_tags(self.conn, motif_id, "element", self.motif_elements.value)
        self.enc_seed_motif_status.object = f"Saved motif id={motif_id} with this encoding's seed string."
        self._clear_motif_fields()

    def _find_sax_string_for_span(self, recording_id, start, end):
        from Working.encoding_cache import read_encoding_file
        for enc in R.list_encodings(self.conn, recording_id):
            if enc["span_start"] == start and enc["span_end"] == end \
                    and enc["encoding_type"].startswith("sax"):
                try:
                    return read_encoding_file(enc["path"])
                except Exception:
                    return None
        return None

    def _save_motif(self, detection_id, recording_id, start, end):
        sax_string = self._find_sax_string_for_span(recording_id, start, end)
        motif_id = R.insert_motif(
            self.conn, detection_id,
            label=self.motif_label.value or None,
            rating=self.motif_rating.value or None,
            notes=self.motif_notes.value or None,
            sax_string=sax_string,
        )
        if self.motif_elements.value:
            v.set_motif_tags(self.conn, motif_id, "element", self.motif_elements.value)
        return motif_id

    def _on_save_detection_as_motif(self, _event=None):
        self.motif_status.object = ""
        df = self.detections_table.value
        selected = self.detections_table.selection
        if not selected:
            self.motif_status.object = "**Select a detection row first.**"
            return
        row = df.iloc[selected[0]]
        detection_id = int(row["id"])
        det = R.get_detection(self.conn, detection_id)
        run = R.get_run(self.conn, det["run_id"])
        motif_id = self._save_motif(detection_id, run["recording_id"], det["start_idx"], det["end_idx"])
        self.motif_status.object = f"Saved motif id={motif_id} (inherited recipe from run_id={det['run_id']})."
        self._clear_motif_fields()

    def _on_save_viewport_as_motif(self, _event=None):
        self.motif_status.object = ""
        try:
            span = self._current_span()
        except ValueError as e:
            self.motif_status.object = f"**{e}**"
            return
        if span is None:
            self.motif_status.object = "**Choose 'Selected span' or 'Current viewport', not 'Whole channel'.**"
            return
        start, end = span

        # A manual span still goes through a (trivial) recipe/run/detection
        # so every motif — algorithmic or manual — inherits its metadata
        # through the same chain, with no special-cased nullable columns.
        recipe = make_recipe(
            self.app._recording_id,
            [{"stage": "catalogue", "algorithm": "manual_selection", "params": {}}],
            span=(start, end),
        )
        config_id, _hash8 = R.get_or_create_config(self.conn, recipe)
        run_id = R.insert_run(self.conn, config_id, self.app._recording_id, start, end, status="completed")
        detection_id = R.insert_detection(self.conn, run_id, start, end)
        motif_id = self._save_motif(detection_id, self.app._recording_id, start, end)
        self.motif_status.object = f"Saved motif id={motif_id} from a manual selection (run_id={run_id})."
        self._clear_motif_fields()

    def _clear_motif_fields(self):
        self.motif_label.value = ""
        self.motif_elements.value = []
        self.motif_rating.value = 0
        self.motif_notes.value = ""
