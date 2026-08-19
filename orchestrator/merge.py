"""Merging a landed ticket into the integration branch.

Held behind a merge lock in the run loop, so this module can assume it is the
only thing touching the working tree while it runs.

Auto-merge is safe here precisely because the target is disposable. `main` is
never written by the runner; in the morning you review the integration branch as
one diff and fast-forward `main` yourself, or throw the night away with one
`git branch -D`.

Post-merge red is its own event: the branch was green alone and red merged.
Revert the merge, quarantine the ticket, continue. The integration branch is
never left red, because every subsequent ticket cuts from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .gates.suite import check_suite
from .gitops import Git, GitError


@dataclass(frozen=True)
class MergeResult:
    status: str                        # merged | reverted | conflict
    merge_sha: str | None = None
    regressions: tuple[str, ...] = ()
    detail: str = ""
    suite_output: str = ""


def merge_ticket(git: Git, *, ticket_id: int, branch: str, integration: str,
                 title: str, suite_command, baseline_failed,
                 timeout_minutes: float) -> MergeResult:
    """`--no-ff` into the integration branch, full suite after, revert on red."""
    if git.current_branch() != integration:
        git.checkout(integration)

    message = f"T{ticket_id:02d}: {title}"
    try:
        merge_sha = git.merge_no_ff(branch, message)
    except GitError as exc:
        # merge_no_ff aborts before raising, so the integration branch is intact.
        return MergeResult(status="conflict", detail=str(exc))

    verdict = check_suite(git.root, suite_command, baseline_failed=baseline_failed,
                          timeout_minutes=timeout_minutes)

    if verdict.status == "fail":
        git.revert_merge(merge_sha)
        return MergeResult(
            status="reverted",
            merge_sha=merge_sha,
            regressions=verdict.regressions,
            detail="post-merge suite regressed; merge reverted",
            suite_output=verdict.output + verdict.rerun_output,
        )

    return MergeResult(status="merged", merge_sha=merge_sha,
                       detail="flaky on the post-merge suite" if verdict.status == "flaky" else "",
                       suite_output=verdict.output)


def append_followups(git: Git, *, ticket_id: int, filename: str, findings) -> None:
    """Majors and minors merge, and land in FOLLOWUPS.md on the integration branch.

    A style finding that blocks a merge overnight also blocks every dependent
    ticket, and that cost is measured in milestones.
    """
    if not findings:
        return

    path = git.root / filename
    lines = []
    if not path.exists():
        lines.append("# Follow-ups\n")
        lines.append("\nRaised by the review gate and merged anyway. "
                     "See docs/ORCHESTRATOR_SPEC.md, gate 4.\n")

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"\n## T{ticket_id:02d} — {stamp}\n\n")
    for finding in findings:
        rule = f"rule {finding.rule}" if finding.rule else "no rule cited"
        lines.append(f"- [{finding.severity}] [{finding.axis}] ({rule}) {finding.summary}\n")

    with path.open("a", encoding="utf-8") as handle:
        handle.writelines(lines)

    git.run("add", filename)
    git.run("commit", "-m", f"T{ticket_id:02d}: record review follow-ups")


def append_run_postmortem(git: Git, *, state, backlog, filename: str) -> None:
    """Write the night's post-mortem skeleton into FOLLOWUPS.md, every run.

    FOLLOWUPS.md carries a hand-written harness section for runs 1157, 2050 and
    0554 — and nothing at all for 1114 and 2244, which were the two most recent
    and the two worst. The improvement loop was a habit, and habits lapse
    exactly when the run was bad enough to be worth writing up.

    Writing the stub mechanically changes what silence means. A section that is
    present but untriaged is visible; a section that was never written is not.
    The runner fills in what it can prove — outcomes, exit classes, cost — and
    leaves the diagnosis, which is the part that needs a human, as an empty
    checkbox.
    """
    from . import status as st

    run_id = getattr(state, "run_id", "unknown-run")
    records = [(int(key), record) for key, record in state.tickets.items()]
    dispatched = [(i, r) for i, r in records
                  if r.status not in (st.PENDING, st.READY, st.HELD, st.BLOCKED_UPSTREAM)]
    merged = [i for i, r in dispatched if r.status == st.MERGED]
    triage = sorted((i, r) for i, r in dispatched if r.status != st.MERGED)

    costed = [r for _, r in dispatched if r.cost_usd is not None]
    if costed:
        total = sum(r.cost_usd or 0.0 for r in costed)
        tokens = sum(r.tokens or 0 for r in costed)
        wasted = sum(r.cost_usd or 0.0 for _, r in dispatched
                     if r.status != st.MERGED and r.cost_usd is not None)
        cost_line = (f"{tokens / 1_000_000:.2f}M tokens, ${total:.2f} total, "
                     f"${wasted:.2f} of it on work that did not land. ")
    else:
        # Said out loud rather than omitted. A night with no cost line and a
        # night that cost nothing look identical otherwise, and the first is a
        # broken measurement while the second never happens.
        cost_line = ("Token cost not measured — check `agent.output_format` in "
                     "config.toml. ")

    path = git.root / filename
    lines = []
    if not path.exists():
        lines.append("# Follow-ups\n")
        lines.append("\nRaised by the review gate and merged anyway. "
                     "See docs/ORCHESTRATOR_SPEC.md, gate 4.\n")

    stamp = datetime.now().strftime("%Y-%m-%d")
    lines.append(f"\n## Harness — {stamp} (post-{run_id})\n\n")
    lines.append(f"{len(merged)} merged of {len(dispatched)} dispatched. {cost_line}"
                 f"Written by the runner; the triage below is not.\n\n")

    if state.circuit_breaker.tripped:
        lines.append(f"- [ ] **The circuit breaker tripped**: "
                     f"{state.circuit_breaker.reason}\n")

    if not triage:
        lines.append("- Nothing to triage: every dispatched ticket landed.\n")
    else:
        for ticket_id, record in triage:
            title = backlog[ticket_id].title if ticket_id in backlog else ""
            failed_gate = next(
                (name for name, verdict in record.gates.items()
                 if verdict in ("fail", "blocked", "hold")), "—")
            lines.append(
                f"- [ ] **T{ticket_id:02d}** {record.status}"
                f" ({record.exit_class or 'no exit class'}, gate: {failed_gate})"
                f" — {title}\n")
        lines.append("\nFor each: was this the ticket, or was this the harness? "
                     "A harness cause belongs in the runner's own tests before "
                     "the next run.\n")

    with path.open("a", encoding="utf-8") as handle:
        handle.writelines(lines)

    git.run("add", filename)
    git.run("commit", "-m", f"Runner: post-mortem stub for {run_id}")
