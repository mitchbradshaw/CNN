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
