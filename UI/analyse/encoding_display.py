"""
The encoding inspection section: the signal/PAA/quantised panels, the symbol
strip, the symbol string and its run-length form, the colour key and the
alphabet legend.
"""

import numpy as np
import panel as pn

from Adapters._sax_common import diagnostic_rows
from Adapters.detection_sax_dsax import delta_diagnostic_rows

from Working.config import ENCODING_STRING_INLINE_THRESHOLD, UI_TABLE_FONT_SIZE

from UI.plots import (
    build_encoding_panels, cutline_domain, same_symbol_index, segment_time_edges,
    symbol_cmap_name, symbol_colors, symbol_label, symbol_letters, symbol_names,
    symbols_to_rle, symbols_to_string, HighlightStream,
)
from UI.analyse.formatting import _rows_to_html


class EncodingDisplayMixin:
    """The encoding section's panes and their content. Mixed into `RunPanel`."""

    def _build_encoding_widgets(self):
        # Part 6/7, Section 3: the encoding inspection view — an entire
        # section, hidden (not shown empty) whenever the last run's
        # output_kind isn't "encoding" (Part 4f). `encoding_section` wraps
        # every widget below so `.visible` toggles the whole thing at once.
        self.enc_preprocessing_banner = pn.pane.Markdown("", styles={"display": "none"})
        self.enc_signal_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.enc_paa_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.enc_quant_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.enc_colour_key = pn.pane.HTML("", sizing_mode="stretch_width")
        self.enc_strip_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.enc_yaxis_mode = pn.widgets.RadioButtonGroup(
            options=["Auto-scale each panel", "Match the signal panel"], value="Auto-scale each panel",
        )
        self.enc_view_toggle = pn.widgets.RadioButtonGroup(
            options=["Whole span", "Visible range only"], value="Whole span",
        )
        self.enc_string_pane = pn.widgets.TextAreaInput(
            name="Symbol string", value="", disabled=True, height=100, sizing_mode="stretch_width",
        )
        self.enc_string_info = pn.pane.Markdown("")
        self.enc_copy_button = pn.widgets.Button(name="Copy", button_type="default", width=80)
        self.enc_rle_pane = pn.widgets.TextAreaInput(
            name="Run-length encoded", value="", disabled=True, height=70, sizing_mode="stretch_width",
        )
        self.enc_rle_info = pn.pane.Markdown("")
        self.enc_diagnostics_pane = pn.pane.HTML("", sizing_mode="stretch_width")
        self.enc_legend_pane = pn.pane.HTML("", sizing_mode="stretch_width")
        self.enc_seed_motif_button = pn.widgets.Button(
            name="Save this encoding as a motif seed", button_type="success",
        )
        self.enc_seed_motif_status = pn.pane.Markdown("")

    def _build_encoding_section(self):
        # Part 7, Part 4 item 5: a collapsible Card (expanded by default)
        # so the controls and the alphabet table don't require heavy
        # scrolling between them; diagnostics + alphabet sit side by side
        # rather than stacked.
        self.encoding_section = pn.Card(
            self.enc_preprocessing_banner,
            pn.pane.Markdown("**Y-axis:**"), self.enc_yaxis_mode,
            self.enc_signal_pane, self.enc_paa_pane, self.enc_quant_pane,
            self.enc_colour_key, self.enc_strip_pane,
            self.enc_view_toggle,
            self.enc_string_pane, self.enc_string_info,
            pn.Row(self.enc_copy_button),
            self.enc_rle_pane, self.enc_rle_info,
            pn.pane.Markdown("**Find a morphology:**"),
            self.enc_search_input,
            pn.Row(self.enc_search_button, self.enc_search_clear_button,
                   self.enc_search_prev_button, self.enc_search_next_button),
            self.enc_search_status,
            pn.Row(
                pn.Column(pn.pane.Markdown("**Diagnostics:**"), self.enc_diagnostics_pane),
                pn.Column(pn.pane.Markdown("**Alphabet:**"), self.enc_legend_pane),
                sizing_mode="stretch_width",
            ),
            pn.Row(self.enc_noise_floor_button, self.enc_noise_floor_alpha),
            self.enc_noise_floor_status,
            pn.Row(self.enc_seed_motif_button, self.enc_seed_motif_status),
            title="Encoding", collapsed=False, visible=False, sizing_mode="stretch_width",
        )

    def _build_colour_key_html(self, details):
        """Part 7, Part 4 item 4: a compact, horizontal letter-to-swatch
        key sitting immediately above the symbol strip — the full
        alphabet table further down the page is too far away to be
        usable while looking at the strip.

        For a trend alphabet the full name is shown beside the letter
        (`D DOWN`, `S SAME`, `U UP`): a single-character alphabet is only
        self-explanatory once, and this key is exactly where someone looks
        to learn it."""
        alphabet_size = int(details["alphabet_size"])
        colors = symbol_colors(alphabet_size, symbol_cmap_name(details))
        letters = symbol_letters(details)
        names = symbol_names(details)
        cells = "".join(
            f'<span style="display:inline-flex;align-items:center;margin-right:10px;">'
            f'<span style="display:inline-block;width:12px;height:12px;background:{colors[i % len(colors)]};'
            f'border:1px solid #999;margin-right:3px;"></span>{symbol_label(i, letters)}'
            f'{f"&nbsp;<span style=\'color:#666;\'>{names[i]}</span>" if names and i < len(names) else ""}'
            f'</span>'
            for i in range(alphabet_size)
        )
        return f'<div style="padding:2px 0;">{cells}</div>'

    def _show_encoding(self, x, t, symbols, details, recording):
        """Build the four panels + string/RLE/diagnostics/legend from a
        fresh (or display-recomputed) encoding result. `x`/`t` are
        whatever was actually encoded (post any preprocessing step — see
        `Adapters.detection_sax_csax`'s module note)."""
        self._last_encoding = (x, t, symbols, details, recording)
        self._update_preprocessing_banner()
        signal_title = (
            "Encoded signal (after preprocessing)" if self._preprocessing_active() else "Encoded signal"
        )
        y_mode = "shared" if self.enc_yaxis_mode.value == "Match the signal panel" else "auto"
        # A fresh highlight stream per encoding: the old one's `spans` are
        # segment INDICES into a different symbol array and would highlight
        # arbitrary places in the new one.
        self._enc_highlight_stream = HighlightStream()
        dmap_signal, dmap_paa, dmap_quant, dmap_strip, range_stream = build_encoding_panels(
            x, t, symbols, details, signal_title=signal_title, y_mode=y_mode,
            highlight_stream=self._enc_highlight_stream,
        )
        self._enc_range_stream = range_stream
        self.enc_signal_pane.object = dmap_signal
        self.enc_paa_pane.object = dmap_paa
        self.enc_quant_pane.object = dmap_quant
        self.enc_strip_pane.object = dmap_strip
        self.enc_colour_key.object = self._build_colour_key_html(details)
        self.enc_view_toggle.visible = True
        self.enc_seed_motif_button.visible = True

        n_symbols = details["n_symbols"]
        # Part 3c: default "Visible range only" above the inline threshold
        # (a several-thousand-symbol string is unreadable rendered whole).
        self.enc_view_toggle.value = (
            "Visible range only" if n_symbols > ENCODING_STRING_INLINE_THRESHOLD else "Whole span"
        )
        self._refresh_encoding_string_display()
        self._reset_morphology_search()
        self._sync_noise_floor_controls(x, details)

        # `diagnostic_rows` is domain-agnostic (occupancy entropy,
        # self-transition rate, realised alphabet size) and serves all
        # three encoders; the trend-specific rows are APPENDED rather than
        # replacing it, so a dSAX run gets both and cSAX/pSAX are
        # untouched. See `Adapters.detection_sax_dsax.delta_diagnostic_rows`.
        rows = list(diagnostic_rows(symbols, details))
        if cutline_domain(details) == "delta":
            rows += delta_diagnostic_rows(symbols, details)
        self.enc_diagnostics_pane.object = _rows_to_html(rows)
        self.enc_legend_pane.object = self._build_legend_html(symbols, details)
        self.enc_seed_motif_status.object = ""

    def _on_enc_yaxis_mode_changed(self, _event=None):
        """Part 7, Part 2 item 4: re-render the last encoding (if any)
        under the newly chosen y-axis mode without re-running anything."""
        if self._last_encoding is not None:
            x, t, symbols, details, recording = self._last_encoding
            self._show_encoding(x, t, symbols, details, recording)

    def _show_encoding_string_only(self, string, encoding_type=None):
        """Part 3a's "too large to recompute" fallback — the cached
        string alone, no detail panels (there's nothing to draw them
        from), with the panels/diagnostics/legend left empty rather than
        stale from a previous run.

        There is no `details` here, so the alphabet cannot be derived the
        way `symbol_letters` derives it everywhere else. It does not need
        to be: `_persist_sax_encoding` wrote this string with the correct
        letters already, so displaying it verbatim is correct. What the
        cached row's `encoding_type` DOES buy is telling the reader which
        alphabet they are looking at — "UDDSU..." and "abcba..." are
        otherwise indistinguishable as to whether they encode trends or
        levels."""
        self._last_encoding = None
        self.enc_preprocessing_banner.object = ""
        self.enc_preprocessing_banner.styles = {"display": "none"}
        self.enc_signal_pane.object = None
        self.enc_paa_pane.object = None
        self.enc_quant_pane.object = None
        self.enc_strip_pane.object = None
        self.enc_colour_key.object = ""
        self.enc_view_toggle.visible = False
        self.enc_seed_motif_button.visible = False
        self.enc_string_pane.value = string
        alphabet_note = ""
        if encoding_type == "sax_dsax":
            alphabet_note = " — dSAX trend alphabet (D = down, S = same, U = up)"
        elif encoding_type:
            alphabet_note = f" — {encoding_type} alphabet (a, b, c, ...)"
        self.enc_string_info.object = (
            f"Length: {len(string):,} symbols (cached; too large to recompute for display)"
            f"{alphabet_note}"
        )
        self.enc_rle_pane.value = ""
        self.enc_rle_info.object = ""
        self.enc_diagnostics_pane.object = ""
        self.enc_legend_pane.object = ""
        self._reset_morphology_search()
        self.enc_noise_floor_button.visible = False
        self.enc_noise_floor_alpha.visible = False
        self.enc_noise_floor_status.object = ""

    def _visible_symbol_slice(self, t, symbols, details):
        """Which symbols fall within the encoding view's CURRENT x-range —
        shared by the string/RLE display's "Visible range only" mode."""
        if self._enc_range_stream is None or self._enc_range_stream.x_range is None:
            return symbols
        x0, x1 = self._enc_range_stream.x_range
        sps = details["samples_per_symbol"]
        n_symbols = details["n_symbols"]
        seg_t = segment_time_edges(t, n_symbols, sps)
        i0 = max(0, int(np.searchsorted(seg_t, x0, side="right")) - 1)
        i1 = min(n_symbols, int(np.searchsorted(seg_t, x1, side="left")) + 1)
        return symbols[i0:i1]

    def _refresh_encoding_string_display(self):
        """Part 3c: the string/RLE boxes respect the current zoom — a
        toggle switches between the full string and just the symbols
        currently in view."""
        if self._last_encoding is None:
            return
        x, t, symbols, details, recording = self._last_encoding
        if self.enc_view_toggle.value == "Visible range only":
            visible = self._visible_symbol_slice(t, symbols, details)
        else:
            visible = symbols
        letters = symbol_letters(details)
        string = symbols_to_string(visible, letters)
        rle = symbols_to_rle(visible, letters)
        self.enc_string_pane.value = string
        self.enc_string_info.object = f"Length: {len(string):,} symbols"
        self.enc_rle_pane.value = rle
        self.enc_rle_info.object = f"Length: {len(rle.split()) if rle else 0:,} runs"

    def _build_legend_html(self, symbols, details):
        """Part 3/7e: symbol index, letter, colour swatch, value range (raw
        amplitude units), representative value, count, and percentage with
        an inline horizontal bar — what lets someone read the
        quantisation/strip panels without guessing, at a glance rather
        than by parsing numbers. A styled HTML pane (not a Tabulator): the
        row-striping and inline occupancy bar are plain CSS/inline-`<div>`
        tricks that are simpler to get right in raw HTML than fighting a
        Tabulator's own per-cell formatter/styler API for the same effect,
        and this table is read-only with no sort/filter/selection need
        that would favour a Tabulator instead."""
        symbols = np.asarray(symbols)
        alphabet_size = details["alphabet_size"]
        colors = symbol_colors(alphabet_size, symbol_cmap_name(details))
        letters = symbol_letters(details)
        names = symbol_names(details)
        same_index = same_symbol_index(details)
        is_delta = cutline_domain(details) == "delta"
        # The range column is in the units of whatever was QUANTISED, and
        # for a trend encoding that is a rise per segment, not an
        # amplitude — labelling it "Value range" there would be the same
        # dimensional error the quantisation panel exists to avoid.
        range_header = "Rise range" if is_delta else "Value range"
        cutlines_raw = np.asarray(details["cutlines_raw"])
        representatives_raw = np.asarray(details.get("representatives_raw", details["representatives"]))
        n = len(symbols)
        counts = np.bincount(symbols, minlength=alphabet_size)[:alphabet_size]
        th = "text-align:left;padding:4px 10px;border-bottom:2px solid #ccc;"
        td = "padding:4px 10px;"
        rows = [f'<table style="border-collapse:collapse;font-size:{UI_TABLE_FONT_SIZE};">',
                f"<tr><th style='{th}'>Symbol</th><th style='{th}'>Colour</th>"
                f"<th style='{th}'>{range_header}</th><th style='{th}'>Representative</th>"
                f"<th style='{th}'>Count</th><th style='{th}'>%</th></tr>"]
        for sym in range(alphabet_size):
            lo = cutlines_raw[sym - 1] if sym > 0 else float("-inf")
            hi = cutlines_raw[sym] if sym < alphabet_size - 1 else float("inf")
            rep = representatives_raw[sym] if sym < len(representatives_raw) else float("nan")
            count = int(counts[sym])
            pct = 100.0 * count / n if n else 0.0
            # The SAME row carries the zero anchor — the one bin whose
            # meaning is fixed a priori rather than learned — so it gets a
            # standing highlight instead of the alternating stripe.
            is_same = same_index is not None and sym == same_index
            row_bg = "#e8f0d8" if is_same else ("#f4f4f4" if sym % 2 else "#ffffff")
            name_suffix = f" {names[sym]}" if names and sym < len(names) else ""
            rows.append(
                f"<tr style='background:{row_bg};{'font-weight:600;' if is_same else ''}'>"
                f"<td style='{td}'>{symbol_label(sym, letters)}{name_suffix} (index {sym})</td>"
                f"<td style='{td}'><span style='display:inline-block;width:14px;height:14px;"
                f"background:{colors[sym % len(colors)]};border:1px solid #999;'></span></td>"
                f"<td style='{td}'>{lo:.4g} to {hi:.4g}</td>"
                f"<td style='{td}'>{rep:.4g}</td>"
                f"<td style='{td}'>{count:,}</td>"
                f"<td style='{td}'>"
                f"<div style='display:inline-block;width:60px;height:10px;background:#e8e8e8;"
                f"vertical-align:middle;margin-right:6px;'>"
                f"<div style='width:{min(pct, 100):.1f}%;height:100%;background:#1f4e8c;'></div>"
                f"</div>{pct:.1f}%</td></tr>"
            )
        rows.append("</table>")
        if is_delta and same_index is None:
            # IMPLEMENTATION_NOTES.md 7.7: an even alphabet has a cutline
            # exactly AT zero and therefore no "no meaningful change" bin.
            # Saying so is the only honest option — highlighting an
            # arbitrary row would assert a SAME bin that does not exist.
            rows.append(
                f"<p style='font-size:{UI_TABLE_FONT_SIZE};color:#7a5b00;background:#fff3cd;"
                "padding:6px;border-radius:3px;margin:6px 0 0 0;'>"
                f"<b>No SAME bin.</b> alphabet_size={alphabet_size} is even, so the cutlines "
                "include one exactly at zero rather than a band around it — every segment is "
                "labelled as rising or falling, however slightly. Use an odd alphabet size "
                "for trend work.</p>"
            )
        return "".join(rows)
