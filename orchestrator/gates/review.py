"""Gate 4 — two-axis review, converted into a number the gate can read.

Three things this module exists to guarantee.

**The reviewer is never asked a question.** The in-repo `code-review` skill asks
for a fixed point if none is given, and asks where the spec is if it cannot find
one. Unattended, either question hangs the ticket until its budget expires, so
both are passed explicitly and the prompt forbids asking.

**Severity is the runner's judgement, not the reviewer's.** `docs/CODING_STANDARDS.md`
already grades every rule `blocker` / `major` / `minor`. A finding that cites a
rule takes that rule's grade; a finding that cites nothing takes the configured
default, which is `minor` — a reviewer that will not cite a rule does not get to
stop a merge at 3am.

**With one exception, added after run-20260817-2050.** The reviewer may mark a
finding `judgement`, and a judgement call never blocks however its rule is
graded. That run quarantined T02 on four blockers the review's own prose
disclaimed — it wrote "No blockers" and labelled every finding a judgement call,
but cited rules 2.5 and 4.2, which are graded `blocker`, so the runner promoted
them. Re-grading exists to stop a reviewer inventing severity upward; it should
not manufacture severity the reviewer refused to claim. The rule must still be
cited, so hedging costs the reviewer its citation either way.

**Nothing is silently dropped.** A line the parser cannot understand becomes an
ungraded finding, which is visible in the morning, rather than silence, which is
not.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

#: `**1.1 — `blocker` [test].**` in docs/CODING_STANDARDS.md
RULE_SEVERITY = re.compile(r"\*\*(\d+\.\d+)\s*[—-]\s*`(blocker|major|minor)`")

#: The machine-readable block the runner asks the reviewer to end with.
FINDINGS_BLOCK = re.compile(r"```findings\s*\n(.*?)```", re.DOTALL)

AXES = ("standards", "spec")

REVIEW_PROMPT = """\
Run the `{skill}` skill against this worktree, with BOTH inputs supplied — do
not ask for either, and do not ask any other question. This session is
unattended: a question hangs the review until its budget expires.

  Fixed point:  {merge_base}
  Spec source:  {ticket_path}
  Standards:    {standards_path}

Review `git diff {merge_base}...HEAD`.
{scope_note}
After the two reports, and as the LAST thing you output, emit one fenced block
listing every finding, one per line, in the form
`axis | rule | judgement | summary`:

```findings
axis | rule | judgement | summary
```

where `axis` is `standards` or `spec`, and `rule` is the rule number you are
citing from {standards_path} (for example `1.1`), or `-` if the finding cites no
documented rule.

The third field is `judgement` or `-`, and it is the only severity input you
have. Use `judgement` when the finding depends on an interpretation someone
could reasonably disagree with — a naming call, a design preference, an
arguable reading of a rule. Use `-` only when the code definitely violates the
rule as written and no reasonable reviewer would say otherwise. A `judgement`
finding is recorded and handed to the human in the morning; a `-` finding
against a `blocker` rule stops the merge tonight and blocks every dependent
ticket, so do not use `-` for something you would want to discuss first.

Do not assign severities beyond that — they are graded from the standards
document. If there are no findings, emit the block with no lines in it.
"""

SCOPE_NOTE = """
The agent touched these files the ticket didn't declare — check whether that is
justified: {files}
"""


@dataclass
class Finding:
    axis: str
    rule: str | None
    summary: str
    severity: str = "minor"
    #: The reviewer would not stand behind this as a definite violation. Capped
    #: below `blocker` at grading time, whatever the cited rule is graded.
    judgement: bool = False


@dataclass(frozen=True)
class ReviewVerdict:
    status: str                       # pass | blocked
    blockers: dict[str, int]
    findings: tuple[Finding, ...] = ()
    followups: tuple[Finding, ...] = ()


def load_rule_severities(standards_path: Path | str) -> dict[str, str]:
    """Rule number → severity, read from the standards document itself."""
    text = Path(standards_path).read_text(encoding="utf-8")
    severities = {m.group(1): m.group(2) for m in RULE_SEVERITY.finditer(text)}
    if not severities:
        raise ValueError(
            f"{standards_path}: no graded rules found — the Standards axis would "
            f"fall back to Fowler smells, which are judgement calls and produce "
            f"false blockers at 3am"
        )
    return severities


def parse_findings(prose: str) -> list[Finding]:
    """Read the structured block out of the reviewer's output."""
    match = FINDINGS_BLOCK.search(prose)
    if not match:
        return []

    findings: list[Finding] = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("axis | rule | summary"):
            continue   # the template line, echoed back

        parts = [p.strip() for p in line.split("|")]
        judgement = False
        if len(parts) >= 3:
            axis = parts[0].lower() if parts[0].lower() in AXES else "standards"
            rule = parts[1] if re.fullmatch(r"\d+\.\d+", parts[1]) else None
            rest = parts[2:]
            # The optional 4th field. Only the exact words `judgement` and `-`
            # are read as the flag, so a summary that merely happens to contain
            # a pipe keeps all of its text — losing half a finding to a stray
            # separator would be worse than missing the hedge.
            if len(rest) >= 2 and rest[0].lower() in ("judgement", "judgment", "-", ""):
                judgement = rest[0].lower().startswith("judg")
                rest = rest[1:]
            summary = " | ".join(rest)
        else:
            # Unparseable, but not discardable.
            axis, rule, summary = "standards", None, line

        findings.append(Finding(axis=axis, rule=rule, summary=summary,
                                judgement=judgement))
    return findings


#: What a `blocker`-graded rule decays to when the reviewer hedges it. `major`
#: rather than `minor`: the finding still lands in FOLLOWUPS.md at the top of the
#: list, it just does not hold the merge overnight.
JUDGEMENT_CAP = "major"


def grade_findings(findings, severities: dict[str, str], *, default: str) -> list[Finding]:
    """Assign each finding the severity its cited rule carries.

    A finding the reviewer marked `judgement` is capped below `blocker`. It is an
    interpretation the reviewer declined to stand behind, and an interpretation
    is a conversation to have in the morning rather than a gate at 3am.
    """
    graded = []
    for finding in findings:
        severity = severities.get(finding.rule or "", default)
        if finding.judgement and severity == "blocker":
            severity = JUDGEMENT_CAP
        graded.append(Finding(axis=finding.axis, rule=finding.rule,
                              summary=finding.summary, severity=severity,
                              judgement=finding.judgement))
    return graded


def check_review(findings, *, blocking_severities) -> ReviewVerdict:
    """The gate reads one integer per axis: the blocker count."""
    blocking = set(blocking_severities)
    blockers = {axis: 0 for axis in AXES}
    followups = []

    for finding in findings:
        if finding.severity in blocking:
            blockers[finding.axis] = blockers.get(finding.axis, 0) + 1
        else:
            followups.append(finding)

    return ReviewVerdict(
        status="blocked" if any(blockers.values()) else "pass",
        blockers=blockers,
        findings=tuple(findings),
        followups=tuple(followups),
    )


def write_review_json(findings, path: Path | str, *, round_number: int) -> None:
    blockers = {axis: 0 for axis in AXES}
    for finding in findings:
        if finding.severity == "blocker":
            blockers[finding.axis] = blockers.get(finding.axis, 0) + 1

    payload = {
        "round": round_number,
        "blockers": blockers,
        "counts": {
            severity: sum(1 for f in findings if f.severity == severity)
            for severity in ("blocker", "major", "minor")
        },
        "findings": [asdict(f) for f in findings],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def build_review_prompt(*, skill: str, merge_base: str, ticket_path: Path | str,
                        standards_path: Path | str, scope_deviations=()) -> str:
    scope_note = ""
    if scope_deviations:
        scope_note = SCOPE_NOTE.format(files=", ".join(scope_deviations))

    return REVIEW_PROMPT.format(
        skill=skill,
        merge_base=merge_base,
        ticket_path=Path(ticket_path).as_posix(),
        standards_path=Path(standards_path).as_posix(),
        scope_note=scope_note,
    )
