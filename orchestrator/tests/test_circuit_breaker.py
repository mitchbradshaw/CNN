"""The circuit breaker, including the half-weight flake rule.

The breaker is the difference between "one ticket was wrong" and "the base is
broken and every agent is now failing for the same reason".
"""

import pytest

from orchestrator.breaker import BreakerState, note_flaky, note_merged, note_quarantine


@pytest.fixture
def thresholds():
    from orchestrator.config import CircuitBreakerConfig
    return CircuitBreakerConfig(consecutive_quarantines=3, quarantine_fraction=0.4,
                                flaky_weight=0.5)


def test_three_consecutive_quarantines_trip_it(thresholds):
    state = BreakerState()

    for _ in range(2):
        note_quarantine(state, thresholds, dispatched=5, quarantined=2)
    assert not state.tripped

    note_quarantine(state, thresholds, dispatched=5, quarantined=3)
    assert state.tripped


def test_a_merge_resets_the_quarantine_streak(thresholds):
    # Kept well under the 40% fraction rule, so this isolates the streak.
    state = BreakerState()
    note_quarantine(state, thresholds, dispatched=20, quarantined=1)
    note_quarantine(state, thresholds, dispatched=20, quarantined=2)

    note_merged(state)
    note_quarantine(state, thresholds, dispatched=20, quarantined=3)

    assert not state.tripped
    assert state.consecutive_quarantines == 1


def test_a_flaky_ticket_that_merges_does_not_wipe_its_own_flake_count(thresholds):
    """A flaky ticket always merges — that is the point of the amendment. If
    the merge reset the flake count, the half-weight rule could never
    accumulate and would be a no-op as built."""
    state = BreakerState()

    note_flaky(state, thresholds, dispatched=1, quarantined=0)
    note_merged(state)

    assert state.consecutive_flakes == 1
    assert state.consecutive_quarantines == 0


def test_six_consecutive_flakes_trip_it_at_half_weight(thresholds):
    """A suite that has become broadly unreliable still halts the run."""
    state = BreakerState()

    for _ in range(5):
        note_flaky(state, thresholds, dispatched=6, quarantined=0)
        note_merged(state)
    assert not state.tripped

    note_flaky(state, thresholds, dispatched=6, quarantined=0)

    assert state.tripped


def test_a_clean_suite_resets_the_flake_streak(thresholds):
    state = BreakerState()
    for _ in range(5):
        note_flaky(state, thresholds, dispatched=6, quarantined=0)

    note_merged(state, suite_was_clean=True)

    assert state.consecutive_flakes == 0


def test_flakes_and_quarantines_combine_toward_the_same_threshold(thresholds):
    state = BreakerState()

    note_flaky(state, thresholds, dispatched=4, quarantined=0)   # 0.5
    note_flaky(state, thresholds, dispatched=4, quarantined=0)   # 1.0
    note_quarantine(state, thresholds, dispatched=4, quarantined=1)   # 2.0
    assert not state.tripped

    note_quarantine(state, thresholds, dispatched=4, quarantined=2)   # 3.0
    assert state.tripped


def test_the_quarantine_fraction_trips_it_independently(thresholds):
    """Alternating merge/quarantine never builds a streak, but half the run
    being quarantined is still a broken base."""
    state = BreakerState()

    for n in range(1, 5):
        note_merged(state)
        note_quarantine(state, thresholds, dispatched=2 * n, quarantined=n)

    assert state.tripped


def test_the_fraction_rule_needs_a_meaningful_sample(thresholds):
    """One quarantine out of one dispatched is 100%, and means nothing."""
    state = BreakerState()

    note_quarantine(state, thresholds, dispatched=1, quarantined=1)

    assert not state.tripped


def test_tripping_is_sticky(thresholds):
    state = BreakerState()
    for _ in range(3):
        note_quarantine(state, thresholds, dispatched=5, quarantined=3)
    assert state.tripped

    note_merged(state)

    assert state.tripped, "a later success does not un-break the base"
