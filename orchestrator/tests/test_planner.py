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


def test_a_done_ticket_is_absent_from_the_plan_entirely(write_ticket, ticket_dir, config):
    """Not dispatched, and not reported as unscheduled either.

    Reporting it under `wall-clock-stop` would read as "T01 never got a slot" —
    the opposite of the truth, and exactly the line a tired reader acts on at 7am.
    """
    write_ticket(1, flags=["done"])
    write_ticket(2, blocked_by=[1])
    backlog = load_backlog(ticket_dir)

    plan = simulate(backlog, config, ceilings=Ceilings(3, 2))

    assert 1 not in plan.not_dispatched
    assert [t.id for w in plan.waves for t in w.tickets] == [2]


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


def test_a_drain_wave_is_visible_rather_than_looking_stalled(write_ticket, ticket_dir,
                                                             config):
    """The plan must show *why* a stretch of the night starts nothing, or a
    drain reads as the runner having hung."""
    write_ticket(1, size="S", budget_minutes=30)
    write_ticket(2, size="L", budget_minutes=120)
    write_ticket(9, flags=["solo"], size="M", budget_minutes=60, blocked_by=[1])
    for i in (3, 4, 5, 6):
        write_ticket(i, blocked_by=[9])
    backlog = load_backlog(ticket_dir)

    plan = simulate(backlog, config, ceilings=Ceilings(3, 2))

    text = render_plan(plan)
    assert "draining" in text
    starts = {t.id: t.start_minutes for w in plan.waves for t in w.tickets}
    # T09 waits for the 120-minute ticket to clear, and nothing starts meanwhile.
    assert starts[9] == 120
    assert not any(0 < s < 120 for i, s in starts.items() if i != 9)


def test_the_wall_clock_stop_prevents_later_dispatch(write_ticket, ticket_dir, config):
    write_ticket(1, size="M", budget_minutes=60)
    write_ticket(2, size="M", budget_minutes=60, blocked_by=[1])
    backlog = load_backlog(ticket_dir)

    plan = simulate(backlog, config, ceilings=Ceilings(3, 2), stop_after_minutes=30)

    assert [t.id for w in plan.waves for t in w.tickets] == [1]
    assert plan.not_dispatched[2].reason == "wall-clock-stop"


# ---------------------------------------------------------------- real backlog


def test_every_live_ticket_is_either_dispatched_or_explained(real, config):
    """Was pinned to 27-of-49. That number is a property of a backlog snapshot,
    not of the planner: it moved to 26 the moment T01 was flagged `done`, and it
    will move again after every night. What must always hold is that the plan
    accounts for every ticket still to be built, and drops the ones already
    built — a ticket silently in neither bucket is the real failure.
    """
    plan = simulate(real, config, ceilings=config.ceilings)

    dispatched = {t.id for w in plan.waves for t in w.tickets}
    live = {t.id for t in real if not t.done}

    assert dispatched | set(plan.not_dispatched) == live
    assert not (dispatched & set(plan.not_dispatched)), "a ticket cannot be both"
    assert not any(real[i].done for i in dispatched), "done tickets are not re-dispatched"
    assert dispatched, "a backlog with live tickets must dispatch something"
    # Deliberately no assertion on the ratio of dispatched to held. That is a
    # fact about ticket 04's bottleneck and about how many tickets have landed
    # so far, not about the planner, and it inverted the moment the fifth ticket
    # was flagged `done`.


def test_a_human_gate_holds_itself_and_everything_downstream_of_it(real, config):
    """Was `test_the_real_backlog_stalls_against_ticket_04`, pinned to T04
    holding exactly 20 tickets. T04 was worked by hand and flagged `done` on
    2026-08-19, which released all twenty and left the assertion asserting
    nothing — it failed with a KeyError rather than a diagnosis.

    The property is about the planner, not about which ticket happens to be the
    bottleneck this week: every remaining human gate must appear as one, and
    anything genuinely downstream of one must be explained rather than silently
    dropped."""
    plan = simulate(real, config, ceilings=config.ceilings)

    gates = [t.id for t in real if t.human_gate and not t.done]
    assert gates, "the backlog has no human gates left — delete this test"
    for gate in gates:
        assert plan.not_dispatched[gate].reason == "human-gate"

    downstream = [i for i, n in plan.not_dispatched.items()
                  if n.reason == "blocked-downstream"]
    for ticket_id in downstream:
        roots = set(plan.not_dispatched[ticket_id].roots)
        assert roots, f"T{ticket_id:02d} held downstream of nothing"


def test_the_projected_drain_fits_inside_one_night(real, config):
    """The assertion that matters is not a number of hours, it is whether the
    plan fits the dispatch window it will actually be run in.

    Pinning "about six hours" made this test a tripwire for every deliberate
    change: it broke when T04 landed and released twenty tickets, and again when
    `ceilings.concurrent` dropped from 3 to 2. Both were intended, and neither
    was what the test was for.

    A run started after `wall_clock_stop` gets the next day's stop and roughly a
    twenty-hour window. If the drain no longer fits, that is a real signal —
    raise the ceiling, or accept that the backlog now needs two nights and a
    `--resume`."""
    plan = simulate(real, config, ceilings=config.ceilings)

    assert plan.drain_minutes > 0
    assert plan.drain_minutes <= 20 * 60, (
        f"projected drain {plan.drain_minutes / 60:.1f}h exceeds a night; the "
        f"backlog now needs two passes at ceiling {config.ceilings.concurrent}"
    )


def test_the_rendered_plan_carries_what_the_spec_illustrates(real, config):
    plan = simulate(real, config, ceilings=config.ceilings)

    text = render_plan(plan)

    first = plan.waves[0].tickets[0]
    dispatched = sum(len(w.tickets) for w in plan.waves)

    assert text.startswith("RUN PLAN")
    # Derived from the config, not pinned: the ceilings are tuning knobs and a
    # test that hardcodes them fails on every deliberate adjustment.
    assert (f"ceiling {config.ceilings.concurrent}, opus {config.ceilings.opus}"
            in text)
    assert "wave 1" in text and "t+0h00" in text
    # Derived, not hardcoded: which ticket leads wave 1 changes as tickets land.
    assert f"T{first.id:02d} {first.model}" in text
    # Derived: pinning T01 here broke once every ticket T01 unblocked had itself
    # landed, leaving nothing in the plan that still named it. What the renderer
    # must do is annotate whichever dispatched ticket did have blockers.
    with_blockers = [t for w in plan.waves for t in w.tickets if t.was_blocked_by]
    if with_blockers:
        example = with_blockers[0]
        assert f"(was blocked by T{example.was_blocked_by[0]:02d}" in text
    # Derived, same reason: T17 was the only `solo` ticket in the backlog and
    # is `done` as of T17 landing, so no dispatched ticket is solo any more.
    solo_dispatched = [t for w in plan.waves for t in w.tickets if t.solo]
    if solo_dispatched:
        assert "[SOLO — runs alone]" in text
    assert "held:" in text
    assert "projected drain" in text
    assert f"{dispatched} tickets autonomous · {len(plan.not_dispatched)} held" in text
    assert "NOT DISPATCHED" in text
    # Derived: T04 was hand-worked and flagged `done`, so it no longer appears
    # here at all. Whatever gates remain must be named.
    for gate in (t for t in real if t.human_gate and not t.done):
        assert f"T{gate.id:02d}  human-gate" in text


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
