"""
test_workspaces.py
==================
Structural tests for the four-workspace shell (ticket T18).

Eight later tickets mount into this shell, so what is pinned here is the
*contract* rather than the contents: four workspaces plus an Admin group,
content reaching a workspace through `UI.workspaces` without the shell being
edited, and every pane non-`None`.

That last one is not ceremony. A broken dynamic map in this codebase renders as
a silently blank pane rather than an error -- tests pass, review passes, the
feature is missing. tests/test_run_panel.py and tests/test_motif_browser.py
construct headlessly for the same reason.

The registry tests need no database and no channel, so they run everywhere. The
shell tests build a real `ViewerApp` and are gated on the real channel .npy in
the same way as tests/test_ui_selection.py.

Run from the project root:
    python tests/test_workspaces.py
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

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from Working.recipes import make_recipe
from UI import workspaces
from UI.viewer import ViewerApp
from tests._session_isolation import scratch_session_file

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600

#: The tab order the shell presents. Admin is a group, not a workspace, and
#: sits after the four.
EXPECTED_TABS = ["Explore", "Analyse", "Review", "Library", "Admin"]


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_app():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    rid = q.insert_recording(conn, "UNITTEST_workspaces.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    q.insert_annotation(conn, rid, 12000, 12600, "interesting", source=q.SOURCE_MANUAL_UI)
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
    """The first `pn.Tabs` anywhere inside `pane` (handles Analyse's
    Row(sidebar, Tabs) shape), or None."""
    if isinstance(pane, pn.Tabs):
        return pane
    for obj in getattr(pane, "objects", ()):
        found = _tabs_inside(obj)
        if found is not None:
            return found
    return None


def _contains_widget(pane, widget):
    """True if `widget` is `pane` or appears anywhere in its object tree."""
    if pane is widget:
        return True
    return any(_contains_widget(o, widget) for o in getattr(pane, "objects", ()))


# ── The registration contract ───────────────────────────────────────────────


def test_workspaces_exposes_the_registration_contract():
    """The names the shell and eight later tickets both depend on."""
    for attribute in ("WORKSPACES", "register", "sections", "build", "reset"):
        assert hasattr(workspaces, attribute), \
            f"UI.workspaces has no {attribute!r} -- the shell cannot mount content without it"
    assert workspaces.WORKSPACES == ("Explore", "Analyse", "Review", "Library")


def test_register_makes_a_section_reachable():
    try:
        workspaces.register("Review", "Queue", lambda app: pn.pane.Markdown("queue"))
        labels = [label for label, _ in workspaces.sections("Review")]
        assert "Queue" in labels
    finally:
        workspaces.reset()


def test_register_rejects_an_unknown_workspace():
    with pytest.raises(workspaces.UnknownWorkspace):
        workspaces.register("Nonsense", "X", lambda app: None)


def test_register_rejects_a_duplicate_label():
    """Two tickets registering the same label into one workspace is a merge
    collision, and it should say so rather than let the second win silently."""
    try:
        workspaces.register("Review", "Queue", lambda app: pn.pane.Markdown("a"))
        with pytest.raises(ValueError):
            workspaces.register("Review", "Queue", lambda app: pn.pane.Markdown("b"))
    finally:
        workspaces.reset()


def test_registry_holds_factories_not_built_panes():
    """A pane belongs to one app. The registry outlives every app, so holding
    built panes here would hand a second app the first app's widgets."""
    try:
        # Explore has no builtin sections, so a single registration renders
        # directly -- the right shape for asserting a factory is called once
        # per app rather than a built pane being shared.
        workspaces.register("Explore", "Queue", lambda app: pn.pane.Markdown(app.token))

        class _FakeApp:
            def __init__(self, token):
                self.token = token

        first = workspaces.build("Explore", _FakeApp("one"))
        second = workspaces.build("Explore", _FakeApp("two"))
        assert first is not second
        assert first.object == "one" and second.object == "two"
    finally:
        workspaces.reset()


def test_an_empty_workspace_builds_a_non_none_placeholder():
    """An unmounted workspace must still render as something. Returning `None`
    is the blank-pane failure this file exists to catch."""
    try:
        workspaces.reset()
        # Explore remains the one workspace with no builtin content.
        pane = workspaces.build("Explore", object())
        assert pane is not None
    finally:
        workspaces.reset()


def test_reset_restores_the_pre_split_surfaces():
    workspaces.register("Review", "Temporary", lambda app: pn.pane.Markdown("x"))
    workspaces.reset()
    assert [label for label, _ in workspaces.sections("Review")] == ["Candidate queue"]
    analyse = [label for label, _ in workspaces.sections("Analyse")]
    assert "Run algorithm" in analyse
    # Ticket 34: run history is folded into Analyse as a sidebar, so it is
    # no longer a registered section.
    assert "Run history" not in analyse


# ── The shell ───────────────────────────────────────────────────────────────


def test_the_shell_has_four_workspaces_and_an_admin_group():
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        assert _tab_names(app.tabs) == EXPECTED_TABS
    finally:
        _close_and_unlink(app, db_path)


def test_no_workspace_pane_is_none():
    """The headless construction check CLAUDE.md requires of every Panel
    surface: a blank workspace is invisible to any test that only counts tabs."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        for name, pane in zip(_tab_names(app.tabs), app.tabs.objects):
            assert pane is not None, f"workspace {name!r} renders as None"
    finally:
        _close_and_unlink(app, db_path)


def test_admin_group_holds_vocabulary_admin_and_import():
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        admin = _pane_named(app.tabs, "Admin")
        assert isinstance(admin, pn.Tabs)
        assert _tab_names(admin) == ["Vocabulary admin", "Import recording"]
        for pane in admin.objects:
            assert pane is not None
    finally:
        _close_and_unlink(app, db_path)


def test_run_history_is_still_reachable_after_the_split():
    """Ticket 34 folded run history into Analyse as a sidebar: it is no
    longer a sub-tab, but the table must still be reachable from the Analyse
    workspace (the Reopen criterion below is unsatisfiable otherwise)."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        analyse = _pane_named(app.tabs, "Analyse")
        assert isinstance(analyse, pn.Row), \
            "Analyse should be a Row(run-history sidebar, section tabs)"
        tabs = _tabs_inside(analyse)
        assert tabs is not None, "Analyse should still contain section tabs"
        assert "Run history" not in _tab_names(tabs), \
            "Run history should no longer be a sub-tab"
        assert _contains_widget(analyse, app.run_history.table), \
            "run-history table should be reachable in the Analyse sidebar"
    finally:
        _close_and_unlink(app, db_path)


def test_reopen_switches_to_the_analyse_workspace():
    """`UI/workspaces/analyse/history.py` activates Analyse; index 1 must
    still be the workspace that holds it, and its first section the run
    panel."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        assert _tab_names(app.tabs)[1] == "Analyse"
        analyse = _pane_named(app.tabs, "Analyse")
        tabs = _tabs_inside(analyse)
        assert tabs is not None
        assert _tab_names(tabs)[0] == "Run algorithm", \
            "Reopen lands on Analyse; its first section must be the run panel"
    finally:
        _close_and_unlink(app, db_path)


def test_seed_is_offered_as_a_verdict_from_the_shared_vocabulary():
    """T18 gains `seed` as a fifth verdict, reading ticket 04's constant rather
    than a literal -- so extending `VERDICTS` extends the form by itself."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        offered = list(app.param.verdict.objects)
        assert offered == list(q.VERDICTS)
        assert "seed" in offered
        assert len(offered) == 5
    finally:
        _close_and_unlink(app, db_path)


def test_a_registered_section_reaches_the_shell_without_editing_it():
    """The whole point of the ticket: a workspace ticket adds a surface by
    registering it, and never touches `UI/viewer/layout.py`."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    workspaces.register("Review", "Queue", lambda app: pn.pane.Markdown("the queue"))
    app, db_path = _fresh_app()
    try:
        review = _pane_named(app.tabs, "Review")
        assert review is not None
        # Review already carries the built-in Candidate queue, so a second
        # registration makes it a tab group rather than a single pane.
        queue = _pane_named(review, "Queue")
        assert queue is not None
        assert queue.object == "the queue"
    finally:
        _close_and_unlink(app, db_path)
        workspaces.reset()


def test_activate_workspace_selects_the_section_too():
    """Reopen must land on a specific section of Analyse, not merely on the
    workspace holding it. With Analyse now a Row(sidebar, Tabs), the section
    lives in the inner Tabs."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        analyse = _pane_named(app.tabs, "Analyse")
        tabs = _tabs_inside(analyse)
        assert tabs is not None
        tabs.active = _tab_names(tabs).index("Run algorithm")
        app.activate_workspace("Analyse", "Chain builder")
        assert app.tabs.active == EXPECTED_TABS.index("Analyse")
        assert _tab_names(tabs)[tabs.active] == "Chain builder"
    finally:
        _close_and_unlink(app, db_path)


def test_activate_workspace_tolerates_a_workspace_without_sub_tabs():
    """Library holds one section, so it renders directly and has no sub-tab to
    select. Naming that section must switch workspace, not raise."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        app.activate_workspace("Library", "Motif browser")
        assert app.tabs.active == EXPECTED_TABS.index("Library")
    finally:
        _close_and_unlink(app, db_path)


def test_analyse_workspace_has_run_history_sidebar():
    """PRD: Analyse holds 'a history sidebar that can reload a past chain'.
    The run-history table must be reachable from the Analyse workspace, and
    no longer occupy a sub-tab."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        analyse = _pane_named(app.tabs, "Analyse")
        assert isinstance(analyse, pn.Row), \
            "Analyse should be a Row with the run-history sidebar first"
        sidebar = analyse.objects[0]
        assert _contains_widget(sidebar, app.run_history.table), \
            "the run-history table should appear in the Analyse sidebar"
        tabs = _tabs_inside(analyse)
        assert tabs is not None
        assert "Run history" not in _tab_names(tabs), \
            "the standalone Run history tab should be gone, not merely hidden"
    finally:
        _close_and_unlink(app, db_path)


def test_run_history_reopens_a_chain_into_the_builder():
    """PRD: 'a history sidebar that can reload a past chain'. Selecting a
    past run and clicking Reopen must reconstruct that run's recipe steps in
    the chain builder."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    rid = q.insert_recording(conn, "UNITTEST_history.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    recipe = make_recipe(rid, [
        {"stage": "preprocessing", "algorithm": "detrend", "params": {}},
        {"stage": "detection", "algorithm": "matrix_profile", "params": {"window_min": 10.0}},
    ], span=(0, 100))
    config_id, _ = R.get_or_create_config(conn, recipe)
    R.insert_run(conn, config_id, rid, 0, 100, status="completed")
    conn.close()

    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=tf.name)
    app._test_session_cm = session_cm
    app.layout()
    try:
        app.run_history._refresh()
        app.run_history.table.selection = [0]
        app.run_history._on_reopen()
        steps = app.chain_builder.chain.steps
        assert [s["algorithm"] for s in steps] == ["detrend", "matrix_profile"]
    finally:
        _close_and_unlink(app, tf.name)


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
