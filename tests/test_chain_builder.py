"""
test_chain_builder.py
=======================
Ticket 29 — the chain builder surface (`UI.workspaces.analyse.builder.
ChainBuilder`). It renders `UI.analyse.chain_state.ChainState` (ticket 28)
as an ordered staged list: add a step, reorder, delete, each revalidating
immediately through `Working.chain_validation` (ticket 13). It does not
compute compatibility itself, and it does not invent a second chain model.

Most of the behaviour below is exercised against a lightweight fake app --
`ChainBuilder` only ever reads `app._recording_id` off it, nothing else, so
these tests need no database and no channel and run everywhere. The two
tests that check mounting into the real Analyse workspace build a real
`ViewerApp` and are gated on the real channel .npy, same convention as
tests/test_workspaces.py.

Run from the project root:
    python tests/test_chain_builder.py
"""

import inspect
import os
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import panel as pn
pn.extension()

from Adapters.registry import discover_adapters, get_adapter, list_adapters

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600

discover_adapters()


class _FakeApp:
    """The minimal shape `ChainBuilder` needs off `app` -- nothing but the
    current recording id, the same "read the app's live state, don't
    duplicate it" contract `RunPanel` uses (see UI/analyse/staged_chain.py)."""

    def __init__(self, recording_id=1):
        self._recording_id = recording_id


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_app():
    import tempfile as _tempfile
    from Working.database.schema import init_db
    from Working.database import queries as q
    from UI.viewer import ViewerApp
    from tests._session_isolation import scratch_session_file

    tf = _tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    q.insert_recording(conn, "UNITTEST_chain_builder.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    conn.close()
    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=tf.name)
    app._test_session_cm = session_cm
    app.layout()
    return app, tf.name


def _close_and_unlink(app, db_path):
    app._test_session_cm.__exit__(None, None, None)
    app.conn.close()
    os.unlink(db_path)


def _tab_names(tabs):
    return list(tabs._names)


def _pane_named(tabs, name):
    names = _tab_names(tabs)
    assert name in names, f"no tab named {name!r}; got {names}"
    return tabs.objects[names.index(name)]


def _tabs_inside(pane):
    """The first `pn.Tabs` anywhere inside `pane` (ticket 34: Analyse is a
    Row(run-history sidebar, Tabs)), or None."""
    if isinstance(pane, pn.Tabs):
        return pane
    for obj in getattr(pane, "objects", ()):
        found = _tabs_inside(obj)
        if found is not None:
            return found
    return None


def _add_row(builder, adapter_name):
    """The (button, reason_pane) row rendered for one adapter's `Add`
    control, found by the adapter's registry name -- order in
    `add_column.objects` matches `list_adapters()`, which is sorted."""
    for block, row in zip(list_adapters(), builder.add_column.objects):
        if block.name == adapter_name:
            return row
    raise AssertionError(f"no add-row for {adapter_name!r}")


# ── construction: a blank chain, every block listed ─────────────────────────

def test_construction_builds_a_non_none_layout_listing_every_block():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    layout = builder.layout()
    assert layout is not None
    assert builder.steps_column is not None
    assert builder.add_column is not None
    assert len(builder.add_column.objects) == len(list_adapters()), (
        "every registered block must be listed, incompatible or not"
    )
    # An empty chain says so rather than rendering nothing.
    assert len(builder.steps_column.objects) >= 1


def test_a_fresh_chain_has_no_incompatible_blocks():
    """Every shipped block that takes the root signal is offered in a fresh
    chain — the legacy blocks take it implicitly (`input_kind=None`) and the
    ticket-06/08 typed blocks declare `input_kind="signal"`. A block
    declaring any *other* input kind genuinely cannot be fed yet, and is
    offered disabled with the kind it wants named inline. That is the type
    checker working, not a regression.

    Derived from the registry rather than from a list of block names. This
    test used to name the two typed blocks it expected to be disabled and
    assert every other button was enabled, which meant each new typed block
    the backlog added broke it — it had stopped testing the builder and
    started tracking the backlog.
    """
    from UI.workspaces.analyse.builder import ChainBuilder
    from Working.chain_validation import ROOT_SIGNAL_KIND

    builder = ChainBuilder(_FakeApp())
    blocks = [block for block, _ok, _reason in builder.chain.available_blocks()]
    rows = builder.add_column.objects
    assert len(rows) == len(blocks)

    typed = 0
    for block, row in zip(blocks, rows):
        button, reason = row[0], row[1]
        expected = block.input_kind or ROOT_SIGNAL_KIND
        if expected == ROOT_SIGNAL_KIND:
            assert button.disabled is False, block.name
        else:
            typed += 1
            assert button.disabled is True, block.name
            assert expected in reason.object, block.name

    # Both branches must actually be exercised, or the loop above would pass
    # just as happily against a registry that had lost its typed blocks.
    assert typed >= 2, "expected at least two typed blocks a fresh chain cannot feed"


# ── add: appends, revalidates, re-renders ────────────────────────────────────

def test_add_step_appends_to_the_staged_list_and_stays_valid():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))

    assert [s["algorithm"] for s in builder.chain.steps] == ["lowpass"]
    assert builder.chain.is_valid is True
    assert len(builder.steps_column.objects) == 1
    assert "invalid" not in builder.status.object.lower()


def test_add_step_that_breaks_compatibility_is_reflected_in_status():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("catalogue.gramian_gasf"))  # signal -> encoding
    builder._add_step(get_adapter("preprocessing.lowpass"))   # wants signal

    assert builder.chain.is_valid is False
    assert "encoding" in builder.status.object
    assert "signal" in builder.status.object


# ── the add-step control: incompatible blocks disabled, reason inline ──────

def test_incompatible_block_is_disabled_with_reason_not_filtered_out():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("catalogue.gramian_gasf"))  # tail now 'encoding'

    # Still every block, not a filtered-down list.
    assert len(builder.add_column.objects) == len(list_adapters())

    row = _add_row(builder, "preprocessing.lowpass")
    button, reason_pane = row[0], row[1]
    assert button.disabled is True
    assert "encoding" in reason_pane.object
    assert "signal" in reason_pane.object

    # Every disabled row's reason matches `check_step_compatibility` exactly
    # -- this surface doesn't invent its own wording.
    from Working.chain_validation import check_step_compatibility
    tail_kind = get_adapter("catalogue.gramian_gasf").output_kind
    for block, row in zip(list_adapters(), builder.add_column.objects):
        expected_ok, expected_reason = check_step_compatibility(tail_kind, block)
        assert row[0].disabled is not expected_ok
        assert row[1].object == expected_reason


# ── reorder ──────────────────────────────────────────────────────────────────

def test_move_step_reorders_and_revalidates_immediately():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))
    builder._add_step(get_adapter("detection.rupture"))
    assert builder.chain.is_valid is True

    # rupture (produces 'spanset') before lowpass (wants 'signal') is invalid.
    builder._move_step(1, -1)

    assert [s["algorithm"] for s in builder.chain.steps] == ["rupture", "lowpass"]
    assert builder.chain.is_valid is False
    assert "spanset" in builder.status.object
    assert len(builder.steps_column.objects) == 2


def test_move_step_at_the_top_is_a_no_op():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))
    builder._add_step(get_adapter("detection.rupture"))

    builder._move_step(0, -1)  # already first
    assert [s["algorithm"] for s in builder.chain.steps] == ["lowpass", "rupture"]


# ── delete ───────────────────────────────────────────────────────────────────

def test_delete_step_removes_it_and_can_repair_an_invalid_chain():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("catalogue.gramian_gasf"))
    builder._add_step(get_adapter("preprocessing.lowpass"))
    assert builder.chain.is_valid is False

    builder._delete_step(1)

    assert [s["algorithm"] for s in builder.chain.steps] == ["gramian_gasf"]
    assert builder.chain.is_valid is True
    assert len(builder.steps_column.objects) == 1
    assert "invalid" not in builder.status.object.lower()


def test_delete_the_last_step_shows_the_empty_state_again():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))
    builder._delete_step(0)

    assert builder.chain.steps == []
    # Same "says so rather than rendering nothing" placeholder as construction.
    assert len(builder.steps_column.objects) >= 1


# ── mounting: reaches the Analyse workspace, survives a registry reset ─────

def test_chain_builder_survives_a_workspace_registry_reset():
    """Not a stray registration a test-isolation `reset()` elsewhere in the
    suite could wipe out -- it is seeded every time, the same as the
    pre-split surfaces (see UI/workspaces/builtins.py)."""
    from UI import workspaces

    workspaces.reset()
    try:
        analyse = [label for label, _ in workspaces.sections("Analyse")]
        assert "Chain builder" in analyse
    finally:
        workspaces.reset()


def test_chain_builder_mounts_into_the_analyse_workspace_as_a_real_pane():
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        analyse = _pane_named(app.tabs, "Analyse")
        # Ticket 34: Analyse is a Row(run-history sidebar, section Tabs).
        tabs = _tabs_inside(analyse)
        assert tabs is not None, \
            "Analyse should still group its sections in sub-tabs"
        assert "Chain builder" in _tab_names(tabs)
        pane = _pane_named(tabs, "Chain builder")
        assert pane is not None, "Chain builder renders as None -- the blank-pane failure"
    finally:
        _close_and_unlink(app, db_path)


# ── runner ───────────────────────────────────────────────────────────────────

def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, skipped, failed = 0, 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except pytest.skip.Exception as e:
            print(f"[SKIP] {fn.__name__}: {e}")
            skipped += 1
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    tally = f"{passed}/{len(fns)} passed"
    if skipped:
        tally += f", {skipped} skipped (real channel data absent)"
    print(f"\n{tally}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
