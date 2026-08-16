"""The baseline — measured where the agents actually live.

The baseline is the set of tests already failing before any ticket runs, and
every suite gate is a comparison against it. Measured in the wrong place it is
not a weak check, it is an inverted one: run-20260816-1943 took its baseline in
the main repo (which has `DATA/derived/`), compared it against a worktree (which
did not), and read the resulting ten collection errors as T01's regressions.
T01 was greenfield `Working/types/` and could not have touched them.
"""

import dataclasses
from pathlib import Path

import pytest

from orchestrator import runloop
from orchestrator.config import load_config
from orchestrator.gates.suite import UNATTRIBUTED, SuiteResult
from orchestrator.gitops import Git
from orchestrator.runloop import BaselineError, capture_baseline

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_CONFIG = REPO_ROOT / "orchestrator" / "config.toml"


@pytest.fixture
def scratch(tmp_path):
    root = tmp_path / "scratch"
    root.mkdir()
    git = Git(root)
    git.run("init", "-b", "main")
    git.run("config", "user.email", "runner@example.invalid")
    git.run("config", "user.name", "Runner Test")
    (root / "README.md").write_text("scratch\n", encoding="utf-8")
    git.run("add", "-A")
    git.run("commit", "-m", "initial")
    git.create_branch("integration", "main")
    return git


@pytest.fixture
def config(scratch, tmp_path):
    """The shipped config, repointed at the scratch repo."""
    loaded = load_config(SHIPPED_CONFIG, repo_root=REPO_ROOT)
    fixture_db = tmp_path / "fixtures" / "annotations.sqlite"
    fixture_db.parent.mkdir(parents=True)
    fixture_db.write_bytes(b"SQLite format 3\x00fixture")
    paths = dataclasses.replace(
        loaded.paths,
        repo_root=scratch.root,
        worktrees=tmp_path / "wt",
        fixture_db=fixture_db,
        recordings=(),
    )
    return dataclasses.replace(loaded, paths=paths)


def _stub_suite(monkeypatch, result: SuiteResult, seen: dict):
    def fake_run_suite(cwd, command, *, timeout_minutes, node_ids=None):
        seen["cwd"] = Path(cwd)
        seen["existed"] = Path(cwd).is_dir()
        seen["had_fixture_db"] = (Path(cwd) / "DATA" / "db" / "annotations.sqlite").is_file()
        return result

    monkeypatch.setattr(runloop, "run_suite", fake_run_suite)


def test_the_baseline_is_measured_inside_a_provisioned_worktree(
        scratch, config, monkeypatch):
    """The root cause. A baseline from the main repo describes a filesystem no
    agent ever sees, so the comparison it feeds is meaningless from ticket one.
    """
    seen: dict = {}
    _stub_suite(monkeypatch, SuiteResult(0, (), "", 1.0), seen)

    capture_baseline(scratch, config, integration_branch="integration")

    assert seen["cwd"] != scratch.root, \
        "baseline measured in the main repo, which has data no worktree has"
    assert seen["existed"], "the baseline suite ran somewhere that does not exist"
    assert seen["had_fixture_db"], \
        "the baseline ran outside a provisioned worktree — same provision() path or nothing"


def test_the_baseline_worktree_is_torn_down_and_leaves_no_branch(
        scratch, config, monkeypatch):
    """It is a throwaway. A leftover tree collides with the next run's
    provisioning, and a leftover branch looks like a ticket in the morning."""
    seen: dict = {}
    _stub_suite(monkeypatch, SuiteResult(0, (), "", 1.0), seen)

    capture_baseline(scratch, config, integration_branch="integration")

    assert not seen["cwd"].exists(), "the baseline worktree outlived the baseline"
    leftover = [b for b in scratch.run("branch", "--format=%(refname:short)").splitlines()
                if b not in {"main", "integration"}]
    assert leftover == [], f"baseline left branches behind: {leftover}"


def test_a_baseline_that_cannot_be_provisioned_refuses_to_start(
        scratch, config, monkeypatch):
    """If the worktree the agents get cannot even be built, dispatching 39
    tickets into it is 20 minutes per ticket of guaranteed waste."""
    broken = dataclasses.replace(
        config, paths=dataclasses.replace(config.paths,
                                          fixture_db=config.paths.fixture_db.parent / "gone.sqlite"))

    with pytest.raises(BaselineError, match="provision"):
        capture_baseline(scratch, broken, integration_branch="integration")


def test_a_baseline_with_unattributable_failures_refuses_to_start(
        scratch, config, monkeypatch):
    """Ten collection errors is not a baseline of ten failing tests — pytest
    never got far enough to say what failed. Recording that as "already red"
    would hand every ticket a gate it cannot pass."""
    seen: dict = {}
    _stub_suite(monkeypatch,
                SuiteResult(2, (UNATTRIBUTED.format(exit_code=2),), "10 errors during collection", 1.0),
                seen)

    with pytest.raises(BaselineError, match="collection|node id"):
        capture_baseline(scratch, config, integration_branch="integration")


def test_a_genuinely_red_baseline_is_returned_not_refused(scratch, config, monkeypatch):
    """The suite is not green by construction. Named failures are data, not an
    error — it is only unattributable ones that mean "do not start"."""
    seen: dict = {}
    _stub_suite(monkeypatch,
                SuiteResult(1, ("tests/test_a.py::test_x", "tests/test_b.py::test_y"), "", 1.0),
                seen)

    failed = capture_baseline(scratch, config, integration_branch="integration")

    assert failed == ("tests/test_a.py::test_x", "tests/test_b.py::test_y")
