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
        # The link must keep the source's path relative to the repo root. Every
        # path constant in the suite is root-relative, so a junction dropped at
        # the worktree root is data nothing can find — indistinguishable from
        # having provisioned nothing, except that it looks like it worked.
        try:
            # Both sides resolved: a case or short-path mismatch here would
            # refuse every worktree in the run, not just this one.
            relative = source.resolve().relative_to(git.root.resolve())
        except ValueError:
            raise ProvisionError(
                f"recording directory {source} is not inside the repo root {git.root}, "
                f"so it has no path relative to the repo root to preserve — refusing "
                f"to guess where it belongs in the worktree"
            ) from None
        _junction(path / relative, source)

    return Worktree(ticket_id=ticket_id, path=path, branch=branch)


def teardown(git: Git, worktree: Worktree) -> None:
    """Remove the worktree. The branch stays — it is the ticket's evidence."""
    # Junctions must be unlinked before the tree is removed, or a recursive
    # delete walks into the shared read-only recordings and deletes those too.
    if worktree.path.exists():
        _unlink_links(worktree.path)
        # Must run after _unlink_links: it walks the whole tree, and a
        # junction still in place would make that walk wander into the
        # shared recordings for the same reason the line above exists.
        _remove_reserved_device_names(worktree.path)

    git.worktree_remove(worktree.path)


def _unlink_links(root: Path) -> None:
    """Unlink every junction/symlink under `root`, without ever traversing one.

    A junction preserves its source's path relative to the repo root, so it sits
    several levels down — `DATA/derived/channels/<name>` — and a scan of `root`'s
    immediate children does not see it. The check has to happen *before* the
    recursion: `os.walk` descends through Windows junctions even with
    `followlinks=False`, which is the very traversal this exists to prevent.
    """
    for child in root.iterdir():
        if child.is_symlink():
            child.unlink()
        elif _is_junction(child):
            child.rmdir()  # removes the link; the target is untouched
        elif child.is_dir():
            _unlink_links(child)


def _is_junction(path: Path) -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(path.lstat().st_file_attributes & 0x400)  # REPARSE_POINT
    except (OSError, AttributeError):
        return False


_RESERVED_DEVICE_NAMES = frozenset({
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
})


def _remove_reserved_device_names(root: Path) -> None:
    """Delete any file whose bare name is a Windows reserved device name.

    `nul` is the one that actually turns up: some tool inside an agent's
    session redirects output with POSIX `> /dev/null` semantics that Windows
    doesn't honour, and a real 0-byte file called `nul` lands in the
    worktree instead. Win32 intercepts that name as a device reference
    ahead of the filesystem, so the ordinary delete path — `os.remove`,
    `git clean`, even `git worktree remove --force` — fails on it with
    "Access is denied" (or, at removal time, "Directory not empty"), even
    though the file underneath is perfectly ordinary. The `\\\\?\\`
    extended-length-path prefix disables that interception and reaches the
    real file. Safe to call whether or not any such file exists.
    """
    if sys.platform != "win32":
        return
    for child in root.rglob("*"):
        # Not `child.is_file()`: stat-ing the plain path hits the same
        # device interception as opening it, and it never reports true for
        # one of these names even though a real file sits there. Directory
        # enumeration (what `rglob` is built on) is a different Win32 call
        # and isn't fooled, so the name match alone is the only signal
        # available here — the extended-path unlink below is a no-op error,
        # swallowed, if this ever did match a real directory instead.
        if child.name.lower() in _RESERVED_DEVICE_NAMES:
            try:
                Path(rf"\\?\{child.resolve()}").unlink()
            except OSError:
                pass
