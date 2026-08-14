"""
test_encoding_view_dsax.py
============================
Tests for bringing dSAX into the UI (DSAX_UI_PROMPT.md, 2026-08-10).

Two things are being protected here, and the FIRST matters more than the
second:

1. **cSAX and pSAX must render exactly as they did before.** The encoding
   view was rewritten to drive its panels off whichever of
   `paa_raw`/`deltas_raw` an encoder produced, and the single largest risk
   in that change is silently altering the amplitude path. The
   `test_amplitude_*` tests pin it structurally — panel 3 still plots
   `paa_raw`, its cutline positions are still exactly
   `details["cutlines_raw"]`, panel 2's bars are still FLAT, and
   `symbols_to_string` with no `letters` argument is still byte-identical
   to what it produced before the change (cSAX/pSAX strings are already
   persisted in the `encodings` cache and in `motifs.sax_string`, so a
   change there would invalidate stored data, not just a display).

2. dSAX renders in its own domain: rise per segment, not amplitude.

Assertions are made against the materialised HoloViews Overlay (element
composition and element data) AND against the rendered Bokeh model (axis
labels, `Range1d` bounds), per UI/plots.py's own documented lesson that
"it constructed without error" is not evidence of anything — two real
bugs in that file were only ever caught by inspecting the Bokeh model.

The run-panel end-to-end tests are real-data-gated exactly like
`tests/test_encoding_view.py`, and always use a fresh temp sqlite file.
Fixtures are IMPORTED from `tests/test_dsax_engineered.py` rather than
redefined, so the UI is proven against the identical arrays the encoder's
own assertions run against.

ASCII-only output (the cp1252 issue in BASELINE.md). Runnable standalone:
    python tests/test_encoding_view_dsax.py
"""

import inspect
import os
import re
import sys
import tempfile
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import panel as pn
pn.extension("tabulator")
import holoviews as hv
hv.extension("bokeh")

from Adapters.registry import discover_adapters, get_adapter
from Adapters.detection_sax_dsax import (
    NOISE_FLOOR_RATIO_ALERT, delta_diagnostic_rows, noise_floor_surrogate_count,
)
from Adapters._sax_common import encoding_diagnostics
from Working.Detection.sax.csax_python.csax import csax
from Working.Detection.sax.psax_python.psax import psax
from Working.Detection.sax.dsax_python.dsax import (
    SYMBOL_LETTERS, SYMBOL_NAMES, dsax, same_band_halfwidth,
    same_fraction_under_halfwidth, working_domain_array,
)
from Working.Detection.sax.dsax_python.trend_estimators import surrogate_same_halfwidth
from UI.plots import (
    ENCODING_HIGHLIGHT_CAP, HighlightStream, build_encoding_panels, cutline_domain,
    quantised_values, same_symbol_index, symbol_cmap_name, symbol_colors, symbol_label,
    symbol_letters, symbol_names, symbols_to_rle, symbols_to_string, value_axis_label,
)

from tests.test_dsax_engineered import (
    CONSTANT, MIXED, NOISE, NOISE_PLUS_DRIFT, NOISE_SPS, SHARKFIN, _detrend_linear,
)

discover_adapters()

SEED = 20260810
REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600

# A signal with real structure at the segment scale, used wherever a
# "typical" encoding is wanted rather than a pathological one.
_rng = np.random.default_rng(SEED)
STRUCTURED = (2.0 * np.sin(2 * np.pi * np.arange(4000) / 300.0)
              + _rng.normal(0.0, 0.5, 4000))
T_STRUCTURED = np.arange(len(STRUCTURED), dtype=float)


def _encode_dsax(x=None, sps=40, **kwargs):
    x = STRUCTURED if x is None else x
    np.random.seed(SEED)
    n_symbols = len(x) // sps
    return dsax(x, len(x), (n_symbols + 0.5) / len(x), return_details=True, **kwargs)


def _encode_csax(x=None, dim_ratio=1 / 20):
    x = STRUCTURED if x is None else x
    np.random.seed(SEED)
    return csax(x, len(x), dim_ratio, return_details=True)


def _encode_psax(x=None, dim_ratio=1 / 20, alphabet_size=8):
    x = STRUCTURED if x is None else x
    np.random.seed(SEED)
    return psax(x, len(x), dim_ratio, alphabet_size=alphabet_size, return_details=True)


def _frame(dmap):
    """The DynamicMap's CURRENT frame as a materialised Overlay. `[()]` is
    the key form for a DynamicMap driven purely by streams."""
    return dmap[()]


def _elements(frame, kind):
    return [v for k, v in frame.items() if k[0] == kind]


def _step_curve_values(frame):
    """Panel 3's quantisation step curve is drawn as two points per
    segment (flat top), so every second y value is one segment's
    quantised value."""
    curve = frame.get(("Curve", "I"))
    return np.asarray(curve.dframe()["amplitude"].values)[::2]


def _hline_positions(frame):
    return np.asarray([h.data for h in _elements(frame, "HLine")], dtype=float)


def _raises(exc, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc:
        return True
    except Exception as e:                                   # noqa: BLE001
        raise AssertionError(f"expected {exc.__name__}, got {e!r}")
    raise AssertionError(f"expected {exc.__name__}, nothing was raised")


# ============================================================================
# 1. Domain resolution
# ============================================================================

def test_cutline_domain_all_three_resolution_paths():
    # (a) declared by the encoder
    _sym, dsax_details = _encode_dsax()
    assert dsax_details["cutline_domain"] == "delta", "dSAX must DECLARE its domain"
    assert cutline_domain(dsax_details) == "delta"

    # (b) inferred from a `deltas` key, for a details dict with no
    #     declaration (the shape cSAX/pSAX would have if they ever grew one)
    inferred = {k: v for k, v in dsax_details.items() if k != "cutline_domain"}
    assert "deltas" in inferred
    assert cutline_domain(inferred) == "delta", "a `deltas` key must infer the delta domain"

    # (c) inferred amplitude, for the real cSAX/pSAX dicts
    for _s, details in (_encode_csax(), _encode_psax()):
        assert "cutline_domain" not in details, \
            "csax/psax must NOT have been edited to declare a domain"
        assert "deltas" not in details
        assert cutline_domain(details) == "amplitude"


def test_quantised_values_picks_the_right_array_per_domain():
    _s, d_details = _encode_dsax()
    assert np.array_equal(quantised_values(d_details), d_details["deltas_raw"])
    _s, c_details = _encode_csax()
    assert np.array_equal(quantised_values(c_details), c_details["paa_raw"])


def test_value_axis_label_per_domain():
    _s, d_details = _encode_dsax()
    _s, c_details = _encode_csax()
    assert value_axis_label(d_details) == "rise per segment"
    assert value_axis_label(c_details) == "amplitude"


def test_requantising_the_displayed_values_reproduces_the_displayed_symbols():
    """The property that makes the panels honest in BOTH domains: the
    array the quantisation panel draws, requantised against the cutlines
    it draws, is the symbol array the strip colours by."""
    for symbols, details in (_encode_dsax(), _encode_csax(), _encode_psax()):
        by_hand = np.searchsorted(np.asarray(details["cutlines_raw"]),
                                  quantised_values(details), side="right")
        assert np.array_equal(by_hand, symbols), \
            f"{cutline_domain(details)} domain: panel arrays do not reproduce the symbols"


# ============================================================================
# 2. Amplitude-path regression pins -- THE IMPORTANT ONES
# ============================================================================

def test_amplitude_panel3_still_plots_paa_and_exact_cutlines():
    for symbols, details in (_encode_csax(), _encode_psax()):
        dmaps = build_encoding_panels(STRUCTURED, T_STRUCTURED, symbols, details)
        frame = _frame(dmaps[2])
        assert np.allclose(_step_curve_values(frame), details["paa_raw"]), \
            "amplitude panel 3 must still plot paa_raw"
        assert np.allclose(_hline_positions(frame), details["cutlines_raw"]), \
            "amplitude panel 3's cutline positions must be exactly cutlines_raw"
        fig = hv.render(frame, backend="bokeh")
        assert fig.yaxis[0].axis_label == "amplitude", fig.yaxis[0].axis_label
        assert "PAA vs. learned cutlines" in fig.title.text, fig.title.text


def test_amplitude_panel2_bars_are_still_flat_at_paa():
    """A regression here would mean the trend-line branch had leaked into
    the amplitude path — the bars must have zero rise."""
    symbols, details = _encode_csax()
    dmaps = build_encoding_panels(STRUCTURED, T_STRUCTURED, symbols, details)
    frame = _frame(dmaps[1])
    bars = frame.get(("Segments", "II")).dframe()
    assert np.allclose(bars["y0"].values, bars["y1"].values), "PAA bars must be flat"
    assert np.allclose(bars["y0"].values, details["paa_raw"])
    assert "symbol" not in bars.columns, \
        "the amplitude path must not have gained the delta path's colour dimension"
    fig = hv.render(frame, backend="bokeh")
    assert "PAA (red) over signal (grey)" in fig.title.text, fig.title.text


def test_symbols_to_string_default_is_byte_identical():
    """cSAX/pSAX strings are already persisted on disk and in
    `motifs.sax_string`; changing them would invalidate stored data."""
    fixed = np.array([0, 0, 1, 2, 2, 2, 1, 0, 25, 26, 27])
    assert symbols_to_string(fixed) == "aabcccbazaaab"
    assert symbols_to_string(fixed, None) == "aabcccbazaaab"
    assert symbols_to_rle(fixed) == "a2 b1 c3 b1 a1 z1 aa1 ab1"
    assert symbols_to_rle(fixed, None) == "a2 b1 c3 b1 a1 z1 aa1 ab1"

    symbols, _details = _encode_csax()
    assert symbols_to_string(symbols) == "".join(
        symbol_label(s, None) for s in symbols
    )


def test_amplitude_encodings_get_no_letters_and_no_same_row():
    for _s, details in (_encode_csax(), _encode_psax()):
        assert symbol_letters(details) is None
        assert symbol_names(details) is None
        assert same_symbol_index(details) is None
        assert symbol_cmap_name(details) == "viridis", \
            "the amplitude palette must not have changed"


def test_amplitude_strip_hover_keeps_its_band_bounds_from_paa():
    symbols, details = _encode_csax()
    dmaps = build_encoding_panels(STRUCTURED, T_STRUCTURED, symbols, details)
    strip = _frame(dmaps[3]).get(("Rectangles", "I")).dframe()
    paa = np.asarray(details["paa_raw"])
    # `value` and `level` are the same quantity in the amplitude domain,
    # by construction -- the shared field set is the point.
    assert np.allclose(strip["value"].values, paa)
    assert np.allclose(strip["level"].values, paa)


# ============================================================================
# 3. Delta-path rendering
# ============================================================================

def test_delta_panel3_plots_deltas_with_the_rise_label():
    symbols, details = _encode_dsax()
    dmaps = build_encoding_panels(STRUCTURED, T_STRUCTURED, symbols, details)
    frame = _frame(dmaps[2])

    assert np.allclose(_step_curve_values(frame), details["deltas_raw"]), \
        "delta panel 3 must plot deltas_raw, not paa_raw"
    assert not np.allclose(_step_curve_values(frame), details["paa_raw"]), \
        "sanity: deltas_raw and paa_raw must actually differ on this fixture"
    assert np.allclose(_hline_positions(frame), details["cutlines_raw"])
    assert len(_elements(frame, "HSpan")) == details["alphabet_size"], \
        "one shaded band per symbol"
    assert len(_elements(frame, "HLine")) == details["alphabet_size"] - 1

    fig = hv.render(frame, backend="bokeh")
    assert fig.yaxis[0].axis_label == "rise per segment", fig.yaxis[0].axis_label
    assert "segment rise vs. learned cutlines" in fig.title.text, fig.title.text
    # The y-range must cover every cutline (see the panel's own comment on
    # why ALL cutlines are included, not just the visible ones).
    assert fig.y_range.start <= details["cutlines_raw"].min()
    assert fig.y_range.end >= details["cutlines_raw"].max()


def test_delta_panel2_draws_one_trend_segment_per_symbol():
    symbols, details = _encode_dsax()
    dmaps = build_encoding_panels(STRUCTURED, T_STRUCTURED, symbols, details)
    bars = _frame(dmaps[1]).get(("Segments", "II")).dframe()

    assert len(bars) == details["n_symbols"], \
        f"expected {details['n_symbols']} trend segments, got {len(bars)}"
    rise = bars["y1"].values - bars["y0"].values
    assert np.allclose(rise, details["deltas_raw"]), \
        "each trend line's rise must equal that segment's delta"
    # Centred on the segment mean, so the line sits on the signal it
    # describes.
    midpoints = (bars["y0"].values + bars["y1"].values) / 2.0
    assert np.allclose(midpoints, details["paa_raw"])
    assert "symbol" in bars.columns, "delta trend lines must be coloured by symbol"

    fig = hv.render(_frame(dmaps[1]), backend="bokeh")
    assert "Segment trends over signal" in fig.title.text, fig.title.text


def test_delta_strip_hover_uses_delta_bounds_plus_a_level_field():
    symbols, details = _encode_dsax()
    dmaps = build_encoding_panels(STRUCTURED, T_STRUCTURED, symbols, details)
    strip = _frame(dmaps[3]).get(("Rectangles", "I")).dframe()

    assert np.allclose(strip["value"].values, details["deltas_raw"]), \
        "the hover value must be the delta in delta mode"
    assert np.allclose(strip["level"].values, details["paa_raw"]), \
        "`level` is the absolute amplitude the trend occurred at"
    assert not np.allclose(strip["value"].values, strip["level"].values), \
        "sanity: the two fields must be genuinely different in delta mode"
    # Band bounds come from the delta cutlines, never from paa_raw's range.
    cut = np.asarray(details["cutlines_raw"])
    inner = strip[strip["symbol"] == "1"]
    if len(inner):
        assert np.allclose(inner["range_lo"].values, cut[0])
        assert np.allclose(inner["range_hi"].values, cut[1])


def test_delta_letters_reach_the_panels():
    symbols, details = _encode_dsax()
    assert symbol_letters(details) == ("D", "S", "U")
    dmaps = build_encoding_panels(STRUCTURED, T_STRUCTURED, symbols, details)
    band_labels = _frame(dmaps[2]).get(("Labels", "I")).dframe()["label"].tolist()
    assert band_labels == ["D", "S", "U"], band_labels
    strip_letters = set(_frame(dmaps[3]).get(("Rectangles", "I")).dframe()["letter"])
    assert strip_letters <= {"D", "S", "U"}, strip_letters


def test_delta_palette_is_diverging_and_dark_enough_for_white_text():
    _s, details = _encode_dsax()
    assert symbol_cmap_name(details) == "dsax_diverging"
    colors = symbol_colors(3, symbol_cmap_name(details))
    assert len(colors) == 3 and len(set(colors)) == 3

    def _luminance(hex_color):
        rgb = [int(hex_color[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    for c in colors:
        contrast = 1.05 / (_luminance(c) + 0.05)
        assert contrast >= 4.0, (
            f"{c} has contrast {contrast:.2f} against the strip's white letters; "
            "a stock diverging colormap's near-white midpoint is exactly the "
            "problem these hand-picked stops avoid"
        )
    # Diverging: the middle bin must be the least saturated of the three.
    def _sat(h):
        rgb = [int(h[i:i + 2], 16) for i in (1, 3, 5)]
        return max(rgb) - min(rgb)
    assert _sat(colors[1]) < _sat(colors[0]) and _sat(colors[1]) < _sat(colors[2])


# ============================================================================
# 4. Strip element composition (the DynamicMap type-stability invariant)
# ============================================================================

def test_strip_composition_is_stable_across_frames_and_highlight_states():
    """UI/plots.py bug 3: a DynamicMap callback must never vary which
    element types it returns across frames. The highlight overlay and the
    letter labels are BOTH always present, whatever the state."""
    symbols, details = _encode_dsax()
    stream = HighlightStream()
    dmaps = build_encoding_panels(STRUCTURED, T_STRUCTURED, symbols, details,
                                  highlight_stream=stream)
    range_stream = dmaps[4]
    expected = [("Rectangles", "I"), ("Rectangles", "II"), ("Labels", "I")]

    assert list(_frame(dmaps[3]).keys()) == expected, "no matches"
    stream.event(spans=((3, 7), (20, 26)))
    assert list(_frame(dmaps[3]).keys()) == expected, "with matches"
    # Zoomed far enough out that the letter-threshold branch flips.
    range_stream.event(x_range=(0.0, float(len(STRUCTURED))))
    assert list(_frame(dmaps[3]).keys()) == expected, "zoomed out past the letter threshold"
    stream.event(spans=())
    assert list(_frame(dmaps[3]).keys()) == expected, "matches cleared again"


def test_highlight_spans_render_at_the_matched_segment_times():
    symbols, details = _encode_dsax()
    stream = HighlightStream()
    dmaps = build_encoding_panels(STRUCTURED, T_STRUCTURED, symbols, details,
                                  highlight_stream=stream)
    sps = details["samples_per_symbol"]
    stream.event(spans=((3, 7),))
    marks = _frame(dmaps[3]).get(("Rectangles", "II")).dframe()
    assert len(marks) == 1
    assert np.isclose(marks["x0"].iloc[0], T_STRUCTURED[3 * sps])
    assert np.isclose(marks["x1"].iloc[0], T_STRUCTURED[7 * sps])


# ============================================================================
# 5. Letters, alphabets, and the even-size case
# ============================================================================

def test_declared_letter_maps_are_single_character_and_unique():
    for k, letters in SYMBOL_LETTERS.items():
        assert len(letters) == k, f"k={k}: {letters}"
        assert all(len(c) == 1 for c in letters), \
            f"k={k}: the string/RLE/strip all assume ONE char per symbol"
        assert len(set(letters)) == k, f"k={k}: letters must be unique, got {letters}"
        assert k in SYMBOL_NAMES and len(SYMBOL_NAMES[k]) == k


def test_five_symbol_alphabet_resolves_letters_and_names():
    symbols, details = _encode_dsax(alphabet_size=5)
    assert symbol_letters(details) == ("d", "D", "S", "U", "u")
    assert symbol_names(details) == ("DOWN2", "DOWN1", "SAME", "UP1", "UP2")
    assert same_symbol_index(details) == 2
    string = symbols_to_string(symbols, symbol_letters(details))
    assert len(string) == details["n_symbols"]
    assert set(string) <= set("dDSUu"), string[:40]
    # Case-insensitively, a k=3 vocabulary pattern still reads at k=5.
    assert re.fullmatch(r"[dDSUu]+", string)


def test_even_alphabet_has_no_same_bin():
    _symbols, details = _encode_dsax(alphabet_size=4)
    assert same_symbol_index(details) is None, \
        "an even alphabet has a cutline AT zero, not a bin around it"
    assert same_band_halfwidth(details) is None
    assert symbol_letters(details) is None, \
        "an even alphabet must fall back to a/b/c, not a misleading D/S/U scheme"
    rows = delta_diagnostic_rows(_symbols, details)
    labels = {label for label, _v, _s in rows}
    assert "SAME band" in labels
    band_row = [r for r in rows if r[0] == "SAME band"][0]
    assert "EVEN" in band_row[1] and band_row[2] == "warn", band_row


def test_symbol_label_falls_back_rather_than_raising():
    assert symbol_label(0, ("D", "S", "U")) == "D"
    assert symbol_label(7, ("D", "S", "U")) == "h", \
        "an out-of-range index must fall back, not kill the render"
    assert symbol_label(1, None) == "b"


# ============================================================================
# 6. Diagnostics
# ============================================================================

def test_pure_noise_trips_the_same_fraction_warning():
    symbols, details = _encode_dsax(x=NOISE, sps=NOISE_SPS)
    rows = delta_diagnostic_rows(symbols, details)
    row = [r for r in rows if r[0] == "SAME fraction"][0]
    assert row[2] == "warn", f"pure noise must be flagged, got {row}"
    assert "IMPLEMENTATION_NOTES.md 6.3" in row[1]
    assert "noise-floor" in row[1]


def test_undetrended_drift_trips_the_mean_delta_warning():
    symbols, details = _encode_dsax(x=NOISE_PLUS_DRIFT, sps=NOISE_SPS)
    row = [r for r in delta_diagnostic_rows(symbols, details) if r[0] == "Mean delta"][0]
    assert row[2] == "warn", f"undetrended drift must be flagged, got {row}"
    assert "Detrending is not optional" in row[1]

    # ... and detrending must clear it, or the warning is not actually
    # measuring what it claims to.
    symbols2, details2 = _encode_dsax(x=_detrend_linear(NOISE_PLUS_DRIFT), sps=NOISE_SPS)
    row2 = [r for r in delta_diagnostic_rows(symbols2, details2) if r[0] == "Mean delta"][0]
    assert row2[2] == "", f"detrended signal must NOT be flagged, got {row2}"


def test_constant_signal_names_the_right_degenerate_case():
    symbols, details = _encode_dsax(x=CONSTANT, sps=100)
    rows = delta_diagnostic_rows(symbols, details)
    row = [r for r in rows if r[0] == "Cutlines degenerate"][0]
    assert row[2] == "error", row
    assert "constant" in row[1], row[1]
    assert "straight ramp" not in row[1], "the two degenerate cases must not be collapsed"


def test_straight_ramp_names_the_other_degenerate_case():
    ramp = np.linspace(0.0, 10.0, 1000)
    symbols, details = _encode_dsax(x=ramp, sps=100, normalize=False)
    assert details["cutlines_degenerate"] is True
    row = [r for r in delta_diagnostic_rows(symbols, details)
           if r[0] == "Cutlines degenerate"][0]
    assert "straight ramp" in row[1], row[1]
    assert "constant" not in row[1], "the two degenerate cases must not be collapsed"


def test_diagnostics_are_appended_to_the_shared_rows_not_replacing_them():
    """The shared rows (occupancy entropy, self-transition rate, realised
    alphabet size) serve all three encoders and must survive."""
    from Adapters._sax_common import diagnostic_rows
    symbols, details = _encode_dsax()
    shared = diagnostic_rows(symbols, details)
    combined = list(shared) + delta_diagnostic_rows(symbols, details)
    labels = [label for label, _v, _s in combined]
    for required in ("Occupancy entropy", "Transition self-rate", "Realised alphabet size",
                     "SAME fraction", "SAME band half-width", "Mean delta"):
        assert required in labels, f"{required} missing from {labels}"


def test_entropy_no_longer_reports_negative_zero():
    """The one permitted change to `_sax_common` (IMPLEMENTATION_NOTES 4.2)."""
    diag = encoding_diagnostics(np.ones(50, dtype=int), 3)
    assert diag["occupancy_entropy_bits"] == 0.0
    assert not np.signbit(diag["occupancy_entropy_bits"]), "entropy must not be -0.0"
    assert not np.signbit(diag["occupancy_entropy_fraction"])


# ============================================================================
# 7. Noise floor
# ============================================================================

def test_noise_floor_on_the_section_6_3_fixture_reports_roughly_three_times():
    """IMPLEMENTATION_NOTES.md 6.3 measured 3.1x on exactly this fixture:
    MSE-optimal Lloyd-Max puts the SAME band far narrower than a
    noise-floor justification supports."""
    symbols, details = _encode_dsax(x=NOISE, sps=NOISE_SPS)
    before_cutlines = np.array(details["cutlines"], copy=True)
    before_symbols = np.array(symbols, copy=True)

    learned = same_band_halfwidth(details)
    working = working_domain_array(NOISE, details)
    n_surrogates = noise_floor_surrogate_count(len(working))
    surrogate = surrogate_same_halfwidth(
        working, NOISE_SPS, trend_estimator=details["trend_estimator"],
        n_surrogates=n_surrogates, alpha=0.95, random_state=0,
    )
    ratio = surrogate / learned
    assert 2.0 < ratio < 4.5, f"expected ~3x, got {ratio:.2f}x"
    assert ratio > NOISE_FLOOR_RATIO_ALERT, "this fixture must trip the alert threshold"

    projected, widened = same_fraction_under_halfwidth(details, surrogate)
    assert projected > details["same_fraction_observed"], \
        "imposing a wider floor must increase the SAME fraction"
    assert projected > 0.85, f"a trendless signal should read as mostly SAME, got {projected}"

    # The measurement must not mutate what it measured.
    assert np.array_equal(details["cutlines"], before_cutlines)
    assert np.array_equal(symbols, before_symbols)
    assert widened is not None and widened[1] >= surrogate - 1e-12


def test_working_domain_array_undoes_only_the_encoders_own_normalisation():
    """A half-width estimated on the raw array would be wrong by a factor
    of norm_std -- the same class of units error `delta_scale` exists to
    prevent inside the encoder."""
    _s, details = _encode_dsax(x=NOISE, sps=NOISE_SPS, normalize=True)
    working = working_domain_array(NOISE, details)
    assert len(working) == details["data_len_trimmed"]
    assert abs(float(np.mean(working))) < 1e-9
    assert abs(float(np.std(working)) - 1.0) < 1e-6

    _s, raw_details = _encode_dsax(x=NOISE, sps=NOISE_SPS, normalize=False)
    assert raw_details["norm_std"] is None
    assert np.array_equal(working_domain_array(NOISE, raw_details),
                          NOISE[:raw_details["data_len_trimmed"]])


def test_surrogate_count_flexes_with_span_length_never_the_span():
    assert noise_floor_surrogate_count(6_000) == 50, "short spans get the full draw"
    assert noise_floor_surrogate_count(2_600_000) == 8, "long spans get the floor"
    assert noise_floor_surrogate_count(200_000) == 50
    assert 8 <= noise_floor_surrogate_count(500_000) <= 50


def test_same_fraction_under_halfwidth_is_a_floor_not_an_override():
    _s, details = _encode_dsax(x=NOISE, sps=NOISE_SPS)
    learned = same_band_halfwidth(details)
    narrower, _ = same_fraction_under_halfwidth(details, learned / 4.0)
    assert np.isclose(narrower, details["same_fraction_observed"]), \
        "a floor below the learned band must change nothing"


def test_same_band_helpers_return_none_without_a_same_bin():
    _s, details = _encode_dsax(alphabet_size=4)
    assert same_band_halfwidth(details) is None
    assert same_fraction_under_halfwidth(details, 0.5) == (None, None)


# ============================================================================
# 8. Regex morphology search (pure, no UI)
# ============================================================================

def test_sharkfin_fixture_matches_the_vocabulary_pattern():
    symbols, details = _encode_dsax(x=SHARKFIN, sps=100, normalize=False,
                                    threshold_mode="absolute", absolute_threshold=0.25)
    string = symbols_to_string(symbols, symbol_letters(details))
    assert string == "UDDDDD", string
    matches = [(m.start(), m.end()) for m in re.finditer(r"UD{3,}", string)]
    assert matches == [(0, 6)], matches


# ============================================================================
# 9. Run-panel end-to-end (real-data gated, same convention as
#    tests/test_encoding_view.py)
# ============================================================================

def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_app():
    from Working.database.schema import init_db
    from Working.database import queries as q
    from UI.app import ViewerApp
    from tests._session_isolation import scratch_session_file

    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    rid = q.insert_recording(conn, "UNITTEST_encoding_view_dsax.mat", 0, 1.0, REAL_L, 0,
                             REAL_CHANNEL_PATH)
    conn.close()
    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=tf.name)
    app._test_session_cm = session_cm
    app.layout()
    return app, tf.name, rid


def _close_and_unlink(app, db_path):
    app._test_session_cm.__exit__(None, None, None)
    app.conn.close()
    os.unlink(db_path)


def _select_algorithm(rp, full_name):
    rp.stage_select.value = full_name.split(".")[0]
    rp.algorithm_select.value = full_name


def _run_and_wait(rp, timeout_s=20):
    rp._on_run()
    deadline = time.time() + timeout_s
    while rp._thread is not None and rp._thread.is_alive() and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(0.05)


def _prepare(rp, app, sps=20):
    app._range_stream.event(x_range=(0.0, 6000.0))
    app._refresh_view()
    rp.span_mode.value = "Current viewport"
    _select_algorithm(rp, "detection.sax_dsax")
    rp._param_widgets["segment_mode"].value = "samples_per_symbol"
    rp._param_widgets["samples_per_symbol"].value = sps


def _show_fixture(rp, x, sps, **kwargs):
    """Drive `_show_encoding` with a KNOWN fixture, so the search /
    diagnostics assertions are deterministic instead of depending on
    whatever the real channel happens to contain."""
    symbols, details = _encode_dsax(x=x, sps=sps, **kwargs)
    t = np.arange(len(x), dtype=float)
    rp._show_encoding(x, t, symbols, details, {"n_samples": len(x)})
    return symbols, details


def test_dsax_appears_in_the_run_panel_algorithm_list():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        rp.stage_select.value = "detection"
        # `options` is {display_name: adapter_name}, so the adapter name is
        # in the VALUES, not the keys.
        assert "detection.sax_dsax" in list(rp.algorithm_select.options.values()), \
            rp.algorithm_select.options
        assert "dSAX trend symbolisation" in rp.algorithm_select.options
        _select_algorithm(rp, "detection.sax_dsax")
        assert rp.derived_pane.object != ""
        assert "Symbols produced" in rp.derived_pane.object
    finally:
        _close_and_unlink(app, db_path)


def test_running_dsax_populates_the_encoding_section():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        _prepare(rp, app)
        _run_and_wait(rp)

        assert rp.encoding_section.visible is True
        assert rp.enc_signal_pane.object is not None
        assert rp.enc_paa_pane.object is not None
        assert rp.enc_quant_pane.object is not None
        assert rp.enc_strip_pane.object is not None
        assert rp.enc_string_pane.value != ""
        assert set(rp.enc_string_pane.value) <= set("DSU"), \
            f"a dSAX string must read D/S/U, got {rp.enc_string_pane.value[:40]!r}"
        assert rp.enc_rle_pane.value != ""
        assert "Rise range" in rp.enc_legend_pane.object, "legend must be in delta units"
        assert "DOWN" in rp.enc_colour_key.object, "colour key must name the symbols"
        assert "SAME fraction" in rp.enc_diagnostics_pane.object
        assert "Realised alphabet size" in rp.enc_diagnostics_pane.object, \
            "the shared diagnostics must survive alongside the trend-specific ones"
        assert rp.enc_noise_floor_button.visible is True
    finally:
        _close_and_unlink(app, db_path)


def test_csax_still_renders_in_the_amplitude_domain_through_the_panel():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        app._range_stream.event(x_range=(0.0, 6000.0))
        app._refresh_view()
        rp.span_mode.value = "Current viewport"
        _select_algorithm(rp, "detection.sax_csax")
        rp._param_widgets["segment_mode"].value = "samples_per_symbol"
        rp._param_widgets["samples_per_symbol"].value = 20
        _run_and_wait(rp)

        _x, _t, _symbols, details, _rec = rp._last_encoding
        assert cutline_domain(details) == "amplitude"
        assert "Value range" in rp.enc_legend_pane.object
        assert "Rise range" not in rp.enc_legend_pane.object
        assert "SAME fraction" not in rp.enc_diagnostics_pane.object, \
            "trend rows must not leak into an amplitude encoding"
        assert rp.enc_noise_floor_button.visible is False
    finally:
        _close_and_unlink(app, db_path)


def test_persisted_string_matches_the_displayed_string():
    """The cached `.txt` and the run panel must agree, or a morphology
    regex saved against one silently fails against the other."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    from Working.database import runs as R
    from Working.encoding_cache import read_encoding_file

    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        _prepare(rp, app)
        _run_and_wait(rp)

        rp.enc_view_toggle.value = "Whole span"
        displayed = rp.enc_string_pane.value
        encodings = list(R.list_encodings(app.conn, app._recording_id))
        assert encodings, "the dSAX run must have persisted an encoding"
        row = encodings[0]
        assert row["encoding_type"] == "sax_dsax", row["encoding_type"]
        assert read_encoding_file(row["path"]) == displayed
        assert set(displayed) <= set("DSU")
    finally:
        _close_and_unlink(app, db_path)


def test_long_encoding_defaults_to_visible_range_and_still_renders():
    """Regression pin for a pre-existing NameError: `_visible_symbol_slice`
    called `segment_time_edges` without importing it, so ANY encoding above
    ENCODING_STRING_INLINE_THRESHOLD symbols -- which auto-selects
    'Visible range only' -- raised. See UI_INTEGRATION_NOTES.md."""
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    from Working.config import ENCODING_STRING_INLINE_THRESHOLD

    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        _show_fixture(rp, NOISE[:60000], NOISE_SPS)
        assert rp._last_encoding[3]["n_symbols"] > ENCODING_STRING_INLINE_THRESHOLD
        assert rp.enc_view_toggle.value == "Visible range only"
        assert rp.enc_string_pane.value != "", "the visible-range string must render"
        assert "Length:" in rp.enc_string_info.object
    finally:
        _close_and_unlink(app, db_path)


def test_morphology_search_finds_the_sharkfin_and_steps_through_matches():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        _show_fixture(rp, SHARKFIN, 100, normalize=False,
                      threshold_mode="absolute", absolute_threshold=0.25)
        rp.enc_search_input.value = "UD{3,}"
        rp._on_morphology_search()

        assert rp._search_matches == [(0, 6)], rp._search_matches
        assert "1 match" in rp.enc_search_status.object, rp.enc_search_status.object
        # Focused on match 1, with the time span reported. The end time is
        # 599.0, not 600.0: `segment_time_edges` clamps the last edge to
        # the last SAMPLE index, and it is the shared helper every panel
        # uses, so the search agrees with what is drawn.
        assert "Match 1 of 1" in rp.enc_search_status.object
        assert "0.0s to 599.0s" in rp.enc_search_status.object, rp.enc_search_status.object
        # A single match leaves stepping disabled.
        assert rp.enc_search_prev_button.disabled is True
        assert rp.enc_search_next_button.disabled is True
        # The highlight actually reached the strip.
        marks = _frame(rp.enc_strip_pane.object).get(("Rectangles", "II")).dframe()
        assert len(marks) == 1
    finally:
        _close_and_unlink(app, db_path)


def test_morphology_search_steps_and_recentres_the_view():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        _show_fixture(rp, MIXED, 40)
        rp.enc_search_input.value = "U"
        rp._on_morphology_search()
        assert len(rp._search_matches) > 3, rp._search_matches

        first_range = rp._enc_range_stream.x_range
        rp._step_morphology_match(+1)
        assert rp._search_index == 1
        assert rp._enc_range_stream.x_range != first_range, \
            "stepping must recentre the shared range stream"
        assert "Match 2 of" in rp.enc_search_status.object
        assert rp.enc_search_next_button.disabled is False

        # Wraps around rather than dead-ending.
        rp._search_index = len(rp._search_matches) - 1
        rp._step_morphology_match(+1)
        assert rp._search_index == 0
    finally:
        _close_and_unlink(app, db_path)


def test_morphology_search_reports_an_invalid_regex_without_raising():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        _show_fixture(rp, SHARKFIN, 100, normalize=False,
                      threshold_mode="absolute", absolute_threshold=0.25)
        rp.enc_search_input.value = "U(D{3,"      # unbalanced group
        rp._on_morphology_search()                # must NOT raise
        assert "Invalid regex" in rp.enc_search_status.object, rp.enc_search_status.object
        assert rp._search_matches == []
        assert rp.enc_search_next_button.disabled is True
    finally:
        _close_and_unlink(app, db_path)


def test_morphology_search_announces_the_highlight_cap():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        symbols, details = _show_fixture(rp, NOISE, NOISE_SPS)
        rp.enc_search_input.value = "U"
        rp._on_morphology_search()

        assert len(rp._search_matches) > ENCODING_HIGHLIGHT_CAP, \
            f"fixture must exceed the cap, got {len(rp._search_matches)}"
        assert str(ENCODING_HIGHLIGHT_CAP) in rp.enc_search_status.object, \
            rp.enc_search_status.object
        # The FULL match list is kept for stepping; only the drawing is capped.
        assert len(rp._enc_highlight_stream.spans) == ENCODING_HIGHLIGHT_CAP
    finally:
        _close_and_unlink(app, db_path)


def test_morphology_search_survives_an_empty_result_and_a_clear():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        _show_fixture(rp, SHARKFIN, 100, normalize=False,
                      threshold_mode="absolute", absolute_threshold=0.25)
        rp.enc_search_input.value = "ZZZ"
        rp._on_morphology_search()
        assert "No matches" in rp.enc_search_status.object
        assert rp._search_matches == []

        rp.enc_search_input.value = "UD{3,}"
        rp._on_morphology_search()
        assert rp._search_matches
        rp._on_morphology_search_clear()
        assert rp._search_matches == []
        assert len(rp._enc_highlight_stream.spans) == 0
    finally:
        _close_and_unlink(app, db_path)


def test_noise_floor_button_reports_and_does_not_recompute():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        # Select the adapter first, so `_param_widgets["min_same_halfwidth"]`
        # exists for the button to fill in -- the button must still REPORT
        # without it, but "it set the control" is part of what is asserted.
        _prepare(rp, app)
        symbols, details = _show_fixture(rp, NOISE[:40000], NOISE_SPS)
        before_symbols = np.array(symbols, copy=True)
        before_cutlines = np.array(details["cutlines"], copy=True)

        assert rp.enc_noise_floor_button.visible is True
        assert rp.enc_noise_floor_button.disabled is False
        rp._on_estimate_noise_floor()
        rp._noise_floor_thread.join(timeout=120)
        assert not rp._noise_floor_thread.is_alive(), "noise-floor worker did not finish"

        status = rp.enc_noise_floor_status.object
        assert "surrogate half-width" in status, status
        assert "ratio surrogate / learned" in status
        assert "narrower than the noise floor" in status, \
            "this fixture is pure noise and must trip the alert wording"
        assert "Re-run for it to take effect" in status, \
            "the button must never silently re-run"
        # It filled in the control, but changed nothing about the encoding.
        assert rp._param_widgets["min_same_halfwidth"].value > 0
        assert np.array_equal(rp._last_encoding[2], before_symbols)
        assert np.array_equal(rp._last_encoding[3]["cutlines"], before_cutlines)
    finally:
        _close_and_unlink(app, db_path)


def test_noise_floor_controls_hidden_and_gated_appropriately():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    from Adapters.detection_sax_dsax import NOISE_FLOOR_MAX_SAMPLES

    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        # Even alphabet -> no SAME band -> nothing to compare a floor to.
        _show_fixture(rp, STRUCTURED, 40, alphabet_size=4)
        assert rp.enc_noise_floor_button.visible is True
        assert rp.enc_noise_floor_button.disabled is True
        assert "even" in rp.enc_noise_floor_status.object

        # Amplitude domain -> hidden entirely.
        symbols, details = _encode_csax()
        rp._show_encoding(STRUCTURED, T_STRUCTURED, symbols, details,
                          {"n_samples": len(STRUCTURED)})
        assert rp.enc_noise_floor_button.visible is False
        assert rp.enc_noise_floor_alpha.visible is False
        assert NOISE_FLOOR_MAX_SAMPLES > 0
    finally:
        _close_and_unlink(app, db_path)


def test_even_alphabet_legend_says_so_and_disables_the_halfwidth_control():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        _prepare(rp, app)
        rp._param_widgets["alphabet_size"].value = 4
        assert rp._param_widgets["min_same_halfwidth"].disabled is True, \
            "min_same_halfwidth must be visibly inert at an even alphabet size"
        assert "(n/a)" in rp._param_widgets["min_same_halfwidth"].name
        assert "no SAME band" in rp._param_widgets["min_same_halfwidth"].description

        _show_fixture(rp, STRUCTURED, 40, alphabet_size=4)
        assert "No SAME bin" in rp.enc_legend_pane.object

        rp._param_widgets["alphabet_size"].value = 5
        assert rp._param_widgets["min_same_halfwidth"].disabled is False
        assert "(n/a)" not in rp._param_widgets["min_same_halfwidth"].name
    finally:
        _close_and_unlink(app, db_path)


def test_motif_seed_records_the_matching_pattern():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
    from Working.database import runs as R

    app, db_path, _rid = _fresh_app()
    try:
        rp = app.run_panel
        _prepare(rp, app)
        _run_and_wait(rp)
        assert rp._last_encoding is not None

        rp.enc_search_input.value = "U"
        rp._on_morphology_search()
        rp.motif_label.value = "dsax seed"
        rp._on_save_encoding_as_motif()

        motifs = R.list_motifs(app.conn)
        assert len(motifs) == 1
        assert set(motifs[0]["sax_string"]) <= set("DSU"), \
            "the motif seed must be stored in the alphabet the user saw"
        assert "morphology pattern: U" in (motifs[0]["notes"] or "")
    finally:
        _close_and_unlink(app, db_path)


# ── runner ───────────────────────────────────────────────────────────────

def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, failed = 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    print(f"\n{passed}/{len(fns)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
