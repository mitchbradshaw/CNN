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


def test_a_done_ticket_is_never_dispatched(write_ticket, ticket_dir, ceilings):
    """`done` means the work is already in the base from an earlier run."""
    write_ticket(1, flags=["done"])
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog), ceilings)

    assert decision.dispatch == ()


def test_a_done_ticket_releases_its_dependents(write_ticket, ticket_dir, ceilings):
    """The half that separates `done` from `human-gate`.

    A human gate *holds* everything downstream, because the work has not
    happened. `done` is the opposite claim — it has happened and landed — so the
    dependents must run. Getting this wrong strands the whole subtree.
    """
    write_ticket(1, flags=["done"])
    write_ticket(2, blocked_by=[1])
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog), ceilings)

    assert decision.dispatch == (2,)
    assert 2 not in decision.holds


def test_a_done_ticket_is_not_reported_as_holding_anything(write_ticket, ticket_dir, ceilings):
    """It is not waiting on anything, so it must not appear in the hold list."""
    write_ticket(1, flags=["done"])
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog), ceilings)

    assert 1 not in decision.holds


def test_done_beats_a_stale_pending_state(write_ticket, ticket_dir, ceilings):
    """A fresh run seeds every ticket PENDING; `done` has to win over that.

    Otherwise the flag would only work on a resumed run, which is the one case
    that never needed it.
    """
    write_ticket(1, flags=["done"])
    write_ticket(2, blocked_by=[1])
    backlog = load_backlog(ticket_dir)

    assert schedule(backlog, {1: PENDING, 2: PENDING}, ceilings).dispatch == (2,)


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
    # Top candidate and solo, so the field is draining for it — which is the
    # stronger form of "waits for the field to clear".
    assert decision.holds[1].reason == "draining"
    assert "T02" in decision.holds[1].detail


def test_the_field_drains_once_a_solo_ticket_is_the_top_candidate(write_ticket, ticket_dir,
                                                                  ceilings):
    """Without this, a solo ticket only starts on a tick where the field
    happens to be empty *and* it happens to sort first. With continuous work
    and a ceiling of 3, that is luck, and T17 gates 26 tickets."""
    write_ticket(1, flags=["solo"], blocked_by=[9])   # top candidate once 9 lands
    write_ticket(2)
    write_ticket(3)
    write_ticket(9)
    for i in (4, 5, 6, 7, 8):                          # give 1 the most dependents
        write_ticket(i, blocked_by=[1])
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog, {9: MERGED, 2: RUNNING}), ceilings)

    assert decision.dispatch == (), "nothing new starts while the solo ticket waits"
    assert decision.holds[1].reason == "draining"
    assert decision.holds[3].reason == "draining"


def test_draining_ends_the_moment_the_field_is_empty(write_ticket, ticket_dir, ceilings):
    write_ticket(1, flags=["solo"], blocked_by=[9])
    write_ticket(2)
    write_ticket(9)
    for i in (4, 5, 6, 7, 8):
        write_ticket(i, blocked_by=[1])
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog, {9: MERGED}), ceilings)

    assert decision.dispatch == (1,)


def test_a_low_priority_solo_ticket_does_not_drain_the_field(write_ticket, ticket_dir,
                                                             ceilings):
    """Draining costs the whole field's throughput. Only the top candidate
    earns it — a solo ticket nothing depends on just waits its turn."""
    write_ticket(1)
    write_ticket(2, blocked_by=[1])
    write_ticket(3, blocked_by=[1])
    write_ticket(9, flags=["solo"])          # no dependents, sorts last
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog), ceilings)

    assert decision.dispatch == (1,)
    assert decision.holds[9].reason == "solo"


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


# ---------------------------------------- the opus sub-ceiling, under a cap
#
# `models.model_cap = "sonnet"` maps every opus ticket onto sonnet before it is
# ever launched, so no opus tokens are spent. The sub-ceiling that exists to
# bound opus spend was still counting the ticket's *declared* tier, so nineteen
# tickets that were all going to run as sonnet queued behind an opus limit
# nobody was paying for — pure serialisation, no saving.


def test_the_opus_ceiling_counts_the_tier_a_ticket_will_actually_run_on(
        write_ticket, ticket_dir):
    for i in (1, 2, 3):
        write_ticket(i, model="opus")
    backlog = load_backlog(ticket_dir)

    capped = Ceilings(concurrent=3, opus=1, capped_tier="sonnet")
    decision = schedule(backlog, all_pending(backlog), capped)

    assert len(decision.dispatch) == 3, (
        "under a sonnet cap these are sonnet tickets; the opus ceiling must not "
        "throttle spend that is not happening"
    )


def test_the_opus_ceiling_still_binds_when_no_cap_is_set(write_ticket, ticket_dir):
    """The mirror: remove the cap and the limit must do its job again."""
    for i in (1, 2, 3):
        write_ticket(i, model="opus")
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog), Ceilings(concurrent=3, opus=1))

    assert len(decision.dispatch) == 1
    assert any(h.reason == "opus-ceiling" for h in decision.holds.values())


def test_a_haiku_cap_frees_the_opus_ceiling_too(write_ticket, ticket_dir):
    for i in (1, 2, 3):
        write_ticket(i, model="opus")
    backlog = load_backlog(ticket_dir)

    decision = schedule(backlog, all_pending(backlog),
                        Ceilings(concurrent=3, opus=1, capped_tier="haiku"))

    assert len(decision.dispatch) == 3
