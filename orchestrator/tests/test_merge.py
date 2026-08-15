"""Merging into the integration branch. Scratch repos only.

`main` is never written by the runner. The integration branch is never left red,
because every subsequent ticket cuts from it.
"""

import textwrap

import pytest

from orchestrator.gitops import Git
from orchestrator.merge import merge_ticket

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
    # As in the real repo — otherwise running the suite leaves the tree dirty.
    (root / ".gitignore").write_text(".pytest_cache/\n__pycache__/\n", encoding="utf-8")
    (root / "tests" / "test_base.py").write_text("def test_base(): assert True\n",
                                                 encoding="utf-8")
    git.run("add", "-A")
    git.run("commit", "-m", "initial")
    git.create_branch("integration", "main")
    git.checkout("integration")
    return git


def ticket_branch(git, name, path, body):
    git.create_branch(name, "integration")
    git.checkout(name)
    target = git.root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(body), encoding="utf-8")
    git.run("add", "-A")
    git.run("commit", "-m", f"{name}: work")
    git.checkout("integration")


def test_a_clean_green_merge_lands(repo):
    ticket_branch(repo, "ticket/T01", "tests/test_one.py", """
        def test_one(): assert True
    """)

    result = merge_ticket(repo, ticket_id=1, branch="ticket/T01",
                          integration="integration", title="a ticket",
                          suite_command=COMMAND, baseline_failed=(), timeout_minutes=5)

    assert result.status == "merged"
    assert result.merge_sha
    assert repo.is_merged("ticket/T01", "integration")


def test_the_merge_is_always_a_merge_commit(repo):
    """`git revert -m 1 <sha>` must remove exactly one ticket's work."""
    ticket_branch(repo, "ticket/T01", "tests/test_one.py", "def test_one(): assert True\n")

    result = merge_ticket(repo, ticket_id=1, branch="ticket/T01",
                          integration="integration", title="a ticket",
                          suite_command=COMMAND, baseline_failed=(), timeout_minutes=5)

    parents = repo.run("rev-list", "--parents", "-n", "1", result.merge_sha).split()
    assert len(parents) == 3


def test_the_merge_message_carries_the_ticket_id(repo):
    ticket_branch(repo, "ticket/T01", "tests/test_one.py", "def test_one(): assert True\n")

    merge_ticket(repo, ticket_id=1, branch="ticket/T01", integration="integration",
                 title="seven interchange types", suite_command=COMMAND,
                 baseline_failed=(), timeout_minutes=5)

    subject = repo.merge_commits("integration")[0].subject
    assert subject.startswith("T01:")
    assert "seven interchange types" in subject


def test_post_merge_red_reverts_the_merge_and_quarantines(repo):
    """The branch was green alone and red merged. The integration branch is
    never left red, because every subsequent ticket cuts from it."""
    ticket_branch(repo, "ticket/T01", "tests/test_poison.py", """
        def test_poison(): assert False
    """)

    result = merge_ticket(repo, ticket_id=1, branch="ticket/T01",
                          integration="integration", title="a ticket",
                          suite_command=COMMAND, baseline_failed=(), timeout_minutes=5)

    assert result.status == "reverted"
    assert result.regressions == ("tests/test_poison.py::test_poison",)
    assert not (repo.root / "tests" / "test_poison.py").exists()
    assert repo.branch_exists("ticket/T01"), "the branch is preserved for the morning"


def test_the_suite_is_green_again_after_an_auto_revert(repo):
    ticket_branch(repo, "ticket/T01", "tests/test_poison.py", "def test_poison(): assert False\n")

    merge_ticket(repo, ticket_id=1, branch="ticket/T01", integration="integration",
                 title="a ticket", suite_command=COMMAND, baseline_failed=(),
                 timeout_minutes=5)

    from orchestrator.gates.suite import run_suite
    assert run_suite(repo.root, COMMAND, timeout_minutes=5).exit_code == 0


def test_a_failure_already_red_at_baseline_does_not_revert(repo):
    repo.checkout("integration")
    (repo.root / "tests" / "test_known.py").write_text("def test_known(): assert False\n",
                                                       encoding="utf-8")
    repo.run("add", "-A")
    repo.run("commit", "-m", "known flake lands on integration")
    ticket_branch(repo, "ticket/T01", "tests/test_one.py", "def test_one(): assert True\n")

    result = merge_ticket(repo, ticket_id=1, branch="ticket/T01",
                          integration="integration", title="a ticket",
                          suite_command=COMMAND,
                          baseline_failed=("tests/test_known.py::test_known",),
                          timeout_minutes=5)

    assert result.status == "merged"


def test_a_conflicting_merge_leaves_the_branch_untouched(repo):
    repo.checkout("integration")
    (repo.root / "shared.py").write_text("integration\n", encoding="utf-8")
    repo.run("add", "-A")
    repo.run("commit", "-m", "integration edit")
    repo.create_branch("ticket/T01", "main")
    repo.checkout("ticket/T01")
    (repo.root / "shared.py").write_text("ticket\n", encoding="utf-8")
    repo.run("add", "-A")
    repo.run("commit", "-m", "T01 edit")
    repo.checkout("integration")
    before = repo.rev_parse("integration")

    result = merge_ticket(repo, ticket_id=1, branch="ticket/T01",
                          integration="integration", title="a ticket",
                          suite_command=COMMAND, baseline_failed=(), timeout_minutes=5)

    assert result.status == "conflict"
    assert repo.rev_parse("integration") == before
    assert not repo.merge_in_progress()


def test_merging_leaves_the_repo_on_the_integration_branch(repo):
    ticket_branch(repo, "ticket/T01", "tests/test_one.py", "def test_one(): assert True\n")

    merge_ticket(repo, ticket_id=1, branch="ticket/T01", integration="integration",
                 title="a ticket", suite_command=COMMAND, baseline_failed=(),
                 timeout_minutes=5)

    assert repo.current_branch() == "integration"


def test_followups_are_appended_to_the_integration_branch(repo):
    from orchestrator.gates.review import Finding
    from orchestrator.merge import append_followups

    ticket_branch(repo, "ticket/T01", "tests/test_one.py", "def test_one(): assert True\n")
    merge_ticket(repo, ticket_id=1, branch="ticket/T01", integration="integration",
                 title="a ticket", suite_command=COMMAND, baseline_failed=(),
                 timeout_minutes=5)

    append_followups(repo, ticket_id=1, filename="FOLLOWUPS.md", findings=[
        Finding("standards", "1.3", "utils module is not a purpose", severity="major"),
    ])

    text = (repo.root / "FOLLOWUPS.md").read_text(encoding="utf-8")
    assert "T01" in text and "1.3" in text and "utils module" in text
    assert repo.is_clean(), "the followup is committed, not left dirty"
