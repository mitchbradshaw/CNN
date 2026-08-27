"""
test_chain_builder.py
=======================
Ticket 29 / 57 — the chain builder surface (`UI.workspaces.analyse.builder.
ChainBuilder`). It renders `UI.analyse.chain_state.ChainState` (ticket 28)
as a horizontally scrolling block canvas in execution order: each card shows
its algorithm and its input/output types, with controls to reorder and delete,
and each edit revalidates immediately through `Working.chain_validation`
(ticket 13). It does not compute compatibility itself, and it does not invent
a second chain model.

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


def _texts(pane):
    """Every Markdown string inside a pane, recursively."""
    if isinstance(pane, pn.pane.Markdown):
        return [str(pane.object)]
    texts = []
    for obj in getattr(pane, "objects", ()):
        texts.extend(_texts(obj))
    return texts


def _card_text(card):
    return " ".join(_texts(card))


def _card_buttons(card):
    """The (up, down, delete) button row rendered on a card."""
    for obj in card.objects:
        if isinstance(obj, pn.Row):
            return obj.objects
    raise AssertionError("card has no button row")


def _plus_buttons(builder):
    """Every `+` insert button on the canvas, as `(insert_index, button)`.

    The insertion index is the position the `+` would insert at — the number
    of cards already drawn to its left. A `+` between card 0 and card 1
    inserts at index 1; the trailing `+` after card N-1 inserts at index N.
    The empty chain offers a single `+` at index 0.
    """
    out = []
    cards_seen = 0
    for obj in builder.steps_row.objects:
        if obj in builder.cards:
            cards_seen += 1
        elif isinstance(obj, pn.widgets.Button) and obj.name == "+":
            out.append((cards_seen, obj))
    return out


# ── construction: a blank chain, every block listed ─────────────────────────

def test_construction_builds_a_non_none_layout_listing_every_block():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    layout = builder.layout()
    assert layout is not None
    assert builder.steps_row is not None
    assert builder.add_column is not None
    assert isinstance(builder.steps_row, pn.Row)
    assert builder.steps_row.scroll is True, \
        "the block canvas must scroll horizontally rather than wrap"
    # No + has been clicked yet, so no picker is open; every block is listed
    # only once the + opens the picker.
    assert builder.add_column.objects == []
    # An empty chain says so rather than rendering nothing, and offers a
    # single + at the only insertion position there is.
    assert len(builder.steps_row.objects) >= 1
    assert [pos for pos, _ in _plus_buttons(builder)] == [0]
    assert builder.cards == []


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
    # The empty chain's only + (position 0) opens the picker.
    builder._open_picker(0)
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
    assert len(builder.cards) == 1
    # A single card is followed by the trailing + (insert at the end).
    assert len(builder.steps_row.objects) == 2
    assert [pos for pos, _ in _plus_buttons(builder)] == [1]
    assert "lowpass" in _card_text(builder.cards[0])
    assert "signal" in _card_text(builder.cards[0])
    assert "invalid" not in builder.status.object.lower()


def test_add_step_that_breaks_compatibility_is_reflected_in_status():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("catalogue.gramian_gasf"))  # signal -> encoding
    builder._add_step(get_adapter("preprocessing.lowpass"))   # wants signal

    assert builder.chain.is_valid is False
    status = builder.status.object
    assert "encoding" in status
    assert "signal" in status
    assert "step 1" in status
    assert "step 2" in status
    assert "between" in status


# ── the add-step control: incompatible blocks disabled, reason inline ──────

def test_incompatible_block_is_disabled_with_reason_not_filtered_out():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("catalogue.gramian_gasf"))  # tail now 'encoding'

    # Open the trailing + (insert at the end) to see the picker.
    builder._open_picker(1)

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
    assert len(builder.cards) == 2
    assert len(builder.connectors) == 1
    assert "rupture" in _card_text(builder.cards[0])
    assert "lowpass" in _card_text(builder.cards[1])


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
    assert len(builder.cards) == 1
    assert "gramian_gasf" in _card_text(builder.cards[0])
    assert "invalid" not in builder.status.object.lower()


def test_delete_the_last_step_shows_the_empty_state_again():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))
    builder._delete_step(0)

    assert builder.chain.steps == []
    assert builder.cards == []
    # Same "says so rather than rendering nothing" placeholder as construction.
    assert len(builder.steps_row.objects) >= 1


# ── the block canvas: horizontal, ordered, scrollable, non-wrapping ─────

def test_canvas_is_a_horizontal_scrolling_row_with_connectors_between_cards():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))
    builder._add_step(get_adapter("detection.rupture"))

    assert isinstance(builder.steps_row, pn.Row)
    assert builder.steps_row.scroll is True, \
        "the row must scroll horizontally, not wrap to a second row"
    assert builder.steps_row.sizing_mode == "stretch_width"

    assert len(builder.cards) == 2
    assert len(builder.connectors) == 1

    # Execution order left to right: card, +, connector, card, +.
    objects = builder.steps_row.objects
    assert len(objects) == 5
    assert objects[0] is builder.cards[0]
    assert objects[2] is builder.connectors[0]
    assert objects[3] is builder.cards[1]
    assert [pos for pos, _ in _plus_buttons(builder)] == [1, 2]

    first = _card_text(builder.cards[0])
    second = _card_text(builder.cards[1])
    assert "lowpass" in first
    assert "signal" in first
    assert "rupture" in second
    assert "spanset" in second


def test_card_controls_reorder_and_delete_the_model():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))
    builder._add_step(get_adapter("detection.rupture"))

    up = _card_buttons(builder.cards[1])[0]
    assert up.disabled is False
    up.clicks = up.clicks + 1
    assert [s["algorithm"] for s in builder.chain.steps] == ["rupture", "lowpass"]
    assert "rupture" in _card_text(builder.cards[0])

    delete = _card_buttons(builder.cards[0])[2]
    delete.clicks = delete.clicks + 1
    assert [s["algorithm"] for s in builder.chain.steps] == ["lowpass"]
    assert len(builder.cards) == 1


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


# ── T59: a block's parameters are edited on its card ─────────────────────────

class _FakeAppWithDb:
    """The shape `ChainBuilder` needs off `app` when a card must reach the
    database for span-aware recommendations and derived readouts."""

    def __init__(self, conn, recording_id):
        self.conn = conn
        self._recording_id = recording_id


def _widgets(pane):
    """Every Panel widget inside `pane`, recursively."""
    if isinstance(pane, pn.widgets.Widget):
        return [pane]
    out = []
    for obj in getattr(pane, "objects", ()):
        out.extend(_widgets(obj))
    return out


def _html_texts(pane):
    """The raw string of every HTML pane inside `pane`, recursively."""
    if isinstance(pane, pn.pane.HTML):
        return [str(pane.object)]
    out = []
    for obj in getattr(pane, "objects", ()):
        out.extend(_html_texts(obj))
    return out


def _synthetic_app(n_samples=200):
    """A fake app backed by a temp db + synthetic channel, headless.
    Returns (app, db_path, npy_path); caller closes `app.conn` and unlinks
    the two files."""
    import tempfile as _tempfile
    import numpy as _np
    from Working.database.schema import init_db as _init_db
    from Working.database import queries as _q

    tf = _tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    db_path = tf.name
    npy_path = os.path.join(os.path.dirname(db_path), "CH0.npy")
    _np.save(npy_path, _np.arange(n_samples, dtype=float))
    conn = _init_db(db_path)
    rid = _q.insert_recording(
        conn, "UNITTEST_chain_builder_synth.mat", 0, 1.0, n_samples, 0, npy_path
    )
    return _FakeAppWithDb(conn, rid), db_path, npy_path


def _close_synthetic(app, db_path, npy_path):
    app.conn.close()
    os.unlink(db_path)
    os.unlink(npy_path)


def test_card_with_parameters_returns_non_none_panes():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))

    card = builder.cards[0]
    assert card is not None
    assert all(obj is not None for obj in card.objects), \
        "every pane on a parameter card must be non-None -- the blank-pane failure"
    # The generated parameter controls are present, not silently blank.
    assert any(isinstance(w, pn.widgets.FloatInput) for w in _widgets(card))
    assert any(isinstance(w, pn.widgets.IntInput) for w in _widgets(card))


def test_card_shows_generated_parameter_controls_for_its_algorithm():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))

    names = [w.name for w in _widgets(builder.cards[0])]
    assert "Cutoff hz" in names
    assert "Order" in names


def test_editing_a_card_param_writes_back_to_the_chain_model():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))

    order = next(w for w in _widgets(builder.cards[0])
                 if isinstance(w, pn.widgets.IntInput))
    order.value = 8
    assert builder.chain.steps[0]["params"]["order"] == 8


def test_render_preserves_existing_card_param_edits():
    from UI.workspaces.analyse.builder import ChainBuilder

    app, db_path, npy_path = _synthetic_app(n_samples=200)
    try:
        builder = ChainBuilder(app)
        builder._add_step(get_adapter("detection.sax_csax"))

        seconds = next(
            w for w in _widgets(builder.cards[0])
            if isinstance(w, pn.widgets.FloatInput)
            and w.name.startswith("Seconds per symbol")
        )
        seconds.value = 24.0

        # Re-rendering (as a reorder/add does) must NOT overwrite the edit
        # with a fresh recommendation.
        builder._add_step(get_adapter("preprocessing.lowpass"))
        rebuilt = next(
            w for w in _widgets(builder.cards[0])
            if isinstance(w, pn.widgets.FloatInput)
            and w.name.startswith("Seconds per symbol")
        )
        assert rebuilt.value == 24.0
    finally:
        _close_synthetic(app, db_path, npy_path)


def test_card_applies_recommended_defaults_and_marks_modified():
    from UI.workspaces.analyse.builder import ChainBuilder

    app, db_path, npy_path = _synthetic_app(n_samples=200)
    try:
        builder = ChainBuilder(app)
        builder._add_step(get_adapter("detection.sax_csax"))
        card = builder.cards[0]

        seconds = next(
            w for w in _widgets(card)
            if isinstance(w, pn.widgets.FloatInput)
            and w.name.startswith("Seconds per symbol")
        )
        # Recommended defaults for the 200-sample span were applied.
        assert seconds.value > 0

        # A value changed away from the recommendation is marked modified.
        seconds.value = seconds.value * 2
        assert seconds.name.endswith("•"), \
            f"expected a modified marker, got {seconds.name!r}"
    finally:
        _close_synthetic(app, db_path, npy_path)


def test_card_derived_readout_recomputes_live_without_running():
    from UI.workspaces.analyse.builder import ChainBuilder

    app, db_path, npy_path = _synthetic_app(n_samples=200)
    try:
        builder = ChainBuilder(app)
        builder._add_step(get_adapter("detection.sax_csax"))
        card = builder.cards[0]

        html = " ".join(_html_texts(card))
        assert "Symbols produced" in html

        seconds = next(
            w for w in _widgets(card)
            if isinstance(w, pn.widgets.FloatInput)
            and w.name.startswith("Seconds per symbol")
        )
        seconds.value = seconds.value * 2

        html_after = " ".join(_html_texts(card))
        assert html_after != html
        assert "Symbols produced" in html_after
    finally:
        _close_synthetic(app, db_path, npy_path)


def test_card_shows_a_side_input_picker_for_declared_side_input():
    from UI.workspaces.analyse.builder import ChainBuilder

    app, db_path, npy_path = _synthetic_app(n_samples=200)
    try:
        builder = ChainBuilder(app)
        builder._add_step(get_adapter("preprocessing.window_matrix"))
        builder._add_step(get_adapter("catalogue.cluster"))
        builder._add_step(get_adapter("catalogue.classifier"))

        card = builder.cards[2]
        source = next(
            (w for w in _widgets(card)
             if isinstance(w, pn.widgets.Select) and w.name == "Source"),
            None,
        )
        assert source is not None, \
            "a block declaring a side input must show a picker on its card"
        assert "earlier_step" in list(source.options.values())
    finally:
        _close_synthetic(app, db_path, npy_path)


def test_card_reuses_shared_param_widgets_and_derive_mixin():
    import UI.workspaces.analyse.builder as b
    from UI.analyse.derive import DeriveMixin
    from UI.analyse.param_widgets import _widget_for_param

    assert b.DeriveMixin is DeriveMixin, \
        "the card must reuse the shared derive mixin, not fork it"
    assert b._widget_for_param is _widget_for_param, \
        "the card must reuse the shared param-widget generator, not fork it"


# ── T58: a + between every pair and at the end opens a mid-chain picker ──────

def test_plus_buttons_appear_between_every_pair_and_after_the_last():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))
    builder._add_step(get_adapter("detection.rupture"))

    plus = _plus_buttons(builder)
    assert [pos for pos, _ in plus] == [1, 2], \
        "a + must sit between the two cards and after the last one"

    # The empty chain offers a single + at the only position there is.
    empty = ChainBuilder(_FakeApp())
    assert [pos for pos, _ in _plus_buttons(empty)] == [0]


def test_clicking_a_plus_opens_the_picker_for_that_position():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))
    builder._add_step(get_adapter("detection.rupture"))

    # No + has been clicked yet, so no picker is open.
    assert builder.add_column.objects == []

    middle = _plus_buttons(builder)[0][1]
    middle.clicks = middle.clicks + 1

    assert builder._active_insert_index == 1
    assert len(builder.add_column.objects) == len(list_adapters()), \
        "the picker must list every registered block, incompatible or not"


def test_choosing_a_block_from_a_plus_inserts_at_that_position_not_the_end():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))
    builder._add_step(get_adapter("detection.rupture"))
    assert [s["algorithm"] for s in builder.chain.steps] == ["lowpass", "rupture"]

    # Click the middle + (insert at index 1), then choose detrend.
    middle_plus = _plus_buttons(builder)[0][1]
    middle_plus.clicks = middle_plus.clicks + 1
    detrend_row = _add_row(builder, "preprocessing.detrend")
    detrend_row[0].clicks = detrend_row[0].clicks + 1

    assert [s["algorithm"] for s in builder.chain.steps] == \
        ["lowpass", "detrend", "rupture"]


def test_picker_lists_every_block_with_incompatible_ones_disabled_and_reason():
    from UI.workspaces.analyse.builder import ChainBuilder
    from Working.chain_validation import check_step_compatibility

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))          # signal -> signal
    builder._add_step(get_adapter("catalogue.gramian_gasf"))         # signal -> encoding

    # The + between the two cards: anything inserted is fed by signal and
    # must itself feed gramian_gasf (which wants signal).
    builder._open_picker(1)
    assert len(builder.add_column.objects) == len(list_adapters())

    producing_kind = get_adapter("preprocessing.lowpass").output_kind
    next_block = get_adapter("catalogue.gramian_gasf")
    for block, row in zip(list_adapters(), builder.add_column.objects):
        button, reason = row[0], row[1]
        ok, expected_reason = check_step_compatibility(producing_kind, block)
        if ok and next_block is not None:
            ok_down, reason_down = check_step_compatibility(block.output_kind, next_block)
            if not ok_down:
                ok, expected_reason = False, reason_down
        assert button.disabled is not ok, block.name
        assert reason.object == expected_reason, block.name

    # Both directions must actually be exercised, or the loop above would
    # pass against a picker that never disabled anything.
    from Adapters.registry import get_adapter as _ga
    rupture = _add_row(builder, "detection.rupture")
    assert rupture[0].disabled is True, "rupture's spanset cannot feed gramian_gasf"


def test_inserting_mid_chain_preserves_steps_after_and_rebinds_side_inputs():
    from UI.workspaces.analyse.builder import ChainBuilder

    builder = ChainBuilder(_FakeApp())
    builder._add_step(get_adapter("preprocessing.lowpass"))        # 0 signal->signal
    builder._add_step(get_adapter("preprocessing.window_matrix"))  # 1 signal->windowset
    builder._add_step(get_adapter("catalogue.cluster"))            # 2 windowset->grouping
    builder._add_step(get_adapter("catalogue.classifier"))         # 3 grouping->model

    # Bind classifier's 'windows' side-input to window_matrix (index 1).
    builder.chain.steps[3]["side_inputs"]["windows"] = {
        "source_kind": "earlier_step", "step_index": 1,
    }

    # Insert detrend between lowpass and window_matrix (index 1).
    builder._insert_step(get_adapter("preprocessing.detrend"), 1)

    assert [s["algorithm"] for s in builder.chain.steps] == [
        "lowpass", "detrend", "window_matrix", "cluster", "classifier",
    ]
    # window_matrix moved from index 1 to 2; the classifier's binding follows.
    binding = builder.chain.steps[4]["side_inputs"]["windows"]
    assert binding == {"source_kind": "earlier_step", "step_index": 2}


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
