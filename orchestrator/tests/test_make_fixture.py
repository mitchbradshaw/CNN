"""The fixture database must not promise data the worktree does not have.

Every recording row the fixture carries is a promise that `npy_path` resolves,
because `UI/app.py` builds a `ViewerApp` at import time and loads the first
recording. A row pointing at an absent file is not a degraded fixture, it is an
unusable one: the load raises `FileNotFoundError` during collection, pytest
abandons the session, and every worktree in the run measures nothing.

`build()` already refuses a fixture with no rows at all. These tests cover the
case that actually happened — rows present, files gone.
"""

import sqlite3

import pytest

from orchestrator import make_fixture

CONFIG = """
[run]
base_branch = "main"
branch_prefix = "integration/run-"
ticket_branch_prefix = "ticket/"
wall_clock_stop = "07:00"
[ceilings]
concurrent = 3
opus = 2
[budgets]
S = 30
M = 60
L = 120
[models]
sonnet = "claude-sonnet-5"
opus = "claude-opus-5"
review = "claude-opus-5"
fix = "claude-opus-5"
[paths]
tickets = "docs/tickets"
runs = "runs"
worktrees = "../.wt"
claude_md = "CLAUDE.md"
coding_standards = "docs/CODING_STANDARDS.md"
fixture_db = "DATA/fixture/annotations.sqlite"
fixture_db_dest = "DATA/db/annotations.sqlite"
recordings = ["DATA/derived/channels/REC"]
[agent]
cli = ["claude"]
extra_args = []
stall_minutes = 20
[suite]
command = ["pytest", "-q"]
timeout_minutes = 25
[retries]
infrastructure = 3
infrastructure_backoff_seconds = 30
stall = 1
[review]
skill = "code-review"
max_rounds = 2
blocking_severities = ["blocker"]
followups_file = "FOLLOWUPS.md"
timeout_minutes = 30
default_severity = "minor"
[overlap]
include_private = true
[circuit_breaker]
consecutive_quarantines = 3
quarantine_fraction = 0.4
flaky_weight = 0.5
[rate_limit]
concurrent_signature = 2
fast_exit_seconds = 60
initial_backoff_seconds = 60
max_backoff_seconds = 900
"""


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """A repo root with one junctioned recording directory and a source db.

    The channel files are deliberately *not* written here — each test decides
    whether they exist, because that is the whole question.
    """
    monkeypatch.setattr(make_fixture, "REPO_ROOT", tmp_path)
    (tmp_path / "orchestrator").mkdir()
    config_path = tmp_path / "orchestrator" / "config.toml"
    config_path.write_text(CONFIG, encoding="utf-8")
    (tmp_path / "DATA" / "derived" / "channels" / "REC").mkdir(parents=True)

    source_db = tmp_path / "source.sqlite"
    conn = sqlite3.connect(source_db)
    conn.execute(
        "CREATE TABLE recordings (id INTEGER PRIMARY KEY, source_file TEXT, "
        "channel INT, fs REAL, n_samples INT, global_offset INT, npy_path TEXT)"
    )
    conn.execute(
        "INSERT INTO recordings VALUES (1, 'REC.mat', 0, 1.0, 100, 0, "
        "'DATA/derived/channels/REC/CH0.npy')"
    )
    conn.commit()
    conn.close()

    return tmp_path, config_path, source_db


def _channel_file(root):
    return root / "DATA" / "derived" / "channels" / "REC" / "CH0.npy"


def test_a_fixture_row_pointing_at_an_absent_channel_is_refused(fake_repo):
    """The run-20260817-1157 failure, in one assertion.

    The channel directory exists and is junctioned, and the row's path resolves
    inside it — so the existing "points inside the junctioned directories" check
    is satisfied. Only the file itself is missing.
    """
    root, config_path, source_db = fake_repo

    with pytest.raises(SystemExit) as exc:
        make_fixture.build(config_path=config_path, source_db=source_db)

    assert "CH0.npy" in str(exc.value), "the message must name the file that is missing"


def test_a_fixture_whose_channels_are_present_is_built(fake_repo):
    root, config_path, source_db = fake_repo
    _channel_file(root).write_bytes(b"not really a npy, but it exists")

    destination = make_fixture.build(config_path=config_path, source_db=source_db)

    conn = sqlite3.connect(destination)
    assert conn.execute("SELECT count(*) FROM recordings").fetchone()[0] == 1
    conn.close()
