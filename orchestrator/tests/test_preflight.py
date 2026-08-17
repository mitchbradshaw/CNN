"""Startup refusals — the cheap place to discover a broken run.

A stale ticket branch is the dangerous one, because it does not look like an
error. `Git.worktree_add` reuses a branch that already exists rather than
cutting a new one, so a fresh run over a backlog whose previous attempt left
`ticket/T02` behind provisions that worktree onto **last night's commits**, cut
from **last night's base**. The agent then finds its own half-finished work
already present, and the red-proof gate reads the previous attempt's test commit
as this run's first commit.

Nothing about that surfaces as a failure. It surfaces as a strange transcript at
3am.
"""

import pytest

from orchestrator.backlog import load_backlog
from orchestrator.runloop import stale_ticket_branches


@pytest.fixture
def backlog(write_ticket, ticket_dir):
    write_ticket(1, flags=["done"])
    write_ticket(2)
    write_ticket(3, flags=["human-gate"])
    write_ticket(4)
    return load_backlog(ticket_dir)


def test_a_leftover_branch_for_a_dispatchable_ticket_is_stale(backlog):
    existing = {"main", "ticket/T02", "integration/run-20260817-1157"}

    assert stale_ticket_branches(backlog, existing, prefix="ticket/") == ("ticket/T02",)


def test_a_clean_repo_has_nothing_stale(backlog):
    assert stale_ticket_branches(backlog, {"main"}, prefix="ticket/") == ()


def test_a_done_tickets_branch_is_not_stale(backlog):
    """T01 is `done`, so it is never provisioned and its branch is never reused.

    It is also the branch most likely to still be lying around — it is the one
    that merged. Refusing to start over it would be a refusal the user cannot
    act on without deleting the evidence of the work they just landed.
    """
    assert stale_ticket_branches(backlog, {"ticket/T01"}, prefix="ticket/") == ()


def test_a_human_gated_tickets_branch_is_not_stale(backlog):
    assert stale_ticket_branches(backlog, {"ticket/T03"}, prefix="ticket/") == ()


def test_every_stale_branch_is_reported_not_just_the_first(backlog):
    """The refusal is only actionable if it names all of them at once."""
    existing = {"ticket/T02", "ticket/T04"}

    assert stale_ticket_branches(backlog, existing, prefix="ticket/") == (
        "ticket/T02", "ticket/T04",
    )


def test_the_prefix_is_honoured(backlog):
    existing = {"wip/T02"}

    assert stale_ticket_branches(backlog, existing, prefix="wip/") == ("wip/T02",)
    assert stale_ticket_branches(backlog, existing, prefix="ticket/") == ()
