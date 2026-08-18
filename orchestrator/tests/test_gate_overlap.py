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


def test_private_names_are_caught_by_default(repo):
    """Two agents both writing `_resample_and_znorm` are still two
    implementations of one idea — being module-private makes the duplication
    harder to spot, not less real. Standards rule 6.4 calls duplicated logic
    across modules a blocker at the merge boundary regardless of visibility."""
    branch_with(repo, "ticket/T35", "Working/distances.py", """
        def _private_helper(): pass
        def public_thing(): pass
    """)

    assert added_symbols(repo, "integration", "ticket/T35") == {
        "_private_helper", "public_thing",
    }


def test_private_names_can_be_excluded_by_configuration(repo):
    branch_with(repo, "ticket/T35", "Working/distances.py", """
        def _private_helper(): pass
        def public_thing(): pass
    """)

    assert added_symbols(repo, "integration", "ticket/T35",
                         include_private=False) == {"public_thing"}


def test_dunder_names_are_never_symbols(repo):
    """`__all__`-adjacent module machinery is not a shared vocabulary."""
    branch_with(repo, "ticket/T35", "Working/distances.py", """
        def __getattr__(name): raise AttributeError(name)
        def real_thing(): pass
    """)

    assert added_symbols(repo, "integration", "ticket/T35") == {"real_thing"}


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


# ------------------------------------------------- test files are not shared vocabulary


def test_symbols_defined_in_test_files_do_not_participate(repo):
    """run-20260818-0554 held T13 for obeying the repo's own convention.

    41 of this repo's 42 test files end with an identical module-private
    `_run_all()` that runs the file's tests under `__main__`. T35 landed first,
    took ownership of the name, and T13's test file — a different module, which
    nothing imports — collided with it and was held. Two test files each
    carrying the mandated boilerplate are not two implementations of one idea.
    """
    branch_with(repo, "ticket/T13", "tests/test_chain_validation.py", """
        def _run_all(): pass
        def test_a_chain_is_validated(): pass
    """)

    assert added_symbols(repo, "integration", "ticket/T13",
                         ignore_paths=("tests/",)) == set()


def test_the_same_branch_still_reports_its_non_test_symbols(repo):
    """Ignoring test files must not blind the gate to the actual work."""
    branch_with(repo, "ticket/T13", "Working/chain_validation.py", """
        def validate_chain(steps): return True
        def _run_all(): pass
    """)

    assert added_symbols(repo, "integration", "ticket/T13",
                         ignore_paths=("tests/",)) == {"validate_chain", "_run_all"}


def test_ignoring_nothing_is_the_default(repo):
    """The narrowing is opt-in, so an unconfigured caller keeps the old reach."""
    branch_with(repo, "ticket/T13", "tests/test_thing.py", """
        def _run_all(): pass
    """)

    assert added_symbols(repo, "integration", "ticket/T13") == {"_run_all"}
