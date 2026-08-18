"""Gate 1 — the agent's first commit must be a test, and it must actually fail.

This is the only way red-green is a fact rather than a claim. It catches the
most common way an autonomous agent produces work that looks finished and
isn't: a test that asserts nothing.
"""

import textwrap

import pytest

from orchestrator.gates.red_proof import check_red_proof
from orchestrator.gitops import Git

COMMAND = ("pytest", "-q", "--tb=no", "-rf")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "scratch"
    (root / "tests").mkdir(parents=True)
    git = Git(root)
    git.run("init", "-b", "main")
    git.run("config", "user.email", "runner@example.invalid")
    git.run("config", "user.name", "Runner Test")
    (root / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    # `tests/__init__.py` is what makes the real repo's test files resolve
    # `from UI.viewer import ...`-style imports: pytest walks up from a
    # package until it finds a directory with no `__init__.py` and inserts
    # *that* onto sys.path, which lands on the repo root, not `tests/`.
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "test_existing.py").write_text("def test_old(): assert True\n",
                                                     encoding="utf-8")
    git.run("add", "-A")
    git.run("commit", "-m", "initial")
    git.create_branch("integration", "main")
    git.checkout("integration")
    return git


def commit(git, path, body, message):
    target = git.root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(body), encoding="utf-8")
    git.run("add", "-A")
    git.run("commit", "-m", message)


def test_a_failing_test_only_first_commit_passes(repo):
    repo.create_branch("ticket/T01", "integration")
    repo.checkout("ticket/T01")
    commit(repo, "tests/test_new.py", """
        from pkg.mod import widget
        def test_widget(): assert widget() == 42
    """, "T01: red")
    commit(repo, "pkg/mod.py", "def widget(): return 42\n", "T01: green")

    verdict = check_red_proof(repo, repo.root, base="integration", branch="ticket/T01",
                              command=COMMAND, timeout_minutes=5)

    assert verdict.status == "pass"
    assert verdict.test_files == ("tests/test_new.py",)
    assert verdict.output


def test_the_worktree_is_left_back_on_the_branch(repo):
    repo.create_branch("ticket/T01", "integration")
    repo.checkout("ticket/T01")
    commit(repo, "tests/test_new.py", """
        def test_x(): assert False
    """, "T01: red")

    check_red_proof(repo, repo.root, base="integration", branch="ticket/T01",
                    command=COMMAND, timeout_minutes=5)

    assert repo.current_branch() == "ticket/T01"


def test_a_first_commit_touching_implementation_fails_the_gate(repo):
    repo.create_branch("ticket/T01", "integration")
    repo.checkout("ticket/T01")
    commit(repo, "pkg/mod.py", "def widget(): return 42\n", "T01: implementation first")

    verdict = check_red_proof(repo, repo.root, base="integration", branch="ticket/T01",
                              command=COMMAND, timeout_minutes=5)

    assert verdict.status == "fail"
    assert "pkg/mod.py" in verdict.detail


def test_a_first_commit_that_passes_on_arrival_is_quarantined(repo):
    """A test that never failed asserts nothing."""
    repo.create_branch("ticket/T01", "integration")
    repo.checkout("ticket/T01")
    commit(repo, "tests/test_new.py", """
        def test_asserts_nothing(): assert True
    """, "T01: vacuous test")

    verdict = check_red_proof(repo, repo.root, base="integration", branch="ticket/T01",
                              command=COMMAND, timeout_minutes=5)

    assert verdict.status == "fail"
    assert "passed" in verdict.detail


def test_a_branch_with_no_commits_fails_the_gate(repo):
    repo.create_branch("ticket/T01", "integration")

    verdict = check_red_proof(repo, repo.root, base="integration", branch="ticket/T01",
                              command=COMMAND, timeout_minutes=5)

    assert verdict.status == "fail"
    assert "no commits" in verdict.detail


def test_a_first_commit_with_no_test_file_fails_the_gate(repo):
    repo.create_branch("ticket/T01", "integration")
    repo.checkout("ticket/T01")
    commit(repo, "tests/fixture_data.txt", "not a test\n", "T01: data only")

    verdict = check_red_proof(repo, repo.root, base="integration", branch="ticket/T01",
                              command=COMMAND, timeout_minutes=5)

    assert verdict.status == "fail"
    assert "no test file" in verdict.detail


def test_uncommitted_work_left_in_the_worktree_does_not_leak_into_the_check(repo):
    """A stalled agent can leave its half-finished implementation sitting on disk,
    uncommitted, after the first (test-only) commit. `checkout --detach` alone
    does not remove untracked files, so without a clean the gate would judge the
    test-only commit against whatever the agent happened to leave behind rather
    than against the commit itself — the exact way run-20260818-1114 quarantined
    T14 and T17: their tests genuinely were red at the test-only commit, but the
    agents' uncommitted, in-progress implementations were still on disk when the
    gate ran, so the test came back green and looked vacuous.
    """
    repo.create_branch("ticket/T01", "integration")
    repo.checkout("ticket/T01")
    commit(repo, "tests/test_new.py", """
        from pkg.mod import widget
        def test_widget(): assert widget() == 42
    """, "T01: red")
    # The agent kept going after its first commit and wrote the implementation
    # to disk, but stalled before ever committing it.
    pkg_dir = repo.root / "pkg"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "mod.py").write_text("def widget(): return 42\n", encoding="utf-8")

    verdict = check_red_proof(repo, repo.root, base="integration", branch="ticket/T01",
                              command=COMMAND, timeout_minutes=5)

    assert verdict.status == "pass"
    assert "1 failing" in verdict.detail


def test_uncommitted_edits_to_tracked_files_do_not_leak_into_the_check(repo):
    """Same failure mode, for a tracked file modified but not committed."""
    repo.create_branch("ticket/T01", "integration")
    repo.checkout("ticket/T01")
    commit(repo, "tests/test_new.py", """
        def test_old_is_still_true(): assert True
        def test_x(): assert False
    """, "T01: red")
    # Dirty an already-tracked file without committing it. It is not one of the
    # gate's `test_files`, so it must not affect the verdict either way.
    (repo.root / "tests" / "test_existing.py").write_text(
        "def test_old(): assert False\n", encoding="utf-8")

    verdict = check_red_proof(repo, repo.root, base="integration", branch="ticket/T01",
                              command=COMMAND, timeout_minutes=5)

    assert verdict.status == "pass"
    assert "1 failing" in verdict.detail  # only test_x — the dirty edit did not leak in
    assert repo.current_branch() == "ticket/T01"


def test_only_the_new_test_runs_not_the_whole_suite(repo):
    """The gate asks whether *this* test was red, not whether the suite was."""
    repo.create_branch("ticket/T01", "integration")
    repo.checkout("ticket/T01")
    commit(repo, "tests/test_new.py", """
        def test_x(): assert False
    """, "T01: red")

    verdict = check_red_proof(repo, repo.root, base="integration", branch="ticket/T01",
                              command=COMMAND, timeout_minutes=5)

    assert verdict.status == "pass"
    assert "test_old" not in verdict.output
