"""Gate 4 — two-axis review, graded into review.json by the runner.

Neither review skill emits structured findings. Converting prose into
severity-tagged JSON is the runner's job, graded against the per-rule severities
already assigned in docs/CODING_STANDARDS.md. The prose stays in the log for a
human; the gate reads one integer.
"""

import json
from pathlib import Path

import pytest

from orchestrator.gates.review import (
    Finding, build_review_prompt, check_review, grade_findings,
    load_rule_severities, parse_findings, write_review_json,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
STANDARDS = REPO_ROOT / "docs" / "CODING_STANDARDS.md"


# ------------------------------------------------------- the severity table


def test_rule_severities_come_from_the_standards_document():
    severities = load_rule_severities(STANDARDS)

    assert severities["1.1"] == "blocker"
    assert severities["1.3"] == "major"
    assert severities["6.2"] == "minor"
    assert severities["3.3"] == "blocker"


def test_every_documented_rule_is_graded():
    severities = load_rule_severities(STANDARDS)

    assert len(severities) >= 25
    assert set(severities.values()) <= {"blocker", "major", "minor"}


def test_a_standards_file_that_grades_nothing_is_an_error(tmp_path):
    empty = tmp_path / "STANDARDS.md"
    empty.write_text("# Standards\n\nBe nice to each other.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no graded rules"):
        load_rule_severities(empty)


# ------------------------------------------------------------ prose parsing


STRUCTURED = """\
## Standards

Some prose about the diff.

## Spec

More prose.

```findings
standards | 1.1 | UI import in Working/types/signal.py
standards | 6.2 | speculative `mode` parameter nobody calls
spec | - | acceptance criterion 3 (round-trip equality) has no test
```
"""


def test_findings_are_read_from_the_structured_block():
    findings = parse_findings(STRUCTURED)

    assert [f.axis for f in findings] == ["standards", "standards", "spec"]
    assert findings[0].rule == "1.1"
    assert findings[2].rule is None
    assert "round-trip" in findings[2].summary


def test_a_review_with_no_findings_block_yields_none():
    findings = parse_findings("## Standards\n\nNothing to report.\n\n## Spec\n\nMatches.\n")

    assert findings == []


def test_a_malformed_line_is_kept_rather_than_dropped():
    """A finding the runner cannot parse must not vanish — it becomes an
    ungraded finding, which is visible, rather than silence, which is not."""
    findings = parse_findings("```findings\nthis line has no pipes at all\n```\n")

    assert len(findings) == 1
    assert findings[0].rule is None
    assert findings[0].axis == "standards"


# ---------------------------------------------------------------- grading


def test_a_cited_rule_takes_its_documented_severity():
    severities = load_rule_severities(STANDARDS)

    graded = grade_findings(parse_findings(STRUCTURED), severities, default="minor")

    assert graded[0].severity == "blocker"   # 1.1
    assert graded[1].severity == "minor"     # 6.2


def test_an_uncited_finding_cannot_block_a_merge():
    """A reviewer that will not cite a rule does not get to stop a merge at 3am."""
    severities = load_rule_severities(STANDARDS)

    graded = grade_findings(parse_findings(STRUCTURED), severities, default="minor")

    assert graded[2].rule is None
    assert graded[2].severity == "minor"


def test_an_unknown_rule_number_falls_back_to_the_default():
    graded = grade_findings([Finding(axis="standards", rule="9.9", summary="?")],
                            {"1.1": "blocker"}, default="minor")

    assert graded[0].severity == "minor"


def test_a_spec_axis_finding_can_still_be_a_blocker():
    """Spec blockers are graded by rule 7.x, not waved through for being spec."""
    severities = load_rule_severities(STANDARDS)

    graded = grade_findings([Finding(axis="spec", rule="7.2", summary="shipped a cut item")],
                            severities, default="minor")

    assert graded[0].severity == "blocker"


# ------------------------------------------------------------------ the gate


def test_no_blockers_passes():
    verdict = check_review([Finding("standards", "6.2", "nit", severity="minor")],
                           blocking_severities=("blocker",))

    assert verdict.status == "pass"
    assert verdict.blockers == {"standards": 0, "spec": 0}


def test_blockers_on_either_axis_hold_the_ticket():
    verdict = check_review(
        [Finding("standards", "1.1", "UI import", severity="blocker"),
         Finding("spec", "7.2", "cut item shipped", severity="blocker"),
         Finding("standards", "6.2", "nit", severity="minor")],
        blocking_severities=("blocker",))

    assert verdict.status == "blocked"
    assert verdict.blockers == {"standards": 1, "spec": 1}


def test_majors_and_minors_merge_and_become_followups():
    verdict = check_review(
        [Finding("standards", "1.3", "breadth not behaviour", severity="major"),
         Finding("spec", None, "undocumented extra", severity="minor")],
        blocking_severities=("blocker",))

    assert verdict.status == "pass"
    assert len(verdict.followups) == 2


def test_review_json_is_written_with_axis_and_severity(tmp_path):
    path = tmp_path / "review.json"
    findings = grade_findings(parse_findings(STRUCTURED),
                              load_rule_severities(STANDARDS), default="minor")

    write_review_json(findings, path, round_number=1)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["round"] == 1
    assert data["blockers"] == {"standards": 1, "spec": 0}
    assert {f["axis"] for f in data["findings"]} == {"standards", "spec"}
    assert data["findings"][0]["severity"] == "blocker"


# ------------------------------------------------------------------- prompt


def test_the_review_prompt_pins_both_the_fixed_point_and_the_spec():
    """Unattended, either question hangs the ticket until its budget expires."""
    prompt = build_review_prompt(skill="code-review", merge_base="9f2c1ab",
                                 ticket_path=Path("docs/tickets/T01-x.md"),
                                 standards_path=Path("docs/CODING_STANDARDS.md"))

    assert "code-review" in prompt
    assert "9f2c1ab" in prompt
    assert "docs/tickets/T01-x.md" in prompt.replace("\\", "/")
    assert "docs/CODING_STANDARDS.md" in prompt.replace("\\", "/")


def test_the_review_prompt_forbids_asking_questions():
    prompt = build_review_prompt(skill="code-review", merge_base="9f2c1ab",
                                 ticket_path=Path("t.md"),
                                 standards_path=Path("s.md"))

    assert "do not ask" in prompt.lower()


def test_the_review_prompt_requests_the_structured_block():
    prompt = build_review_prompt(skill="code-review", merge_base="9f2c1ab",
                                 ticket_path=Path("t.md"),
                                 standards_path=Path("s.md"))

    assert "```findings" in prompt
    assert "axis | rule | summary" in prompt


def test_out_of_scope_files_are_appended_to_the_review_prompt():
    prompt = build_review_prompt(skill="code-review", merge_base="9f2c1ab",
                                 ticket_path=Path("t.md"), standards_path=Path("s.md"),
                                 scope_deviations=["Adapters/base.py"])

    assert "Adapters/base.py" in prompt
    assert "didn't declare" in prompt
