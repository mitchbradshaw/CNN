"""The backlog loader: front-matter in, validated graph out."""

import pytest

from orchestrator.backlog import BacklogError, load_backlog


def test_loads_front_matter_fields(write_ticket, ticket_dir):
    write_ticket(1, model="sonnet", size="M", files=["a.py"], budget_minutes=60)
    write_ticket(5, model="opus", size="L", blocked_by=[1], mutex=[1],
                 flags=["solo"], budget_minutes=120)

    backlog = load_backlog(ticket_dir)

    assert sorted(backlog.ids) == [1, 5]
    one = backlog[1]
    assert one.model == "sonnet"
    assert one.size == "M"
    assert one.files == ("a.py",)
    assert one.budget_minutes == 60
    assert one.blocked_by == ()

    five = backlog[5]
    assert five.model == "opus"
    assert five.blocked_by == (1,)
    assert five.mutex == (1,)
    assert five.flags == ("solo",)


def test_unknown_blocker_is_an_error(write_ticket, ticket_dir):
    write_ticket(1)
    write_ticket(2, blocked_by=[99])

    with pytest.raises(BacklogError, match="99"):
        load_backlog(ticket_dir)


def test_unknown_mutex_partner_is_an_error(write_ticket, ticket_dir):
    write_ticket(1, mutex=[42])

    with pytest.raises(BacklogError, match="42"):
        load_backlog(ticket_dir)


def test_self_reference_is_an_error(write_ticket, ticket_dir):
    write_ticket(1, blocked_by=[1])

    with pytest.raises(BacklogError, match="self"):
        load_backlog(ticket_dir)


def test_cycle_is_an_error(write_ticket, ticket_dir):
    write_ticket(1, blocked_by=[3])
    write_ticket(2, blocked_by=[1])
    write_ticket(3, blocked_by=[2])

    with pytest.raises(BacklogError, match="cycle"):
        load_backlog(ticket_dir)


def test_derives_level_dependents_and_critical_path(write_ticket, ticket_dir):
    # 1 → 2 → 4  and  1 → 3
    write_ticket(1)
    write_ticket(2, blocked_by=[1])
    write_ticket(3, blocked_by=[1])
    write_ticket(4, blocked_by=[2])

    backlog = load_backlog(ticket_dir)

    assert [backlog.level(i) for i in (1, 2, 3, 4)] == [0, 1, 1, 2]
    # transitive dependents, not immediate ones
    assert backlog.dependents(1) == {2, 3, 4}
    assert backlog.dependents(2) == {4}
    assert backlog.dependents(4) == set()
    # longest chain of remaining work, counting the ticket itself
    assert backlog.critical_path(1) == 3
    assert backlog.critical_path(3) == 1


def test_mutex_edges_are_symmetric_even_when_declared_once(write_ticket, ticket_dir):
    write_ticket(1, mutex=[2])
    write_ticket(2)

    backlog = load_backlog(ticket_dir)

    assert backlog.mutex_partners(1) == {2}
    assert backlog.mutex_partners(2) == {1}
