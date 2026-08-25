"""
test_chain_validation.py
==========================
Ticket 13 — chain validation. `Working.chain_validation.check_step_compatibility`
is the single function that answers "can this output type feed this block,
and if not, why not" (PRD "Type checking"). Two callers use it and neither
inlines its own check: `Working.recipes.make_recipe` (reject at construction)
and `Working.execution.execute_recipe` (hard-fail before the first step runs).

Run from the project root:
    python tests/test_chain_validation.py
"""

import inspect
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Adapters.base import AdapterResult, AdapterSpec, SideInputSpec, TYPE_KINDS
from Adapters.registry import discover_adapters
from Working.chain_validation import check_step_compatibility, validate_chain
from Working.database.schema import init_db
from Working.database import queries as q
from Working.execution import execute_recipe
from Working.recipes import make_recipe

ROOT_SIGNAL_KIND = "signal"


def _block(name, input_kind=None, output_kind="signal", side_inputs=None):
    """A minimal, otherwise-valid AdapterSpec standing in for a registered
    block — not registered in the real registry, so tests can compose
    hypothetical typed chains without waiting on the twenty adapters being
    remapped (a later ticket)."""
    return AdapterSpec(
        name=name,
        display_name=name,
        stage="preprocessing",
        params=[],
        run=lambda x, t, fs, **params: AdapterResult(output_kind=output_kind),
        output_kind=output_kind,
        input_kind=input_kind,
        side_inputs=side_inputs or [],
    )


def _fresh_db_with_recording():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    q.insert_recording(conn, "fake.mat", 0, 1.0, 1000, 0, "nonexistent.npy")
    conn.close()
    return tf.name


# ── check_step_compatibility: the core function ─────────────────────────────

def test_root_signal_feeds_a_legacy_block_with_no_declared_input_kind():
    block = _block("preprocessing.stub", input_kind=None, output_kind="signal")
    ok, reason = check_step_compatibility(ROOT_SIGNAL_KIND, block)
    assert ok is True
    assert reason == ""


def test_root_signal_does_not_feed_a_block_expecting_a_typed_input():
    block = _block("detection.needs_windowset", input_kind="windowset")
    ok, reason = check_step_compatibility(ROOT_SIGNAL_KIND, block)
    assert ok is False
    # names both types, and says what's needed, not just "incompatible"
    assert "signal" in reason
    assert "windowset" in reason
    assert "needs_windowset" in reason


def test_a_typed_producer_feeds_a_block_declaring_the_matching_input_kind():
    block = _block("catalogue.needs_windowset", input_kind="windowset")
    ok, reason = check_step_compatibility("windowset", block)
    assert ok is True
    assert reason == ""


def test_every_mismatched_type_pair_is_rejected_with_a_teaching_reason():
    for expected in TYPE_KINDS:
        block = _block(f"stage.wants_{expected}", input_kind=expected)
        for producing in TYPE_KINDS:
            ok, reason = check_step_compatibility(producing, block)
            if producing == expected:
                assert ok is True, (producing, expected)
                assert reason == ""
            else:
                assert ok is False, (producing, expected)
                assert producing in reason
                assert expected in reason


def test_legacy_intervals_output_does_not_satisfy_any_typed_input():
    # 'intervals' is legacy-only output vocabulary (Adapters.base) — it has
    # no interchange-type counterpart, so nothing declaring a typed
    # input_kind can accept it.
    block = _block("catalogue.needs_spanset", input_kind="spanset")
    ok, reason = check_step_compatibility("intervals", block)
    assert ok is False
    assert "intervals" in reason
    assert "spanset" in reason


# ── the full compatibility matrix against every registered block ───────────

def test_full_matrix_of_seven_types_against_every_registered_block():
    discover_adapters()
    from Adapters.registry import list_adapters
    blocks = list_adapters()
    assert blocks, "expected the shipped adapters to be registered"

    for block in blocks:
        expected = block.input_kind or ROOT_SIGNAL_KIND
        for producing in TYPE_KINDS:
            ok, reason = check_step_compatibility(producing, block)
            if producing == expected:
                assert ok is True, (block.name, producing)
                assert reason == ""
            else:
                assert ok is False, (block.name, producing)
                assert producing in reason
                assert expected in reason
                assert block.name in reason


# ── the three worked chains validate end to end ─────────────────────────────

def test_cnn_chain_validates_end_to_end():
    # signal -> window set -> grouping -> model
    window = _block("preprocessing.window", input_kind=None, output_kind="windowset")
    group = _block("catalogue.group", input_kind="windowset", output_kind="grouping")
    train = _block("catalogue.train_cnn", input_kind="grouping", output_kind="model")
    ok, reason = validate_chain([window, group, train])
    assert ok is True, reason
    assert reason == ""


def test_seeded_search_chain_validates_end_to_end():
    # signal -> scores (with an exemplar side-input) -> span set
    score = _block(
        "detection.seeded_score", input_kind=None, output_kind="scores",
        side_inputs=[SideInputSpec(
            name="exemplar", type_kind="signal", sources=["library_exemplar"],
        )],
    )
    threshold = _block("detection.threshold", input_kind="scores", output_kind="spanset")
    ok, reason = validate_chain([score, threshold])
    assert ok is True, reason
    assert reason == ""


def test_banded_search_chain_validates_end_to_end():
    # signal -> bandpass -> scores -> span set, reusing the real, shipped
    # bandpass adapter (input_kind="signal" / output_kind="signal", the
    # ticket-06 type) alongside two typed blocks — the expand/contract
    # migration means the vocabularies must interoperate, not just each
    # validate alone.
    discover_adapters()
    from Adapters.registry import get_adapter
    bandpass = get_adapter("preprocessing.bandpass")
    score = _block("detection.banded_score", input_kind="signal", output_kind="scores")
    threshold = _block("detection.threshold", input_kind="scores", output_kind="spanset")
    ok, reason = validate_chain([bandpass, score, threshold])
    assert ok is True, reason
    assert reason == ""


def test_a_shuffled_worked_chain_is_rejected():
    window = _block("preprocessing.window", input_kind=None, output_kind="windowset")
    group = _block("catalogue.group", input_kind="windowset", output_kind="grouping")
    train = _block("catalogue.train_cnn", input_kind="grouping", output_kind="model")
    # group before window: group expects a windowset, but the root is signal
    ok, reason = validate_chain([group, window, train])
    assert ok is False
    assert "windowset" in reason


# ── make_recipe rejects an invalid chain at construction ───────────────────

def test_make_recipe_accepts_a_valid_chain_of_real_adapters():
    r = make_recipe(1, [
        {"stage": "preprocessing", "algorithm": "lowpass", "params": {}},
        {"stage": "detection", "algorithm": "rupture", "params": {}},
    ])
    assert r["steps"][0]["algorithm"] == "lowpass"


def test_make_recipe_rejects_an_invalid_chain_with_the_reason_string():
    # gramian_gasf declares output_kind="encoding"; lowpass declares
    # input_kind="signal" (expects "signal") — an encoding cannot feed it.
    try:
        make_recipe(1, [
            {"stage": "catalogue", "algorithm": "gramian_gasf", "params": {}},
            {"stage": "preprocessing", "algorithm": "lowpass", "params": {}},
        ])
        assert False, "expected ValueError"
    except ValueError as e:
        assert "encoding" in str(e)
        assert "signal" in str(e)


def test_make_recipe_still_builds_a_recipe_naming_an_unregistered_algorithm():
    # make_recipe has never validated that an algorithm name is registered
    # (that surfaces at execution, via Adapters.registry.get_adapter) — a
    # step this function can't resolve can't be type-checked either, and
    # must not become a new way for make_recipe to reject a recipe it
    # accepted before this ticket.
    r = make_recipe(1, [{"stage": "detection", "algorithm": "x"}])
    assert r["steps"][0]["params"] == {}


# ── execute_recipe hard-fails before the first step runs ───────────────────

def test_execute_recipe_rejects_an_invalid_chain_before_any_step_runs():
    db_path = _fresh_db_with_recording()
    calls = []
    try:
        recipe = {
            "recording_id": 1,
            "span": None,
            "steps": [
                {"stage": "catalogue", "algorithm": "gramian_gasf", "params": {}},
                {"stage": "preprocessing", "algorithm": "lowpass", "params": {}},
            ],
        }
        try:
            execute_recipe(
                recipe, db_path=db_path,
                on_progress=lambda *a: calls.append(a),
            )
            assert False, "expected ValueError"
        except ValueError as e:
            assert "encoding" in str(e)
            assert "signal" in str(e)
        # on_progress is only called once a step is about to run — an
        # empty list proves nothing ran before the chain was rejected.
        assert calls == []

        conn = init_db(db_path)
        runs = conn.execute("SELECT * FROM runs").fetchall()
        conn.close()
        assert len(runs) == 0, "no run row should be written for a chain rejected before execution"
    finally:
        os.unlink(db_path)


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
