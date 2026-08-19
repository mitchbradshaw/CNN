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

import json
import re
import subprocess
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
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


#: `You're out of extra usage · resets 3:30am (Australia/Brisbane)`, and the
#: several ways the CLI says the same thing. The hour is the only part worth
#: reading: the timezone is the machine's own, and a run that guesses at a UTC
#: offset waits for the wrong dawn.
RESET_TIME = re.compile(r"resets?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.IGNORECASE)


@dataclass(frozen=True)
class AgentUsage:
    """What one `claude -p` session actually consumed.

    Recorded because `ORCHESTRATOR_SPEC.md` §REPORT.md has always asked for it
    and five runs shipped without it. Every model-tier decision in `config.toml`
    — capping tickets to sonnet, moving review off opus — was taken against no
    measurement at all.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    num_turns: int = 0

    @property
    def total_tokens(self) -> int:
        """Every class of token, because every class of token is billed.

        Cache reads dominate a long agent session by an order of magnitude.
        Reporting `input_tokens` alone would show four thousand against a
        session that moved three million, which is worse than showing nothing.
        """
        return (self.input_tokens + self.output_tokens
                + self.cache_creation_tokens + self.cache_read_tokens)

    def __add__(self, other: "AgentUsage | None") -> "AgentUsage":
        """A ticket costs its agent plus its reviews plus its fix rounds."""
        if other is None:
            return self
        return AgentUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
            num_turns=self.num_turns + other.num_turns,
        )

    __radd__ = __add__


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
    #: `None` when the CLI emitted nothing parseable — an older binary, a killed
    #: agent that never reached its result line, a schema that has moved on.
    #: A missing measurement must read as missing and never as zero.
    usage: AgentUsage | None = None
    #: The raw bytes the CLI produced, kept when `transcript` is a reconstruction
    #: of them. This is what a human reads when the reconstruction looks wrong.
    raw: str = ""


def extract_usage(raw: str) -> AgentUsage | None:
    """Pull the cost record out of `--output-format json` or `stream-json`.

    Deliberately forgiving. The CLI's output schema is not ours, and a harness
    that hard-fails on an unrecognised line is worse than one that reports
    nothing: the cost column is a convenience, and the run is not.
    """
    record = _last_result_record(raw)
    if record is None:
        return None

    usage = record.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}

    def count(*keys) -> int:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, (int, float)):
                return int(value)
        return 0

    return AgentUsage(
        input_tokens=count("input_tokens"),
        output_tokens=count("output_tokens"),
        cache_creation_tokens=count("cache_creation_input_tokens", "cache_creation_tokens"),
        cache_read_tokens=count("cache_read_input_tokens", "cache_read_tokens"),
        cost_usd=float(record.get("total_cost_usd") or record.get("cost_usd") or 0.0),
        num_turns=int(record.get("num_turns") or 0),
    )


def extract_text(raw: str) -> str:
    """Reconstruct readable prose from a structured session.

    Everything downstream reads prose: the review gate greps the transcript for
    a fenced ```findings``` block, the stall retry injects the tail into the next
    prompt, and a human reads it at 8am. If structured output buried the findings
    block inside a JSON string literal, every review would silently return zero
    findings and every ticket would merge unreviewed — so this is load-bearing,
    not cosmetic.

    Text that is not structured comes back untouched, which is what keeps the
    `output_format = "text"` path and every existing test working.
    """
    lines = raw.splitlines()
    records = [parsed for parsed in (_json_object(line) for line in lines)
               if parsed is not None]
    if not records:
        return raw

    chunks: list[str] = []
    for record in records:
        kind = record.get("type")
        if kind == "assistant":
            message = record.get("message") or {}
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    chunks.append(str(block.get("text", "")))
        elif kind == "result":
            result = record.get("result")
            if isinstance(result, str) and result:
                chunks.append(result)

    if not chunks:
        return raw

    # Anything the CLI printed outside the JSON stream — an orchestrator note
    # appended after a kill, a stray stderr line — is kept. It is usually the
    # most important line in the file.
    unstructured = [line for line in lines
                    if line.strip() and _json_object(line) is None]
    return "\n\n".join(chunks + unstructured) + "\n"


def parse_reset_delay_seconds(transcript: str, *, now: datetime | None = None
                              ) -> float | None:
    """Seconds until the usage window the transcript names reopens.

    `rate_limit.max_backoff_seconds` was fifteen minutes against a cap that
    resets in hours, so the runner gave up long before the environment
    recovered. The CLI prints the answer; this reads it.

    Returns `None` when no reset time is named — a plain 429 carries no such
    sentence, and the caller must fall back to exponential backoff rather than
    invent a wait.
    """
    match = RESET_TIME.search(transcript)
    if match is None:
        return None

    now = now or datetime.now()
    hour = int(match.group(1)) % 12
    minute = int(match.group(2) or 0)
    if match.group(3).lower() == "pm":
        hour += 12

    if not (0 <= minute < 60):
        return None

    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)   # `resets 3:30am` read at 4am means tomorrow
    return (target - now).total_seconds()


def _last_result_record(raw: str) -> dict | None:
    """The final `{"type":"result"}` object, whichever output format produced it."""
    for line in reversed(raw.splitlines()):
        record = _json_object(line)
        if record is not None and record.get("type") == "result":
            return record
    # `--output-format json` may pretty-print across several lines rather than
    # emitting one object per line.
    whole = _json_object(raw)
    if whole is not None and whole.get("type") == "result":
        return whole
    return None


def _json_object(text: str) -> dict | None:
    text = text.strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


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
              poll_seconds: float = 5.0, output_format: str = "text",
              max_budget_usd: float = 0.0) -> AgentResult:
    """Run one agent to completion, its budget, or its death.

    With `stall_minutes` and `commit_count` supplied, the agent is also killed
    early once it has gone that long without a *new* commit. Progress is measured
    in commits and not in output on purpose: both failures this exists to catch
    emit output happily. One is a CLI looping on a config parse error, which
    produces nothing but noise; the other is an agent that finished its work and
    then hung, which produced everything it was asked for. Killing is not a
    verdict on either — the commits go to the gates regardless, and the gates
    decide.

    `output_format` buys the cost record. `stream-json` is preferred over `json`
    for one reason: it emits a line per turn, so an agent that is killed still
    leaves a transcript behind. Under `json` a killed agent leaves nothing at
    all, which is the defect FOLLOWUPS.md records as `[open]` after T35's
    69-byte transcript.

    `max_budget_usd` is a hard ceiling the CLI enforces on itself. Zero means
    no ceiling.
    """
    argv = [*cli, "-p", prompt, "--model", model]
    if output_format and output_format != "text":
        argv += ["--output-format", output_format]
        if output_format == "stream-json":
            # The CLI refuses stream-json without it.
            argv += ["--verbose"]
    if max_budget_usd and max_budget_usd > 0:
        argv += ["--max-budget-usd", str(max_budget_usd)]
    argv += list(extra_args)
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
        transcript=extract_text(transcript),
        duration_seconds=time.monotonic() - started,
        timed_out=timed_out,
        stalled_without_commit=stalled_without_commit,
        usage=extract_usage(transcript),
        raw=transcript,
    )

    if transcript_path is not None:
        transcript_path = Path(transcript_path)
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(result.transcript, encoding="utf-8")
        # The structured stream is kept beside the prose rather than instead of
        # it: the prose is what gets read, and the stream is what gets believed
        # when the prose looks wrong.
        if result.raw and result.raw != result.transcript:
            transcript_path.with_suffix(".jsonl").write_text(
                result.raw, encoding="utf-8")

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
    # Both, because they are not always the same text: a CLI that dies before
    # emitting a single JSON line leaves only `raw`, and a reconstruction that
    # dropped a stderr line would silently lose the marker with it.
    lowered = (result.transcript + "\n" + result.raw).lower()
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
