"""Worktree provisioning — scratch repos, plus one acceptance test on the real one."""

import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator.config import load_config
from orchestrator.gitops import Git
from orchestrator.worktree import ProvisionError, _junction, provision, teardown

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_CONFIG = REPO_ROOT / "orchestrator" / "config.toml"


@pytest.fixture
def scratch(tmp_path):
    root = tmp_path / "scratch"
    root.mkdir()
    git = Git(root)
    git.run("init", "-b", "main")
    git.run("config", "user.email", "runner@example.invalid")
    git.run("config", "user.name", "Runner Test")
    (root / "README.md").write_text("scratch\n", encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    skills = root / ".claude" / "skills" / "code-review"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: code-review\n---\n", encoding="utf-8")
    git.run("add", "-A")
    git.run("commit", "-m", "initial")
    git.create_branch("integration", "main")
    return git


@pytest.fixture
def fixture_db(tmp_path):
    db = tmp_path / "fixtures" / "annotations.sqlite"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"SQLite format 3\x00fixture")
    return db


def test_provision_creates_a_worktree_on_a_ticket_branch(scratch, tmp_path, fixture_db):
    wt = provision(scratch, ticket_id=1, worktrees_root=tmp_path / "wt",
                   integration_branch="integration", branch_prefix="ticket/",
                   fixture_db=fixture_db, fixture_db_dest="DATA/annotations.sqlite")

    assert wt.path.is_dir()
    assert wt.branch == "ticket/T01"
    assert scratch.branch_exists("ticket/T01")
    assert (wt.path / "README.md").is_file()


def test_the_worktree_carries_the_committed_review_skill_and_pytest_ini(scratch, tmp_path, fixture_db):
    """Worktrees materialise only committed files. If these are missing the
    review gate degrades to nothing and every ticket merges unreviewed."""
    wt = provision(scratch, ticket_id=1, worktrees_root=tmp_path / "wt",
                   integration_branch="integration", branch_prefix="ticket/",
                   fixture_db=fixture_db, fixture_db_dest="DATA/annotations.sqlite")

    assert (wt.path / ".claude" / "skills" / "code-review" / "SKILL.md").is_file()
    assert (wt.path / "pytest.ini").is_file()


def test_the_fixture_database_is_copied_in_never_referenced(scratch, tmp_path, fixture_db):
    wt = provision(scratch, ticket_id=1, worktrees_root=tmp_path / "wt",
                   integration_branch="integration", branch_prefix="ticket/",
                   fixture_db=fixture_db, fixture_db_dest="DATA/annotations.sqlite")

    copied = wt.path / "DATA" / "annotations.sqlite"
    assert copied.is_file()
    assert copied.read_bytes() == fixture_db.read_bytes()

    # A copy, not a link: an agent that corrupts it cannot reach back.
    copied.write_bytes(b"agent scribbled here")
    assert fixture_db.read_bytes() == b"SQLite format 3\x00fixture"


def test_a_missing_fixture_database_is_an_error_not_a_silent_skip(scratch, tmp_path):
    with pytest.raises(ProvisionError, match="fixture"):
        provision(scratch, ticket_id=1, worktrees_root=tmp_path / "wt",
                  integration_branch="integration", branch_prefix="ticket/",
                  fixture_db=tmp_path / "nope.sqlite",
                  fixture_db_dest="DATA/annotations.sqlite")


def test_recording_directories_are_linked_not_copied(scratch, tmp_path, fixture_db):
    recordings = scratch.root / "DATA" / "derived" / "channels" / "M2_aug_concat_fs1"
    recordings.mkdir(parents=True)
    (recordings / "big.bin").write_bytes(b"x" * 1024)

    wt = provision(scratch, ticket_id=1, worktrees_root=tmp_path / "wt",
                   integration_branch="integration", branch_prefix="ticket/",
                   fixture_db=fixture_db, fixture_db_dest="DATA/annotations.sqlite",
                   recordings=[recordings])

    linked = wt.path / "DATA" / "derived" / "channels" / "M2_aug_concat_fs1"
    assert linked.is_dir()
    assert (linked / "big.bin").read_bytes() == b"x" * 1024
    assert linked not in wt.path.glob("DATA/derived/channels/**/*.copy")


def test_a_junction_preserves_its_path_relative_to_the_repo_root(scratch, tmp_path, fixture_db):
    """`DATA/derived/channels/X` must land at `<worktree>/DATA/derived/channels/X`.

    Linking it in as `<worktree>/X` puts real data somewhere nothing looks for
    it: every path constant in the suite is repo-root-relative, so the tests
    stay just as broken as if nothing had been junctioned at all — but silently,
    with 317 MB apparently provisioned.
    """
    recordings = scratch.root / "DATA" / "derived" / "channels" / "M2_aug_concat_fs1"
    recordings.mkdir(parents=True)
    (recordings / "CH0.npy").write_bytes(b"signal")

    wt = provision(scratch, ticket_id=1, worktrees_root=tmp_path / "wt",
                   integration_branch="integration", branch_prefix="ticket/",
                   fixture_db=fixture_db, fixture_db_dest="DATA/annotations.sqlite",
                   recordings=[recordings])

    assert (wt.path / "DATA" / "derived" / "channels" / "M2_aug_concat_fs1" / "CH0.npy").is_file()
    assert not (wt.path / "M2_aug_concat_fs1").exists(), \
        "junctioned at the worktree root, where no path constant in the suite looks"


def test_a_recording_outside_the_repo_root_is_refused(scratch, tmp_path, fixture_db):
    """There is no correct place to put it, so guessing one is worse than stopping."""
    stray = tmp_path / "elsewhere" / "channels"
    stray.mkdir(parents=True)

    with pytest.raises(ProvisionError, match="relative to the repo root"):
        provision(scratch, ticket_id=1, worktrees_root=tmp_path / "wt",
                  integration_branch="integration", branch_prefix="ticket/",
                  fixture_db=fixture_db, fixture_db_dest="DATA/annotations.sqlite",
                  recordings=[stray])


def test_teardown_unlinks_a_nested_junction_without_touching_its_target(
        scratch, tmp_path, fixture_db):
    """The one failure mode in this module that destroys data.

    A junction preserves its source's path relative to the repo root, so in
    production it lands at `DATA/derived/channels/<name>` — several levels down,
    not as a child of the worktree root. Teardown therefore has to walk the tree
    to find it. If it does not, the recursive delete walks *through* the
    junction and takes the shared read-only recordings with it: 317 MB of
    derived channel data in production, and 2.3 GB if `recordings` is ever
    widened. Proved here against a scratch directory, never against DATA.
    """
    shared = tmp_path / "shared" / "M2_aug_concat_fs1"
    shared.mkdir(parents=True)
    sentinel = shared / "CH0.npy"
    sentinel.write_bytes(b"expensive to regenerate")

    wt = provision(scratch, ticket_id=1, worktrees_root=tmp_path / "wt",
                   integration_branch="integration", branch_prefix="ticket/",
                   fixture_db=fixture_db, fixture_db_dest="DATA/annotations.sqlite")
    _junction(wt.path / "DATA" / "derived" / "channels" / "M2_aug_concat_fs1", shared)

    teardown(scratch, wt)

    assert not wt.path.exists()
    assert sentinel.is_file(), \
        "teardown followed the junction and deleted the shared recordings"
    assert sentinel.read_bytes() == b"expensive to regenerate"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows reserved device names only")
def test_teardown_removes_a_stray_nul_file(scratch, tmp_path, fixture_db):
    """run-20260818-2244: a stalled agent left a real 0-byte file named `nul`
    in its worktree (some tool redirected output with POSIX `> /dev/null`
    semantics Windows doesn't honour). Win32 intercepts that name as a
    device reference ahead of the filesystem, so `git worktree remove
    --force` failed with "Directory not empty" and the whole ticket came
    down as an orchestrator error instead of a clean quarantine.
    """
    wt = provision(scratch, ticket_id=1, worktrees_root=tmp_path / "wt",
                   integration_branch="integration", branch_prefix="ticket/",
                   fixture_db=fixture_db, fixture_db_dest="DATA/annotations.sqlite")
    nested = wt.path / "Working"
    nested.mkdir()
    # A plain `open(nested / "nul", "w")` doesn't reproduce this: Python's
    # own path handling special-cases "nul" as the null device before it
    # ever reaches Win32, so it writes nothing and creates no file — the
    # same reason a `> nul` redirect quietly discards output instead of
    # creating one. The extended-length-path prefix is what actually
    # reaches a real file at that name, same as the fix under test.
    with open(rf"\\?\{(nested / 'nul').resolve()}", "w") as f:
        f.write("x")
    # Not `(nested / "nul").is_file()`: stat-ing the plain path hits the
    # same device interception as opening it, and reports it as not a
    # regular file even though it is one. Directory enumeration is a
    # different Win32 call and isn't fooled.
    assert "nul" in {p.name for p in nested.iterdir()}

    teardown(scratch, wt)

    assert not wt.path.exists()


def test_teardown_removes_the_worktree_but_keeps_the_branch(scratch, tmp_path, fixture_db):
    wt = provision(scratch, ticket_id=1, worktrees_root=tmp_path / "wt",
                   integration_branch="integration", branch_prefix="ticket/",
                   fixture_db=fixture_db, fixture_db_dest="DATA/annotations.sqlite")

    teardown(scratch, wt)

    assert not wt.path.exists()
    assert scratch.branch_exists("ticket/T01"), "a quarantined branch must survive for the morning"


def test_a_real_provisioned_worktree_can_import_the_application(tmp_path):
    """Acceptance: is a worktree the agents get actually usable?

    Against the real repo and the real config, because the two halves are
    coupled — the fixture's recording rows name paths only the junction
    supplies, and the junction is pointless without rows naming it. Verified
    together or not at all.

    `import UI.app` is the whole check. UI/app.py:2279 constructs a full
    ViewerApp at import time, so that one statement exercises the fixture
    database, the junction, and the junction's placement in a couple of seconds
    — where the suite gate costs four minutes. This test failing at t+0 is
    exactly what run-20260816-1943 needed and did not have.
    """
    config = load_config(SHIPPED_CONFIG, repo_root=REPO_ROOT)
    git = Git(config.paths.repo_root)
    branch = "ticket/acceptance-T99"
    if git.branch_exists(branch):
        git.delete_branch(branch)

    worktree = provision(
        git, ticket_id=99, worktrees_root=tmp_path / "wt",
        integration_branch=git.current_branch(),
        branch_prefix="ticket/acceptance-",
        fixture_db=config.paths.fixture_db,
        fixture_db_dest=config.paths.fixture_db_dest,
        recordings=config.paths.recordings,
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import UI.app"],
            cwd=worktree.path, capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, (
            "a provisioned worktree cannot import the application, so every test "
            "file that imports UI.app will fail at COLLECTION and read as a "
            f"regression:\n{result.stderr[-2000:]}"
        )
    finally:
        teardown(git, worktree)
        if git.branch_exists(worktree.branch):
            git.delete_branch(worktree.branch)

    for source in config.paths.recordings:
        assert source.is_dir() and any(source.iterdir()), \
            f"teardown destroyed the shared recordings at {source}"


def test_provisioning_twice_reuses_the_existing_branch(scratch, tmp_path, fixture_db):
    kwargs = dict(worktrees_root=tmp_path / "wt", integration_branch="integration",
                  branch_prefix="ticket/", fixture_db=fixture_db,
                  fixture_db_dest="DATA/annotations.sqlite")
    first = provision(scratch, ticket_id=1, **kwargs)
    teardown(scratch, first)

    second = provision(scratch, ticket_id=1, **kwargs)

    assert second.branch == "ticket/T01"
    assert second.path.is_dir()
