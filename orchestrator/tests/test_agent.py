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


# ------------------------------------------------------------- classification


def a_result(**kwargs) -> AgentResult:
    base = dict(exit_code=0, transcript="", duration_seconds=600.0, timed_out=False)
    base.update(kwargs)
    return AgentResult(**base)


def test_a_clean_exit_with_commits_proceeds_to_the_gates(config):
    verdict = classify_exit(a_result(), commits_made=3, config=config)

    assert verdict == "ok"


def test_a_timeout_is_a_stall(config):
    verdict = classify_exit(a_result(exit_code=124, timed_out=True), commits_made=1,
                            config=config)

    assert verdict == "stall"


def test_a_clean_exit_with_no_commits_is_a_stall(config):
    """The agent believes it finished and produced nothing. Retrying the *agent*
    is right here in a way it never is after a red suite."""
    verdict = classify_exit(a_result(), commits_made=0, config=config)

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
