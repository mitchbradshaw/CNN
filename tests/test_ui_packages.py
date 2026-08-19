"""
test_ui_packages.py
===================
Structural tests for the T17 split of the two god-class UI modules.

`UI/app.py` (2282 lines, one `ViewerApp`) and `UI/run_panel.py` (2248 lines,
one `RunPanel` with ~70 methods) were single files that every subsequent UI
ticket had to queue on. They are now packages of focused modules — `UI/viewer/`
and `UI/analyse/` — so that work on the signal view, the filters, the encoding
display and the motif actions can proceed in parallel without touching the
same file.

These tests assert the *shape* of that result, which is the part no behavioural
test can see: that the seams exist as separate modules, that no module has
quietly grown back into a god class, and that the dependency direction between
`UI/` and the headless core still points one way (coding standard 1.2).

Behaviour preservation is asserted by the existing UI suite — test_run_panel.py,
test_ribbon_panes.py, test_ui_selection.py, test_filters.py,
test_session_persistence.py, test_shortcuts_and_view_controls.py — which is
deliberately left unchanged by the split.
"""

import ast
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

UI_DIR = os.path.join(PROJECT_ROOT, "UI")
VIEWER_DIR = os.path.join(UI_DIR, "viewer")
ANALYSE_DIR = os.path.join(UI_DIR, "analyse")

# The seams named in the ticket's acceptance criteria. `ViewerApp` is split
# along the boundaries it already had; `RunPanel` along the six the ticket
# enumerates. A module per seam is the whole point — a package whose modules
# do not line up with the seams buys nothing over the single file.
VIEWER_SEAM_MODULES = [
    "signal_view.py",     # recording load, channel dmap, cross-channel peek
    "overlays.py",        # overlay toggles, ribbon panes, table, summary
    "selection.py",       # pending span, shared table<->plot selection
    "navigation.py",      # drag modes, zoom presets, pan, annotation navigator
    "annotations.py",     # annotation form, save, staging, bulk actions, delete
    "filters.py",         # filter/search widgets and the filtered-row query
    "session.py",         # session persistence (Part E9)
    "layout.py",          # the seven-tab layout
]

ANALYSE_SEAM_MODULES = [
    "staged_chain.py",      # staged-chain state
    "controls.py",          # parameter / derive controls
    "execution.py",         # run execution and progress
    "results.py",           # result display
    "encoding_display.py",  # encoding display
    "motifs.py",            # motif-save actions
    "layout.py",            # the run-tab layout
]

# 600 lines is the line the ticket draws. A module over it is a module that has
# started to become the thing this ticket dismantled.
MAX_MODULE_LINES = 600

# An archival copy of the UI as it stood on 2026-08-10, kept beside the dSAX
# implementation notes as evidence for what that integration changed. It is not
# imported by anything and is not part of `Working/`'s runtime surface.
_ARCHIVE_DIR_MARKER = "UI_snapshot_"


def _python_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d != "__pycache__" and not d.startswith(_ARCHIVE_DIR_MARKER)]
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _line_count(path):
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def _imported_module_names(path):
    """Every dotted module name this file imports, module-scope or nested."""
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


# ── The packages exist, with a module per seam ───────────────────────────────

def test_viewer_package_exists_with_a_module_per_seam():
    assert os.path.isdir(VIEWER_DIR), "UI/viewer/ package missing"
    present = set(os.listdir(VIEWER_DIR))
    assert "__init__.py" in present
    missing = [m for m in VIEWER_SEAM_MODULES if m not in present]
    assert not missing, f"UI/viewer/ is missing seam modules: {missing}"


def test_analyse_package_exists_with_a_module_per_seam():
    assert os.path.isdir(ANALYSE_DIR), "UI/analyse/ package missing"
    present = set(os.listdir(ANALYSE_DIR))
    assert "__init__.py" in present
    missing = [m for m in ANALYSE_SEAM_MODULES if m not in present]
    assert not missing, f"UI/analyse/ is missing seam modules: {missing}"


def test_run_panel_god_module_is_gone():
    """`UI/run_panel.py` had exactly one importer (`UI/app.py`); nothing else
    in the repo imports it, so it is replaced outright rather than shimmed."""
    assert not os.path.exists(os.path.join(UI_DIR, "run_panel.py")), (
        "UI/run_panel.py still exists — the RunPanel split left the old module behind"
    )


def test_app_module_is_now_only_the_panel_entry_point():
    """`UI/app.py` stays: `panel serve UI/app.py` is the documented way to run
    this application, and the orchestrator's worktree check imports it. What it
    must no longer contain is the class — that lives in `UI/viewer/`."""
    app_py = os.path.join(UI_DIR, "app.py")
    assert os.path.exists(app_py)
    with open(app_py, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=app_py)
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    assert classes == [], f"UI/app.py still defines classes: {classes}"
    assert _line_count(app_py) < 120, "UI/app.py is meant to be a thin entry point"


# ── No module grew back into a god class ─────────────────────────────────────

@pytest.mark.parametrize("package_dir", [VIEWER_DIR, ANALYSE_DIR],
                         ids=["viewer", "analyse"])
def test_every_split_module_is_under_the_line_limit(package_dir):
    assert os.path.isdir(package_dir), f"{package_dir} missing"
    oversized = {os.path.relpath(p, PROJECT_ROOT): _line_count(p)
                 for p in _python_files(package_dir)
                 if _line_count(p) >= MAX_MODULE_LINES}
    assert not oversized, f"modules at or over {MAX_MODULE_LINES} lines: {oversized}"


# ── Dependencies still point one way (coding standard 1.2) ───────────────────

def test_nothing_in_working_or_adapters_imports_from_ui():
    """`UI/` may call into `Working/` and `Adapters/`; never the reverse. Walked
    over the import statements rather than trusted, because a single import
    added the wrong way round is what makes the core unrunnable on the cluster."""
    offenders = {}
    for root in ("Working", "Adapters"):
        for path in _python_files(os.path.join(PROJECT_ROOT, root)):
            ui_imports = sorted(n for n in _imported_module_names(path)
                                if n == "UI" or n.startswith("UI."))
            if ui_imports:
                offenders[os.path.relpath(path, PROJECT_ROOT)] = ui_imports
    assert not offenders, f"core modules importing from UI/: {offenders}"


# ── The classes are still importable and still whole ─────────────────────────

def test_viewer_app_is_importable_from_the_package():
    from UI.viewer import ViewerApp
    assert ViewerApp.__name__ == "ViewerApp"


def test_run_panel_is_importable_from_the_package():
    from UI.analyse import RunPanel
    assert RunPanel.__name__ == "RunPanel"


def test_viewer_app_keeps_every_method_it_had():
    """A mixin split loses a method silently: the class still constructs, the
    handler is simply never found because nothing calls an absent attribute
    until a user clicks. This pins the public and private method surface that
    the single-file `ViewerApp` had."""
    from UI.viewer import ViewerApp
    expected = {
        "_load_session_state", "_save_session_state", "_restore_session_state",
        "_refresh_vocabulary_options", "_refresh_bulk_tag_value_options",
        "_refresh_source_file_options", "_refresh_channel_options",
        "_on_source_file_change", "_on_channel_change", "_load_recording",
        "_rebuild_cross_channel_peek", "_rebuild_plot", "_on_filters_changed",
        "_on_clear_filters", "_update_filter_match_count", "_export_records",
        "_export_csv_callback", "_export_json_callback", "_filtered_annotation_rows",
        "_refresh_view", "_on_overlay_toggle_changed", "_update_ribbon_pane_visibility",
        "_refresh_table", "_refresh_summary", "_on_drag_mode_changed",
        "_on_reset_full_view", "_on_pan_y", "_on_pan_y_up", "_on_pan_y_down",
        "_on_range_changed", "_on_view_transform_changed", "_on_zoom_preset",
        "_on_zoom_preset_full", "_navigator_rows", "_navigate_to", "_on_nav_next",
        "_on_nav_prev", "_unit_scale", "_x_range_to_samples", "_on_time_unit_toggle",
        "_update_time_field_steps", "_set_pending_bounds", "_sync_time_fields_from_bounds",
        "_update_selection_info", "_update_similarity_warning", "_on_compare_similar",
        "_on_bounds_selected", "_toggle_annotations_in_range", "_on_time_field_changed",
        "_on_clear_selection", "_sync_table_selection_from_ids",
        "_on_table_selection_changed", "_on_table_cell_edited",
        "_update_annotation_selection_info", "_on_clear_annotation_selection",
        "_zoom_to_ids", "_on_zoom_to_selected", "_on_find_near_duplicates",
        "_save_annotation", "_refresh_staged_badge", "_stage_span",
        "_switch_to_run_tab", "_on_tab_changed", "_on_save_and_run",
        "_on_stage_pending", "_on_run_selected", "_stage_bulk_action",
        "_on_bulk_apply_verdict", "_on_bulk_apply_status", "_on_bulk_apply_tag",
        "_on_bulk_cancel", "_on_bulk_confirm", "_mark_viewport_reviewed",
        "_delete_selected", "_on_undo_delete", "layout",
    }
    missing = sorted(name for name in expected if not hasattr(ViewerApp, name))
    assert not missing, f"ViewerApp lost methods in the split: {missing}"


def test_run_panel_keeps_every_method_it_had():
    from UI.analyse import RunPanel
    expected = {
        "refresh_staged_list", "_staged_duration_label", "_on_remove_staged",
        "_on_clear_staged", "_refresh_element_options", "_on_stage_changed",
        "_on_algorithm_changed", "_refresh_window_matrix_panel", "_current_params",
        "_current_span_signal", "_apply_recommended_defaults", "_on_param_widget_changed",
        "_sync_trend_param_controls", "_sync_segment_mode_controls",
        "_on_preprocess_changed", "_refresh_derived", "_is_sax_shaped_encoding",
        "_schedule_auto_preview", "_run_auto_preview", "_staged_row_index",
        "_current_span", "_on_span_context_changed", "_refresh_preview",
        "_has_valid_manual_span", "_update_motif_button_states", "_on_yaxis_mode_changed",
        "_build_steps", "_on_run", "_gather_display_data", "_gather_encoding_display_data",
        "_gather_generic_encoding_display_data", "_persist_sax_encoding", "_on_cancel",
        "_on_run_finished", "_on_run_cancelled", "_on_run_failed", "_show_before_after",
        "_preprocessing_active", "_preprocessing_description", "_update_preprocessing_banner",
        "_build_colour_key_html", "_show_encoding", "_on_enc_yaxis_mode_changed",
        "_show_encoding_string_only", "_visible_symbol_slice",
        "_refresh_encoding_string_display", "_build_legend_html",
        "_reset_morphology_search", "_on_morphology_search_clear", "_on_morphology_search",
        "_match_time_span", "_focus_morphology_match", "_step_morphology_match",
        "_sync_noise_floor_controls", "_on_estimate_noise_floor",
        "_on_noise_floor_finished", "_on_save_encoding_as_motif", "_show_detections",
        "_find_sax_string_for_span", "_save_motif", "_on_save_detection_as_motif",
        "_on_save_viewport_as_motif", "_clear_motif_fields", "_on_save_plot", "layout",
    }
    missing = sorted(name for name in expected if not hasattr(RunPanel, name))
    assert not missing, f"RunPanel lost methods in the split: {missing}"


# ── The entry point is importable without building the application ───────────
#
# `UI/app.py` ended with a bare `create_app().servable(...)` at module scope, so
# `import UI.app` constructed a whole ViewerApp, opened the database and mmap'd
# a channel `.npy`. Consequences, all of them paid for:
#
#   - The ten test files that imported it failed at *collection* whenever the
#     data was absent, before their own skip guards could run. That is what
#     quarantined an innocent T01 and put 36 tickets into BLOCKED_UPSTREAM in
#     run-20260816-1943, and what made a repaired-but-empty channel directory
#     read as "505 passed" in run-20260817-1157.
#   - It forced the orchestrator to junction 317 MB of real channel data into
#     every worktree purely so that `import` would succeed, which is the sole
#     reason the writable-recordings isolation tradeoff had to be accepted.
#
# Raised in FOLLOWUPS.md on 2026-08-16, re-raised as a blocker on 2026-08-17.

def test_importing_the_app_module_does_not_build_the_application():
    """Importing the entry point must define the app, not construct it."""
    app_py = os.path.join(UI_DIR, "app.py")
    with open(app_py, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=app_py)

    called_at_import = [
        node for node in tree.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
    ]
    assert called_at_import == [], (
        "UI/app.py calls something at module scope: importing it has side "
        "effects, so every test file that imports it fails at collection "
        "whenever the data is absent"
    )


def test_a_serve_entry_point_exists_and_is_the_only_thing_that_builds_the_app():
    """`panel serve` needs a module whose import *does* make a servable app.
    That module is the one place allowed to have the side effect."""
    serve_py = os.path.join(UI_DIR, "serve.py")
    assert os.path.exists(serve_py), (
        "UI/serve.py missing — `panel serve` has nothing to serve once the "
        "side effect leaves app.py"
    )
    with open(serve_py, "r", encoding="utf-8") as f:
        source = f.read()
    assert "servable" in source


def test_the_app_module_imports_cleanly_with_no_database_and_no_channel_data(tmp_path):
    """The property the orchestrator actually depends on, asserted end to end:
    a subprocess with no DATA/ at all must still be able to import UI.app.

    This is the negative control for the whole worktree-provisioning story. If
    it passes, `paths.recordings` exists for the suite's benefit rather than
    the importer's, and dropping it becomes a data question rather than an
    import-time crash."""
    import subprocess

    # Run from an empty directory, not the repo root. `schema.DB_PATH` is the
    # relative `DATA/db/annotations.sqlite` and resolves against cwd, so a cwd
    # with no `DATA/` is a process with no database and no channel files —
    # which is precisely the worktree the orchestrator used to have to junction
    # 317 MB into. `PYTHONPATH` is what makes `UI` importable from there.
    result = subprocess.run(
        [sys.executable, "-c",
         "import UI.app; assert callable(UI.app.create_app); print('ok')"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=300,
        env={**os.environ, "PYTHONPATH": PROJECT_ROOT},
    )
    assert result.returncode == 0, (
        f"importing UI.app has side effects that need real data:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert "ok" in result.stdout
