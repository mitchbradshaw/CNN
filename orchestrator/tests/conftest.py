"""Test support for the orchestrator's own suite.

These tests live outside `tests/` on purpose: the 486-test ticket suite is the
baseline every gate compares against, and the runner's tests must not enter it.
Run them with `pytest orchestrator/tests`.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def ticket_dir(tmp_path):
    """An empty directory that fake tickets get written into."""
    d = tmp_path / "tickets"
    d.mkdir()
    return d


@pytest.fixture
def write_ticket(ticket_dir):
    """Write a fake ticket file and return its path.

    Only the front-matter matters to the runner, so the prose is a stub.
    """

    def _write(id, *, model="sonnet", size="M", blocked_by=(), mutex=(),
               files=(), flags=(), level=0, unblocks=0, budget_minutes=60,
               title=None, body="Fake ticket."):
        title = title or f"Fake ticket {id}"

        def _list(xs):
            return "[" + ", ".join(repr(x) if isinstance(x, str) else str(x) for x in xs) + "]"

        text = (
            "---\n"
            f"id: {id}\n"
            f'title: "{title}"\n'
            f"model: {model}\n"
            f"size: {size}\n"
            f"blocked_by: {_list(blocked_by)}\n"
            f"mutex: {_list(mutex)}\n"
            f"files: {_list(files)}\n"
            f"flags: {_list(flags)}\n"
            f"level: {level}\n"
            f"unblocks: {unblocks}\n"
            f"budget_minutes: {budget_minutes}\n"
            "---\n"
            f"# {id:02d} — {title}\n\n{body}\n"
        )
        path = ticket_dir / f"T{id:02d}-fake-ticket.md"
        path.write_text(text, encoding="utf-8")
        return path

    return _write
