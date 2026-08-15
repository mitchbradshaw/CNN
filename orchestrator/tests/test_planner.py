"""`--plan`: simulate the run without dispatching anything."""

from pathlib import Path

import pytest

from orchestrator.backlog import load_backlog
from orchestrator.config import load_config
from orchestrator.planner import render_plan, simulate
from orchestrator.scheduler import Ceilings

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED = REPO_ROOT / "orchestrator" / "config.toml"


@pytest.fixture(scope="module")
def config():
    return load_config(SHIPPED, repo_root=REPO_ROOT)


@pytest.fixture(scope="module")
def real(config):
    return load_backlog(config.paths.tickets)


def test_waves_advance_by_the_duration_of_the_tickets_in_them(write_ticket, ticket_dir, config):
    write_ticket(1, size="M", budget_minutes=60)
    write_ticket(2, size="S", budget_minutes=30, blocked_by=[1])
    backlog = load_backlog(ticket_dir)

    plan = simulate(backlog, config, ceilings=Ceilings(3, 2))

    assert [w.at_minutes for w in plan.waves] == [0, 60]
    assert plan.drain_minutes == 90


def test_a_short_ticket_frees_its_slot_early(write_ticket, ticket_dir, config):
    """Simulation is event-driven, not lock-step: a 30m ticket releases its
    slot at t+30, not at the end of the longest ticket in its wave."""
    write_ticket(1, size="S", budget_minutes=30)
    write_ticket(2, size="L", budget_minutes=120)
    write_ticket(3, size="S", budget_minutes=30)
    backlog = load_backlog(ticket_dir)

    plan = simulate(backlog, config, ceilings=Ceilings(2, 2))

    starts = {t.id: t.start_minutes for w in plan.waves for t in w.tickets}
    assert starts == {1: 0, 2: 0, 3: 30}


def test_human_gated_tickets_are_reported_as_not_dispatched(write_ticket, ticket_dir, config):
    write_ticket(1, flags=["human-gate"])
    write_ticket(2, blocked_by=[1])
    backlog = load_backlog(ticket_dir)

    plan = simulate(backlog, config, ceilings=Ceilings(3, 2))

    assert plan.waves == ()
    assert plan.not_dispatched[1].reason == "human-gate"
    assert plan.not_dispatched[2].reason == "blocked-downstream"
    assert "T01" in plan.not_dispatched[2].detail


def test_a_wave_records_what_each_ticket_was_blocked_on(write_ticket, ticket_dir, config):
    write_ticket(1)
    write_ticket(2, blocked_by=[1])
    backlog = load_backlog(ticket_dir)

    plan = simulate(backlog, config, ceilings=Ceilings(3, 2))

    second = plan.waves[1].tickets[0]
    assert second.id == 2
    assert second.was_blocked_by == (1,)


def test_a_wave_records_which_mutex_held_a_ready_ticket_back(write_ticket, ticket_dir, config):
    write_ticket(1, mutex=[2])
    write_ticket(2)
    backlog = load_backlog(ticket_dir)

    plan = simulate(backlog, config, ceilings=Ceilings(3, 2))

    holds = dict(plan.waves[0].holds)
    assert holds[2].reason == "mutex"
    assert "T01" in holds[2].detail


def test_holds_report_only_tickets_that_were_ready_and_held_back(write_ticket, ticket_dir, config):
    """A ticket waiting on its blockers is not "held" — it is simply not ready.

    Reporting those swamps the line the spec cares about: which ceiling, mutex
    or solo flag kept a ticket that could otherwise have started.
    """
    write_ticket(1)
    write_ticket(2)
    write_ticket(3)
    write_ticket(4)                    # ready, will lose to the ceiling
    write_ticket(5, blocked_by=[1])    # not ready at all
    backlog = load_backlog(ticket_dir)

    plan = simulate(backlog, config, ceilings=Ceilings(3, 2))

    held = dict(plan.waves[0].holds)
    assert set(held) == {4}
    assert held[4].reason == "ceiling"


def test_the_wall_clock_stop_prevents_later_dispatch(write_ticket, ticket_dir, config):
    write_ticket(1, size="M", budget_minutes=60)
    write_ticket(2, size="M", budget_minutes=60, blocked_by=[1])
    backlog = load_backlog(ticket_dir)

    plan = simulate(backlog, config, ceilings=Ceilings(3, 2), stop_after_minutes=30)

    assert [t.id for w in plan.waves for t in w.tickets] == [1]
    assert plan.not_dispatched[2].reason == "wall-clock-stop"


# ---------------------------------------------------------------- real backlog


def test_the_real_backlog_drains_27_autonomous_tickets(real, config):
    plan = simulate(real, config, ceilings=config.ceilings)

    dispatched = [t.id for w in plan.waves for t in w.tickets]
    assert len(dispatched) == 27, "the spec's night-one figure is 27 of 49"
    assert len(plan.not_dispatched) == 22


def test_the_real_backlog_stalls_against_ticket_04(real, config):
    plan = simulate(real, config, ceilings=config.ceilings)

    assert plan.not_dispatched[4].reason == "human-gate"
    downstream = [i for i, n in plan.not_dispatched.items()
                  if n.reason == "blocked-downstream" and 4 in n.roots]
    assert len(downstream) == 20


def test_projected_drain_is_about_ten_hours(real, config):
    plan = simulate(real, config, ceilings=config.ceilings)

    assert 8 * 60 <= plan.drain_minutes <= 12 * 60, plan.drain_minutes


def test_the_rendered_plan_carries_what_the_spec_illustrates(real, config):
    plan = simulate(real, config, ceilings=config.ceilings)

    text = render_plan(plan)

    assert text.startswith("RUN PLAN")
    assert "ceiling 3, opus 2" in text
    assert "wave 1" in text and "t+0h00" in text
    assert "T01 sonnet M  60m" in text
    assert "(was blocked by T01)" in text
    assert "[SOLO — runs alone]" in text
    assert "held:" in text
    assert "projected drain" in text
    assert "27 tickets autonomous · 22 held" in text
    assert "NOT DISPATCHED" in text
    assert "T04  human-gate" in text
    assert "T49  human-gate" in text
    assert "20 further tickets held downstream of T04" in text


def test_the_plan_never_violates_a_scheduler_invariant(real, config):
    """The preview and the runner share one scheduler, so the preview is
    evidence about the run rather than a second implementation of it."""
    from .test_real_backlog import HUMAN_GATE, LIVE_MUTEX_PAIRS

    plan = simulate(real, config, ceilings=config.ceilings)

    for wave in plan.waves:
        ids = {t.id for t in wave.tickets}
        assert not ids & HUMAN_GATE
        for a, b in LIVE_MUTEX_PAIRS:
            assert not {a, b} <= ids
        if 17 in ids:
            assert ids == {17}
