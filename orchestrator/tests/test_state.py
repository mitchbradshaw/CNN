"""state.json — the orchestrator's memory, and its reconciliation against git.

Git is the durable truth; state.json is an index over it. Every test here that
touches git uses a disposable scratch repo.
"""

import json
import subprocess

import pytest

from orchestrator.gitops import Git
from orchestrator.state import RunState, TicketRecord, load_state, reconcile, save_state
from orchestrator.status import (
    BLOCKED_UPSTREAM, FAILED, GATING, MERGED, MERGING, PENDING, READY, RUNNING,
)


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
    git.checkout("integration")
    return git


def a_state(**overrides) -> RunState:
    state = RunState(
        run_id="run-20260815-2130",
        integration_branch="integration",
        base_sha="9f2c1ab",
        config_hash="sha256:abc",
        started_at="2026-08-15T21:30:00+10:00",
        wall_clock_stop="2026-08-16T07:00:00+10:00",
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def branch_with_commits(git, name, *, start="integration"):
    git.create_branch(name, start)
    git.checkout(name)
    (git.root / f"{name.replace('/', '_')}.py").write_text("x = 1\n", encoding="utf-8")
    git.run("add", "-A")
    git.run("commit", "-m", f"{name}: work")
    git.checkout("integration")


# ------------------------------------------------------------------ the file


def test_state_round_trips_through_disk(tmp_path):
    path = tmp_path / "state.json"
    state = a_state()
    state.tickets["17"] = TicketRecord(
        status=MERGED, attempts=1, branch="ticket/T17",
        worktree="C:/Users/mmebr/Documents/.wt/T17",
        gates={"red_proof": "pass", "suite": "pass", "scope": "warn",
               "review": "pass", "overlap": "pass"},
        review_rounds=1, review_blockers={"standards": 0, "spec": 0},
        scope_deviations=["UI/plots.py"], merge_sha="4b7e0c2",
    )
    state.symbols = {"resample_and_znorm": 35}

    save_state(state, path)
    again = load_state(path)

    assert again == state
    assert again.tickets["17"].gates["scope"] == "warn"


def test_the_written_file_matches_appendix_a(tmp_path):
    path = tmp_path / "state.json"

    save_state(a_state(), path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert set(data) >= {
        "schema", "run_id", "integration_branch", "base_sha", "config_hash",
        "started_at", "wall_clock_stop", "circuit_breaker", "merge_lock_holder",
        "symbols", "tickets",
    }
    assert data["circuit_breaker"] == {"consecutive_quarantines": 0, "tripped": False}


def test_the_write_is_atomic_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "state.json"

    save_state(a_state(), path)
    save_state(a_state(run_id="run-2"), path)

    assert load_state(path).run_id == "run-2"
    assert list(p.name for p in tmp_path.iterdir()) == ["state.json"]


def test_a_failed_serialisation_does_not_destroy_the_previous_state(tmp_path):
    path = tmp_path / "state.json"
    save_state(a_state(), path)
    broken = a_state(run_id="run-2")
    broken.symbols = {"bad": object()}   # not JSON-serialisable

    with pytest.raises(TypeError):
        save_state(broken, path)

    assert load_state(path).run_id == "run-20260815-2130", "the old file survived"


# --------------------------------------------------------- git reconciliation


def test_a_merged_branch_whose_suite_passed_is_reconciled_to_merged(scratch):
    branch_with_commits(scratch, "ticket/T01")
    sha = scratch.merge_no_ff("ticket/T01", "Merge T01")
    state = a_state()
    state.tickets["1"] = TicketRecord(status=RUNNING, branch="ticket/T01",
                                      gates={"post_merge_suite": "pass"})

    reconcile(state, scratch)

    assert state.tickets["1"].status == MERGED
    assert state.tickets["1"].merge_sha == sha


def test_a_merge_with_no_recorded_suite_returns_to_merging(scratch):
    """A ticket has landed only once the suite is green *after* the merge.
    With no record of that suite, the merge alone is not evidence it ran."""
    branch_with_commits(scratch, "ticket/T01")
    scratch.merge_no_ff("ticket/T01", "Merge T01")
    state = a_state()
    state.tickets["1"] = TicketRecord(status=RUNNING, branch="ticket/T01")

    reconcile(state, scratch)

    assert state.tickets["1"].status == MERGING
    assert state.tickets["1"].merge_sha is not None


def test_a_branch_with_unmerged_commits_resumes_at_gating(scratch):
    branch_with_commits(scratch, "ticket/T01")
    state = a_state()
    state.tickets["1"] = TicketRecord(status=RUNNING, branch="ticket/T01")

    reconcile(state, scratch)

    assert state.tickets["1"].status == GATING, "resume at the first ungated step"


def test_a_branch_with_no_commits_is_reset_to_ready_and_deleted(scratch):
    scratch.create_branch("ticket/T01", "integration")
    state = a_state()
    state.tickets["1"] = TicketRecord(status=RUNNING, branch="ticket/T01")

    reconcile(state, scratch)

    assert state.tickets["1"].status == READY
    assert not scratch.branch_exists("ticket/T01")


def test_a_missing_branch_is_reset_to_ready(scratch):
    state = a_state()
    state.tickets["1"] = TicketRecord(status=GATING, branch="ticket/T01")

    reconcile(state, scratch)

    assert state.tickets["1"].status == READY
    assert state.tickets["1"].branch is None


def test_a_crash_mid_merge_reruns_the_post_merge_suite(scratch):
    """The merge commit exists but the suite never ran. Running it twice is
    free; skipping it is not."""
    branch_with_commits(scratch, "ticket/T01")
    scratch.merge_no_ff("ticket/T01", "Merge T01")
    state = a_state()
    state.tickets["1"] = TicketRecord(status=MERGING, branch="ticket/T01",
                                      gates={"post_merge_suite": "not-run"})

    reconcile(state, scratch)

    assert state.tickets["1"].status == MERGING
    assert state.tickets["1"].gates["post_merge_suite"] == "not-run"


def test_terminal_statuses_are_left_alone(scratch):
    branch_with_commits(scratch, "ticket/T01")
    state = a_state()
    state.tickets["1"] = TicketRecord(status=FAILED, branch="ticket/T01")
    state.tickets["2"] = TicketRecord(status=BLOCKED_UPSTREAM)
    state.tickets["3"] = TicketRecord(status=PENDING)

    reconcile(state, scratch)

    assert state.tickets["1"].status == FAILED
    assert state.tickets["2"].status == BLOCKED_UPSTREAM
    assert state.tickets["3"].status == PENDING


def test_reconcile_clears_a_stale_merge_lock(scratch):
    state = a_state(merge_lock_holder="17")

    reconcile(state, scratch)

    assert state.merge_lock_holder is None
