"""The global circuit breaker — pure functions over a small mutable record.

Three consecutive quarantines, or more than 40% of dispatched tickets
quarantined, halts the run. This is the difference between "one ticket was
wrong" and "the base is broken and every agent is now failing for the same
reason".

**Flakes need their own counter.** The spec says consecutive `FLAKY` marks count
toward the breaker at half weight, so a suite that has become broadly unreliable
still halts the run. But a flaky ticket *merges* — that is the whole point of
the flake amendment — so if the flake count shared the quarantine counter, the
merge it enabled would immediately reset it and the rule could never accumulate.
The two streaks are therefore separate, and only a genuinely clean suite clears
the flake streak.

Extracted from the run loop so the policy can be tested without git,
subprocesses or a clock.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Below this many dispatched tickets the quarantine *fraction* is noise —
#: one failure out of one is 100% and means nothing.
MIN_SAMPLE_FOR_FRACTION = 3


@dataclass
class BreakerState:
    consecutive_quarantines: float = 0.0
    consecutive_flakes: int = 0
    tripped: bool = False
    reason: str = ""

    def weight(self, flaky_weight: float) -> float:
        """Quarantines at full weight, flake marks at half."""
        return self.consecutive_quarantines + flaky_weight * self.consecutive_flakes


def note_quarantine(state: BreakerState, config, *, dispatched: int,
                    quarantined: int) -> BreakerState:
    state.consecutive_quarantines += 1
    return _evaluate(state, config, dispatched=dispatched, quarantined=quarantined)


def note_flaky(state: BreakerState, config, *, dispatched: int,
               quarantined: int) -> BreakerState:
    """A FLAKY mark is a finding, not a shrug."""
    state.consecutive_flakes += 1
    return _evaluate(state, config, dispatched=dispatched, quarantined=quarantined)


def note_merged(state: BreakerState, *, suite_was_clean: bool = False) -> BreakerState:
    """A landed ticket clears the quarantine streak.

    It clears the *flake* streak only if its suite was actually clean. A ticket
    that merged because its re-run went green is evidence of an unreliable
    suite, not evidence against one.
    """
    state.consecutive_quarantines = 0.0
    if suite_was_clean:
        state.consecutive_flakes = 0
    return state


def _evaluate(state: BreakerState, config, *, dispatched: int,
              quarantined: int) -> BreakerState:
    if state.tripped:
        return state   # sticky: a later success does not un-break the base

    weight = state.weight(config.flaky_weight)
    if weight >= config.consecutive_quarantines:
        state.tripped = True
        state.reason = (
            f"{state.consecutive_quarantines:g} consecutive quarantine(s) and "
            f"{state.consecutive_flakes} consecutive flake mark(s) — weighted "
            f"{weight:g} against a threshold of {config.consecutive_quarantines}"
        )
        return state

    fraction = quarantined / dispatched if dispatched else 0.0
    if dispatched >= MIN_SAMPLE_FOR_FRACTION and fraction > config.quarantine_fraction:
        state.tripped = True
        state.reason = (
            f"{quarantined}/{dispatched} dispatched tickets quarantined "
            f"({fraction:.0%}, threshold {config.quarantine_fraction:.0%})"
        )
    return state
