"""The loader, graded against `docs/tickets/README.md`.

The README's tables are an independent source of truth: they were written by
hand from the tickets, not derived by this code. If the loader and the README
disagree, one of them is wrong and the run should not start.
"""

from pathlib import Path

import pytest

from orchestrator.backlog import load_backlog

REPO_ROOT = Path(__file__).resolve().parents[2]
TICKETS = REPO_ROOT / "docs" / "tickets"

# docs/tickets/README.md — "Dependency levels"
README_LEVELS = {
    0: [1, 2, 3, 17],
    1: [4, 5, 16, 35],
    2: [6, 7, 8, 13, 18, 19, 36],
    3: [9, 11, 14, 20, 28, 37, 38, 41, 43],
    4: [12, 15, 21, 29, 39, 42],
    5: [10, 22, 24, 30, 34, 40],
    6: [23, 25, 47],
    7: [26, 27],
    8: [31, 33, 45, 46],
    9: [32],
    10: [44],
    11: [48],
    12: [49],
}

# docs/tickets/README.md — "Mutexes", the 18 live pairs
LIVE_MUTEX_PAIRS = [
    (3, 8), (3, 15), (3, 17), (7, 8), (7, 9), (8, 13), (12, 14), (12, 26),
    (16, 17), (18, 27), (21, 39), (23, 37), (25, 43), (30, 34), (31, 34),
    (32, 34), (34, 38), (45, 46),
]

# docs/tickets/README.md — "Flags"
HUMAN_GATE = {4, 49}
SOLO = {17}
HUMAN_VERIFY = {17, 18, 20, 21, 22, 23, 29, 30, 31, 32, 33, 34, 37, 38, 39, 42, 44}

# docs/tickets/README.md — "The ticket 04 bottleneck". The README's prose lists
# 20 tickets; the graph holds 21, because T49 sits downstream via T48. The prose
# is counting only the tickets that would otherwise have been *dispatched* —
# T49 is `human-gate` itself, so it was never going to run regardless.
DOWNSTREAM_OF_04 = {
    18, 19, 20, 21, 22, 23, 29, 30, 31, 32, 34, 37, 38, 39, 40, 42, 44, 45, 47, 48,
}


@pytest.fixture(scope="module")
def real():
    return load_backlog(TICKETS)


def test_all_49_tickets_load(real):
    assert real.ids == list(range(1, 50))


def test_levels_match_the_readme(real):
    derived: dict[int, list[int]] = {}
    for ticket in real:
        derived.setdefault(real.level(ticket.id), []).append(ticket.id)
    assert {k: sorted(v) for k, v in derived.items()} == README_LEVELS


def test_critical_path_is_thirteen_deep(real):
    assert max(real.critical_path(i) for i in real.ids) == 13


def test_the_readme_critical_path_is_a_real_chain(real):
    chain = [1, 5, 13, 14, 15, 24, 25, 26, 31, 32, 44, 48, 49]
    for earlier, later in zip(chain, chain[1:]):
        assert earlier in real[later].blocked_by, f"T{later:02d} is not blocked by T{earlier:02d}"
    assert real.critical_path(1) == len(chain)


def test_live_mutex_pairs_are_declared_and_symmetric(real):
    for a, b in LIVE_MUTEX_PAIRS:
        assert b in real.mutex_partners(a), f"mutex {a}<->{b} missing from the front-matter"
        assert a in real.mutex_partners(b)


def test_live_mutex_pairs_are_not_already_ordered_by_a_blocking_edge(real):
    """A live pair is live precisely because no edge already separates them."""
    for a, b in LIVE_MUTEX_PAIRS:
        assert b not in real.dependents(a), f"{a}->{b} is an edge; the pair is not live"
        assert a not in real.dependents(b), f"{b}->{a} is an edge; the pair is not live"


def test_flags_match_the_readme(real):
    assert {t.id for t in real if t.human_gate} == HUMAN_GATE
    assert {t.id for t in real if t.solo} == SOLO
    assert {t.id for t in real if t.human_verify} == HUMAN_VERIFY


def test_twenty_tickets_sit_downstream_of_04(real):
    assert len(DOWNSTREAM_OF_04) == 20
    assert real.dependents(4) == DOWNSTREAM_OF_04 | {49}
    # …and every one of the README's twenty is autonomous, which is what makes
    # 04 the bottleneck rather than merely a blocker.
    assert not any(real[i].human_gate for i in DOWNSTREAM_OF_04)


def test_declared_unblocks_matches_derived_transitive_dependents(real):
    """`unblocks:` is denormalised. Drift should be loud, not silent."""
    drift = {
        t.id: (t.declared_unblocks, len(real.dependents(t.id)))
        for t in real
        if t.declared_unblocks != len(real.dependents(t.id))
    }
    assert drift == {}, f"front-matter `unblocks` disagrees with the graph: {drift}"


def test_every_ticket_declares_a_budget_matching_its_size(real):
    expected = {"S": 30, "M": 60, "L": 120}
    mismatched = {
        t.id: (t.size, t.budget_minutes)
        for t in real
        if t.budget_minutes != expected[t.size]
    }
    assert mismatched == {}
