"""
test_value_rendering.py
=========================
Tests for T56: `UI.plots.render_value` — the single entry point for
turning a value of any of the seven interchange types (Signal, Encoding,
Scores, SpanSet, WindowSet, Grouping, Model) into a renderable HoloViews
element.

The rule this ticket exists to enforce: nothing downstream may switch on a
value's type locally. Every plot-centric surface — filmstrip, focus mode,
block-card preview — goes through this one function, so a value whose type
the author happened not to test must still render instead of silently
producing a blank pane (the failure mode this codebase has shipped twice).

Headless and database-free: constructs typed values directly and asserts
the returned HoloViews object is renderable. Run from the project root:
    python tests/test_value_rendering.py
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import holoviews as hv

hv.extension("bokeh")

from Working.types import Signal, Encoding, Scores, SpanSet, WindowSet, Grouping, Model
from UI.plots import render_value


def _rng():
    return np.random.default_rng(0)


def _signal_value():
    return Signal(x=_rng().normal(0, 1, 500), fs=1.0)


def _scores_value():
    return Scores(values=_rng().normal(0, 1, 500), fs=1.0)


def _encoding_value():
    """A symbolic Encoding plus the metadata the strip renderer needs —
    built through the real cSAX path so the details dict is genuine."""
    from Working.Detection.sax.csax_python.csax import csax
    x = np.concatenate([_rng().normal(0, 1, 3000), _rng().normal(5, 2, 3000)])
    t = np.arange(len(x)) / 1.0
    symbols, details = csax(x, len(x), 0.05, normalize=True, return_details=True)
    value = Encoding(values=symbols, kind="symbolic")
    meta = {"encoded_x": x, "encoded_t": t, "details": details}
    return value, meta


def _spanset_value():
    return SpanSet(starts=(0, 5, 10), ends=(3, 8, 12))


def _windowset_value():
    return WindowSet(starts=np.array([0, 100, 200]), length=50, fs=1.0)


def _grouping_value():
    return Grouping(labels=np.array([0, 0, 1, 1, 2]))


def _model_value():
    return Model(path="model.joblib")


# ── all seven types ─────────────────────────────────────────────────────────

def test_all_seven_types_return_renderable_elements():
    """Every interchange type must return a renderable HoloViews object,
    never None — a pane that renders nothing does not raise, it is blank."""
    cases = [
        ("signal", _signal_value(), {}),
        ("scores", _scores_value(), {}),
        ("encoding", *_encoding_value()),
        ("spanset", _spanset_value(), {}),
        ("windowset", _windowset_value(), {}),
        ("grouping", _grouping_value(), {}),
        ("model", _model_value(), {}),
    ]
    for kind, value, meta in cases:
        result = render_value(kind, value, meta)
        assert result is not None, f"{kind} returned None"
        assert isinstance(result, hv.Dimensioned), (
            f"{kind} returned {type(result).__name__}, not a renderable "
            "HoloViews object"
        )
        # A DynamicMap that raises inside its callback renders as a
        # silently blank pane — evaluating a frame catches that here.
        if isinstance(result, hv.DynamicMap):
            frame = result[()]
            assert isinstance(frame, hv.Dimensioned), (
                f"{kind} DynamicMap produced {type(frame).__name__}, not a "
                "renderable frame"
            )


def test_degenerate_values_still_render():
    """A degenerate value of each type (empty SpanSet, one-window
    WindowSet, empty signal, ...) still returns something renderable
    rather than None."""
    cases = [
        ("signal", Signal(x=np.array([]), fs=1.0), {}),
        ("scores", Scores(values=np.array([]), fs=1.0), {}),
        ("encoding", Encoding(values=np.array([], dtype=int), kind="symbolic"), {}),
        ("spanset", SpanSet(starts=(), ends=()), {}),
        ("windowset", WindowSet(starts=np.array([0]), length=10, fs=1.0), {}),
        ("grouping", Grouping(labels=np.array([], dtype=int)), {}),
        ("model", Model(path=""), {}),
    ]
    for kind, value, meta in cases:
        result = render_value(kind, value, meta)
        assert result is not None, f"degenerate {kind} returned None"
        assert isinstance(result, hv.Dimensioned), (
            f"degenerate {kind} returned {type(result).__name__}, not a "
            "renderable HoloViews object"
        )


def test_unknown_type_raises_naming_type():
    """An unknown type name raises, and the message names the value it was
    given so a misspelled type is diagnosable."""
    import pytest
    with pytest.raises(ValueError) as excinfo:
        render_value("bogus_type", object())
    assert "bogus_type" in str(excinfo.value)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
