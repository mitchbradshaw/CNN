"""
test_encoding_panels.py
=========================
Tests for Part 7 (2026-08): two confirmed bugs in
`UI.plots.build_encoding_panels` (the Run algorithm tab's four-panel
encoding view).

Part 1 — the Quantisation panel collapsed to a small fixed-size square on
pan/zoom, with mismatched axis labels ("x"/"y" instead of "time (s)"/
"amplitude") and a different toolbar from its siblings. Confirmed root
causes (see `build_encoding_panels`'s docstring for the full account):
    (a) that panel's Overlay mixed a `hv.Labels` element using HoloViews'
        default "x"/"y" kdims with sibling elements using "time"/
        "amplitude" — confirmed directly (a minimal repro) that this
        corrupts the OVERLAY's inferred axis label independent of which
        element "wins" the ambiguity.
    (b) that panel's per-frame `.opts()` call never included
        `responsive=True` (every OTHER panel's did, one way or another) —
        confirmed directly that this alone is sufficient to leave a
        DynamicMap's figure at Bokeh's plain fixed ~300px default forever,
        since nothing else ever corrects it on a later frame.
Per UI/README.md's own documented lesson (and this project's ribbon-pane
history): a test that calls `renderer.get_plot()` fresh after every event
only ever exercises first-frame behaviour and would have passed even with
this bug present. `test_all_four_panels_stay_aligned_across_pan_and_zoom`
creates the plot objects ONCE and `.refresh()`s those same objects across
a simulated pan/zoom/pan sequence, exactly like
`tests/test_ribbon_panes.py`.

Part 2 — with preprocessing active, the signal/PAA/quantisation panels'
y-axes spanned the RAW signal's scale (or wider) while the preprocessed
data occupied a tiny band near zero, rendering as a flat line. Confirmed
mechanism: panel y-ranges were computed ONCE, from the whole span, at
`build_encoding_panels` construction time — never per-frame from the
CURRENTLY VISIBLE slice — so zooming into a quiet stretch never rescaled
to it. Fixed via the same per-frame `compute_display_y_range` autoscale
the Viewer's main curve and the Before/After panels already use.

Part 2b (found during live-screenshot verification, not in the original
bug report) — a THIRD bug in the same family as Part 2: the PAA and
Quantisation panels' `Overlay`s each set `axiswise=True` at the Overlay
level only, not on their constituent leaf elements. Confirmed directly,
via a LIVE BROWSER's own Bokeh model state (`Bokeh.documents[...].
y_range.id`, read via Playwright against a real `pn.serve` server, not a
headless test) that this does NOT stop HoloViews' cross-plot "same
dimension name -> shared Range1d" linking, which reaches across
completely separate `pn.pane.HoloViews` panes in one live session, not
just within one `hv.Layout`. Two real instances, found and fixed in that
order: PAA and Quantisation shared a `Range1d` with EACH OTHER, and
separately `_decimated_curve` (the "staged span" preview / cross-channel
peek, sharing this module's "amplitude" vdim name) had no `axiswise` at
all and kept winning the shared object back with its own never-changing
raw-scale range. Fixed by adding `axiswise=True` to every leaf element
and to `_decimated_curve`. `test_leaf_level_axiswise_prevents_cross_panel_
range_sharing` below asserts the resulting invariant (no two panels share
a `Range1d` object) using the same `pn.pane.HoloViews` + real `bokeh.
Document` wiring `_show_encoding` uses — but, per that test's own
docstring, this does NOT actually reproduce the original failure; the bug
was only ever caught and confirmed live, in a real browser.

Pure UI.plots + Working.Detection.sax, no database/UI — runnable
standalone:
    python tests/test_encoding_panels.py
"""

import inspect
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import panel as pn
import holoviews as hv
from bokeh.document import Document
from bokeh.plotting import figure as _bokeh_figure_cls
pn.extension()
hv.extension("bokeh")

from Working.config import (
    ENCODING_FRAME_MIN_BORDER_LEFT, ENCODING_PAA_HEIGHT, ENCODING_QUANT_HEIGHT,
    ENCODING_SIGNAL_HEIGHT, ENCODING_STRIP_HEIGHT,
)
from Working.Detection.sax.csax_python.csax import csax
from Adapters.registry import discover_adapters, get_adapter
from UI.plots import build_encoding_panels

discover_adapters()

_rng = np.random.default_rng(1)
BIMODAL = np.concatenate([_rng.normal(0, 1, 3000), _rng.normal(5, 2, 3000)])
T_BIMODAL = np.arange(len(BIMODAL)) / 1.0


def _build(x, t, dim_ratio=1 / 20, seed=1, **kwargs):
    np.random.seed(seed)
    symbols, details = csax(x, len(x), dim_ratio, normalize=True, return_details=True)
    dmaps = build_encoding_panels(x, t, symbols, details, **kwargs)
    return dmaps


def _get_plots(dmaps):
    dmap_signal, dmap_paa, dmap_quant, dmap_strip, range_stream = dmaps
    renderer = hv.renderer("bokeh")
    return (renderer.get_plot(dmap_signal), renderer.get_plot(dmap_paa),
            renderer.get_plot(dmap_quant), renderer.get_plot(dmap_strip), range_stream)


def _report(p):
    p.refresh()
    fig = p.state
    return {
        "width": fig.width, "sizing_mode": fig.sizing_mode, "height": fig.height,
        "xr": (fig.x_range.start, fig.x_range.end),
        "xlabel": fig.xaxis[0].axis_label if fig.xaxis else None,
        "min_border_left": fig.min_border_left,
        "toolbar_loc": fig.toolbar_location,
    }


# ── Part 1: sizing/labelling/alignment survive pan and zoom ────────────────

def test_all_four_panels_stay_aligned_across_pan_and_zoom():
    """The important one -- see module docstring. Plot objects created
    ONCE, `.refresh()`d across a simulated pan/zoom/pan sequence; a fresh
    `get_plot()` per step would silently pass even with the bug present."""
    p1, p2, p3, p4, range_stream = _get_plots(_build(BIMODAL, T_BIMODAL))

    for x_range in [(0.0, 6000.0), (2000.0, 5000.0), (2000.0, 2500.0), (0.0, 6000.0), (3000.0, 3200.0)]:
        range_stream.event(x_range=x_range)
        reports = [_report(p) for p in (p1, p2, p3, p4)]

        xrs = [r["xr"] for r in reports]
        assert len(set(xrs)) == 1, f"x_range={x_range}: panels disagree on rendered x_range: {xrs}"
        for i, r in enumerate(reports):
            assert r["sizing_mode"] == "stretch_width", (
                f"x_range={x_range}: panel {i} is not full-width "
                f"(sizing_mode={r['sizing_mode']}, width={r['width']}) -- the collapsed-square bug"
            )
            assert r["width"] is None, f"x_range={x_range}: panel {i} has a fixed width {r['width']}"
            assert r["xlabel"] == "time (s)", (
                f"x_range={x_range}: panel {i} xlabel={r['xlabel']!r}, expected 'time (s)'"
            )
        min_borders = [r["min_border_left"] for r in reports]
        assert len(set(min_borders)) == 1, (
            f"x_range={x_range}: panels have different min_border_left, would misalign: {min_borders}"
        )
        assert min_borders[0] == ENCODING_FRAME_MIN_BORDER_LEFT

    # Only the top panel keeps a toolbar (Part 1 item 6).
    final = [_report(p) for p in (p1, p2, p3, p4)]
    assert final[0]["toolbar_loc"] is not None
    assert all(r["toolbar_loc"] is None for r in final[1:])

    # Each panel's configured height is exactly what config.py says, and
    # never changes across frames.
    assert final[0]["height"] == ENCODING_SIGNAL_HEIGHT
    assert final[1]["height"] == ENCODING_PAA_HEIGHT
    assert final[2]["height"] == ENCODING_QUANT_HEIGHT
    assert final[3]["height"] == ENCODING_STRIP_HEIGHT


def test_quantisation_panel_kdims_are_not_default_x_y():
    """The direct symptom check: the Quantisation panel's element kdims
    must never be HoloViews' bare default "x"/"y" (the confirmed tell —
    see module docstring)."""
    # hv.HSpan/HLine are annotation-style elements that ALWAYS use generic
    # "x"/"y" internally by HoloViews' own design (an HSpan has no x
    # extent at all) -- confirmed directly (a minimal repro) that mixing
    # THOSE with a properly-dimensioned Curve does not corrupt an
    # Overlay's axis label the way a data-bearing element with mismatched
    # kdims does. Only the DATA-bearing element types are checked here.
    _, _, dmap_quant, _, range_stream = _build(BIMODAL, T_BIMODAL)
    range_stream.event(x_range=(1000.0, 4000.0))
    element = dmap_quant[dmap_quant.last_key] if dmap_quant.last_key else dmap_quant[()]
    checked = 0
    for el in element.traverse(lambda x: x):
        if not isinstance(el, (hv.Curve, hv.Labels, hv.Rectangles, hv.Segments)):
            continue
        checked += 1
        kdims = [d.name for d in getattr(el, "kdims", [])]
        assert "x" not in kdims and "y" not in kdims, f"{type(el).__name__} kept default kdims: {kdims}"
    assert checked > 0, "no data-bearing element found to check"


# ── Part 2: per-frame y-autoscale, especially with preprocessing ───────────

def test_signal_panel_autoscales_to_preprocessed_not_raw_range():
    """`max - min` (a "span") is translation-invariant, so a constant DC
    offset alone would NOT inflate it -- the actual bug symptom was the
    rendered axis BOUNDS sitting near the raw signal's offset (e.g. "0 to
    -0.65") rather than near the preprocessed data's own numbers (near
    0), not a wider spread per se. This checks the bounds themselves."""
    rng = np.random.default_rng(2)
    n = 6000
    t = np.arange(n) / 1.0
    dc_offset = -0.6
    raw = dc_offset + 0.02 * np.sin(t / 17) + rng.normal(0, 0.005, n)  # big DC offset, small feature

    detrend_spec = get_adapter("preprocessing.detrend")
    dparams = detrend_spec.validate_params({"mode": "rolling_mean", "window_s": 600})
    dresult = detrend_spec.run(raw, t, 1.0, **dparams)

    sax_spec = get_adapter("detection.sax_csax")
    sparams = sax_spec.validate_params({"segment_mode": "samples_per_symbol", "samples_per_symbol": 20})
    np.random.seed(2)
    sresult = sax_spec.run(dresult.value.x, t, 1.0, **sparams)

    dmap_signal, dmap_paa, dmap_quant, _dmap_strip, range_stream = build_encoding_panels(
        sresult.meta["encoded_x"], sresult.meta["encoded_t"],
        sresult.value.values, sresult.meta["details"],
    )
    renderer = hv.renderer("bokeh")
    p1 = renderer.get_plot(dmap_signal)
    p1.refresh()
    rendered_mid = (p1.state.y_range.start + p1.state.y_range.end) / 2.0

    preprocessed_mid = (dresult.value.x.min() + dresult.value.x.max()) / 2.0

    assert abs(rendered_mid - preprocessed_mid) < 0.05, (
        f"rendered axis midpoint {rendered_mid:.4g} is not close to the "
        f"preprocessed data's own midpoint {preprocessed_mid:.4g}"
    )
    assert abs(rendered_mid - dc_offset) > 0.3, (
        f"rendered axis midpoint {rendered_mid:.4g} is suspiciously close to the "
        f"raw signal's DC offset {dc_offset} -- looks like the flat-line bug"
    )


def test_zooming_into_a_quiet_stretch_rescales_the_y_axis():
    """The exact "flat line" mechanism: a fixed, whole-span y-range never
    rescales on zoom. After the fix, a narrower view with a smaller local
    range must render a visibly TIGHTER y-axis, not the same one."""
    rng = np.random.default_rng(3)
    n = 6000
    t = np.arange(n) / 1.0
    # A signal with one loud spike early on and otherwise near-flat --
    # zooming away from the spike must tighten the range a lot.
    x = np.full(n, 0.0)
    x[100:110] = 5.0
    x += rng.normal(0, 0.01, n)

    dmap_signal, _dp, _dq, _ds, range_stream = _build(x, t, dim_ratio=1 / 20, seed=3)
    renderer = hv.renderer("bokeh")
    p1 = renderer.get_plot(dmap_signal)

    range_stream.event(x_range=(0.0, 6000.0))
    p1.refresh()
    whole_span = p1.state.y_range.end - p1.state.y_range.start

    range_stream.event(x_range=(3000.0, 3500.0))  # nowhere near the spike
    p1.refresh()
    quiet_span = p1.state.y_range.end - p1.state.y_range.start

    assert quiet_span < whole_span / 5, (
        f"zooming into a quiet stretch should tighten the y-axis a lot, "
        f"got whole={whole_span:.4g} quiet={quiet_span:.4g}"
    )


def test_shared_mode_matches_panels_auto_mode_may_differ():
    rng = np.random.default_rng(4)
    n = 6000
    t = np.arange(n) / 1.0
    # PAA averaging smooths away brief spikes -- the raw signal panel's
    # range should end up visibly wider than the PAA/quantisation panel's
    # in "auto" mode, and identical in "shared" mode.
    x = rng.normal(0, 0.05, n)
    x[::37] += 3.0  # frequent brief spikes, averaged away by a 20-sample PAA window

    renderer = hv.renderer("bokeh")

    dmaps_auto = _build(x, t, dim_ratio=1 / 20, seed=4, y_mode="auto")
    p1a, _p2a, p3a, _p4a, rsa = _get_plots(dmaps_auto)
    rsa.event(x_range=(0.0, 6000.0))
    p1a.refresh(); p3a.refresh()
    signal_range_auto = (p1a.state.y_range.start, p1a.state.y_range.end)
    quant_range_auto = (p3a.state.y_range.start, p3a.state.y_range.end)

    dmaps_shared = _build(x, t, dim_ratio=1 / 20, seed=4, y_mode="shared")
    p1s, _p2s, p3s, _p4s, rss = _get_plots(dmaps_shared)
    rss.event(x_range=(0.0, 6000.0))
    p1s.refresh(); p3s.refresh()
    signal_range_shared = (p1s.state.y_range.start, p1s.state.y_range.end)
    quant_range_shared = (p3s.state.y_range.start, p3s.state.y_range.end)

    assert signal_range_auto != quant_range_auto, (
        "auto mode should let the signal and quantisation panels differ "
        f"when their own data genuinely differs: {signal_range_auto} vs {quant_range_auto}"
    )
    assert abs(signal_range_shared[0] - quant_range_shared[0]) < 1e-9
    assert abs(signal_range_shared[1] - quant_range_shared[1]) < 1e-9


# ── Part 2b: leaf-level axiswise prevents cross-panel Range1d sharing ──────

def _find_figures(bokeh_model):
    return list(bokeh_model.select({"type": _bokeh_figure_cls}))


def test_leaf_level_axiswise_prevents_cross_panel_range_sharing():
    """See module docstring, Part 2b. Wires panes the same way `UI/
    run_panel.py`'s `_show_encoding` does -- persistent `pn.pane.
    HoloViews` panes, all attached to ONE real `bokeh.Document` -- and
    asserts the invariant the real bug violated: independent panels never
    share a literal `Range1d` object.

    Honesty note: this does NOT reproduce the original failure. The real
    bug was found and confirmed entirely through a live browser session
    (`Bokeh.documents[...].y_range.id`, read via Playwright against a real
    `pn.serve` server) -- with the exact same leaf-level `axiswise=True`
    calls reverted, this Document-based harness still renders every panel
    with its own distinct `Range1d` and correct values, in every ordering
    and pane combination tried. Whatever HoloViews/Bokeh machinery
    actually links ranges across panes in a live session isn't triggered
    by `Document()` + `pane.get_root(doc)` alone, so this test cannot
    currently fail the way the real bug did. It's kept anyway because the
    invariant it checks is correct and worth asserting, but a future
    regression in this exact class of bug would most reliably resurface
    through a live-browser check, not this test -- see
    `UI/README.md`'s "y-range linking is document-wide" note.
    """
    from UI.plots import _decimated_curve

    rng = np.random.default_rng(5)
    n = 6000
    t = np.arange(n) / 1.0
    x = rng.normal(0, 0.05, n)
    x[::37] += 3.0  # PAA-averaging smooths this away -- panels should end up with different ranges

    dmap_signal, dmap_paa, dmap_quant, dmap_strip, range_stream = _build(x, t, dim_ratio=1 / 20, seed=5)
    unrelated_curve = _decimated_curve(x[:100], t[:100], 100, "#999999", 100)  # a totally different range

    panes = [pn.pane.HoloViews(sizing_mode="stretch_width") for _ in range(5)]
    doc = Document()
    roots = [p.get_root(doc) for p in panes]

    panes[0].object = dmap_signal
    panes[1].object = dmap_paa
    panes[2].object = dmap_quant
    panes[3].object = dmap_strip
    panes[4].object = unrelated_curve

    range_stream.event(x_range=(0.0, 6000.0))

    figs = {name: _find_figures(root)[0] for name, root in
            zip(["signal", "paa", "quant", "strip", "unrelated"], roots)}

    # The PAA and Quantisation panels must not share a literal Range1d
    # object with each other, or with the unrelated "amplitude"-named
    # curve -- object identity, not just value equality, since a shared
    # object is exactly what let one panel's hook silently clobber
    # another's on every subsequent refresh.
    ids = {name: fig.y_range.id for name, fig in figs.items() if name != "strip"}
    assert len(set(ids.values())) == len(ids), (
        f"panels are sharing a Range1d object (would let one panel's y-range "
        f"silently clobber another's on refresh): {ids}"
    )

    # And the values themselves must reflect each panel's OWN data, not a
    # merged/unioned range dominated by the unrelated curve or by a sibling.
    paa_range = (figs["paa"].y_range.start, figs["paa"].y_range.end)
    quant_range = (figs["quant"].y_range.start, figs["quant"].y_range.end)
    assert paa_range != quant_range, (
        f"PAA and Quantisation panels rendered identical y-ranges "
        f"({paa_range}) -- looks like a shared Range1d, not independent data"
    )


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
