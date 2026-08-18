"""Gate 1 — TDD is verified, not trusted.

The agent's first commit must touch only `tests/`. The orchestrator checks out
that commit and runs the new test file: it **must fail**. A ticket that cannot
produce a failing test first is quarantined before any implementation happens,
which is cheap.

The gate deliberately runs only the newly added test file, not the whole suite.
The question is whether *this* test was red before its implementation existed —
a suite that happened to be red for an unrelated reason would answer a different
question and pass a vacuous test.

**Why a collection error counts as red here.** `exit_code != 0` is the whole
test, so a test file that cannot even be imported passes this gate. That is
usually correct and is ordinary TDD: the file imports a module the ticket has
not written yet. It is only trustworthy, though, because `capture_baseline`
refuses to start a run whose collection is interrupted — so by the time any red
proof runs, the worktree fixture is known sound and an import failure is
attributable to the ticket's own new test rather than to broken provisioning.
In run-20260817-1157 that guard did not exist, and T03's red proof was a
`FileNotFoundError` from an empty channel directory: a false red, on a gate
whose entire purpose is to refuse tests that assert nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..gitops import Git
from .suite import run_suite


@dataclass(frozen=True)
class RedProofVerdict:
    status: str                      # pass | fail
    detail: str = ""
    first_commit: str = ""
    test_files: tuple[str, ...] = ()
    output: str = ""


def check_red_proof(git: Git, worktree_path: Path | str, *, base: str, branch: str,
                    command, timeout_minutes: float,
                    tests_prefix: str = "tests/") -> RedProofVerdict:
    commits = git.commits_between(base, branch)
    if not commits:
        return RedProofVerdict("fail", detail="branch has no commits")

    first = commits[0]
    touched = git.files_in_commit(first.sha)

    outside = [f for f in touched if not f.startswith(tests_prefix)]
    if outside:
        return RedProofVerdict(
            "fail",
            detail=f"first commit touched non-test files: {', '.join(sorted(outside))}",
            first_commit=first.sha,
        )

    test_files = tuple(f for f in touched
                       if f.startswith(tests_prefix) and f.endswith(".py"))
    if not test_files:
        return RedProofVerdict(
            "fail",
            detail=f"first commit contains no test file: {', '.join(sorted(touched))}",
            first_commit=first.sha,
        )

    worktree = Git(worktree_path)
    restore_to = worktree.current_branch()
    # `checkout` alone only touches files that differ between the two commits
    # — it does not remove untracked files, and it leaves alone a tracked file
    # whose uncommitted edit doesn't conflict with the target tree. An agent
    # that stalled after its first commit routinely leaves exactly this behind
    # (a part-written implementation, never `git add`ed), and without cleaning
    # it first the isolated check silently grades the test against that
    # leftover work instead of against the commit it is supposed to verify —
    # a false green that reads as "this test never failed".
    worktree.run("checkout", "--force", "--detach", first.sha)
    # Best-effort: `nul` (Windows' reserved device name) turns up as a stray
    # untracked file surprisingly often — some tool in an agent's session
    # redirects output with POSIX-style `> /dev/null` semantics that Windows
    # doesn't honour, and it creates a literal file called `nul` instead.
    # Win32 refuses to delete a file with that name through the ordinary
    # path, so `git clean` exits non-zero even after successfully removing
    # everything else. That must not abort the whole gate over one inert
    # leftover file `run_suite` was never going to collect anyway.
    worktree.try_run("clean", "-fd")
    try:
        result = run_suite(worktree_path, command, timeout_minutes=timeout_minutes,
                           node_ids=list(test_files))
    finally:
        # Whatever happened, the worktree goes back where the agent left it.
        worktree.run("checkout", restore_to)

    if result.exit_code == 0:
        return RedProofVerdict(
            "fail",
            detail=("the first commit's test passed on arrival — a test that never "
                    "failed asserts nothing"),
            first_commit=first.sha, test_files=test_files, output=result.output,
        )

    return RedProofVerdict("pass", detail=f"{len(result.failed)} failing at the test-only commit",
                           first_commit=first.sha, test_files=test_files,
                           output=result.output)
