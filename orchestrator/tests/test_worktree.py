"""Worktree provisioning — scratch repos only."""

import pytest

from orchestrator.gitops import Git
from orchestrator.worktree import ProvisionError, provision, teardown


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
    recordings = tmp_path / "shared" / "RECORDINGS"
    recordings.mkdir(parents=True)
    (recordings / "big.bin").write_bytes(b"x" * 1024)

    wt = provision(scratch, ticket_id=1, worktrees_root=tmp_path / "wt",
                   integration_branch="integration", branch_prefix="ticket/",
                   fixture_db=fixture_db, fixture_db_dest="DATA/annotations.sqlite",
                   recordings=[recordings])

    linked = wt.path / "RECORDINGS"
    assert linked.is_dir()
    assert (linked / "big.bin").read_bytes() == b"x" * 1024
    assert linked not in wt.path.glob("RECORDINGS/**/*.copy")


def test_teardown_removes_the_worktree_but_keeps_the_branch(scratch, tmp_path, fixture_db):
    wt = provision(scratch, ticket_id=1, worktrees_root=tmp_path / "wt",
                   integration_branch="integration", branch_prefix="ticket/",
                   fixture_db=fixture_db, fixture_db_dest="DATA/annotations.sqlite")

    teardown(scratch, wt)

    assert not wt.path.exists()
    assert scratch.branch_exists("ticket/T01"), "a quarantined branch must survive for the morning"


def test_provisioning_twice_reuses_the_existing_branch(scratch, tmp_path, fixture_db):
    kwargs = dict(worktrees_root=tmp_path / "wt", integration_branch="integration",
                  branch_prefix="ticket/", fixture_db=fixture_db,
                  fixture_db_dest="DATA/annotations.sqlite")
    first = provision(scratch, ticket_id=1, **kwargs)
    teardown(scratch, first)

    second = provision(scratch, ticket_id=1, **kwargs)

    assert second.branch == "ticket/T01"
    assert second.path.is_dir()
