"""Gate 2 — suite green on the branch, as a baseline comparison.

The gate is "nothing that passed at baseline may fail", never a fixed count:
a hardcoded number is wrong by the second merged ticket.
"""

import textwrap

import pytest

from orchestrator.gates.suite import SuiteResult, check_suite, run_suite


class Project:
    """A tiny real pytest suite on disk.

    Real, rather than a mocked runner: parsing pytest's own output is the part
    that breaks, and a fake would never catch that.
    """

    def __init__(self, root):
        self.root = root
        (root / "tests").mkdir(parents=True)
        (root / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")

    def write(self, name, body):
        (self.root / "tests" / name).write_text(textwrap.dedent(body), encoding="utf-8")

    def __fspath__(self):
        return str(self.root)


@pytest.fixture
def suite_dir(tmp_path):
    project = Project(tmp_path / "proj")
    project.write("test_ok.py", """
        def test_one(): assert True
        def test_two(): assert True
    """)
    return project


COMMAND = ("pytest", "-q", "--tb=no", "-rf")


def test_a_green_suite_reports_no_failures(suite_dir):
    result = run_suite(suite_dir, COMMAND, timeout_minutes=5)

    assert result.exit_code == 0
    assert result.failed == ()
    assert result.output


def test_failing_node_ids_are_parsed_out(suite_dir):
    suite_dir.write("test_bad.py", """
        def test_broken(): assert False
        def test_fine(): assert True
    """)

    result = run_suite(suite_dir, COMMAND, timeout_minutes=5)

    assert result.exit_code != 0
    assert result.failed == ("tests/test_bad.py::test_broken",)


def test_a_collection_error_is_red_even_with_no_failed_lines(suite_dir):
    suite_dir.write("test_broken_import.py", "import nonexistent_module_xyz\n")

    result = run_suite(suite_dir, COMMAND, timeout_minutes=5)

    assert result.exit_code != 0
    assert result.failed, "a collection error must not read as a green suite"


def test_only_the_named_node_ids_run_on_a_targeted_rerun(suite_dir):
    suite_dir.write("test_bad.py", """
        def test_broken(): assert False
    """)

    result = run_suite(suite_dir, COMMAND, timeout_minutes=5,
                       node_ids=["tests/test_ok.py::test_one"])

    assert result.exit_code == 0
    assert "1 passed" in result.output


# --------------------------------------------------------------- the gate


def test_a_green_branch_passes(suite_dir):
    verdict = check_suite(suite_dir, COMMAND, baseline_failed=(), timeout_minutes=5)

    assert verdict.status == "pass"
    assert verdict.regressions == ()


def test_a_failure_already_failing_at_baseline_is_not_a_regression(suite_dir):
    suite_dir.write("test_bad.py", """
        def test_broken(): assert False
    """)

    verdict = check_suite(suite_dir, COMMAND,
                          baseline_failed=("tests/test_bad.py::test_broken",),
                          timeout_minutes=5)

    assert verdict.status == "pass"
    assert verdict.regressions == ()


def test_a_new_failure_that_reproduces_is_quarantined(suite_dir):
    suite_dir.write("test_bad.py", """
        def test_broken(): assert False
    """)

    verdict = check_suite(suite_dir, COMMAND, baseline_failed=(), timeout_minutes=5)

    assert verdict.status == "fail"
    assert verdict.regressions == ("tests/test_bad.py::test_broken",)
    assert verdict.rerun_output, "both outputs are retained in the run directory"


def test_a_new_failure_that_passes_on_rerun_is_flaky_not_failed(suite_dir):
    """The flake amendment: re-run only the failing node ids, exactly once."""
    suite_dir.write("test_flaky.py", """
        import pathlib
        MARK = pathlib.Path(__file__).with_name('.ran')
        def test_flaky():
            first = not MARK.exists()
            MARK.write_text('x')
            assert not first, 'fails the first time only'
    """)

    verdict = check_suite(suite_dir, COMMAND, baseline_failed=(), timeout_minutes=5)

    assert verdict.status == "flaky"
    assert verdict.flaky == ("tests/test_flaky.py::test_flaky",)
    assert verdict.regressions == ()


def test_a_red_with_no_node_ids_is_never_marked_flaky(suite_dir):
    """A collection error has no node id to re-run. Re-running the synthetic
    placeholder would ask pytest a nonsense question, get a *different* nonsense
    answer back, and read the mismatch as "it passed on re-run" — turning a hard
    red into a merge. The re-run is skipped entirely."""
    suite_dir.write("test_broken_import.py", "import nonexistent_module_xyz\n")

    verdict = check_suite(suite_dir, COMMAND, baseline_failed=(), timeout_minutes=5)

    assert verdict.status == "fail"
    assert verdict.flaky == ()


def test_the_rerun_happens_exactly_once(suite_dir, monkeypatch):
    suite_dir.write("test_bad.py", """
        def test_broken(): assert False
    """)
    calls = []
    real = run_suite

    def counting(*args, **kwargs):
        calls.append(kwargs.get("node_ids"))
        return real(*args, **kwargs)

    monkeypatch.setattr("orchestrator.gates.suite.run_suite", counting)

    check_suite(suite_dir, COMMAND, baseline_failed=(), timeout_minutes=5)

    assert len(calls) == 2, "one full suite, one targeted re-run — never a third"
    assert calls[0] is None and calls[1] is not None


def test_a_timeout_is_reported_rather_than_hanging_the_run(suite_dir):
    suite_dir.write("test_slow.py", """
        import time
        def test_slow(): time.sleep(30)
    """)

    result = run_suite(suite_dir, COMMAND, timeout_minutes=1 / 120)  # 0.5 s

    assert result.timed_out
    assert result.exit_code != 0


def test_the_suite_command_is_never_run_in_parallel():
    """tests/_session_isolation.py documents exactly why `-n` breaks this suite."""
    from orchestrator.config import load_config
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    config = load_config(root / "orchestrator" / "config.toml", repo_root=root)

    assert "-n" not in config.suite.command
    assert not any(part.startswith("-n") for part in config.suite.command)
