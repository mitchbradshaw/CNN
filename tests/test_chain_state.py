"""
test_chain_state.py
=====================
Ticket 28 — the headless chain state model. `UI.analyse.chain_state.ChainState`
represents a chain under construction (steps, ordering, params, side-input
bindings) without a browser. It does not compute type compatibility itself —
it calls `Working.chain_validation.check_step_compatibility` (ticket 13) — and
it does not invent a second recipe serialiser: it converts to/from a recipe
via `Working.recipes.make_recipe`.

Run from the project root:
    python tests/test_chain_state.py
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

from Adapters.registry import discover_adapters
from UI.analyse.chain_state import ChainState, ChainStateError

ROOT_SIGNAL_KIND = "signal"

discover_adapters()


def _lowpass():
    return {"stage": "preprocessing", "algorithm": "lowpass", "params": {}}


def _bandpass():
    return {"stage": "preprocessing", "algorithm": "bandpass", "params": {}}


def _rupture():
    return {"stage": "detection", "algorithm": "rupture", "params": {}}


def _gramian_gasf():
    # declares output_kind="encoding" — feeding it into lowpass (which wants
    # "signal") is the invalid transition used below.
    return {"stage": "catalogue", "algorithm": "gramian_gasf", "params": {}}


# ── construction and the no-UI-import boundary ──────────────────────────────

def test_module_imports_no_ui_library():
    src_path = os.path.join(PROJECT_ROOT, "UI", "analyse", "chain_state.py")
    with open(src_path, "r", encoding="utf-8") as f:
        src = f.read()
    for banned in ("panel", "holoviews", "bokeh", "matplotlib"):
        assert banned not in src.lower(), f"chain_state.py must not mention {banned}"


def test_new_chain_is_empty_and_valid():
    chain = ChainState(recording_id=1)
    assert chain.steps == []
    assert chain.is_valid is True


# ── add / remove / reorder, each revalidating ───────────────────────────────

def test_add_step_appends_and_keeps_a_valid_chain_valid():
    chain = ChainState(recording_id=1)
    chain.add_step("preprocessing", "lowpass")
    assert [s["algorithm"] for s in chain.steps] == ["lowpass"]
    assert chain.is_valid is True

    chain.add_step("detection", "rupture")
    assert [s["algorithm"] for s in chain.steps] == ["lowpass", "rupture"]
    assert chain.is_valid is True


def test_add_step_that_breaks_type_compatibility_marks_the_chain_invalid():
    chain = ChainState(recording_id=1)
    chain.add_step("catalogue", "gramian_gasf")  # signal -> encoding, fine as step 1
    assert chain.is_valid is True
    chain.add_step("preprocessing", "lowpass")   # wants signal, gets encoding
    assert chain.is_valid is False
    assert "encoding" in chain.invalid_reason
    assert "signal" in chain.invalid_reason


def test_remove_step_revalidates_and_can_repair_an_invalid_chain():
    chain = ChainState(recording_id=1)
    chain.add_step("catalogue", "gramian_gasf")
    chain.add_step("preprocessing", "lowpass")
    assert chain.is_valid is False

    chain.remove_step(1)
    assert [s["algorithm"] for s in chain.steps] == ["gramian_gasf"]
    assert chain.is_valid is True


def test_reorder_revalidates_the_chain():
    chain = ChainState(recording_id=1)
    chain.add_step("preprocessing", "lowpass")
    chain.add_step("detection", "rupture")
    assert chain.is_valid is True

    # rupture (wants signal) before lowpass: root signal still feeds rupture
    # fine, but lowpass after rupture wants signal and gets 'intervals'.
    chain.reorder([1, 0])
    assert [s["algorithm"] for s in chain.steps] == ["rupture", "lowpass"]
    assert chain.is_valid is False
    assert "intervals" in chain.invalid_reason


def test_reorder_rejects_a_non_permutation():
    chain = ChainState(recording_id=1)
    chain.add_step("preprocessing", "lowpass")
    chain.add_step("detection", "rupture")
    try:
        chain.reorder([0, 0])
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── available_blocks: delegates to ticket 13, doesn't compute it itself ────

def test_available_blocks_on_an_empty_chain_matches_check_step_compatibility():
    from Working.chain_validation import check_step_compatibility
    from Adapters.registry import list_adapters

    chain = ChainState(recording_id=1)
    got = {block.name: (ok, reason) for block, ok, reason in chain.available_blocks()}
    for block in list_adapters():
        expected_ok, expected_reason = check_step_compatibility(ROOT_SIGNAL_KIND, block)
        assert got[block.name] == (expected_ok, expected_reason)


def test_available_blocks_reflects_the_current_tail_not_the_root():
    chain = ChainState(recording_id=1)
    chain.add_step("catalogue", "gramian_gasf")  # tail now produces 'encoding'
    by_name = {block.name: (ok, reason) for block, ok, reason in chain.available_blocks()}
    # lowpass wants 'signal' — no longer compatible once the tail is 'encoding'
    ok, reason = by_name["preprocessing.lowpass"]
    assert ok is False
    assert "encoding" in reason


# ── round trip through make_recipe ──────────────────────────────────────────

def test_round_trips_through_make_recipe_and_back():
    chain = ChainState(recording_id=7, span=(10, 20))
    chain.add_step("preprocessing", "lowpass", params={"cutoff_hz": 0.1})
    chain.add_step("detection", "rupture")

    recipe = chain.to_recipe()
    assert recipe["recording_id"] == 7
    assert recipe["span"] == [10, 20]
    assert [s["algorithm"] for s in recipe["steps"]] == ["lowpass", "rupture"]
    assert recipe["steps"][0]["params"]["cutoff_hz"] == 0.1

    rebuilt = ChainState.from_recipe(recipe)
    assert rebuilt.recording_id == 7
    assert rebuilt.span == (10, 20)
    assert [s["algorithm"] for s in rebuilt.steps] == ["lowpass", "rupture"]
    assert rebuilt.steps[0]["params"]["cutoff_hz"] == 0.1
    assert rebuilt.is_valid is True
    assert rebuilt.to_recipe() == recipe


def test_to_recipe_raises_on_an_invalid_chain_same_as_make_recipe():
    chain = ChainState(recording_id=1)
    chain.add_step("catalogue", "gramian_gasf")
    chain.add_step("preprocessing", "lowpass")
    try:
        chain.to_recipe()
        assert False, "expected ValueError"
    except ValueError as e:
        assert "encoding" in str(e)


# ── side-input bindings: removing a bound-to step rebinds or reports it ────

def test_removing_an_unrelated_step_rebinds_later_step_index_references():
    chain = ChainState(recording_id=1)
    chain.add_step("preprocessing", "lowpass")   # index 0 — bound-to step
    chain.add_step("preprocessing", "bandpass")  # index 1 — removed below
    chain.add_step(
        "detection", "rupture",
        side_inputs={"exemplar": {"source_kind": "earlier_step", "step_index": 0}},
    )  # index 2, bound to index 0

    chain.remove_step(1)  # removes bandpass, between the binding and its target

    assert [s["algorithm"] for s in chain.steps] == ["lowpass", "rupture"]
    binding = chain.steps[1]["side_inputs"]["exemplar"]
    assert binding == {"source_kind": "earlier_step", "step_index": 0}


def test_removing_the_bound_to_step_reports_the_break_by_default():
    chain = ChainState(recording_id=1)
    chain.add_step("preprocessing", "lowpass")  # index 0 — will be removed
    chain.add_step(
        "detection", "rupture",
        side_inputs={"exemplar": {"source_kind": "earlier_step", "step_index": 0}},
    )  # index 1, bound to index 0

    try:
        chain.remove_step(0)
        assert False, "expected ChainStateError"
    except ChainStateError as e:
        assert "exemplar" in str(e)

    # the chain is unchanged — no silent invalid state
    assert [s["algorithm"] for s in chain.steps] == ["lowpass", "rupture"]


def test_removing_the_bound_to_step_with_force_clears_the_binding():
    chain = ChainState(recording_id=1)
    chain.add_step("preprocessing", "lowpass")
    chain.add_step(
        "detection", "rupture",
        side_inputs={"exemplar": {"source_kind": "earlier_step", "step_index": 0}},
    )

    chain.remove_step(0, force=True)

    assert [s["algorithm"] for s in chain.steps] == ["rupture"]
    assert "exemplar" not in chain.steps[0]["side_inputs"]


def test_reorder_rebinds_earlier_step_index_references():
    chain = ChainState(recording_id=1)
    chain.add_step("preprocessing", "lowpass")   # index 0
    chain.add_step("preprocessing", "bandpass")  # index 1
    chain.add_step(
        "detection", "rupture",
        side_inputs={"exemplar": {"source_kind": "earlier_step", "step_index": 1}},
    )  # index 2, bound to index 1 (bandpass)

    chain.reorder([1, 0, 2])  # bandpass moves to index 0, lowpass to index 1

    assert [s["algorithm"] for s in chain.steps] == ["bandpass", "lowpass", "rupture"]
    binding = chain.steps[2]["side_inputs"]["exemplar"]
    assert binding["step_index"] == 0  # still points at bandpass


# ── runner ───────────────────────────────────────────────────────────────────

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
