"""Launching `claude -p` in a worktree, and classifying how it came back.

The agent is the only non-deterministic thing in the system, and it is boxed:
one worktree, one ticket, a wall-clock budget, and a transcript that is kept
whatever happens.

Exit classification answers one question — *what kind of event was this?* — and
only two of the spec's four classes can be decided here. `red at exit` and
`review-rejected` are the gates' verdicts, not the process's, so an agent that
exits non-zero having done real work is classified `ok` and handed to the gates
to judge.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .backlog import Ticket
from .config import Config

#: Substrings that mark the failure as the environment's, not the ticket's.
#:
#: `configuration file` covers the CLI's own `~/.claude.json` being unreadable.
#: That file is global and shared, so concurrent agents can race on it — in
#: run-20260817-2050 two of three agents read it mid-write, looped on a parse
#: error for their whole budget, and the tickets were blamed for it.
INFRASTRUCTURE_MARKERS = (
    "rate_limit", "rate limit", "429", "overloaded_error", "api_error",
    "internal server error", "503", "econnreset", "connection error",
    "authentication_error", "credit balance",
    "configuration file", "is corrupted",
    # run-20260818-2244: every agent printed this and did nothing further —
    # a plan/session usage cap, not an API rate limit, but the same shape:
    # the environment can't do work right now, not "the ticket is wrong".
    "out of extra usage", "out of usage",
)

PROMPT = """\
You are working ticket {label} in this repository.

Your ticket is {ticket_path}. Read it, and read CLAUDE.md and
docs/CODING_STANDARDS.md. Those three files are your whole brief — do not read
other tickets, and do not read docs/PIPELINE_PRD.md beyond the section your
ticket points at.

Work test-first. Your FIRST commit must touch only tests/ and must contain a
test that FAILS. This is checked mechanically: the orchestrator checks out that
commit and runs the test, and a ticket whose first test passes on arrival is
quarantined before implementation begins.

Then: make it pass with the simplest change, refactor, commit. Prefix every
commit message with the ticket id, e.g. "{label}: bind side-inputs by content".

Stay inside the files your ticket declares. Run `pytest` from this worktree root
before you finish; the suite must show no regressions.

Stop and say so rather than guessing if the ticket contradicts the PRD, if you
need a file another ticket owns, or if you need a new dependency.
"""

RETRY_PREFIX = """\
This is a RETRY. The previous attempt at this ticket stalled and was killed.
The tail of its transcript follows, so you can see where it got stuck — you are
starting again from a clean worktree, so do not assume any of its work exists.

--- previous attempt, transcript tail ---
{tail}
--- end of previous attempt ---

"""


@dataclass(frozen=True)
class AgentResult:
    exit_code: int
    transcript: str
    duration_seconds: float
    timed_out: bool = False
    #: Killed for going `stall_minutes` without a new commit, rather than at the
    #: budget. Distinct from `timed_out` so the run log can say which bound hit,
    #: and it says nothing about whether the work so far is any good — an agent
    #: that finished and then hung trips this having done everything asked.
    stalled_without_commit: bool = False


def build_prompt(ticket: Ticket, config: Config, *,
                 previous_transcript_tail: str = "") -> str:
    """The brief handed to one agent: its own ticket, and nothing else's."""
    try:
        ticket_path = ticket.path.relative_to(config.paths.repo_root)
    except ValueError:
        ticket_path = ticket.path

    prompt = PROMPT.format(label=ticket.label, ticket_path=ticket_path.as_posix())
    if previous_transcript_tail:
        prompt = RETRY_PREFIX.format(tail=previous_transcript_tail) + prompt
    return prompt


def run_agent(cli, *, cwd: Path | str, prompt: str, model: str, budget_minutes: float,
              extra_args=(), transcript_path: Path | str | None = None,
              stall_minutes: float | None = None, commit_count=None,
              poll_seconds: float = 5.0) -> AgentResult:
    """Run one agent to completion, its budget, or its death.

    With `stall_minutes` and `commit_count` supplied, the agent is also killed
    early once it has gone that long without a *new* commit. Progress is measured
    in commits and not in output on purpose: both failures this exists to catch
    emit output happily. One is a CLI looping on a config parse error, which
    produces nothing but noise; the other is an agent that finished its work and
    then hung, which produced everything it was asked for. Killing is not a
    verdict on either — the commits go to the gates regardless, and the gates
    decide.
    """
    argv = [*cli, "-p", prompt, "--model", model, *extra_args]
    started = time.monotonic()
    timed_out = False
    stalled_without_commit = False

    watch_for_stall = stall_minutes is not None and commit_count is not None

    try:
        if not watch_for_stall:
            completed = subprocess.run(
                argv, cwd=str(Path(cwd)), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=budget_minutes * 60,
            )
            exit_code = completed.returncode
            transcript = completed.stdout + completed.stderr
        else:
            exit_code, transcript, timed_out, stalled_without_commit = _run_watched(
                argv, cwd=cwd, budget_minutes=budget_minutes,
                stall_minutes=stall_minutes, commit_count=commit_count,
                poll_seconds=poll_seconds,
            )
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        transcript = _decode(exc.stdout) + _decode(exc.stderr)
        transcript += (f"\n[orchestrator] agent exceeded its {budget_minutes:g} minute "
                       f"budget and was killed\n")
    except OSError as exc:
        exit_code = 127
        transcript = f"[orchestrator] agent could not be launched: {exc}\n"

    result = AgentResult(
        exit_code=exit_code,
        transcript=transcript,
        duration_seconds=time.monotonic() - started,
        timed_out=timed_out,
        stalled_without_commit=stalled_without_commit,
    )

    if transcript_path is not None:
        transcript_path = Path(transcript_path)
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(result.transcript, encoding="utf-8")

    return result


def _run_watched(argv, *, cwd, budget_minutes: float, stall_minutes: float,
                 commit_count, poll_seconds: float):
    """Popen plus a poll loop, returning `(exit_code, transcript, timed_out, stalled)`.

    Output goes to a temp file rather than a pipe: an agent that fills a pipe
    buffer nobody is draining deadlocks, and the whole point here is to keep
    watching while it talks.
    """
    import tempfile

    started = time.monotonic()
    budget_deadline = started + budget_minutes * 60
    #: Reset on every new commit, so the deadline measures silence rather than
    #: total runtime. T35 in run-20260817-2050 committed twice inside twelve
    #: minutes and then hung for another forty-eight; a deadline anchored to the
    #: start would have left all forty-eight of them on the clock.
    quiet_since = started
    last_commits = 0
    timed_out = False
    stalled = False

    with tempfile.TemporaryDirectory() as scratch:
        sink_path = Path(scratch) / "transcript"
        with open(sink_path, "w+b") as sink:
            process = subprocess.Popen(
                argv, cwd=str(Path(cwd)), stdout=sink, stderr=subprocess.STDOUT,
            )
            try:
                while True:
                    try:
                        process.wait(timeout=poll_seconds)
                        break
                    except subprocess.TimeoutExpired:
                        pass

                    now = time.monotonic()
                    if now >= budget_deadline:
                        timed_out = True
                        break

                    commits = commit_count()
                    if commits != last_commits:
                        last_commits = commits
                        quiet_since = now
                    elif now - quiet_since >= stall_minutes * 60:
                        stalled = True
                        break
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

        transcript = sink_path.read_bytes().decode("utf-8", "replace")

    if timed_out:
        exit_code = 124
        transcript += (f"\n[orchestrator] agent exceeded its {budget_minutes:g} minute "
                       f"budget and was killed\n")
    elif stalled:
        exit_code = 124
        transcript += (f"\n[orchestrator] agent made no new commit in {stall_minutes:g} "
                       f"minutes and was killed. Whatever it had already committed "
                       f"still goes to the gates.\n")
    else:
        exit_code = process.returncode

    return exit_code, transcript, timed_out, stalled


def _decode(stream) -> str:
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", "replace")
    return stream


def looks_like_rate_limiting(result: AgentResult, commits_made: int,
                             config: Config) -> bool:
    """The fleet-wide signature: fast exit, non-zero code, no commits.

    `claude-retry.log` records the naive version — one agent retrying every 3
    seconds into a limit it had already hit. Three agents doing that
    independently is 60 requests a minute into a closed door, which is why this
    is detected across agents rather than inside one.
    """
    return (result.exit_code != 0
            and commits_made == 0
            and result.duration_seconds < config.rate_limit.fast_exit_seconds)


def classify_exit(result: AgentResult, *, commits_made: int, config: Config) -> str:
    """`ok` | `infrastructure` | `stall`.

    `red at exit` and `review-rejected` are the gates' verdicts, not this
    function's — an agent that exited non-zero after real work still goes to
    the gates, because the gates are what judge the work.

    That principle governs timeouts too, which it did not until
    run-20260817-2050: a hung process is a process failure, but its commits are
    still work, and only the gates can say whether the work is any good.
    Commits, not the exit path, decide whether there is anything to judge.
    """
    # Checked before `timed_out`, because the environment can break in ways that
    # present as a timeout: a CLI that cannot read its own config never exits,
    # and grading that as a stall spends the ticket's one retry, quarantines it,
    # and counts it toward the circuit breaker for something it did not do.
    # The `exit_code != 0` guard stays: an agent that finished cleanly and merely
    # *mentioned* a rate limit in its output has not hit one, and quarantining it
    # for the word would be worse than the bug this reordering fixes.
    lowered = result.transcript.lower()
    if result.exit_code != 0 and any(m in lowered for m in INFRASTRUCTURE_MARKERS):
        return "infrastructure"

    if (result.timed_out or result.stalled_without_commit) and commits_made == 0:
        return "stall"

    if looks_like_rate_limiting(result, commits_made, config):
        return "infrastructure"

    if commits_made == 0:
        # The agent believes it finished and produced nothing. Retrying the
        # agent is right here in a way it never is after a red suite.
        return "stall"

    return "ok"
