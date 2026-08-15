"""`state.json` — the orchestrator's memory, per ORCHESTRATOR_SPEC Appendix A.

Two properties matter more than anything else in this module.

**The DAG is not stored here.** Blocking edges, mutexes, flags and models are
re-derived from the ticket front-matter on every start. This file holds only
what is *mutable*, so editing a ticket's `blocked_by` never requires migrating
state.

**Git is the durable truth; this file is an index over it.** On restart,
nothing is re-dispatched on the strength of a field in this file. Every ticket
that was mid-flight is reconciled against what git can actually show.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import status as st
from .gitops import Git

SCHEMA = 1


@dataclass
class TicketRecord:
    status: str = st.PENDING
    attempts: int = 0
    branch: str | None = None
    worktree: str | None = None
    gates: dict[str, str] = field(default_factory=dict)
    review_rounds: int = 0
    review_blockers: dict[str, int] = field(default_factory=dict)
    scope_deviations: list[str] = field(default_factory=list)
    flaky_tests: list[str] = field(default_factory=list)
    overlap_symbols: list[str] = field(default_factory=list)
    merge_sha: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    exit_class: str | None = None


@dataclass
class CircuitBreaker:
    consecutive_quarantines: int = 0
    tripped: bool = False


@dataclass
class RunState:
    run_id: str
    integration_branch: str
    base_sha: str
    config_hash: str
    started_at: str
    wall_clock_stop: str
    schema: int = SCHEMA
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    merge_lock_holder: str | None = None
    symbols: dict[str, int] = field(default_factory=dict)
    tickets: dict[str, TicketRecord] = field(default_factory=dict)

    def record(self, ticket_id: int) -> TicketRecord:
        return self.tickets.setdefault(str(ticket_id), TicketRecord())

    def statuses(self, ticket_ids) -> dict[int, str]:
        """The mapping the pure scheduler consumes."""
        return {i: self.tickets.get(str(i), TicketRecord()).status for i in ticket_ids}


def _to_dict(state: RunState) -> dict:
    data = asdict(state)
    # Field order in the file follows Appendix A, which is the order a human
    # reads it in at 8am.
    ordered = {
        "schema": data.pop("schema"),
        "run_id": data.pop("run_id"),
        "integration_branch": data.pop("integration_branch"),
        "base_sha": data.pop("base_sha"),
        "config_hash": data.pop("config_hash"),
        "started_at": data.pop("started_at"),
        "wall_clock_stop": data.pop("wall_clock_stop"),
        "circuit_breaker": data.pop("circuit_breaker"),
        "merge_lock_holder": data.pop("merge_lock_holder"),
        "symbols": data.pop("symbols"),
        "tickets": data.pop("tickets"),
    }
    ordered.update(data)
    return ordered


def save_state(state: RunState, path: Path | str) -> None:
    """Write atomically. `os.replace` is atomic on NTFS."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Serialise *before* touching the temp file, so a non-serialisable value
    # raises without having disturbed the state already on disk.
    payload = json.dumps(_to_dict(state), indent=1)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def load_state(path: Path | str) -> RunState:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError(f"{path}: unsupported state schema {data.get('schema')!r}")
    tickets = {
        key: TicketRecord(**value) for key, value in data.pop("tickets", {}).items()
    }
    breaker = CircuitBreaker(**data.pop("circuit_breaker", {}))
    return RunState(tickets=tickets, circuit_breaker=breaker, **data)


def reconcile(state: RunState, git: Git) -> list[str]:
    """Re-derive mid-flight ticket status from git. Returns a note per change.

    Every ticket found in RUNNING, GATING or MERGING is stale by definition —
    its subprocess died with the orchestrator. None of them is trusted.
    """
    notes: list[str] = []

    # A lock held by a process that no longer exists is not a lock.
    if state.merge_lock_holder is not None:
        notes.append(f"cleared stale merge lock held by T{int(state.merge_lock_holder):02d}")
        state.merge_lock_holder = None

    integration = state.integration_branch

    for key, record in state.tickets.items():
        if record.status not in st.IN_FLIGHT:
            continue
        label = f"T{int(key):02d}"
        branch = record.branch

        if not branch or not git.branch_exists(branch):
            record.status = st.READY
            record.branch = None
            record.worktree = None
            notes.append(f"{label}: no branch in git — reset to READY")
            continue

        # `is_merged` is not the question to ask: a branch that never committed
        # anything is trivially an ancestor of the integration branch and would
        # read as landed. Every merge here is `--no-ff`, so the honest question
        # is whether a merge commit on the integration branch names this
        # branch's tip as a parent.
        merge_sha = _find_merge_sha(git, integration, branch)

        if merge_sha:
            record.merge_sha = merge_sha
            # A crash between the merge and the post-merge suite must re-run the
            # suite: running it twice is free, skipping it is not.
            if record.gates.get("post_merge_suite") in (None, "not-run"):
                record.status = st.MERGING
                notes.append(f"{label}: merged but post-merge suite never ran — re-running")
            else:
                record.status = st.MERGED
                notes.append(f"{label}: already merged into {integration} — MERGED")
            continue

        if git.commits_between(integration, branch):
            record.status = st.GATING
            notes.append(f"{label}: branch has unmerged commits — resuming at the gates")
            continue

        git.delete_branch(branch)
        record.status = st.READY
        record.branch = None
        record.worktree = None
        notes.append(f"{label}: branch had no commits — deleted, reset to READY")

    return notes


def _find_merge_sha(git: Git, integration: str, branch: str) -> str | None:
    """The merge commit on `integration` that brought `branch` in."""
    tip = git.rev_parse(branch)
    for commit in git.merge_commits(integration):
        parents = git.run("rev-list", "--parents", "-n", "1", commit.sha).split()[1:]
        if tip in parents:
            return commit.sha
    return None
