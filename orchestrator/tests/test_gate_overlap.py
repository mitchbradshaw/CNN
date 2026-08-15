"""Gate 5 — two agents in different modules both writing `resample_and_znorm`.

Blocking edges capture logical dependency. They do not capture this. Git merges
it cleanly and you find out in week three.

The check is mechanical, never an LLM judgement, and it **never auto-resolves**:
two implementations of the same idea are precisely the 3am decision that cannot
be audited the next morning.
"""

import textwrap

import pytest

from orchestrator.gates.overlap import added_symbols, check_overlap
from orchestrator.gitops import Git


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "scratch"
    root.mkdir()
    git = Git(root)
    git.run("init", "-b", "main")
    git.run("config", "user.email", "runner@example.invalid")
    git.run("config", "user.name", "Runner Test")
    (root / "existing.py").write_text("def already_here(): pass\n", encoding="utf-8")
    git.run("add", "-A")
    git.run("commit", "-m", "initial")
    git.create_branch("integration", "main")
    return git


def branch_with(git, name, path, body):
    git.create_branch(name, "integration")
    git.checkout(name)
    target = git.root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(body), encoding="utf-8")
    git.run("add", "-A")
    git.run("commit", "-m", f"{name}: work")
    git.checkout("integration")


# ------------------------------------------------------------ symbol extraction


def test_added_top_level_functions_and_classes_are_extracted(repo):
    branch_with(repo, "ticket/T35", "Working/distances.py", """
        def resample_and_znorm(x): return x
        class DistanceTable: pass
    """)

    assert added_symbols(repo, "integration", "ticket/T35") == {
        "resample_and_znorm", "DistanceTable",
    }


def test_nested_names_are_not_top_level_symbols(repo):
    branch_with(repo, "ticket/T35", "Working/distances.py", """
        class Outer:
            def inner_method(self): pass
        def outer_function():
            def helper(): pass
            return helper
    """)

    assert added_symbols(repo, "integration", "ticket/T35") == {"Outer", "outer_function"}


def test_a_symbol_that_already_existed_is_not_an_addition(repo):
    branch_with(repo, "ticket/T35", "existing.py", """
        def already_here(): return 1
        def newly_added(): return 2
    """)

    assert added_symbols(repo, "integration", "ticket/T35") == {"newly_added"}


def test_private_names_are_ignored(repo):
    """A module-private helper is not a shared-vocabulary collision."""
    branch_with(repo, "ticket/T35", "Working/distances.py", """
        def _private_helper(): pass
        def public_thing(): pass
    """)

    assert added_symbols(repo, "integration", "ticket/T35") == {"public_thing"}


def test_a_file_that_does_not_parse_is_skipped_rather_than_crashing(repo):
    branch_with(repo, "ticket/T35", "Working/broken.py", """
        def this is not python(
    """)

    assert added_symbols(repo, "integration", "ticket/T35") == set()


def test_non_python_files_are_ignored(repo):
    branch_with(repo, "ticket/T35", "docs/notes.md", "# def not_a_symbol\n")

    assert added_symbols(repo, "integration", "ticket/T35") == set()


def test_a_deleted_file_does_not_break_extraction(repo):
    repo.create_branch("ticket/T35", "integration")
    repo.checkout("ticket/T35")
    (repo.root / "existing.py").unlink()
    repo.run("add", "-A")
    repo.run("commit", "-m", "T35: remove")
    repo.checkout("integration")

    assert added_symbols(repo, "integration", "ticket/T35") == set()


# ------------------------------------------------------------------- the gate


def test_no_collision_passes():
    verdict = check_overlap(ticket_id=35, symbols={"resample_and_znorm"},
                            owners={"load_fixture_db": 2})

    assert verdict.status == "pass"
    assert verdict.collisions == {}


def test_a_collision_holds_the_second_branch_and_never_resolves_it():
    verdict = check_overlap(ticket_id=40, symbols={"resample_and_znorm", "search_scales"},
                            owners={"resample_and_znorm": 35})

    assert verdict.status == "hold"
    assert verdict.collisions == {"resample_and_znorm": 35}
    assert "T35" in verdict.render()


def test_a_ticket_does_not_collide_with_its_own_earlier_symbols():
    """Resuming a ticket after a crash must not report it colliding with itself."""
    verdict = check_overlap(ticket_id=35, symbols={"resample_and_znorm"},
                            owners={"resample_and_znorm": 35})

    assert verdict.status == "pass"
