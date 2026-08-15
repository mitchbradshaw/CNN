"""Gate 3 — declared files vs touched files. A soft gate, on purpose.

Out-of-scope files do not block the merge; they are listed in REPORT.md and
appended to the review prompt. Hard-blocking would be wrong — sometimes a
legitimate fix needs a neighbour — but an unexplained edit to `Adapters/base.py`
from a ticket that isn't 05 or 10 is exactly what you want in a table at 8am.
"""

from orchestrator.gates.scope import check_scope


def test_a_ticket_that_stayed_inside_its_declared_files_passes():
    verdict = check_scope(touched=["Working/types/signal.py", "tests/test_types.py"],
                          declared=["Working/types/signal.py", "tests/test_types.py"])

    assert verdict.status == "pass"
    assert verdict.deviations == ()


def test_bare_filenames_in_the_front_matter_match_by_basename():
    """T01 declares `signal.py`, not `Working/types/signal.py`. The backlog was
    written that way and the gate reads the backlog as it is."""
    verdict = check_scope(
        touched=["Working/types/signal.py", "Working/types/__init__.py"],
        declared=["signal.py", "__init__.py"],
    )

    assert verdict.status == "pass"


def test_an_undeclared_file_is_a_warning_not_a_failure():
    verdict = check_scope(touched=["Working/types/signal.py", "Adapters/base.py"],
                          declared=["signal.py"])

    assert verdict.status == "warn"
    assert verdict.deviations == ("Adapters/base.py",)


def test_a_declared_directory_covers_everything_under_it():
    verdict = check_scope(touched=["Working/types/signal.py", "Working/types/scores.py"],
                          declared=["Working/types/"])

    assert verdict.status == "pass"


def test_declared_files_the_agent_never_touched_are_reported_separately():
    """Not a deviation — a ticket may legitimately not need every file it
    named — but worth seeing next to a thin diff."""
    verdict = check_scope(touched=["signal.py"], declared=["signal.py", "scores.py"])

    assert verdict.status == "pass"
    assert verdict.untouched == ("scores.py",)


def test_a_ticket_declaring_nothing_puts_everything_in_the_report():
    verdict = check_scope(touched=["a.py", "b.py"], declared=[])

    assert verdict.status == "warn"
    assert verdict.deviations == ("a.py", "b.py")


def test_the_rendered_summary_names_both_sides():
    verdict = check_scope(touched=["Adapters/base.py"], declared=["signal.py"])

    text = verdict.render()

    assert "Adapters/base.py" in text
    assert "signal.py" in text
