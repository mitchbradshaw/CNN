"""A whole run, end to end, against a disposable repo with fake agents.

This is the test that proves the pieces compose: scheduler → worktree → agent →
five gates → merge → report. Nothing here launches a real agent, and nothing
here touches the real repository — the stand-in `claude` is a Python script
whose behaviour each test dictates.
"""

import json
import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from orchestrator.backlog import load_backlog
from orchestrator.config import load_config
from orchestrator.gitops import Git
from orchestrator.report import RunDirectory
from orchestrator.runloop import Runner
from orchestrator.state import RunState
from orchestrator.status import (
    BLOCKED_UPSTREAM, DEFERRED, FAILED, HELD, MERGED, PENDING, READY,
)

# A stand-in for `claude -p`. Reads the prompt out of argv and acts on it.
FAKE_AGENT = '''
import os, pathlib, re, subprocess, sys

argv = sys.argv[1:]
prompt = argv[argv.index("-p") + 1]
cwd = pathlib.Path.cwd()


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

# Per-ticket first, then the run-wide default. A test that wants one ticket to
# misbehave sets `FAKE_AGENT_MODE_T01` once, before the run: agents are launched
# on concurrent threads, so flipping a single global between dispatches is a race
# that the two agents resolve by whichever happens to read it last.
mode = os.environ.get("FAKE_AGENT_MODE_" + label,
                      os.environ.get("FAKE_AGENT_MODE", "good"))

# The environment refusing to work, not the ticket being wrong. The counter
# lives outside every worktree so `-once` survives the teardown between
# attempts. See run-20260818-2244, where four agents printed exactly this.
if mode in ("usage-exhausted", "usage-exhausted-once"):
    counter = pathlib.Path(os.environ["FAKE_FLAKE_DIR"]) / (label + ".usage")
    seen = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(seen + 1))
    if mode == "usage-exhausted" or seen == 0:
        print("You're out of extra usage \\u00b7 resets 3:30am (Australia/Brisbane)")
        sys.exit(1)
    mode = "good"

if mode == "silent":            # exits clean having committed nothing
    print("I have decided to do nothing.")
    sys.exit(0)

# Stalls once, having dirtied the worktree without committing anything, then
# reports on its second run whether that mess was still there. RETRY_PREFIX
# promises the retry "a clean worktree"; this is what checks the promise.
if mode == "dirty-stall":
    scratch = pathlib.Path(os.environ["FAKE_FLAKE_DIR"])
    marker = scratch / (label + ".attempt")
    seen = int(marker.read_text()) if marker.exists() else 0
    marker.write_text(str(seen + 1))
    if seen == 0:
        (cwd / "half_written.py").write_text("garbage the agent left behind\\n")
        (cwd / "tests" / "test_base.py").write_text("def test_base(): assert False\\n")
        print("I got confused and stopped.")
        sys.exit(0)
    dirt = []
    if (cwd / "half_written.py").exists():
        dirt.append("untracked-leftover")
    if "assert False" in (cwd / "tests" / "test_base.py").read_text():
        dirt.append("modified-tracked")
    (scratch / (label + ".sawdirt")).write_text(",".join(dirt) or "clean")
    mode = "good"

if mode == "impl-first":        # first commit touches implementation
    (cwd / "pkg").mkdir(exist_ok=True)
    (cwd / "pkg" / "__init__.py").write_text("")
    (cwd / "pkg" / (slug + ".py")).write_text("def widget():\\n    return 1\\n")
    git("add", "-A"); git("commit", "-m", label + ": implementation first")
    sys.exit(0)

tests = cwd / "tests"
tests.mkdir(exist_ok=True)

if mode == "flaky":
    # Fails the first two times it is ever run, passes afterwards. The count
    # lives outside the worktree so the flake does not follow the test into
    # the next ticket's branch: run 1 is the red-proof gate, run 2 is the
    # suite gate, run 3 is the targeted re-run that goes green.
    (tests / ("test_" + slug + ".py")).write_text(
        "import os, pathlib\\n"
        "def test_" + slug + "():\\n"
        "    counter = pathlib.Path(os.environ['FAKE_FLAKE_DIR']) / '" + slug + ".count'\\n"
        "    n = int(counter.read_text()) if counter.exists() else 0\\n"
        "    counter.write_text(str(n + 1))\\n"
        "    assert n >= 2, 'flaky: run number ' + str(n + 1)\\n"
    )
    git("add", "-A"); git("commit", "-m", label + ": red")
    sys.exit(0)

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

# Speak whichever dialect the runner asked for. Under `--output-format
# stream-json` the CLI emits one JSON object per line and ends with a `result`
# record carrying the usage; the runner reconstructs the prose from it.
if "stream-json" in argv:
    import json as _json
    print(_json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Working " + label + "."}]}}))
    print(_json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "num_turns": 7, "result": label + " complete", "total_cost_usd": 0.5,
        "usage": {"input_tokens": 100, "output_tokens": 900,
                  "cache_creation_input_tokens": 1000,
                  "cache_read_input_tokens": 98000},
    }))
else:
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
launch_stagger_seconds = {stagger}
output_format = "{output_format}"
max_budget_usd = 0.0

[suite]
command = ["pytest", "-q", "--tb=no", "-rf"]
timeout_minutes = 5

[retries]
infrastructure = {infra_retries}
infrastructure_backoff_seconds = 0
stall = {stall_retries}

[review]
skill = "code-review"
max_rounds = 2
blocking_severities = ["blocker"]
followups_file = "FOLLOWUPS.md"
timeout_minutes = 2
default_severity = "minor"

[overlap]
include_private = true

[circuit_breaker]
consecutive_quarantines = {breaker}
quarantine_fraction = 0.4
flaky_weight = 0.5

[rate_limit]
concurrent_signature = 2
fast_exit_seconds = 60
initial_backoff_seconds = 0
max_backoff_seconds = 0
max_usage_wait_seconds = {max_usage_wait}
usage_reset_grace_seconds = 0
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

    # Where the `flaky` mode keeps its run counts — outside every worktree, so a
    # flake does not follow its test file into the next ticket's branch.
    flake_dir = tmp_path / "flake"
    flake_dir.mkdir()
    os.environ["FAKE_FLAKE_DIR"] = str(flake_dir)

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

        def config(self, *, ceiling=2, breaker=3, stall_retries=0, stagger=0.0,
                   infra_retries=2, max_usage_wait=0, output_format="text"):
            path = tmp_path / "config.toml"
            cli = json.dumps([sys.executable, str(agent)])
            path.write_text(CONFIG.format(cli=cli, ceiling=ceiling, breaker=breaker,
                                          stall_retries=stall_retries, stagger=stagger,
                                          infra_retries=infra_retries,
                                          max_usage_wait=max_usage_wait,
                                          output_format=output_format),
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
    # Only ticket 1 misbehaves; the others are fine. Declared per ticket and up
    # front, because tickets 1 and 3 are dispatched into concurrent threads.
    monkeypatch.setenv("FAKE_AGENT_MODE_T01", "no-impl")
    runner = build_runner(world, world.config())

    runner.run()

    assert runner.state.tickets["1"].status == FAILED
    assert runner.state.tickets["2"].status == BLOCKED_UPSTREAM
    assert runner.state.tickets["3"].status == MERGED, "the run continues with the rest"


def test_agents_in_one_wave_are_not_launched_in_the_same_instant(world):
    """run-20260817-2050 launched three agents at 20:56:35 and lost two of them.

    The CLI writes a global `~/.claude.json` at startup, so simultaneous launches
    race on it; two agents read it mid-write, looped on a JSON parse error, and
    burned their whole budget. The worktrees are isolated but that file is not,
    and nothing else in the design notices — so the launches are spaced instead.

    A lower bound on elapsed time, which `sleep` guarantees; upper bounds would
    be flaky.
    """
    world.ticket(1)
    world.ticket(2)
    world.commit()
    runner = build_runner(world, world.config(ceiling=2, stagger=0.3))

    started = time.monotonic()
    dispatched = runner._dispatch_wave()
    elapsed = time.monotonic() - started

    assert len(dispatched) == 2
    assert elapsed >= 0.3, "the second agent waited for the first to clear the config"
    runner._join_all()


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


def test_consecutive_flakes_trip_the_breaker_even_though_each_one_merges(world, monkeypatch):
    """The half-weight flake rule has to survive the merges it enables. If the
    flake count shared the quarantine counter, every flaky ticket would wipe
    its own contribution and the rule would be a no-op."""
    for i in range(1, 8):
        world.ticket(i)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "flaky")
    runner = build_runner(world, world.config(ceiling=1, breaker=3))

    runner.run()

    merged = [i for i, r in runner.state.tickets.items() if r.status == MERGED]
    assert merged, "flaky tickets still merge — that is the amendment"
    assert runner.state.circuit_breaker.consecutive_flakes >= 6
    assert runner.state.circuit_breaker.tripped
    assert "flake mark" in runner.state.circuit_breaker.reason


def test_a_clean_ticket_clears_the_flake_streak(world, monkeypatch):
    world.ticket(1)
    world.commit()
    runner = build_runner(world, world.config())
    runner.state.circuit_breaker.consecutive_flakes = 2

    runner.run()

    assert runner.state.tickets["1"].status == MERGED
    assert runner.state.circuit_breaker.consecutive_flakes == 0


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


# ------------------------------------------- the environment, not the ticket
#
# run-20260818-2244 is the run these tests exist for. Four agents printed
# `You're out of extra usage`, and every one of them was quarantined: the
# breaker tripped, twenty-odd dependents went BLOCKED_UPSTREAM, and the night
# ended at 23:00 having merged nothing. ORCHESTRATOR_SPEC.md's failure table
# has always said an infrastructure failure backs off, retries, and *does not
# count against the ticket* — that policy was implemented for provisioning and
# never for the agent.


def test_a_usage_exhaustion_defers_the_ticket_rather_than_quarantining_it(
        world, monkeypatch):
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "usage-exhausted")
    runner = build_runner(world, world.config(infra_retries=2))

    runner.run()

    record = runner.state.tickets["1"]
    assert record.status == DEFERRED, "the environment failed, not the ticket"
    assert record.exit_class == "infrastructure"
    assert record.attempts == 0, "an environment failure is not an attempt at the work"


def test_a_deferred_ticket_does_not_block_its_dependents(world, monkeypatch):
    """BLOCKED_UPSTREAM is a verdict on the blocker's *work*. Nothing was
    judged here, so the dependent is merely not-yet-runnable."""
    world.ticket(1)
    world.ticket(2, blocked_by=[1])
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "usage-exhausted")
    runner = build_runner(world, world.config(ceiling=1, infra_retries=1))

    runner.run()

    assert runner.state.tickets["1"].status == DEFERRED
    # Read through `statuses`, not `tickets`: records are created lazily, and a
    # dependent with no record at all is the strongest form of "nothing was
    # decided about it" — which is the property under test.
    assert runner.state.statuses([2])[2] != BLOCKED_UPSTREAM
    assert runner.state.statuses([2])[2] in (PENDING, READY, DEFERRED)


def test_infrastructure_failures_never_trip_the_circuit_breaker(world, monkeypatch):
    """The breaker's question is 'is the base broken?'. A usage cap is not
    evidence about the base, and tripping on it throws away the whole night."""
    for i in range(1, 6):
        world.ticket(i)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "usage-exhausted")
    runner = build_runner(world, world.config(ceiling=1, breaker=3, infra_retries=1))

    runner.run()

    assert not runner.state.circuit_breaker.tripped
    assert all(r.status == DEFERRED for r in runner.state.tickets.values())


def test_a_ticket_recovers_when_the_environment_does(world, monkeypatch):
    """The whole point of retrying: the usage window reopens and the work lands."""
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "usage-exhausted-once")
    runner = build_runner(world, world.config(infra_retries=3))

    runner.run()

    assert runner.state.tickets["1"].status == MERGED
    assert runner.state.tickets["1"].attempts == 1, "the retry was not charged to the ticket"


def test_a_deferred_ticket_leaves_no_branch_to_collide_with_the_next_run(
        world, monkeypatch):
    """`provision` uses `git worktree add -b`, which fails outright when the
    branch already exists — the defect that killed the first three dispatches
    of run 2. A ticket that produced no commits must leave nothing behind."""
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "usage-exhausted")
    runner = build_runner(world, world.config(infra_retries=1))

    runner.run()

    assert "ticket/T01" not in world.git.branch_names()


def test_a_deferred_ticket_keeps_its_branch_when_it_had_committed_work(
        world, monkeypatch):
    """The mirror of the rule above. A branch carrying commits is evidence and
    is never deleted, however the run ended."""
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "usage-exhausted-once")
    runner = build_runner(world, world.config(infra_retries=3))

    runner.run()

    assert runner.state.tickets["1"].status == MERGED
    assert "ticket/T01" in world.git.branch_names()


def test_deferred_tickets_are_named_in_the_report_as_retryable(world, monkeypatch):
    """At 8am the difference between 'this ticket is wrong' and 'the plan ran
    out of usage' is the difference between debugging and rerunning."""
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "usage-exhausted")
    runner = build_runner(world, world.config(infra_retries=1))

    runner.run()

    report = (runner.run_dir.report_path).read_text(encoding="utf-8")
    assert "DEFERRED" in report
    assert "--resume" in report, "the report must say how to pick them back up"


def test_a_resumed_run_re_dispatches_deferred_tickets(world, monkeypatch):
    """A deferred ticket is the one thing a resume exists to retry. Quarantined
    tickets stay quarantined; deferred ones go back in the queue."""
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "usage-exhausted")
    runner = build_runner(world, world.config(infra_retries=1))
    runner.run()
    assert runner.state.tickets["1"].status == DEFERRED

    monkeypatch.setenv("FAKE_AGENT_MODE", "good")
    resumed = Runner(config=world.config(infra_retries=1), backlog=runner.backlog,
                     git=world.git, state=runner.state, run_dir=runner.run_dir,
                     baseline_failed=(), deadline=None, poll_seconds=0.05)
    resumed.run()

    assert resumed.state.tickets["1"].status == MERGED


# --------------------------------------------------- the post-mortem (item 6)
#
# FOLLOWUPS.md carries a hand-written harness section for runs 1157, 2050 and
# 0554, and nothing at all for 1114 and 2244 — the two most recent and the two
# worst. The improvement loop was a habit, and habits lapse. Writing the stub
# mechanically makes a *missing* post-mortem visible instead of silent.


def test_every_run_appends_a_postmortem_stub(world, monkeypatch):
    world.ticket(1)
    world.commit()
    runner = build_runner(world, world.config())

    runner.run()

    followups = (world.root / "FOLLOWUPS.md").read_text(encoding="utf-8")
    assert "## Harness —" in followups
    assert runner.state.run_id in followups


def test_the_stub_names_every_ticket_that_did_not_land(world, monkeypatch):
    """The triage list writes itself: one line per ticket that cost tokens and
    produced no merge, with the exit class that says which kind of failure it
    was."""
    world.ticket(1)
    world.ticket(2)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE_T02", "no-impl")
    runner = build_runner(world, world.config())

    runner.run()

    followups = (world.root / "FOLLOWUPS.md").read_text(encoding="utf-8")
    section = followups.split("## Harness —")[-1]
    assert "T02" in section
    assert "red-at-exit" in section
    assert "T01" not in section, "a ticket that landed is not a post-mortem item"


def test_a_clean_run_still_writes_a_stub_saying_so(world):
    """A night where nothing failed is itself a finding, and the absence of a
    section must never be ambiguous between 'clean' and 'nobody wrote it up'."""
    world.ticket(1)
    world.commit()
    runner = build_runner(world, world.config())

    runner.run()

    followups = (world.root / "FOLLOWUPS.md").read_text(encoding="utf-8")
    section = followups.split("## Harness —")[-1]
    assert "1 merged" in section or "nothing to triage" in section.lower()


def test_the_stub_records_what_the_night_cost(world):
    """The post-mortem and the cost report answer the same morning question."""
    world.ticket(1)
    world.commit()
    runner = build_runner(world, world.config())

    runner.run()

    section = (world.root / "FOLLOWUPS.md").read_text(
        encoding="utf-8").split("## Harness —")[-1]
    assert "token" in section.lower() or "cost" in section.lower()


# ------------------------------------------ cost accounting, end to end (item 4)


def test_a_structured_session_lands_its_cost_in_the_state_and_the_report(world):
    """The wiring the unit tests cannot cover: CLI flags -> usage extraction ->
    state -> REPORT.md. `ORCHESTRATOR_SPEC.md` has specified this column since
    the design settled and five runs shipped without it."""
    world.ticket(1)
    world.commit()
    runner = build_runner(world, world.config(output_format="stream-json"))

    runner.run()

    record = runner.state.tickets["1"]
    assert record.status == MERGED
    assert record.tokens and record.tokens > 0, "no usage recorded"
    assert record.cost_usd and record.cost_usd > 0

    report = runner.run_dir.report_path.read_text(encoding="utf-8")
    assert "tokens" in report
    assert "Run total:" in report


def test_the_prose_transcript_survives_structured_output(world):
    """`transcript-N.log` must stay readable — it is what a human opens at 8am,
    and what the stall retry injects into the next prompt. If structured output
    left raw JSON there, the review gate would also stop finding its fenced
    findings block and every ticket would merge unreviewed."""
    world.ticket(1)
    world.commit()
    runner = build_runner(world, world.config(output_format="stream-json"))

    runner.run()

    transcript = runner.run_dir.artifact(1, "transcript-1.log").read_text(encoding="utf-8")
    assert "T01 complete" in transcript
    assert '"type":"result"' not in transcript, "raw JSON leaked into the prose log"
    # The stream itself is kept beside it, because the reconstruction is the
    # thing you stop trusting when something looks wrong.
    assert runner.run_dir.artifact(1, "transcript-1.jsonl").exists()


def test_review_rounds_are_costed_too(world, monkeypatch):
    """A review is two parallel sub-agents plus an orchestrating session, and it
    runs on every ticket. Costing only the ticket agent would hide the more
    expensive half of the night."""
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_REVIEW_FINDINGS", "standards | 6.2 | - | speculative generality")
    runner = build_runner(world, world.config(output_format="stream-json"))

    runner.run()

    # The fake reviewer prints prose, not stream-json, so it contributes no
    # usage — but the ticket agent's must still have been recorded, and the
    # accumulator must not have been clobbered by the uncosted review.
    assert runner.state.tickets["1"].tokens == 100 + 900 + 1000 + 98000


# ------------------------------- the retry's clean worktree, actually clean
#
# `RETRY_PREFIX` tells the retrying agent: "you are starting again from a clean
# worktree, so do not assume any of its work exists." That was never true —
# `_run_agent_with_retry` handed it the same worktree the previous attempt
# stalled in, half-edited. The agent was being lied to about the state of its
# own tree, which is the one thing it cannot check cheaply.


def test_the_retry_gets_the_clean_worktree_its_prompt_promises(world, monkeypatch):
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "dirty-stall")
    runner = build_runner(world, world.config(stall_retries=1))

    runner.run()

    saw = (Path(os.environ["FAKE_FLAKE_DIR"]) / "T01.sawdirt").read_text()
    assert saw == "clean", (
        f"the retry inherited the stalled attempt's mess ({saw}) while its "
        f"prompt told it the worktree was clean"
    )
    assert runner.state.tickets["1"].status == MERGED


def test_a_stall_retry_still_lands_on_the_same_branch(world, monkeypatch):
    """Re-provisioning must not strand the ticket: same branch name, and the
    merge still happens from it."""
    world.ticket(1)
    world.commit()
    monkeypatch.setenv("FAKE_AGENT_MODE", "dirty-stall")
    runner = build_runner(world, world.config(stall_retries=1))

    runner.run()

    assert runner.state.tickets["1"].branch == "ticket/T01"
    assert "ticket/T01" in world.git.branch_names()
    subjects = [c.subject for c in world.git.merge_commits("integration")]
    assert subjects == ["T01: Fake ticket 1"]


def test_a_stall_that_committed_work_is_never_wiped(world, monkeypatch):
    """The safety bound on the whole idea. Re-provisioning is only safe because
    a stall means zero commits by construction — `classify_exit` returns `ok`
    for a timeout that produced commits, precisely so the gates judge the work
    rather than the run loop discarding it. If that ever stops holding, this
    test is what says so."""
    world.ticket(1)
    world.commit()
    # `no-impl` commits its failing test and then exits: real work, red suite.
    monkeypatch.setenv("FAKE_AGENT_MODE", "no-impl")
    runner = build_runner(world, world.config(stall_retries=1))

    runner.run()

    record = runner.state.tickets["1"]
    assert record.exit_class == "red-at-exit", "committed work went to the gates"
    assert record.attempts == 1, "a ticket that produced work is not re-run blind"
    assert world.git.commits_between("integration", "ticket/T01"), (
        "the committed work is still on the branch as evidence"
    )
