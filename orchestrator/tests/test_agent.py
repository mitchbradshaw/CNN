"""Agent dispatch and exit classification.

Every test here drives a **fake** CLI — a small Python script standing in for
`claude`. No test in this suite launches a real agent on a real ticket.
"""

import sys
import textwrap

import pytest

from orchestrator.agent import (
    AgentResult, build_prompt, classify_exit, run_agent,
)
from orchestrator.backlog import load_backlog
from orchestrator.config import load_config

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def config():
    return load_config(REPO_ROOT / "orchestrator" / "config.toml", repo_root=REPO_ROOT)


@pytest.fixture
def fake_cli(tmp_path):
    """A stand-in for `claude` whose behaviour each test dictates."""

    def _make(body, name="fake_claude.py"):
        script = tmp_path / name
        script.write_text(textwrap.dedent(body), encoding="utf-8")
        return [sys.executable, str(script)]

    return _make


# ------------------------------------------------------------------- dispatch


def test_the_agent_runs_in_its_own_worktree(fake_cli, tmp_path):
    cli = fake_cli("""
        import os, sys
        print("cwd=" + os.getcwd())
    """)
    worktree = tmp_path / "wt"
    worktree.mkdir()

    result = run_agent(cli, cwd=worktree, prompt="do the thing",
                       model="claude-sonnet-5", budget_minutes=1)

    assert result.exit_code == 0
    assert str(worktree.resolve()).lower() in result.transcript.lower()


def test_the_transcript_captures_both_streams(fake_cli, tmp_path):
    cli = fake_cli("""
        import sys
        print("on stdout")
        print("on stderr", file=sys.stderr)
    """)

    result = run_agent(cli, cwd=tmp_path, prompt="p", model="m", budget_minutes=1)

    assert "on stdout" in result.transcript
    assert "on stderr" in result.transcript


def test_the_prompt_and_model_reach_the_cli(fake_cli, tmp_path):
    cli = fake_cli("""
        import sys
        print("ARGV=" + "|".join(sys.argv[1:]))
    """)

    result = run_agent(cli, cwd=tmp_path, prompt="ticket T01", model="claude-opus-5",
                       budget_minutes=1, extra_args=["--dangerously-skip-permissions"])

    assert "-p|ticket T01" in result.transcript
    assert "--model|claude-opus-5" in result.transcript
    assert "--dangerously-skip-permissions" in result.transcript


def test_exceeding_the_budget_kills_the_agent(fake_cli, tmp_path):
    cli = fake_cli("""
        import time
        time.sleep(30)
    """)

    result = run_agent(cli, cwd=tmp_path, prompt="p", model="m",
                       budget_minutes=1 / 120)   # 0.5 s

    assert result.timed_out
    assert result.exit_code != 0


def test_the_transcript_is_written_to_the_run_directory(fake_cli, tmp_path):
    cli = fake_cli("""
        print("agent said something")
    """)
    transcript = tmp_path / "run" / "T01" / "transcript.log"

    run_agent(cli, cwd=tmp_path, prompt="p", model="m", budget_minutes=1,
              transcript_path=transcript)

    assert "agent said something" in transcript.read_text(encoding="utf-8")


def test_a_missing_cli_is_reported_rather_than_raising(tmp_path):
    result = run_agent(["definitely-not-a-real-binary-xyz"], cwd=tmp_path,
                       prompt="p", model="m", budget_minutes=1)

    assert result.exit_code != 0
    assert "could not be launched" in result.transcript


# ----------------------------------------------- stalling without ever committing


def test_an_agent_that_never_commits_is_killed_at_the_stall_deadline(fake_cli, tmp_path):
    """run-20260817-2050: T35 produced output continuously and work never.

    `~/.claude.json` was corrupt, so the CLI printed a parse error in a loop and
    made no progress. `stall_minutes` was configured at 20 and never implemented,
    so the agent held its slot for the full 60-minute budget, retried, and burned
    another 60. Any definition of progress based on *output* would have called it
    healthy — it was producing plenty. Commits are the only honest signal.
    """
    cli = fake_cli("""
        import sys, time
        for _ in range(2000):
            print("config is corrupted", flush=True)
            time.sleep(0.01)
    """)

    result = run_agent(cli, cwd=tmp_path, prompt="p", model="m",
                       budget_minutes=5,              # nowhere near the budget
                       stall_minutes=0.5 / 60,        # 0.5 s
                       commit_count=lambda: 0,
                       poll_seconds=0.05)

    assert result.stalled_without_commit
    assert result.duration_seconds < 60, "killed at the stall deadline, not the budget"
    assert "config is corrupted" in result.transcript, "the transcript is still kept"


def test_an_agent_that_keeps_committing_is_left_alone(fake_cli, tmp_path):
    """The false-kill this must not cause: steady progress is not a stall."""
    cli = fake_cli("""
        import time
        time.sleep(0.6)
        print("done")
    """)
    ticks = iter(range(1, 500))

    result = run_agent(cli, cwd=tmp_path, prompt="p", model="m",
                       budget_minutes=5,
                       stall_minutes=0.2 / 60,        # would fire if it went quiet
                       commit_count=lambda: next(ticks),
                       poll_seconds=0.05)

    assert not result.stalled_without_commit
    assert result.exit_code == 0
    assert "done" in result.transcript


def test_an_agent_that_finishes_its_work_and_then_hangs_is_cut_loose(fake_cli, tmp_path):
    """T35's night: two commits inside twelve minutes, then forty-eight idle.

    The commits are real work and must survive — the kill is about reclaiming the
    slot, not about judging the ticket.
    """
    cli = fake_cli("""
        import time
        print("committed everything", flush=True)
        time.sleep(30)
    """)

    result = run_agent(cli, cwd=tmp_path, prompt="p", model="m",
                       budget_minutes=5,
                       stall_minutes=0.4 / 60,
                       commit_count=lambda: 2,        # committed, then silent
                       poll_seconds=0.05)

    assert result.stalled_without_commit
    assert not result.timed_out, "the stall deadline hit first, not the budget"
    assert "committed everything" in result.transcript


def test_stall_detection_is_off_unless_asked_for(fake_cli, tmp_path):
    """Callers that pass no `stall_minutes` keep the plain run-to-completion path."""
    cli = fake_cli("""
        print("quick")
    """)

    result = run_agent(cli, cwd=tmp_path, prompt="p", model="m", budget_minutes=1)

    assert result.exit_code == 0
    assert not result.stalled_without_commit
    assert "quick" in result.transcript


def test_the_budget_still_wins_when_nothing_stalls(fake_cli, tmp_path):
    """Stall detection must not displace the budget as the outer bound."""
    cli = fake_cli("""
        import time
        time.sleep(30)
    """)

    result = run_agent(cli, cwd=tmp_path, prompt="p", model="m",
                       budget_minutes=1 / 120,        # 0.5 s
                       stall_minutes=10,              # never reached
                       commit_count=lambda: 5,
                       poll_seconds=0.05)

    assert result.timed_out
    assert not result.stalled_without_commit


# ------------------------------------------------------------- classification


def a_result(**kwargs) -> AgentResult:
    base = dict(exit_code=0, transcript="", duration_seconds=600.0, timed_out=False)
    base.update(kwargs)
    return AgentResult(**base)


def test_a_clean_exit_with_commits_proceeds_to_the_gates(config):
    verdict = classify_exit(a_result(), commits_made=3, config=config)

    assert verdict == "ok"


def test_a_timeout_with_no_work_is_a_stall(config):
    verdict = classify_exit(a_result(exit_code=124, timed_out=True), commits_made=0,
                            config=config)

    assert verdict == "stall"


def test_a_timeout_after_real_work_goes_to_the_gates(config):
    """run-20260817-2050 threw away a finished ticket, twice.

    T35 committed its failing tests at 21:02 and its implementation at 21:08,
    then hung until the 60-minute budget killed it at 21:56. `timed_out` was
    checked before the commit count, so a complete piece of test-first work was
    discarded, retried from a clean worktree, and quarantined — while the branch
    still held both commits.

    This module's own contract already says otherwise: "an agent that exited
    non-zero having done real work is classified `ok` and handed to the gates to
    judge". A hung process is a process failure; the commits are the work, and
    the gates are what decide whether the work is good.
    """
    verdict = classify_exit(a_result(exit_code=124, timed_out=True), commits_made=2,
                            config=config)

    assert verdict == "ok"


def test_a_clean_exit_with_no_commits_is_a_stall(config):
    """The agent believes it finished and produced nothing. Retrying the *agent*
    is right here in a way it never is after a red suite."""
    verdict = classify_exit(a_result(), commits_made=0, config=config)

    assert verdict == "stall"


def test_a_corrupted_cli_config_is_infrastructure_not_the_tickets_fault(config):
    """run-20260817-2050 blamed T35 for a broken `~/.claude.json`.

    Three agents launched in the same second, raced on the CLI's global config
    file, and two read it mid-write. The CLI then looped on a parse error until
    the budget killed it — and because `timed_out` was checked before the
    infrastructure markers, the verdict was `stall`: one retry, then the ticket
    was quarantined and counted toward the circuit breaker. The environment
    broke, so the environment should wear it.
    """
    transcript = ("Claude configuration file at C:\\Users\\x\\.claude.json is corrupted: "
                  "JSON Parse error: Unexpected EOF\n" * 40)

    verdict = classify_exit(a_result(exit_code=124, timed_out=True, transcript=transcript),
                            commits_made=0, config=config)

    assert verdict == "infrastructure"


def test_exhausted_usage_quota_is_infrastructure_not_the_tickets_fault(config):
    """run-20260818-2244: every one of four agents printed this and did
    nothing further. Same shape as the corrupted-config case above — the
    environment had no budget left to give, not a ticket anyone got wrong —
    but it isn't an API rate limit, so it needs its own marker."""
    transcript = "You're out of extra usage · resets 3:30am (Australia/Brisbane)\n"

    verdict = classify_exit(a_result(exit_code=1, timed_out=True, transcript=transcript),
                            commits_made=0, config=config)

    assert verdict == "infrastructure"


def test_a_plain_timeout_with_no_infrastructure_signature_is_still_a_stall(config):
    """The reordering must not turn every timeout into an infrastructure excuse."""
    verdict = classify_exit(a_result(exit_code=124, timed_out=True,
                                     transcript="thinking very hard about spans"),
                            commits_made=0, config=config)

    assert verdict == "stall"


def test_the_rate_limit_signature_is_infrastructure(config):
    """Fast exit, non-zero code, no commits — the signature `claude-retry.log`
    recorded one agent retrying every 3 seconds into a limit it had hit."""
    verdict = classify_exit(a_result(exit_code=1, duration_seconds=4.0),
                            commits_made=0, config=config)

    assert verdict == "infrastructure"


def test_an_api_error_in_the_transcript_is_infrastructure(config):
    verdict = classify_exit(
        a_result(exit_code=1, duration_seconds=900.0,
                 transcript="... Error: 429 rate_limit_error ..."),
        commits_made=0, config=config)

    assert verdict == "infrastructure"


def test_a_nonzero_exit_after_real_work_still_reaches_the_gates(config):
    """The gates, not the exit code, decide whether the work is good."""
    verdict = classify_exit(a_result(exit_code=1, duration_seconds=1800.0),
                            commits_made=5, config=config)

    assert verdict == "ok"


# -------------------------------------------------------------------- prompt


@pytest.fixture(scope="module")
def real_backlog(config):
    return load_backlog(config.paths.tickets)


def test_the_prompt_names_the_ticket_and_the_two_context_files(real_backlog, config):
    prompt = build_prompt(real_backlog[1], config)

    assert "T01" in prompt
    assert "docs/tickets/T01" in prompt.replace("\\", "/")
    assert "CLAUDE.md" in prompt
    assert "CODING_STANDARDS.md" in prompt


def test_the_prompt_never_hands_over_the_whole_backlog(real_backlog, config):
    prompt = build_prompt(real_backlog[1], config)

    assert "docs/tickets/README.md" not in prompt.replace("\\", "/")
    assert "T02" not in prompt


def test_the_prompt_states_the_test_first_requirement(real_backlog, config):
    prompt = build_prompt(real_backlog[1], config)

    assert "first commit" in prompt.lower()
    assert "tests/" in prompt


def test_a_retry_prompt_carries_the_previous_transcript_tail(real_backlog, config):
    prompt = build_prompt(real_backlog[1], config,
                          previous_transcript_tail="...agent stalled here...")

    assert "...agent stalled here..." in prompt
    assert "previous attempt" in prompt.lower()
