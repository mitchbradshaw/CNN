"""What to dispatch right now — a pure function over ticket state.

No git, no subprocess, no clock, no I/O. Everything the scheduler needs arrives
as arguments and everything it decides comes back as a value. That is what lets
it be tested exhaustively against the real 49-ticket graph, and it is the reason
no LLM is anywhere near this decision.

Constraints are applied in the priority order the spec fixes:

  1. blocking edges   a ticket dispatches only when every blocker has *landed*
  2. mutexes          never two declared merge-risk partners in flight at once
  3. solo             ticket 17 runs alone
  4. ceilings         global concurrency, then the Opus sub-ceiling
  5. human gates      never dispatched at all

Ordering among the ready is most-unblocking first, tie-broken by critical-path
length, then by id. Deterministic to the last position.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from . import status as st
from .backlog import Backlog


@dataclass(frozen=True)
class Ceilings:
    """Concurrency limits. Configuration, not constants — see config.toml."""

    concurrent: int = 3
    opus: int = 2


@dataclass(frozen=True)
class Hold:
    """Why a ticket that was otherwise dispatchable is not being dispatched."""

    reason: str   # human-gate | blocked | mutex | solo | ceiling | opus-ceiling
    detail: str = ""


@dataclass(frozen=True)
class Decision:
    dispatch: tuple[int, ...]
    holds: Mapping[int, Hold]


def _sort_key(backlog: Backlog, ticket_id: int) -> tuple[int, int, int]:
    """Most-unblocking, then longest critical path, then lowest id."""
    return (
        -len(backlog.dependents(ticket_id)),
        -backlog.critical_path(ticket_id),
        ticket_id,
    )


def _blocking_detail(backlog: Backlog, ticket_id: int, states: Mapping[int, str]) -> str:
    unlanded = [b for b in backlog[ticket_id].blocked_by if states.get(b) != st.LANDED]
    return ", ".join(f"T{b:02d}" for b in sorted(unlanded))


def schedule(backlog: Backlog, states: Mapping[int, str], ceilings: Ceilings) -> Decision:
    """Return the tickets to dispatch now, and why each other candidate is held."""
    holds: dict[int, Hold] = {}

    in_flight = [i for i, s in states.items() if s in st.IN_FLIGHT]
    opus_in_flight = sum(1 for i in in_flight if backlog[i].model == "opus")
    solo_in_flight = any(backlog[i].solo for i in in_flight)

    candidates: list[int] = []
    for ticket in backlog:
        current = states.get(ticket.id, st.PENDING)
        if current in st.TERMINAL or current in st.IN_FLIGHT:
            continue

        # 5. Human gates. Reported first because it is the most final answer.
        if ticket.human_gate:
            holds[ticket.id] = Hold("human-gate", ticket.title)
            continue

        # 1. Blocking edges.
        if any(states.get(b) != st.LANDED for b in ticket.blocked_by):
            holds[ticket.id] = Hold("blocked", _blocking_detail(backlog, ticket.id, states))
            continue

        candidates.append(ticket.id)

    candidates.sort(key=lambda i: _sort_key(backlog, i))

    # 3a. Drain for solo. Holding a solo ticket whenever anything is in flight
    # is not enough on its own: nothing would ever stop *other* tickets taking
    # the slots, so the solo ticket could only start on a tick where the field
    # happened to be empty and it happened to sort first. With a ceiling of 3
    # and continuous work that is luck, and T17 gates 26 tickets.
    #
    # So once a solo ticket is the top candidate, the field drains: nothing new
    # dispatches until the in-flight tickets finish. Only the *top* candidate
    # earns this — draining costs the whole field's throughput, and a solo
    # ticket nothing depends on can wait its turn.
    if candidates and backlog[candidates[0]].solo and in_flight:
        waiting = ", ".join(f"T{i:02d}" for i in sorted(in_flight))
        holds[candidates[0]] = Hold(
            "draining", f"runs alone; waiting for {waiting} to finish")
        for other in candidates[1:]:
            holds[other] = Hold(
                "draining", f"field draining for T{candidates[0]:02d} (solo)")
        return Decision(dispatch=(), holds=holds)

    dispatch: list[int] = []
    slots = ceilings.concurrent - len(in_flight)
    opus_slots = ceilings.opus - opus_in_flight

    for ticket_id in candidates:
        ticket = backlog[ticket_id]

        # 3. Solo, in both directions: a solo ticket needs an empty field, and
        #    while one is in flight or about to be, nothing else may start.
        if solo_in_flight or any(backlog[d].solo for d in dispatch):
            holds[ticket_id] = Hold("solo", "a solo ticket holds the field")
            continue
        if ticket.solo and (in_flight or dispatch):
            others = [f"T{i:02d}" for i in sorted(set(in_flight) | set(dispatch))]
            holds[ticket_id] = Hold("solo", f"runs alone; in flight: {', '.join(others)}")
            continue

        # 2. Mutexes — against what is in flight and against this same tick.
        partners = backlog.mutex_partners(ticket_id)
        clash = sorted(partners & (set(in_flight) | set(dispatch)))
        if clash:
            holds[ticket_id] = Hold("mutex", ", ".join(f"T{i:02d}" for i in clash))
            continue

        # 4. Ceilings.
        if slots <= 0:
            holds[ticket_id] = Hold("ceiling", f"global ceiling {ceilings.concurrent}")
            continue
        if ticket.model == "opus" and opus_slots <= 0:
            holds[ticket_id] = Hold("opus-ceiling", f"opus ceiling {ceilings.opus}")
            continue

        dispatch.append(ticket_id)
        slots -= 1
        if ticket.model == "opus":
            opus_slots -= 1

    return Decision(dispatch=tuple(dispatch), holds=holds)
