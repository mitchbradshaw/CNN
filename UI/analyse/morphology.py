"""
Regex search over the symbol string -- find every "sharkfin", step to each
match, and centre the encoding view on it. Offered for every encoding, not
just trend ones: a cSAX string is just as searchable.
"""

import re

import numpy as np
import panel as pn

from UI.plots import (
    segment_time_edges, symbol_letters, symbols_to_string, ENCODING_HIGHLIGHT_CAP,
)


# The sharkfin from the tag vocabulary, pre-loaded into the morphology
# search box so the feature explains itself rather than presenting an
# empty box with no clue what belongs in it.
DEFAULT_MORPHOLOGY_PATTERN = "UD{3,}"


class MorphologySearchMixin:
    """The morphology pattern search and match stepping. Mixed into `RunPanel`."""

    def _build_morphology_widgets(self):
        # ── Morphology regex search (dSAX Phase F) ───────────────────────
        # Deliberately visible for EVERY encoding, not just trend ones — a
        # cSAX string is just as searchable, and gating it on the domain
        # would be an arbitrary restriction on a feature that costs
        # nothing to offer.
        self.enc_search_input = pn.widgets.TextInput(
            name="Morphology pattern (regex over the symbol string)",
            value=DEFAULT_MORPHOLOGY_PATTERN, sizing_mode="stretch_width",
        )
        self.enc_search_button = pn.widgets.Button(name="Find", button_type="primary", width=80)
        self.enc_search_clear_button = pn.widgets.Button(name="Clear", width=80)
        self.enc_search_prev_button = pn.widgets.Button(name="< Prev", width=80, disabled=True)
        self.enc_search_next_button = pn.widgets.Button(name="Next >", width=80, disabled=True)
        self.enc_search_status = pn.pane.Markdown(
            f"*`{DEFAULT_MORPHOLOGY_PATTERN}` is the sharkfin pattern: one sharp rise, "
            "then a sustained fall. Searches the WHOLE span, not just the visible range.*"
        )
        self._search_matches = []      # [(seg_start, seg_end)] over the whole span
        self._search_index = -1        # which match the view is currently centred on
        self._search_summary = ""      # match count + cap notice, re-rendered on every step
        self._enc_highlight_stream = None

    # ── Morphology regex search (dSAX Phase F) ───────────────────────────

    def _reset_morphology_search(self):
        """Clear match state without clearing the PATTERN — someone
        scanning several spans for the same morphology should not have to
        retype it after every run."""
        self._search_matches = []
        self._search_index = -1
        self._search_summary = ""
        self.enc_search_prev_button.disabled = True
        self.enc_search_next_button.disabled = True
        if self._enc_highlight_stream is not None:
            self._enc_highlight_stream.event(spans=())
        self.enc_search_status.object = (
            f"*`{DEFAULT_MORPHOLOGY_PATTERN}` is the sharkfin pattern: one sharp rise, "
            "then a sustained fall. Searches the WHOLE span, not just the visible range.*"
        )

    def _on_morphology_search_clear(self, _event=None):
        self._reset_morphology_search()

    def _on_morphology_search(self, _event=None):
        """Find every match of the user's regex over the WHOLE-span symbol
        string and highlight them in the symbol strip.

        Whole-span, never the visible slice: searching only what happens to
        be on screen is a trap — the answer would silently change with the
        zoom level, and "no matches" would mean "none here", which is not
        what anyone reads it as.
        """
        if self._last_encoding is None:
            self.enc_search_status.object = "**Run an encoding first.**"
            return
        pattern = self.enc_search_input.value or ""
        if not pattern.strip():
            self._reset_morphology_search()
            return

        _x, t, symbols, details, _recording = self._last_encoding
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            # Never raise into a Panel callback — an exception here is
            # swallowed by Panel's handler and the button just silently
            # stops working (this module's plots.py sibling documents the
            # same failure mode for DynamicMap callbacks).
            self._search_matches = []
            self._search_index = -1
            self.enc_search_prev_button.disabled = True
            self.enc_search_next_button.disabled = True
            self.enc_search_status.object = f"**Invalid regex:** {e}"
            return

        string = symbols_to_string(symbols, symbol_letters(details))
        # Zero-width matches would produce zero-width highlights and an
        # infinite-looking match list (one per position); dropped rather
        # than rendered, with the count reported so the user can see their
        # pattern matched nothing useful.
        matches = [(m.start(), m.end()) for m in compiled.finditer(string) if m.end() > m.start()]
        self._search_matches = matches
        self._search_index = 0 if matches else -1

        if not matches:
            self.enc_search_prev_button.disabled = True
            self.enc_search_next_button.disabled = True
            if self._enc_highlight_stream is not None:
                self._enc_highlight_stream.event(spans=())
            self.enc_search_status.object = (
                f"**No matches** for `{pattern}` in {len(string):,} symbols."
            )
            return

        capped = matches[:ENCODING_HIGHLIGHT_CAP]
        if self._enc_highlight_stream is not None:
            self._enc_highlight_stream.event(spans=tuple(capped))
        self.enc_search_prev_button.disabled = len(matches) < 2
        self.enc_search_next_button.disabled = len(matches) < 2

        cap_note = ""
        if len(matches) > ENCODING_HIGHLIGHT_CAP:
            cap_note = (f" Highlighting the first {ENCODING_HIGHLIGHT_CAP:,} only "
                        "(rendering every one would stall pan/zoom); Prev/Next still "
                        "steps through all of them.")
        # Held separately and re-rendered by `_focus_morphology_match`,
        # which runs immediately below and would otherwise overwrite it —
        # the cap notice must survive stepping, not flash once and vanish.
        self._search_summary = (
            f"**{len(matches):,} match{'es' if len(matches) != 1 else ''}** for `{pattern}` "
            f"in {len(string):,} symbols.{cap_note}"
        )
        self._focus_morphology_match(0)

    def _match_time_span(self, seg_start, seg_end):
        """(t0, t1) in seconds for a match covering segments
        [seg_start, seg_end)."""
        _x, t, _symbols, details, _recording = self._last_encoding
        seg_t = segment_time_edges(t, int(details["n_symbols"]), int(details["samples_per_symbol"]))
        i0 = int(np.clip(seg_start, 0, len(seg_t) - 1))
        i1 = int(np.clip(seg_end, 0, len(seg_t) - 1))
        return float(seg_t[i0]), float(seg_t[i1])

    def _focus_morphology_match(self, index):
        """Recentre the encoding view's x-range on one match, through the
        SAME `range_stream` the panels already share — so all four panels
        move together and the string/RLE "Visible range only" display
        follows, rather than a second, independent notion of "where we are
        looking"."""
        if not self._search_matches or self._last_encoding is None:
            return
        index = int(index) % len(self._search_matches)
        self._search_index = index
        seg_start, seg_end = self._search_matches[index]
        t0, t1 = self._match_time_span(seg_start, seg_end)
        duration = t1 - t0
        # A match rendered edge-to-edge is hard to see in context; one
        # match-width of padding either side keeps the surrounding shape
        # visible, which is what makes a morphology judgeable at all.
        pad = max(duration, 1e-9)
        if self._enc_range_stream is not None:
            self._enc_range_stream.event(x_range=(t0 - pad, t1 + pad))
        # ASCII only: this string is echoed to a cp1252 console by a failing
        # test's `[FAIL]` line, and an em-dash there raises
        # UnicodeEncodeError inside the test runner itself (BASELINE.md).
        self.enc_search_status.object = (
            f"{self._search_summary}\n\n"
            f"**Match {index + 1} of {len(self._search_matches):,}** - segments "
            f"{seg_start}-{seg_end - 1}, {t0:,.1f}s to {t1:,.1f}s ({duration:,.1f}s long)."
        )
        self._refresh_encoding_string_display()

    def _step_morphology_match(self, delta):
        if not self._search_matches:
            return
        self._focus_morphology_match(self._search_index + int(delta))
