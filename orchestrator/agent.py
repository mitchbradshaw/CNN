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
INFRASTRUCTURE_MARKERS = (
    "rate_limit", "rate limit", "429", "overloaded_error", "api_error",
    "internal server error", "503", "econnreset", "connection error",
    "authentication_error", "credit balance",
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
              extra_args=(), transcript_path: Path | str | None = None) -> AgentResult:
    """Run one agent to completion, its budget, or its death."""
    argv = [*cli, "-p", prompt, "--model", model, *extra_args]
    started = time.monotonic()
    timed_out = False

    try:
        completed = subprocess.run(
            argv, cwd=str(Path(cwd)), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=budget_minutes * 60,
        )
        exit_code = completed.returncode
        transcript = completed.stdout + completed.stderr
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
    )

    if transcript_path is not None:
        transcript_path = Path(transcript_path)
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(result.transcript, encoding="utf-8")

    return result


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
    """
    if result.timed_out:
        return "stall"

    if looks_like_rate_limiting(result, commits_made, config):
        return "infrastructure"

    lowered = result.transcript.lower()
    if result.exit_code != 0 and any(m in lowered for m in INFRASTRUCTURE_MARKERS):
        return "infrastructure"

    if commits_made == 0:
        # The agent believes it finished and produced nothing. Retrying the
        # agent is right here in a way it never is after a red suite.
        return "stall"

    return "ok"
