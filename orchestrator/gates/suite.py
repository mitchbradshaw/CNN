"""Gate 2 — the suite, compared against the run's baseline.

The gate is **no regressions**, never a fixed count: every merged ticket adds
tests, so a hardcoded 486 is wrong by the second merge.

Tracking only the *failing* set is enough to express that. A test that fails now
and did not fail at baseline is a regression; a test that failed at baseline and
still fails is the known-broken state the run started in. Recording the passing
set as well would cost a `-v` run of 486 lines and tell us nothing more.

The **flake amendment** lives here: on red, re-run only the failing node ids,
exactly once. A real regression reproduces every time, so this does not weaken
the gate against anything it exists to catch. What it prevents is a known-flaky
test quarantining innocent tickets and tripping the circuit breaker.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

#: pytest's short summary lines, e.g. `FAILED tests/test_x.py::test_y - AssertionError`
SUMMARY_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)

#: Stands in for a red the runner could not attribute to a node id — a
#: collection error, an internal pytest error, a timeout. It is not a node id
#: and must never be handed back to pytest as one.
UNATTRIBUTED = "<no node id: pytest exited {exit_code}>"
UNATTRIBUTED_PREFIX = "<no node id:"


@dataclass(frozen=True)
class SuiteResult:
    exit_code: int
    failed: tuple[str, ...]
    output: str
    duration_seconds: float
    timed_out: bool = False


@dataclass(frozen=True)
class SuiteVerdict:
    status: str                      # pass | flaky | fail
    regressions: tuple[str, ...] = ()
    flaky: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    output: str = ""
    rerun_output: str = ""
    timed_out: bool = False


def parse_failures(output: str) -> tuple[str, ...]:
    """Node ids from pytest's short summary, in first-seen order."""
    seen: dict[str, None] = {}
    for match in SUMMARY_LINE.finditer(output):
        seen.setdefault(match.group(1), None)
    return tuple(seen)


def run_suite(cwd: Path | str, command, *, timeout_minutes: float,
              node_ids=None) -> SuiteResult:
    """Run the suite in `cwd`. Never under `-n` — see `tests/_session_isolation.py`."""
    import time

    argv = list(command) + (list(node_ids) if node_ids else [])
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            argv, cwd=str(Path(cwd)), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout_minutes * 60,
        )
        exit_code = completed.returncode
        output = completed.stdout + completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        output = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        output += f"\n[orchestrator] suite exceeded {timeout_minutes} minutes and was killed\n"

    failed = parse_failures(output)
    if exit_code != 0 and not failed:
        # A collection error, an internal pytest error, or a timeout produces a
        # non-zero exit with no FAILED lines. It must never read as green.
        failed = (UNATTRIBUTED.format(exit_code=exit_code),)

    return SuiteResult(
        exit_code=exit_code,
        failed=failed,
        output=output,
        duration_seconds=time.monotonic() - started,
        timed_out=timed_out,
    )


def check_suite(cwd: Path | str, command, *, baseline_failed, timeout_minutes: float,
                ) -> SuiteVerdict:
    """Run the suite and grade it against the baseline, with one re-run on red."""
    baseline = set(baseline_failed)
    result = run_suite(cwd, command, timeout_minutes=timeout_minutes)
    regressions = tuple(n for n in result.failed if n not in baseline)

    if not regressions:
        return SuiteVerdict(status="pass", failed=result.failed, output=result.output,
                            timed_out=result.timed_out)

    if result.timed_out:
        # A timeout is not a flake to be re-run; it is a stall in the suite.
        return SuiteVerdict(status="fail", regressions=regressions, failed=result.failed,
                            output=result.output, timed_out=True)

    if any(n.startswith(UNATTRIBUTED_PREFIX) for n in regressions):
        # There is no node id to re-run. Handing the placeholder back to pytest
        # asks a nonsense question, gets a different nonsense answer, and the
        # mismatch would read as "passed on re-run" — turning a hard red into a
        # merge. A red the runner cannot attribute is simply red.
        return SuiteVerdict(status="fail", regressions=regressions, failed=result.failed,
                            output=result.output)

    rerun = run_suite(cwd, command, timeout_minutes=timeout_minutes, node_ids=regressions)
    still_failing = tuple(n for n in regressions if n in set(rerun.failed))

    if still_failing:
        return SuiteVerdict(status="fail", regressions=still_failing, failed=result.failed,
                            output=result.output, rerun_output=rerun.output)

    # Passed on re-run. A FLAKY mark is a finding, not a shrug: the ids and both
    # outputs are retained, and the run loop counts it toward the breaker.
    return SuiteVerdict(status="flaky", flaky=regressions, failed=result.failed,
                        output=result.output, rerun_output=rerun.output)
