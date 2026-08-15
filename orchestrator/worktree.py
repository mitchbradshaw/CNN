"""Per-ticket worktree provisioning and teardown.

One `git worktree` per in-flight ticket, cut from the run's integration branch.
Worktrees share the object store and cost nothing to create.

Two provisioning decisions carry the isolation guarantee:

* The fixture database is **copied**, never linked. An agent that cannot reach
  the 11,000-row database also cannot damage it.
* Recording directories are **junctioned**, never copied — they are read-only
  and large. `.git/config` has `symlinks = false`; junctions are unaffected.

Teardown removes the worktree and keeps the branch. A quarantined ticket's work
has to survive until the morning.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .gitops import Git, GitError


class ProvisionError(Exception):
    """A worktree could not be provisioned. Classified as infrastructure."""


@dataclass(frozen=True)
class Worktree:
    ticket_id: int
    path: Path
    branch: str


def _junction(link: Path, target: Path) -> None:
    """Directory junction on Windows, symlink elsewhere.

    `mklink /J` needs no elevation, unlike a symlink, which is why the spec
    names it specifically.
    """
    link.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise ProvisionError(
                f"could not junction {link} -> {target}: "
                f"{(result.stdout + result.stderr).strip()}"
            )
    else:
        link.symlink_to(target, target_is_directory=True)


def provision(git: Git, *, ticket_id: int, worktrees_root: Path | str,
              integration_branch: str, branch_prefix: str,
              fixture_db: Path | str, fixture_db_dest: str,
              recordings: list[Path] | tuple[Path, ...] = ()) -> Worktree:
    """Create and populate the worktree for one ticket."""
    branch = f"{branch_prefix}T{ticket_id:02d}"
    path = Path(worktrees_root) / f"T{ticket_id:02d}"
    fixture_db = Path(fixture_db)

    if not fixture_db.is_file():
        raise ProvisionError(
            f"fixture database missing at {fixture_db} — refusing to provision a "
            f"worktree with no database rather than let the agent find the real one"
        )

    if path.exists():
        raise ProvisionError(f"{path} already exists; tear the previous worktree down first")

    try:
        git.worktree_add(path, branch=branch, start_point=integration_branch)
    except GitError as exc:
        raise ProvisionError(str(exc)) from exc

    destination = path / fixture_db_dest
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fixture_db, destination)

    for source in recordings:
        source = Path(source)
        if not source.is_dir():
            raise ProvisionError(f"recording directory missing: {source}")
        _junction(path / source.name, source)

    return Worktree(ticket_id=ticket_id, path=path, branch=branch)


def teardown(git: Git, worktree: Worktree) -> None:
    """Remove the worktree. The branch stays — it is the ticket's evidence."""
    # Junctions must be unlinked before the tree is removed, or a recursive
    # delete walks into the shared read-only recordings and deletes those too.
    if worktree.path.exists():
        for child in worktree.path.iterdir():
            if child.is_dir() and child.is_symlink():
                child.unlink()
            elif child.is_dir() and _is_junction(child):
                child.rmdir()

    git.worktree_remove(worktree.path)


def _is_junction(path: Path) -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(path.lstat().st_file_attributes & 0x400)  # REPARSE_POINT
    except (OSError, AttributeError):
        return False
