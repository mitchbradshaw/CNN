"""REPORT.md and the run directory — what you actually read at 8am.

The requirement the whole design serves: the next morning, a fault isolates to
one ticket without a full re-audit.
"""

from pathlib import Path

import pytest

from orchestrator.backlog import load_backlog
from orchestrator.config import load_config
from orchestrator.report import RunDirectory, render_report
from orchestrator.state import RunState, TicketRecord
from orchestrator.status import BLOCKED_UPSTREAM, FAILED, HELD, MERGED, OVERLAP

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def config():
    return load_config(REPO_ROOT / "orchestrator" / "config.toml", repo_root=REPO_ROOT)


@pytest.fixture(scope="module")
def backlog(config):
    return load_backlog(config.paths.tickets)


@pytest.fixture
def state():
    return RunState(
        run_id="run-20260815-2130", integration_branch="integration/run-20260815-2130",
        base_sha="9f2c1ab", config_hash="sha256:abc",
        started_at="2026-08-15T21:30:00+10:00",
        wall_clock_stop="2026-08-16T07:00:00+10:00",
    )


# ------------------------------------------------------------ run directory


def test_the_run_directory_has_the_layout_the_spec_describes(tmp_path):
    run_dir = RunDirectory.create(tmp_path, label="run", timestamp="20260815-2130")

    assert run_dir.path.name == "run-20260815-2130"
    assert run_dir.state_path.name == "state.json"
    assert run_dir.report_path.name == "REPORT.md"
    assert run_dir.plan_path.name == "plan.md"

    ticket_dir = run_dir.ticket_dir(17)
    assert ticket_dir.name == "T17"
    assert ticket_dir.is_dir()
    assert run_dir.artifact(17, "transcript.log").parent == ticket_dir


def test_writing_an_artifact_creates_its_ticket_directory(tmp_path):
    run_dir = RunDirectory.create(tmp_path, label="run", timestamp="20260815-2130")

    run_dir.write(17, "red-proof.txt", "1 failed\n")

    assert (run_dir.path / "T17" / "red-proof.txt").read_text(encoding="utf-8") == "1 failed\n"


# ----------------------------------------------------------------- REPORT.md


def test_one_row_per_dispatched_ticket(state, backlog):
    state.tickets["1"] = TicketRecord(status=MERGED, merge_sha="4b7e0c2",
                                      gates={"red_proof": "pass", "suite": "pass",
                                             "scope": "pass", "review": "pass",
                                             "overlap": "pass"},
                                      started_at="2026-08-15T21:30:00",
                                      ended_at="2026-08-15T22:31:00")
    state.tickets["2"] = TicketRecord(status=FAILED, exit_class="red-at-exit",
                                      gates={"red_proof": "pass", "suite": "fail"})

    text = render_report(state, backlog)

    assert "| T01 |" in text
    assert "| T02 |" in text
    assert "4b7e0c2" in text
    assert "1h01" in text


def test_review_blockers_are_reported_per_axis(state, backlog):
    state.tickets["5"] = TicketRecord(status=FAILED, review_rounds=2,
                                      review_blockers={"standards": 1, "spec": 2},
                                      gates={"review": "fail"})

    text = render_report(state, backlog)

    assert "1/2" in text, "standards/spec blocker counts"


def test_scope_deviations_and_overlap_flags_appear(state, backlog):
    state.tickets["17"] = TicketRecord(status=MERGED, scope_deviations=["UI/plots.py"],
                                       gates={"scope": "warn", "overlap": "pass"})
    state.tickets["40"] = TicketRecord(status=OVERLAP,
                                       overlap_symbols=["resample_and_znorm"])

    text = render_report(state, backlog)

    assert "UI/plots.py" in text
    assert "resample_and_znorm" in text


def test_a_test_marked_flaky_twice_is_listed_as_work_to_be_ticketed(state, backlog):
    """A FLAKY mark is a finding, not a shrug."""
    flake = "tests/test_window_matrix_panel.py::test_ladder_renders_one_entry_per_scale"
    state.tickets["1"] = TicketRecord(status=MERGED, flaky_tests=[flake])
    state.tickets["2"] = TicketRecord(status=MERGED, flaky_tests=[flake])

    text = render_report(state, backlog)

    head = text.split("## Tickets")[0]
    assert flake in head, "repeat flakes belong at the top, not buried in the table"
    assert "twice" in head.lower() or "2×" in head


def test_a_flake_seen_once_is_recorded_but_not_escalated(state, backlog):
    state.tickets["1"] = TicketRecord(status=MERGED, flaky_tests=["tests/t.py::test_x"])

    text = render_report(state, backlog)

    head = text.split("## Tickets")[0]
    assert "work to be ticketed" not in head.lower()


def test_human_verify_tickets_are_listed_for_the_morning(state, backlog):
    state.tickets["17"] = TicketRecord(status=MERGED, merge_sha="abc1234")
    state.tickets["1"] = TicketRecord(status=MERGED, merge_sha="def5678")

    text = render_report(state, backlog)

    assert "human-verify" in text.lower()
    assert "T17" in text.split("human-verify")[1][:400]


def test_human_gated_and_upstream_blocked_tickets_are_reported_as_waiting(state, backlog):
    state.tickets["4"] = TicketRecord(status=HELD)
    state.tickets["18"] = TicketRecord(status=BLOCKED_UPSTREAM)

    text = render_report(state, backlog)

    assert "T04" in text
    assert "waiting on you" in text.lower()


def test_the_report_names_the_branch_and_how_to_undo_a_ticket(state, backlog):
    state.tickets["1"] = TicketRecord(status=MERGED, merge_sha="4b7e0c2")

    text = render_report(state, backlog)

    assert state.integration_branch in text
    assert "git revert -m 1" in text


def test_a_run_with_nothing_dispatched_still_renders(state, backlog):
    text = render_report(state, backlog)

    assert "REPORT" in text
