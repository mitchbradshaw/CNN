"""A thin, deterministic wrapper over the `git` CLI.

Deliberately thin. Every method is one git invocation whose output is parsed in
one obvious way, because git is the ledger this whole design rests on: if the
orchestrator and git ever disagree about what landed, git is right and this
module is how that is discovered.

Two rules the callers depend on:

* A failed git command raises. It never returns an empty string that a caller
  could mistake for "nothing changed" — a silently-empty `files_changed` would
  turn the scope gate into a no-op.
* A failed merge cleans up after itself, so the integration branch is never
  left half-merged for the next ticket to cut from.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    """A git command failed, or its output could not be trusted."""


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str


class Git:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    # ------------------------------------------------------------------ core

    def run(self, *args: str, check: bool = True) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and result.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed ({result.returncode})\n"
                f"{result.stdout}\n{result.stderr}".strip()
            )
        return result.stdout.strip()

    def try_run(self, *args: str) -> tuple[int, str]:
        result = subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        return result.returncode, (result.stdout + result.stderr).strip()

    # --------------------------------------------------------------- queries

    def rev_parse(self, ref: str) -> str:
        return self.run("rev-parse", "--verify", f"{ref}^{{commit}}")

    def current_branch(self) -> str:
        return self.run("rev-parse", "--abbrev-ref", "HEAD")

    def branch_exists(self, name: str) -> bool:
        code, _ = self.try_run("show-ref", "--verify", "--quiet", f"refs/heads/{name}")
        return code == 0

    def merge_base(self, a: str, b: str) -> str:
        return self.run("merge-base", a, b)

    def is_merged(self, branch: str, into: str) -> bool:
        """True when every commit on `branch` is already reachable from `into`."""
        code, _ = self.try_run("merge-base", "--is-ancestor", branch, into)
        return code == 0

    def commits_between(self, base: str, branch: str) -> list[Commit]:
        """Commits on `branch` since it diverged from `base`, oldest first."""
        out = self.run("log", "--reverse", "--no-merges", "--format=%H%x00%s",
                       f"{base}..{branch}")
        return [
            Commit(*line.split("\x00", 1))
            for line in out.splitlines() if "\x00" in line
        ]

    def merge_commits(self, branch: str) -> list[Commit]:
        """The landing order: `git log --merges`, newest first."""
        out = self.run("log", "--merges", "--format=%H%x00%s", branch)
        return [
            Commit(*line.split("\x00", 1))
            for line in out.splitlines() if "\x00" in line
        ]

    def files_changed(self, base: str, branch: str) -> list[str]:
        """Three-dot: what `branch` changed, not what `base` moved on to."""
        out = self.run("diff", "--name-only", f"{base}...{branch}")
        return [line for line in out.splitlines() if line]

    def files_in_commit(self, sha: str) -> list[str]:
        out = self.run("show", "--name-only", "--format=", sha)
        return [line for line in out.splitlines() if line]

    def diff(self, base: str, branch: str) -> str:
        return self.run("diff", f"{base}...{branch}")

    def merge_in_progress(self) -> bool:
        return (self.root / ".git" / "MERGE_HEAD").exists()

    def is_clean(self) -> bool:
        return self.run("status", "--porcelain") == ""

    # --------------------------------------------------------------- writing

    def create_branch(self, name: str, start_point: str) -> str:
        self.run("branch", name, start_point)
        return self.rev_parse(name)

    def delete_branch(self, name: str, *, force: bool = True) -> None:
        self.run("branch", "-D" if force else "-d", name)

    def checkout(self, ref: str) -> None:
        self.run("checkout", ref)

    def merge_no_ff(self, branch: str, message: str) -> str:
        """Merge `branch` into the current branch, always with a merge commit.

        `--no-ff` is not a preference: one merge commit per ticket is what makes
        `git revert -m 1 <sha>` remove exactly one ticket's work.
        """
        code, output = self.try_run("merge", "--no-ff", "--no-edit", "-m", message, branch)
        if code != 0:
            # Never leave a half-merge behind for the next ticket to cut from.
            self.try_run("merge", "--abort")
            raise GitError(f"merge of {branch} failed:\n{output}")
        return self.rev_parse("HEAD")

    def revert_merge(self, merge_sha: str, *, mainline: int = 1) -> str:
        code, output = self.try_run("revert", "--no-edit", "-m", str(mainline), merge_sha)
        if code != 0:
            self.try_run("revert", "--abort")
            raise GitError(f"revert of merge {merge_sha} failed:\n{output}")
        return self.rev_parse("HEAD")

    # -------------------------------------------------------------- worktrees

    def worktree_add(self, path: Path | str, *, branch: str, start_point: str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.branch_exists(branch):
            self.run("worktree", "add", str(path), branch)
        else:
            self.run("worktree", "add", "-b", branch, str(path), start_point)
        return path

    def worktree_remove(self, path: Path | str, *, force: bool = True) -> None:
        args = ["worktree", "remove", str(path)]
        if force:
            args.append("--force")
        code, output = self.try_run(*args)
        if code != 0 and Path(path).exists():
            raise GitError(f"could not remove worktree {path}:\n{output}")
        self.try_run("worktree", "prune")

    def worktree_list(self) -> list[Path]:
        out = self.run("worktree", "list", "--porcelain")
        return [Path(line.split(" ", 1)[1]) for line in out.splitlines()
                if line.startswith("worktree ")]
