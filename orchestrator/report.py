"""The run directory and `REPORT.md`.

The requirement: the next morning, a fault isolates to one ticket without a full
re-audit. `REPORT.md` is one row per ticket; you open a ticket directory only
for the rows that are red.

```
runs/<label>-<timestamp>/
  REPORT.md          one table row per ticket
  plan.md            the run-plan preview as printed at launch
  state.json         the DAG state, written atomically on every transition
  T17/
    transcript.log   the full agent session
    red-proof.txt    the test output at the test-only commit
    suite.txt        the full suite output on the branch
    post-merge.txt   the full suite output after merging
    review.json      structured findings
    review.md        the reviewer's prose
    scope.txt        files touched vs files declared
    diff.patch
```
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import status as st
from .backlog import Backlog
from .state import RunState

#: Gate name -> the letter the legend promises. Not `name[0].upper()`: that
#: renders scope as `S` (colliding with suite) and review as `R` (colliding with
#: red-proof), so `R✓ S✓ S✓ R✓ O✓` gives no way to tell which gate failed.
GATE_ORDER = (
    ("red_proof", "R"),
    ("suite", "S"),
    ("scope", "C"),
    ("review", "V"),
    ("overlap", "O"),
)
#: `blocked` is the review gate's own word for a fail (gates/review.py) and has
#: to be mapped, or the one column that explains a review-rejected ticket prints
#: `V?`.
GATE_MARK = {"pass": "✓", "warn": "!", "fail": "✗", "blocked": "✗", "flaky": "~",
             "hold": "H", "skipped": "-", "not-run": "-"}


@dataclass(frozen=True)
class RunDirectory:
    path: Path

    @classmethod
    def create(cls, runs_root: Path | str, *, label: str, timestamp: str) -> RunDirectory:
        path = Path(runs_root) / f"{label}-{timestamp}"
        path.mkdir(parents=True, exist_ok=True)
        return cls(path=path)

    @property
    def state_path(self) -> Path:
        return self.path / "state.json"

    @property
    def report_path(self) -> Path:
        return self.path / "REPORT.md"

    @property
    def plan_path(self) -> Path:
        return self.path / "plan.md"

    def ticket_dir(self, ticket_id: int) -> Path:
        directory = self.path / f"T{ticket_id:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def artifact(self, ticket_id: int, name: str) -> Path:
        return self.ticket_dir(ticket_id) / name

    def write(self, ticket_id: int, name: str, content: str) -> Path:
        path = self.artifact(ticket_id, name)
        path.write_text(content or "", encoding="utf-8")
        return path


def _duration(record) -> str:
    if not (record.started_at and record.ended_at):
        return "—"
    try:
        started = datetime.fromisoformat(record.started_at)
        ended = datetime.fromisoformat(record.ended_at)
    except ValueError:
        return "—"
    minutes = int((ended - started).total_seconds() // 60)
    return f"{minutes // 60}h{minutes % 60:02d}"


def _gates(record) -> str:
    return " ".join(
        f"{letter}{GATE_MARK.get(record.gates.get(name, 'not-run'), '?')}"
        for name, letter in GATE_ORDER
    )


def render_report(state: RunState, backlog: Backlog) -> str:
    lines = [
        f"# REPORT — {state.run_id}",
        "",
        f"Integration branch: `{state.integration_branch}`  ",
        f"Base: `{state.base_sha}`  ·  started {state.started_at}  ·  "
        f"wall-clock stop {state.wall_clock_stop}",
        "",
        "Review this branch as one diff and fast-forward `main` yourself, or throw the "
        "night away with `git branch -D`.",
        f"To remove exactly one ticket's work: `git revert -m 1 <merge sha>` on "
        f"`{state.integration_branch}`.",
        "",
    ]

    if state.circuit_breaker.tripped:
        lines += [
            "> **The circuit breaker tripped and the run halted.** "
            "Read the quarantined rows below before restarting — this is the "
            "difference between one ticket being wrong and the base being broken.",
            "",
        ]

    lines += _flake_section(state)
    lines += _table_section(state, backlog)
    lines += _human_verify_section(state, backlog)
    lines += _waiting_section(state, backlog)

    return "\n".join(lines) + "\n"


def _flake_section(state: RunState) -> list[str]:
    counts = Counter(
        test for record in state.tickets.values() for test in record.flaky_tests
    )
    repeats = {test: n for test, n in counts.items() if n >= 2}
    if not repeats:
        return []

    lines = ["## Flaky tests — work to be ticketed", "",
             "Marked `FLAKY` more than once in a single run. A `FLAKY` mark is a "
             "finding, not a shrug.", ""]
    for test, n in sorted(repeats.items(), key=lambda kv: (-kv[1], kv[0])):
        times = "twice" if n == 2 else f"{n}×"
        lines.append(f"- `{test}` — marked flaky {times}")
    lines.append("")
    return lines


def _table_section(state: RunState, backlog: Backlog) -> list[str]:
    lines = [
        "## Tickets", "",
        "Gates: R=red-proof S=suite C=scope V=review O=overlap · "
        "`✓` pass `!` warn `✗` fail `~` flaky `H` hold `-` not run",
        "",
        "| # | model | status | wall | gates | review (std/spec) | scope deviations | "
        "overlap | merge |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    dispatched = [
        (int(key), record) for key, record in state.tickets.items()
        if record.status not in (st.PENDING, st.READY, st.HELD, st.BLOCKED_UPSTREAM)
    ]

    for ticket_id, record in sorted(dispatched):
        ticket = backlog[ticket_id] if ticket_id in backlog else None
        blockers = record.review_blockers or {}
        review = f"{blockers.get('standards', 0)}/{blockers.get('spec', 0)}"
        if record.review_rounds:
            review += f" ({record.review_rounds}r)"
        lines.append(
            f"| T{ticket_id:02d} "
            f"| {ticket.model if ticket else '—'} "
            f"| {record.status} "
            f"| {_duration(record)} "
            f"| {_gates(record)} "
            f"| {review} "
            f"| {', '.join(record.scope_deviations) or '—'} "
            f"| {', '.join(record.overlap_symbols) or '—'} "
            f"| {record.merge_sha[:7] if record.merge_sha else '—'} |"
        )

    if not dispatched:
        lines.append("| — | — | nothing dispatched | — | — | — | — | — | — |")

    lines.append("")
    return lines


def _human_verify_section(state: RunState, backlog: Backlog) -> list[str]:
    landed = [
        int(key) for key, record in state.tickets.items()
        if record.status == st.MERGED and int(key) in backlog
        and backlog[int(key)].human_verify
    ]
    if not landed:
        return []

    lines = ["## Needs your eyes — `human-verify`", "",
             "These landed normally. The headless construction test proves the surface "
             "is not blank; interaction and aesthetics are yours.", ""]
    for ticket_id in sorted(landed):
        lines.append(f"- **T{ticket_id:02d}** — {backlog[ticket_id].title}")
    lines.append("")
    return lines


def _waiting_section(state: RunState, backlog: Backlog) -> list[str]:
    held = sorted(int(k) for k, r in state.tickets.items() if r.status == st.HELD)
    upstream = sorted(int(k) for k, r in state.tickets.items()
                      if r.status == st.BLOCKED_UPSTREAM)
    if not held and not upstream:
        return []

    lines = ["## Waiting on you", ""]
    for ticket_id in held:
        title = backlog[ticket_id].title if ticket_id in backlog else ""
        lines.append(f"- **T{ticket_id:02d}** `human-gate` — {title}")
    if upstream:
        lines.append(
            "- Held downstream of a quarantined or gated ticket: "
            + ", ".join(f"T{i:02d}" for i in upstream)
        )
    lines.append("")
    return lines
