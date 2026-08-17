"""`--plan` — the run schedule, printed without dispatching anything.

It exists so the plan is inspectable before you go to bed rather than
reconstructable afterwards. The simulation drives the *same* `schedule()` the
runner uses, so the preview is evidence about the run rather than a second
implementation of it; only the durations are invented, and they come from the
ticket's own size flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import status as st
from .backlog import Backlog
from .config import Config
from .scheduler import Ceilings, Hold, schedule

#: Reasons worth printing on a wave's `held:` line. A ticket waiting on its
#: blockers is not held back — it is simply not ready, and listing all of them
#: would bury the ceiling and mutex decisions this line exists to show.
HELD_BACK = ("ceiling", "opus-ceiling", "mutex", "solo", "draining")


@dataclass(frozen=True)
class PlannedTicket:
    id: int
    model: str
    size: str
    budget_minutes: int
    title: str
    start_minutes: int
    was_blocked_by: tuple[int, ...]
    solo: bool

    @property
    def label(self) -> str:
        return f"T{self.id:02d}"


@dataclass(frozen=True)
class Wave:
    index: int
    at_minutes: int
    tickets: tuple[PlannedTicket, ...]
    holds: tuple[tuple[int, Hold], ...]


@dataclass(frozen=True)
class NotDispatched:
    reason: str            # human-gate | blocked-downstream | wall-clock-stop
    detail: str = ""
    roots: tuple[int, ...] = ()   # the human-gated tickets responsible


@dataclass
class Plan:
    branch: str
    ceilings: Ceilings
    stop_label: str
    waves: tuple[Wave, ...] = ()
    not_dispatched: dict[int, NotDispatched] = field(default_factory=dict)
    drain_minutes: int = 0


def _format_clock(minutes: int) -> str:
    return f"t+{minutes // 60}h{minutes % 60:02d}"


def _blocked_roots(backlog: Backlog, ticket_id: int, gated: set[int]) -> tuple[int, ...]:
    """Which human-gated tickets ultimately hold this one, transitively."""
    roots, seen, stack = set(), set(), list(backlog[ticket_id].blocked_by)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        if current in gated:
            roots.add(current)
        stack.extend(backlog[current].blocked_by)
    return tuple(sorted(roots))


def simulate(backlog: Backlog, config: Config, *, ceilings: Ceilings | None = None,
             stop_after_minutes: int | None = None, branch: str = "") -> Plan:
    """Event-driven simulation over size-based durations.

    A ticket occupies its slot for its budget and then lands. Slots free as
    each ticket finishes, not at the end of the wave — lock-step waves would
    understate throughput and misrepresent when the ceiling actually binds.
    """
    ceilings = ceilings or config.ceilings
    gated = {t.id for t in backlog if t.human_gate}

    # `done` is seeded MERGED for the same reason the scheduler overlays it:
    # the ticket has landed. Left PENDING it would never dispatch (the scheduler
    # sees to that) and then fall out of the loop below as "no slot before the
    # stop" — reporting merged work as work that never got a slot.
    states = {
        t.id: st.MERGED if t.done else (st.HELD if t.human_gate else st.PENDING)
        for t in backlog
    }
    finishing: dict[int, int] = {}          # ticket id -> minute it lands
    waves: list[Wave] = []
    now = 0
    stopped_at: int | None = None
    draining_shown = False

    while True:
        if stop_after_minutes is not None and now > stop_after_minutes:
            stopped_at = stop_after_minutes
            decision = None
        else:
            decision = schedule(backlog, states, ceilings)

        if decision and not decision.dispatch and not draining_shown:
            # A tick that starts nothing because the field is draining for a
            # solo ticket is a real event in the night, and the only one that
            # legitimately leaves the machine idle. Recorded once per drain
            # episode, so the plan shows why rather than looking hung.
            draining = tuple(sorted(
                ((i, h) for i, h in decision.holds.items() if h.reason == "draining"),
                key=lambda pair: pair[0],
            ))
            if draining:
                waves.append(Wave(len(waves) + 1, now, (), draining))
                draining_shown = True

        if decision and decision.dispatch:
            draining_shown = False
            planned = []
            for ticket_id in decision.dispatch:
                ticket = backlog[ticket_id]
                budget = ticket.budget_minutes or config.budget_minutes(ticket.size)
                states[ticket_id] = st.RUNNING
                finishing[ticket_id] = now + budget
                planned.append(PlannedTicket(
                    id=ticket_id,
                    model=ticket.model,
                    size=ticket.size,
                    budget_minutes=budget,
                    title=ticket.title,
                    start_minutes=now,
                    was_blocked_by=tuple(sorted(ticket.blocked_by)),
                    solo=ticket.solo,
                ))
            held = tuple(sorted(
                ((i, h) for i, h in decision.holds.items() if h.reason in HELD_BACK),
                key=lambda pair: pair[0],
            ))
            waves.append(Wave(len(waves) + 1, now, tuple(planned), held))

        if not finishing:
            break

        now = min(finishing.values())
        for ticket_id in [i for i, at in finishing.items() if at == now]:
            states[ticket_id] = st.MERGED
            del finishing[ticket_id]

    plan = Plan(
        branch=branch,
        ceilings=ceilings,
        stop_label=config.wall_clock_stop.strftime("%H:%M"),
        waves=tuple(waves),
        drain_minutes=now,
    )

    for ticket in backlog:
        if states[ticket.id] == st.MERGED:
            continue
        if ticket.human_gate:
            plan.not_dispatched[ticket.id] = NotDispatched("human-gate", ticket.title,
                                                           (ticket.id,))
            continue
        roots = _blocked_roots(backlog, ticket.id, gated)
        if roots:
            plan.not_dispatched[ticket.id] = NotDispatched(
                "blocked-downstream",
                ", ".join(f"T{r:02d}" for r in roots),
                roots,
            )
        else:
            plan.not_dispatched[ticket.id] = NotDispatched(
                "wall-clock-stop",
                f"no slot before the {plan.stop_label} stop" if stopped_at is not None else "",
            )
    return plan


def render_plan(plan: Plan) -> str:
    """Print the plan in the form the spec illustrates."""
    lines = [
        f"RUN PLAN — {plan.branch or '(unnamed run)'}  "
        f"(ceiling {plan.ceilings.concurrent}, opus {plan.ceilings.opus}, "
        f"stop {plan.stop_label})",
        "",
    ]

    for wave in plan.waves:
        prefix = f"wave {wave.index:<3} {_format_clock(wave.at_minutes):>8}   "
        pad = " " * len(prefix)

        if not wave.tickets:
            solo = [i for i, h in wave.holds if "runs alone" in h.detail]
            who = f"T{solo[0]:02d}" if solo else "a solo ticket"
            lines.append(f"{prefix}— draining: nothing starts until {who} can run alone —")

        for n, ticket in enumerate(wave.tickets):
            note = ""
            if ticket.was_blocked_by:
                blockers = ", ".join(f"T{b:02d}" for b in ticket.was_blocked_by)
                note = f"(was blocked by {blockers})"
            if ticket.solo:
                note = ("[SOLO — runs alone]" if not note else f"{note} [SOLO — runs alone]")
            lines.append(
                f"{prefix if n == 0 else pad}"
                f"{ticket.label} {ticket.model:<6} {ticket.size} {ticket.budget_minutes:>3}m  "
                f"{ticket.title[:44]:<46}{note}".rstrip()
            )
        if wave.holds:
            held = ", ".join(f"T{i:02d} ({h.reason})" for i, h in wave.holds[:6])
            more = "" if len(wave.holds) <= 6 else f", +{len(wave.holds) - 6} more"
            lines.append(f"{pad}held: {held}{more}")

    autonomous = sum(len(w.tickets) for w in plan.waves)
    drains = sum(1 for w in plan.waves if not w.tickets)
    if drains:
        lines.append("")
        lines.append(f"{drains} drain wave(s): the field is deliberately emptied so a "
                     f"solo ticket can run alone.")
    lines += [
        "",
        f"projected drain {plan.drain_minutes / 60:.1f} h · "
        f"{autonomous} tickets autonomous · {len(plan.not_dispatched)} held",
        "",
        "NOT DISPATCHED",
    ]

    gated = [i for i, n in plan.not_dispatched.items() if n.reason == "human-gate"]
    for ticket_id in sorted(gated):
        entry = plan.not_dispatched[ticket_id]
        lines.append(f"  T{ticket_id:02d}  human-gate   {entry.detail}")

    downstream: dict[int, list[int]] = {}
    for ticket_id, entry in plan.not_dispatched.items():
        for root in entry.roots:
            if root != ticket_id:
                downstream.setdefault(root, []).append(ticket_id)
    for root in sorted(downstream):
        held = sorted(downstream[root])
        lines.append(
            f"  {len(held)} further tickets held downstream of T{root:02d}: "
            + ", ".join(f"T{i:02d}" for i in held)
        )

    stalled = sorted(i for i, n in plan.not_dispatched.items()
                     if n.reason == "wall-clock-stop")
    if stalled:
        lines.append(
            f"  {len(stalled)} tickets had no slot before the {plan.stop_label} stop: "
            + ", ".join(f"T{i:02d}" for i in stalled)
        )

    return "\n".join(lines) + "\n"
