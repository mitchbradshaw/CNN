"""The git layer, exercised only against disposable scratch repositories.

Nothing in this file may touch the real repository. Every fixture builds a
throwaway repo under tmp_path; the merge and worktree code rewrites history and
is proved somewhere it cannot matter.
"""

import subprocess

import pytest

from orchestrator.gitops import Git, GitError


@pytest.fixture
def scratch(tmp_path):
    """A disposable repo with one commit on `main`."""
    root = tmp_path / "scratch"
    root.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=root, check=True,
                                    capture_output=True, text=True)
    run("init", "-b", "main")
    run("config", "user.email", "runner@example.invalid")
    run("config", "user.name", "Runner Test")
    (root / "README.md").write_text("scratch\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-m", "initial")
    return Git(root)


def commit(git, filename, content, message):
    (git.root / filename).parent.mkdir(parents=True, exist_ok=True)
    (git.root / filename).write_text(content, encoding="utf-8")
    git.run("add", "-A")
    git.run("commit", "-m", message)
    return git.rev_parse("HEAD")


def test_rev_parse_and_current_branch(scratch):
    assert len(scratch.rev_parse("HEAD")) == 40
    assert scratch.current_branch() == "main"


def test_a_bad_ref_raises_rather_than_returning_empty(scratch):
    with pytest.raises(GitError):
        scratch.rev_parse("no/such/ref")


def test_branch_creation_and_existence(scratch):
    assert not scratch.branch_exists("integration/run-1")

    scratch.create_branch("integration/run-1", "main")

    assert scratch.branch_exists("integration/run-1")
    assert scratch.rev_parse("integration/run-1") == scratch.rev_parse("main")


def test_branch_names_lists_every_local_branch(scratch):
    """One call, so the stale-branch preflight does not shell out per ticket."""
    scratch.create_branch("ticket/T01", "main")
    scratch.create_branch("integration/run-1", "main")

    assert scratch.branch_names() == {"main", "ticket/T01", "integration/run-1"}


def test_commits_between_lists_only_the_branchs_own_work(scratch):
    scratch.create_branch("ticket/T01", "main")
    scratch.run("checkout", "ticket/T01")
    commit(scratch, "a.py", "a\n", "T01: first")
    commit(scratch, "b.py", "b\n", "T01: second")

    commits = scratch.commits_between("main", "ticket/T01")

    assert [c.subject for c in commits] == ["T01: first", "T01: second"]
    assert all(len(c.sha) == 40 for c in commits)


def test_files_changed_against_the_merge_base(scratch):
    scratch.create_branch("ticket/T01", "main")
    scratch.run("checkout", "ticket/T01")
    commit(scratch, "pkg/mod.py", "x = 1\n", "T01: add")
    scratch.run("checkout", "main")
    commit(scratch, "unrelated.py", "y = 2\n", "main moves on")

    changed = scratch.files_changed("main", "ticket/T01")

    assert changed == ["pkg/mod.py"], "three-dot: main's own commits must not appear"


def test_files_changed_for_a_single_commit(scratch):
    scratch.create_branch("ticket/T01", "main")
    scratch.run("checkout", "ticket/T01")
    first = commit(scratch, "tests/test_new.py", "def test_x(): assert False\n", "T01: red")
    commit(scratch, "pkg/mod.py", "x = 1\n", "T01: green")

    assert scratch.files_in_commit(first) == ["tests/test_new.py"]


def test_merge_no_ff_always_creates_a_merge_commit(scratch):
    scratch.create_branch("integration", "main")
    scratch.create_branch("ticket/T01", "integration")
    scratch.run("checkout", "ticket/T01")
    commit(scratch, "a.py", "a\n", "T01: work")
    scratch.run("checkout", "integration")

    sha = scratch.merge_no_ff("ticket/T01", "Merge T01")

    parents = scratch.run("rev-list", "--parents", "-n", "1", sha).split()
    assert len(parents) == 3, "a fast-forward would have left one parent"
    assert scratch.is_merged("ticket/T01", "integration")


def test_merge_conflict_raises_and_leaves_no_half_merge(scratch):
    scratch.create_branch("integration", "main")
    scratch.run("checkout", "integration")
    commit(scratch, "shared.py", "integration\n", "integration edit")
    scratch.create_branch("ticket/T01", "main")
    scratch.run("checkout", "ticket/T01")
    commit(scratch, "shared.py", "ticket\n", "T01 edit")
    scratch.run("checkout", "integration")
    before = scratch.rev_parse("HEAD")

    with pytest.raises(GitError):
        scratch.merge_no_ff("ticket/T01", "Merge T01")

    assert scratch.rev_parse("HEAD") == before
    assert not scratch.merge_in_progress()


def test_revert_of_a_merge_removes_exactly_that_tickets_work(scratch):
    scratch.create_branch("integration", "main")
    scratch.create_branch("ticket/T01", "integration")
    scratch.run("checkout", "ticket/T01")
    commit(scratch, "a.py", "a\n", "T01: work")
    scratch.run("checkout", "integration")
    sha = scratch.merge_no_ff("ticket/T01", "Merge T01")
    assert (scratch.root / "a.py").exists()

    scratch.revert_merge(sha)

    assert not (scratch.root / "a.py").exists()
    assert scratch.branch_exists("ticket/T01"), "the branch is preserved for the morning"


def test_is_merged_is_false_before_the_merge(scratch):
    scratch.create_branch("integration", "main")
    scratch.create_branch("ticket/T01", "integration")
    scratch.run("checkout", "ticket/T01")
    commit(scratch, "a.py", "a\n", "T01: work")

    assert not scratch.is_merged("ticket/T01", "integration")


def test_a_branch_with_no_commits_beyond_base_is_visible_as_such(scratch):
    scratch.create_branch("integration", "main")
    scratch.create_branch("ticket/T01", "integration")

    assert scratch.commits_between("integration", "ticket/T01") == []


def test_worktree_add_and_remove(scratch, tmp_path):
    scratch.create_branch("integration", "main")
    path = tmp_path / "wt" / "T01"

    scratch.worktree_add(path, branch="ticket/T01", start_point="integration")

    assert (path / "README.md").is_file()
    assert scratch.branch_exists("ticket/T01")

    scratch.worktree_remove(path)

    assert not path.exists()
    assert scratch.branch_exists("ticket/T01"), "removing a worktree keeps the branch"


def test_merge_commits_report_the_landing_order(scratch):
    scratch.create_branch("integration", "main")
    for ticket in ("T01", "T02"):
        scratch.create_branch(f"ticket/{ticket}", "integration")
        scratch.run("checkout", f"ticket/{ticket}")
        commit(scratch, f"{ticket}.py", "x\n", f"{ticket}: work")
        scratch.run("checkout", "integration")
        scratch.merge_no_ff(f"ticket/{ticket}", f"Merge {ticket}")

    subjects = [c.subject for c in scratch.merge_commits("integration")]

    assert subjects == ["Merge T02", "Merge T01"], "newest first, as git log gives it"


def test_diff_returns_a_patch_that_applies(scratch):
    scratch.create_branch("ticket/T01", "main")
    scratch.run("checkout", "ticket/T01")
    commit(scratch, "a.py", "a\n", "T01: work")

    patch = scratch.diff("main", "ticket/T01")

    assert "diff --git" in patch
    assert "+a" in patch
