"""The scheduler, driven to exhaustion over the real 49-ticket graph.

Every invariant the spec names is asserted at *every* tick of a full drain, not
just at the first one. These are the assertions that would have caught a mutex
pair slipping through on wave nine, when no one is watching.
"""

from pathlib import Path

import pytest

from orchestrator.backlog import load_backlog
from orchestrator.scheduler import Ceilings, schedule
from orchestrator.status import HELD, MERGED, PENDING, RUNNING

from .test_real_backlog import HUMAN_GATE, LIVE_MUTEX_PAIRS

REPO_ROOT = Path(__file__).resolve().parents[2]
TICKETS = REPO_ROOT / "docs" / "tickets"


@pytest.fixture(scope="module")
def real():
    return load_backlog(TICKETS)


def drain(backlog, ceilings, *, max_ticks=500):
    """Run the scheduler to a fixed point, one wave per tick.

    Each tick dispatches, then lands everything dispatched — the optimistic
    case, which is the one that stresses concurrency hardest. Yields the set
    dispatched on each tick together with the set that was in flight with it.
    """
    states = {
        t.id: MERGED if t.done else (HELD if t.human_gate else PENDING)
        for t in backlog
    }
    for _ in range(max_ticks):
        decision = schedule(backlog, states, ceilings)
        if not decision.dispatch:
            return
        yield decision.dispatch
        for ticket_id in decision.dispatch:
            states[ticket_id] = MERGED
    raise AssertionError("scheduler did not reach a fixed point")


def test_a_full_drain_lands_every_autonomous_ticket(real):
    landed = [i for wave in drain(real, Ceilings(3, 2)) for i in wave]

    assert len(landed) == len(set(landed)), "a ticket was dispatched twice"
    # Everything except the two human gates, the 21 held downstream of T04, and
    # anything already flagged `done` — that work is in the base, not the night.
    held_downstream = real.dependents(4) | {49}
    already_done = {t.id for t in real if t.done}
    assert set(landed) == set(real.ids) - HUMAN_GATE - held_downstream - already_done


def test_human_gated_tickets_are_never_dispatched_at_any_tick(real):
    for wave in drain(real, Ceilings(3, 2)):
        assert not (set(wave) & HUMAN_GATE), f"human-gate dispatched in {wave}"


@pytest.mark.parametrize("ceilings", [Ceilings(3, 2), Ceilings(1, 1), Ceilings(8, 4)])
def test_no_live_mutex_pair_is_ever_co_scheduled(real, ceilings):
    for wave in drain(real, ceilings):
        for a, b in LIVE_MUTEX_PAIRS:
            assert not {a, b} <= set(wave), f"mutex pair {a}<->{b} co-scheduled in {wave}"


@pytest.mark.parametrize("ceilings", [Ceilings(3, 2), Ceilings(1, 1), Ceilings(8, 4)])
def test_no_declared_mutex_pair_at_all_is_ever_co_scheduled(real, ceilings):
    """Stronger than the README's 18: *every* declared pair, live or redundant."""
    for wave in drain(real, ceilings):
        for ticket_id in wave:
            clash = real.mutex_partners(ticket_id) & set(wave)
            assert not clash, f"T{ticket_id:02d} co-scheduled with its mutex {clash}"


def test_ticket_17_always_runs_alone(real):
    for wave in drain(real, Ceilings(3, 2)):
        if 17 in wave:
            assert wave == (17,), f"solo ticket 17 dispatched alongside {wave}"


def test_ceilings_are_never_exceeded(real):
    ceilings = Ceilings(3, 2)
    for wave in drain(real, ceilings):
        assert len(wave) <= ceilings.concurrent
        assert sum(1 for i in wave if real[i].model == "opus") <= ceilings.opus


def test_blockers_always_land_before_their_dependents(real):
    # `done` tickets start landed — that is the claim the flag makes, and the
    # dependents it releases would otherwise all look dispatched-too-early.
    landed: set[int] = {t.id for t in real if t.done}
    for wave in drain(real, Ceilings(3, 2)):
        for ticket_id in wave:
            missing = set(real[ticket_id].blocked_by) - landed
            assert not missing, f"T{ticket_id:02d} dispatched before {missing} landed"
        landed |= set(wave)


def test_the_run_opens_on_the_most_unblocking_tickets_available(real):
    """The spec claims most-unblocking-first opens 01, 02, 03 then 05, 35, 16.

    That ordering was arrived at by hand in the backlog's reading section, and
    the scheduler reaching it mechanically was the check that the rule is the
    one the backlog was written against. It is asserted as a property rather
    than as that literal tuple because the literal decays: T01 is now `done`, so
    the run opens on 02, 05, 35, and it will shift again after every night. The
    rule is what has to hold — nothing left waiting may unblock more than
    something that went first.
    """
    states = {
        t.id: MERGED if t.done else (HELD if t.human_gate else PENDING)
        for t in real
    }
    decision = schedule(real, states, Ceilings(3, 2))

    fanout = real.dependents
    weakest_dispatched = min(len(fanout(i)) for i in decision.dispatch)

    # Only the tickets held for *lack of a slot* test the priority rule. `solo`
    # and `mutex` hold tickets for reasons that have nothing to do with fan-out
    # — T17 unblocks 26 and still waits, because it runs alone.
    starved = [i for i, h in decision.holds.items() if h.reason == "ceiling"]
    if not starved:
        # The other legitimate shape for tick one: the top candidate is `solo`,
        # so the field drains for it and nothing is competing for a slot at all.
        # T17 became the opening ticket once T02, T05, T13 and T35 had landed.
        assert decision.dispatch and real[decision.dispatch[0]].solo, (
            "nothing held for a slot, and no solo ticket to explain why"
        )
        return
    for ticket_id in starved:
        assert len(fanout(ticket_id)) <= weakest_dispatched, (
            f"T{ticket_id:02d} unblocks {len(fanout(ticket_id))} but lost its slot to a "
            f"ticket unblocking {weakest_dispatched}"
        )


def test_solo_waits_rather_than_starving(real):
    """Whatever solo ticket is currently live must appear in some wave,
    alone. T17 was the concrete example here until it landed and dropped
    out of scheduling as `done` — vacuously true with no live solo ticket,
    since the mechanism itself has synthetic coverage in test_scheduler.py
    regardless of which ticket happens to carry the flag."""
    solo_ids = [t.id for t in real if t.solo and not t.done]
    waves = list(drain(real, Ceilings(3, 2)))
    for solo_id in solo_ids:
        assert [w for w in waves if solo_id in w] == [(solo_id,)]


def test_an_in_flight_ticket_still_constrains_the_next_decision(real):
    """A one-shot check that in-flight state, not just same-tick state, binds
    — for whichever solo ticket is currently live. T17 was the concrete
    example until it landed and dropped out of scheduling as `done`."""
    solo_ids = [t.id for t in real if t.solo and not t.done]
    if not solo_ids:
        return
    solo_id = solo_ids[0]
    states = {t.id: (HELD if t.human_gate else PENDING) for t in real}
    states[solo_id] = RUNNING

    decision = schedule(real, states, Ceilings(3, 2))

    assert decision.dispatch == ()
    assert all(h.reason == "solo" for i, h in decision.holds.items()
               if i not in HUMAN_GATE and not real[i].blocked_by)
