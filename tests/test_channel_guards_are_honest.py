"""The guards that decide whether a real-data test runs must skip, not return.

Ninety-eight call sites across ten files opened with:

    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return

A test that returns early **reports as passed**. So with the channel data
absent, a large slice of this suite was green without executing anything, and
the numbers say how large: when the data was rematerialised on 2026-08-17 the
suite went from 152 s to 276 s and from "505 passed" to a genuinely different
505 passed. Nothing failed; the suite had simply been lying at scale.

That mattered beyond tidiness. The orchestrator gates every ticket on "no
regressions against the baseline", and both the baseline and the ticket run
were measuring the same vacuum. `runs/run-20260817-1157` merged T01 on a suite
gate that had executed zero tests.

These tests are the standing guarantee that the conversion does not quietly
regress — a `return` is one careless edit away from coming back, and nothing
else in the suite would notice.
"""

import ast
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(PROJECT_ROOT, "tests")

#: The files that gate on real recording data being present.
GUARDED_FILES = (
    "test_encoding_view.py",
    "test_encoding_view_dsax.py",
    "test_execution.py",
    "test_filters.py",
    "test_ribbon_panes.py",
    "test_run_panel.py",
    "test_run_panel_matrix_profile.py",
    "test_session_persistence.py",
    "test_shortcuts_and_view_controls.py",
    "test_ui_selection.py",
)


def _parse(filename):
    path = os.path.join(TESTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def _guard_bodies(tree):
    """Every `if not _channel_available():` body in the module."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)):
            continue
        call = test.operand
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == "_channel_available"):
            yield node


@pytest.mark.parametrize("filename", GUARDED_FILES)
def test_no_channel_guard_returns_instead_of_skipping(filename):
    """A bare `return` inside the guard is the defect. It must not come back."""
    offenders = []
    for guard in _guard_bodies(_parse(filename)):
        for statement in guard.body:
            if isinstance(statement, ast.Return):
                offenders.append(guard.lineno)

    assert not offenders, (
        f"{filename}: `if not _channel_available():` returns at lines "
        f"{offenders} — a test that returns early is reported as PASSED, so "
        f"absent data reads as green rather than as skipped"
    )


@pytest.mark.parametrize("filename", GUARDED_FILES)
def test_every_channel_guard_calls_pytest_skip(filename):
    """The positive form: each guard must actually raise a skip."""
    tree = _parse(filename)
    guards = list(_guard_bodies(tree))
    assert guards, f"{filename}: no _channel_available guard found — has it moved?"

    for guard in guards:
        calls = [
            node for statement in guard.body for node in ast.walk(statement)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "skip"
        ]
        assert calls, (
            f"{filename}:{guard.lineno}: guard body does not call pytest.skip"
        )


@pytest.mark.parametrize("filename", GUARDED_FILES)
def test_the_guarded_modules_import_pytest(filename):
    """`pytest.skip` is only available if the module imported pytest."""
    tree = _parse(filename)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "pytest" in imported, f"{filename} calls pytest.skip without importing pytest"


@pytest.mark.parametrize("filename", GUARDED_FILES)
def test_the_standalone_runner_reports_skips_rather_than_dying(filename):
    """These modules double as scripts (`python tests/test_x.py`) via `_run_all`.

    `pytest.skip` raises `Skipped`, which derives from `BaseException` and not
    `Exception` — so the existing `except Exception` in `_run_all` does not
    catch it, and the first skipped test would abort the whole standalone run.
    The runner has to know about skips for the script mode to survive the
    conversion.
    """
    source_path = os.path.join(TESTS_DIR, filename)
    with open(source_path, "r", encoding="utf-8") as handle:
        source = handle.read()

    assert "def _run_all" in source, f"{filename}: no standalone runner to check"
    assert "skip.Exception" in source or "Skipped" in source, (
        f"{filename}: `_run_all` does not handle pytest.skip's Skipped "
        f"exception, so `python tests/{filename}` dies on the first skip"
    )


def test_the_guard_actually_skips_when_the_data_is_absent(tmp_path, monkeypatch):
    """The behaviour itself, not its shape: run a guarded test from a directory
    where the channel file cannot be found, and assert pytest records a skip.

    `REAL_CHANNEL_PATH` is relative, so changing cwd is enough to hide it.
    """
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         "test_encoding_view.py::test_running_csax_populates_encoding_section",
         "-q", "--no-header", "-p", "no:cacheprovider",
         "--rootdir", TESTS_DIR],
        cwd=TESTS_DIR, capture_output=True, text=True, timeout=600,
        env={**os.environ, "PYTHONPATH": PROJECT_ROOT},
    )

    combined = result.stdout + result.stderr
    assert "1 skipped" in combined, (
        "with the channel data unreachable the test should be reported as "
        f"skipped, not passed:\n{combined[-2000:]}"
    )
