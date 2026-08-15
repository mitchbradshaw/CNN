"""A whole run, end to end, against a disposable repo with fake agents.

This is the test that proves the pieces compose: scheduler → worktree → agent →
five gates → merge → report. Nothing here launches a real agent, and nothing
here touches the real repository — the stand-in `claude` is a Python script
whose behaviour each test dictates.
"""

import json
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from orchestrator.backlog import load_backlog
from orchestrator.config import load_config
from orchestrator.gitops import Git
from orchestrator.report import RunDirectory
from orchestrator.runloop import Runner
from orchestrator.state import RunState
from orchestrator.status import BLOCKED_UPSTREAM, FAILED, HELD, MERGED

# A stand-in for `claude -p`. Reads the prompt out of argv and acts on it.
FAKE_AGENT = '''
import os, pathlib, re, subprocess, sys

argv = sys.argv[1:]
prompt = argv[argv.index("-p") + 1]
cwd = pathlib.Path.cwd()
mode = os.environ.get("FAKE_AGENT_MODE", "good")


def git(*args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


# The review agent: emit prose plus the structured block the runner asks for.
if "code-review" in prompt:
    print("## Standards\\n\\nNothing to report.\\n\\n## Spec\\n\\nMatches the ticket.\\n")
    findings = os.environ.get("FAKE_REVIEW_FINDINGS", "")
    print("```findings")
    if findings:
        print(findings)
    print("```")
    sys.exit(0)

label = re.search(r"T(\\d\\d)", prompt).group(0)
slug = label.lower()

if mode == "silent":            # exits clean having committed nothing
    print("I have decided to do nothing.")
    sys.exit(0)

if mode == "impl-first":        # first commit touches implementation
    (cwd / "pkg").mkdir(exist_ok=True)
    (cwd / "pkg" / "__init__.py").write_text("")
    (cwd / "pkg" / (slug + ".py")).write_text("def widget():\\n    return 1\\n")
    git("add", "-A"); git("commit", "-m", label + ": implementation first")
    sys.exit(0)

tests = cwd / "tests"
tests.mkdir(exist_ok=True)
if mode == "vacuous":           # a test that asserts nothing
    (tests / ("test_" + slug + ".py")).write_text("def test_" + slug + "(): assert True\\n")
    git("add", "-A"); git("commit", "-m", label + ": vacuous test")
    sys.exit(0)

(tests / ("test_" + slug + ".py")).write_text(
    "from pkg." + slug + " import widget\\n"
    "def test_" + slug + "():\\n    assert widget() == 1\\n"
)
git("add", "-A"); git("commit", "-m", label + ": red")

if mode == "no-impl":           # leaves the suite red
    sys.exit(0)

(cwd / "pkg").mkdir(exist_ok=True)
(cwd / "pkg" / "__init__.py").write_text("")
# Each ticket owns its own symbol unless the test asks for a collision, so the
# overlap gate fires only where a test means it to.
name = "widget" if mode == "collide" else "widget_" + slug
(cwd / "pkg" / (slug + ".py")).write_text(
    "def " + name + "():\\n    return 1\\n"
    + ("" if name == "widget" else "widget = " + name + "\\n")
)
git("add", "-A"); git("commit", "-m", label + ": green")
print(label + " complete")
'''

CONFIG = """
[run]
base_branch = "main"
branch_prefix = "integration/run-"
ticket_branch_prefix = "ticket/"
wall_clock_stop = "07:00"

[ceilings]
concurrent = {ceiling}
opus = 2

[budgets]
S = 2
M = 2
L = 2

[models]
sonnet = "fake-sonnet"
opus = "fake-opus"
review = "fake-review"
fix = "fake-fix"

[paths]
tickets = "docs/tickets"
runs = "runs"
worktrees = "../wt"
claude_md = "CLAUDE.md"
coding_standards = "docs/CODING_STANDARDS.md"
fixture_db = "fixtures/annotations.sqlite"
fixture_db_dest = "DATA/annotations.sqlite"
recordings = []

[agent]
cli = {cli}
extra_args = []
stall_minutes = 5

[suite]
command = ["pytest", "-q", "--tb=no", "-rf"]
timeout_minutes = 5

[retries]
infrastructure = 2
infrastructure_backoff_seconds = 0
stall = {stall_retries}

[review]
skill = "code-review"
max_rounds = 2
blocking_severities = ["blocker"]
followups_file = "FOLLOWUPS.md"
timeout_minutes = 2
default_severity = "minor"

[circuit_breaker]
consecutive_quarantines = {breaker}
quarantine_fraction = 0.4
flaky_weight = 0.5

[rate_limit]
concurrent_signature = 2
fast_exit_seconds = 60
initial_backoff_seconds = 0
max_backoff_seconds = 0
"""

STANDARDS = """\
# Coding standards — scratch

**1.1 — `blocker`.** No module outside `UI/` may import panel.
**6.2 — `minor`.** No speculative generality.
"""

TICKET = """\
---
id: {id}
title: "Fake ticket {id}"
model: sonnet
size: S
blocked_by: {blocked_by}
mutex: []
files: ["tests/test_t{id:02d}.py", "pkg/t{id:02d}.py", "pkg/__init__.py"]
flags: {flags}
level: 0
unblocks: 0
budget_minutes: 2
---
# {id:02d} — Fake ticket

Build a `widget()` that returns 1.
"""


@pytest.fixture
def world(tmp_path):
    """A disposable repo, a fake agent, and a config wired to both."""
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "docs" / "tickets").mkdir(parents=True)
    (root / "fixtures").mkdir()

    (root / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    # As in the real repo: the rootdir has to be importable for `pkg` to resolve.
    (root / "conftest.py").write_text(
        "import sys, pathlib\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).parent))\n", encoding="utf-8")
    (root / ".gitignore").write_text(".pytest_cache/\n__pycache__/\nruns/\nDATA/\n",
                                     encoding="utf-8")
    (root / "CLAUDE.md").write_text("# scratch repo\n", encoding="utf-8")
    (root / "docs" / "CODING_STANDARDS.md").write_text(STANDARDS, encoding="utf-8")
    (root / "tests" / "test_base.py").write_text("def test_base(): assert True\n",
                                                 encoding="utf-8")
    (root / "fixtures" / "annotations.sqlite").write_bytes(b"SQLite format 3\x00")

    agent = tmp_path / "fake_agent.py"
    agent.write_text(textwrap.dedent(FAKE_AGENT), encoding="utf-8")

    git = Git(root)
    git.run("init", "-b", "main")
    git.run("config", "user.email", "runner@example.invalid")
    git.run("config", "user.name", "Runner Test")

    class World:
        def __init__(self):
            self.root = root
            self.git = git
            self.agent = agent
            self.tmp = tmp_path

        def ticket(self, id, *, blocked_by=(), flags=()):
            (root / "docs" / "tickets" / f"T{id:02d}-fake.md").write_text(
                TICKET.format(id=id, blocked_by=list(blocked_by), flags=list(flags)),
                encoding="utf-8")

        def commit(self):
            git.run("add", "-A")
            git.run("commit", "-m", "initial")
            git.create_branch("integration", "main")
            git.checkout("integration")

        def config(self, *, ceiling=2, breaker=3, stall_retries=0):
            path = tmp_path / "config.toml"
            cli = json.dumps([sys.executable, str(agent)])
            path.write_text(CONFIG.format(cli=cli, ceiling=ceiling, breaker=breaker,
                                          stall_retries=stall_retries),
                            encoding="utf-8")
            return load_config(path, repo_root=root)

    return World()


def build_runner(world, config, *, run_label="run"):
    backlog = load_backlog(config.paths.tickets)
    run_dir = RunDirectory.create(config.paths.runs, label=run_label, timestamp="test")
    state = RunState(
        run_id=f"{run_label}-test", integration_branch="integration",
        base_sha=world.git.rev_parse("integration"), config_hash=config.config_hash,
        started_at=datetime.now().isoformat(timespec="seconds"),
        wall_clock_stop=(datetime.now() + timedelta(hours=1)).isoformat(timespec="seconds"),
    )
    return Runner(config=config, backlog=backlog, git=world.git, state=state,
                  run_dir=run_dir, baseline_failed=(), deadline=None, poll_seconds=0.05)


# --------------------------------------------------------------- the happy path


def test_a_two_ticket_run_lands_both_in_dependency_order(world):
    world.ticket(1)
    world.ticket(2, blocked_by=[1])
    world.commit()
    runner = build_runner(world, world.config())

    runner.run()

    assert runner.state.tickets["1"].status == MERGED
    assert runner.state.tickets["2"].status == MERGED

    subjects = [c.subject for c in world.git.merge_commits("integration")]
    assert subjects == ["T02: Fake ticket 2", "T01: Fake ticket 1"], "newest first"


def test_every_gate_is_recorded_for_a_landed_ticket(world):
    world.ticket(1)
    world.commit()
    runner = build_runner(world, world.config())

    runner.run()

    gates = runner.state.tickets["1"].gates
    assert gates["red_proof"] == "pass"
    assert gates["suite"] == "pass"
    assert gates["scope"] == "pass"
    assert gates["review"] == "pass"
    assert gates["overlap"] == "pass"
    assert gates["post_merge_suite"] == "pass"


def test_the_run_directory_holds_the_evidence(world):
    world.ticket(1)
    world.commit()
    runner = build_runner(world, world.config())

    runner.run()

    ticket_dir = runner.run_dir.path / "T01"
    for artifact in ("transcript-1.log", "red-proof.txt", "suite.txt", "scope.txt",
                     "diff.patch", "review.json", "post-merge.txt", "overlap.txt"):
        assert (ticket_dir / artifact).is_file(), artifact
    assert runner.run_dir.report_path.is_file()
    assert "T01" in runner.run_dir.report_path.read_text(encoding="utf-8")


def test_state_json_is_written_and_reloadable(world):
    world.ticket(1)
    world.commit()
    runner = build_runner(world, world.config())

    runner.run()

    from orchestrator.state import load_state
    reloaded = load_state(runner.run_dir.state_path)
    assert reloaded.tickets["1"].status == MERGED
    assert reloaded.tickets["1"].merge_sha


def test_the_working_tree_is_left_clean_and_on_the_integration_branch(world):
    world.ticket(1)
    world.ticket(2)
    world.commit()
    runner = build_runner(world, world.config())

    runner.run()

    assert world.git.current_branch() == "integration"
    assert world.git.is_clean()
    assert world.git.worktree_list() == [world.root]


def test_main_is_never_written(world):
    world.ticket(1)
    world.commit()
    before = world.git.rev_parse("main")
    runner = build_runner(world, world.config())

    runner.run()

    assert world.git.rev_parse("main") == before


# ------------------------------------------------------------------- failures


def test_an_implementation_first_commit_is_quarantined_by_the_red_proof_gate(world, monkeypatch):
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "impl-first")
    runner = build_runner(world, world.config())

    runner.run()

    assert runner.state.tickets["1"].status == FAILED
    assert runner.state.tickets["1"].gates["red_proof"] == "fail"
    assert world.git.branch_exists("ticket/T01"), "the branch survives for the morning"


def test_a_vacuous_first_test_is_quarantined(world, monkeypatch):
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "vacuous")
    runner = build_runner(world, world.config())

    runner.run()

    assert runner.state.tickets["1"].status == FAILED
    assert runner.state.tickets["1"].exit_class == "red-proof"


def test_a_red_suite_at_exit_is_quarantined_without_retrying_the_agent(world, monkeypatch):
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "no-impl")
    runner = build_runner(world, world.config())

    runner.run()

    record = runner.state.tickets["1"]
    assert record.status == FAILED
    assert record.exit_class == "red-at-exit"
    assert record.attempts == 1, "the agent is never retried after a red suite"


def test_an_agent_that_commits_nothing_is_a_stall_and_is_retried(world, monkeypatch):
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "silent")
    runner = build_runner(world, world.config(stall_retries=1))

    runner.run()

    record = runner.state.tickets["1"]
    assert record.status == FAILED
    assert record.exit_class == "stall"
    assert record.attempts == 2, "one retry from a clean worktree, then quarantine"


def test_a_quarantined_blocker_holds_its_dependents_and_the_run_continues(world, monkeypatch):
    world.ticket(1)
    world.ticket(2, blocked_by=[1])
    world.ticket(3)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "no-impl")
    runner = build_runner(world, world.config())
    # Only ticket 1 misbehaves; the others are fine.
    original = runner._run_agent_with_retry

    def selective(ticket, worktree):
        monkeypatch.setenv("FAKE_AGENT_MODE", "no-impl" if ticket.id == 1 else "good")
        return original(ticket, worktree)

    runner._run_agent_with_retry = selective

    runner.run()

    assert runner.state.tickets["1"].status == FAILED
    assert runner.state.tickets["2"].status == BLOCKED_UPSTREAM
    assert runner.state.tickets["3"].status == MERGED, "the run continues with the rest"


def test_a_human_gated_ticket_is_never_dispatched(world):
    world.ticket(1, flags=["human-gate"])
    world.ticket(2)
    world.commit()
    runner = build_runner(world, world.config())

    runner.run()

    assert runner.state.tickets["1"].status == HELD
    assert runner.state.tickets["1"].attempts == 0
    assert not world.git.branch_exists("ticket/T01")
    assert runner.state.tickets["2"].status == MERGED


def test_review_blockers_survive_the_fix_round_and_quarantine(world, monkeypatch):
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_REVIEW_FINDINGS", "standards | 1.1 | imports panel outside UI/")
    runner = build_runner(world, world.config())

    runner.run()

    record = runner.state.tickets["1"]
    assert record.status == FAILED
    assert record.exit_class == "review-rejected"
    assert record.review_rounds == 2, "a hard cap of two rounds"
    assert record.review_blockers == {"standards": 1, "spec": 0}


def test_a_minor_finding_merges_and_becomes_a_followup(world, monkeypatch):
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_REVIEW_FINDINGS", "standards | 6.2 | a speculative parameter")
    runner = build_runner(world, world.config())

    runner.run()

    assert runner.state.tickets["1"].status == MERGED
    followups = (world.root / "FOLLOWUPS.md").read_text(encoding="utf-8")
    assert "speculative parameter" in followups
    assert "6.2" in followups


def test_the_circuit_breaker_halts_a_run_that_is_failing_wholesale(world, monkeypatch):
    for i in range(1, 6):
        world.ticket(i)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "no-impl")
    runner = build_runner(world, world.config(ceiling=1, breaker=3))

    runner.run()

    assert runner.state.circuit_breaker.tripped
    quarantined = sum(1 for r in runner.state.tickets.values() if r.status == FAILED)
    assert quarantined == 3, "it halts at three, rather than burning the whole backlog"
    assert "CIRCUIT BREAKER" in "\n".join(runner.log)


def test_the_overlap_check_holds_the_second_ticket_and_never_resolves_it(world, monkeypatch):
    world.ticket(1)
    world.ticket(2)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "collide")
    runner = build_runner(world, world.config(ceiling=1))

    runner.run()

    statuses = {i: runner.state.tickets[i].status for i in ("1", "2")}
    assert statuses["1"] == MERGED
    assert statuses["2"] == "OVERLAP"
    assert runner.state.tickets["2"].overlap_symbols == ["widget"]
    assert not world.git.is_merged("ticket/T02", "integration")
