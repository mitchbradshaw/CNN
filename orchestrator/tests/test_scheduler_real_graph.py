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
    states = {t.id: (HELD if t.human_gate else PENDING) for t in backlog}
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
    # Everything except the two human gates and the 21 held downstream of T04.
    held_downstream = real.dependents(4) | {49}
    assert set(landed) == set(real.ids) - HUMAN_GATE - held_downstream


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
    landed: set[int] = set()
    for wave in drain(real, Ceilings(3, 2)):
        for ticket_id in wave:
            missing = set(real[ticket_id].blocked_by) - landed
            assert not missing, f"T{ticket_id:02d} dispatched before {missing} landed"
        landed |= set(wave)


def test_the_run_opens_on_the_backlogs_own_reading_order(real):
    """The spec claims most-unblocking-first opens 01, 02, 03 then 05, 35, 16.

    That ordering was arrived at by hand in the backlog's reading section; the
    scheduler reaching it mechanically is the check that the rule is the one
    the backlog was actually written against.
    """
    waves = list(drain(real, Ceilings(3, 2)))

    assert waves[0] == (1, 2, 3)
    assert set(waves[1]) == {5, 35, 16}


def test_solo_waits_rather_than_starving(real):
    """17 has no blockers, so it must appear in some wave, alone."""
    waves = list(drain(real, Ceilings(3, 2)))
    solo_waves = [w for w in waves if 17 in w]

    assert solo_waves == [(17,)]


def test_an_in_flight_ticket_still_constrains_the_next_decision(real):
    """A one-shot check that in-flight state, not just same-tick state, binds."""
    states = {t.id: (HELD if t.human_gate else PENDING) for t in real}
    states[17] = RUNNING

    decision = schedule(real, states, Ceilings(3, 2))

    assert decision.dispatch == ()
    assert all(h.reason == "solo" for i, h in decision.holds.items()
               if i not in HUMAN_GATE and not real[i].blocked_by)
