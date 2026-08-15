"""The scheduler is a pure function. No git, no subprocess, no clock."""

import pytest

from orchestrator.backlog import load_backlog
from orchestrator.scheduler import Ceilings, schedule
from orchestrator.status import (
    BLOCKED_UPSTREAM, FAILED, GATING, HELD, MERGED, MERGING, PENDING, RUNNING,
)


@pytest.fixture
def ceilings():
    return Ceilings(concurrent=3, opus=2)


def all_pending(backlog, overrides=None):
    states = {t.id: PENDING for t in backlog}
    states.update(overrides or {})
    return states


def test_dispatches_only_tickets_whose_blockers_have_landed(write_ticket, ticket_dir, ceilings):
    write_ticket(1)
    write_ticket(2, blocked_by=[1])
    backlog = load_backlog(ticket_dir)

    assert schedule(backlog, all_pending(backlog), ceilings).dispatch == (1,)
    assert schedule(backlog, all_pending(backlog, {1: MERGED}), ceilings).dispatch == (2,)


def test_a_blocker_merely_running_does_not_unblock(write_ticket, ticket_dir, ceilings):
    write_ticket(1)
    write_ticket(2, blocked_by=[1])
    backlog = load_backlog(ticket_dir)

    for status in (RUNNING, GATING, MERGING):
        assert schedule(backlog, all_pending(backlog, {1: status}), ceilings).dispatch == ()


def test_human_gated_tickets_are_never_dispatched(write_ticket, ticket_dir, ceilings):
    write_ticket(1, flags=["human-gate"])
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog), ceilings)

    assert decision.dispatch == ()
    assert decision.holds[1].reason == "human-gate"


def test_mutex_partners_are_never_co_dispatched(write_ticket, ticket_dir, ceilings):
    write_ticket(1, mutex=[2])
    write_ticket(2)
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog), ceilings)

    assert decision.dispatch == (1,)
    assert decision.holds[2].reason == "mutex"
    assert "T01" in decision.holds[2].detail


def test_mutex_holds_against_an_in_flight_partner(write_ticket, ticket_dir, ceilings):
    write_ticket(1, mutex=[2])
    write_ticket(2)
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog, {1: RUNNING}), ceilings)

    assert decision.dispatch == ()
    assert decision.holds[2].reason == "mutex"


def test_mutex_is_simultaneity_only_not_ordering(write_ticket, ticket_dir, ceilings):
    write_ticket(1, mutex=[2])
    write_ticket(2)
    backlog = load_backlog(ticket_dir)

    # Once 1 has landed, its mutex partner is free — the pair was never ordered.
    decision = schedule(backlog, all_pending(backlog, {1: MERGED}), ceilings)

    assert decision.dispatch == (2,)


def test_a_solo_ticket_runs_alone(write_ticket, ticket_dir, ceilings):
    write_ticket(1, flags=["solo"])
    write_ticket(2)
    write_ticket(3)
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog), ceilings)

    assert decision.dispatch == (1,)
    assert decision.holds[2].reason == "solo"


def test_a_solo_ticket_waits_for_the_field_to_clear(write_ticket, ticket_dir, ceilings):
    write_ticket(1, flags=["solo"])
    write_ticket(2)
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog, {2: RUNNING}), ceilings)

    assert decision.dispatch == ()
    assert decision.holds[1].reason == "solo"


def test_global_ceiling_caps_dispatch(write_ticket, ticket_dir):
    for i in range(1, 6):
        write_ticket(i)
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog), Ceilings(concurrent=3, opus=2))

    assert len(decision.dispatch) == 3
    assert decision.holds[4].reason == "ceiling"


def test_ceiling_counts_tickets_already_in_flight(write_ticket, ticket_dir):
    for i in range(1, 6):
        write_ticket(i)
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog, {1: RUNNING, 2: GATING}),
                        Ceilings(concurrent=3, opus=2))

    assert len(decision.dispatch) == 1


def test_opus_sub_ceiling_caps_opus_but_lets_sonnet_through(write_ticket, ticket_dir):
    write_ticket(1, model="opus")
    write_ticket(2, model="opus")
    write_ticket(3, model="opus")
    write_ticket(4, model="sonnet")
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog), Ceilings(concurrent=3, opus=2))

    assert decision.dispatch == (1, 2, 4)
    assert decision.holds[3].reason == "opus-ceiling"


def test_orders_by_most_unblocking_then_critical_path_then_id(write_ticket, ticket_dir):
    # 3 unblocks two tickets; 1 and 2 unblock none. 1 wins the tie on id.
    write_ticket(1)
    write_ticket(2)
    write_ticket(3)
    write_ticket(4, blocked_by=[3])
    write_ticket(5, blocked_by=[4])
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog), Ceilings(concurrent=2, opus=2))

    assert decision.dispatch == (3, 1)


def test_critical_path_breaks_a_tie_on_dependent_count(write_ticket, ticket_dir):
    """Equal fan-out, unequal depth — and the deeper one has the *higher* id,
    so passing this cannot be the id tie-break doing the work."""
    write_ticket(1)                 # 1 fans out to 2 and 3: dependents 2, path 2
    write_ticket(2, blocked_by=[1])
    write_ticket(3, blocked_by=[1])
    write_ticket(4)                 # 4 chains 5 then 6: dependents 2, path 3
    write_ticket(5, blocked_by=[4])
    write_ticket(6, blocked_by=[5])
    backlog = load_backlog(ticket_dir)

    assert len(backlog.dependents(1)) == len(backlog.dependents(4)) == 2
    assert backlog.critical_path(4) > backlog.critical_path(1)

    decision = schedule(backlog, all_pending(backlog), Ceilings(concurrent=1, opus=2))

    assert decision.dispatch == (4,)


def test_a_quarantined_blocker_never_releases_its_dependents(write_ticket, ticket_dir, ceilings):
    write_ticket(1)
    write_ticket(2, blocked_by=[1])
    backlog = load_backlog(ticket_dir)

    for status in (FAILED, BLOCKED_UPSTREAM, HELD):
        decision = schedule(backlog, all_pending(backlog, {1: status}), ceilings)
        assert decision.dispatch == ()
        assert decision.holds[2].reason == "blocked"


def test_already_terminal_tickets_are_not_redispatched(write_ticket, ticket_dir, ceilings):
    write_ticket(1)
    write_ticket(2)
    backlog = load_backlog(ticket_dir)

    states = all_pending(backlog, {1: MERGED, 2: FAILED})

    assert schedule(backlog, states, ceilings).dispatch == ()
