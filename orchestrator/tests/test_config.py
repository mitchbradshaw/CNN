"""Configuration: everything tuneable, nothing hardcoded."""

from datetime import datetime
from pathlib import Path

import pytest

from orchestrator.config import Config, ConfigError, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED = REPO_ROOT / "orchestrator" / "config.toml"


def test_the_shipped_config_loads(tmp_path):
    config = load_config(SHIPPED, repo_root=REPO_ROOT)

    assert config.ceilings.concurrent == 3
    assert config.ceilings.opus == 2
    assert config.budget_minutes("S") == 30
    assert config.budget_minutes("M") == 60
    assert config.budget_minutes("L") == 120
    assert config.review.max_rounds == 2


def test_paths_resolve_against_the_repo_root():
    config = load_config(SHIPPED, repo_root=REPO_ROOT)

    assert config.paths.tickets == REPO_ROOT / "docs" / "tickets"
    assert config.paths.coding_standards.is_file()
    assert config.paths.claude_md.is_file()


def test_the_shipped_config_junctions_the_channel_data_the_ui_suite_needs():
    """Ten test files import `UI.app`, which builds a full ViewerApp at import
    time (UI/app.py:2279) and mmaps the first recording's channel. Absent that
    directory they fail during COLLECTION, before their own skip guards can run,
    and all ten read as regressions — which is exactly how run-20260816-1943
    quarantined an innocent T01 and blocked 36 tickets behind it.
    """
    config = load_config(SHIPPED, repo_root=REPO_ROOT)

    assert config.paths.recordings, \
        "nothing junctioned: UI.app cannot be imported inside a worktree"
    assert "M2_aug_concat_fs1" in {p.name for p in config.paths.recordings}
    for source in config.paths.recordings:
        assert source.is_dir(), f"declared recording directory does not exist: {source}"
        assert source.is_relative_to(REPO_ROOT), \
            "a recording outside the repo root has no worktree-relative home"


def test_the_shipped_fixture_database_is_not_the_real_one(tmp_path):
    """The fixture is copied into every worktree, so it is the one database an
    agent can reach. It must carry no annotation corpus and no schema drift.

    It was a byte-identical copy of DATA/db/annotations.sqlite — 2.9 MB, 11,266
    annotations — which is how a worktree ended up depending on real research
    data to collect its tests at all.
    """
    import sqlite3

    from Working.database.schema import init_db

    config = load_config(SHIPPED, repo_root=REPO_ROOT)
    fixture = config.paths.fixture_db
    assert fixture.is_file(), f"fixture database missing: {fixture}"
    assert fixture.stat().st_size < 1_000_000, \
        f"{fixture.stat().st_size} bytes — this is the real database, not a fixture"

    conn = sqlite3.connect(fixture)
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute("SELECT count(*) FROM annotations").fetchone()[0] == 0, \
            "the fixture carries real annotations; worktree behaviour must not depend on them"

        # Not empty either: UI/app.py builds a ViewerApp at import time and
        # raises RuntimeError if no recording exists. Every row must point at
        # data the junction actually supplies.
        rows = conn.execute("SELECT npy_path FROM recordings").fetchall()
        assert rows, "no recordings: importing UI.app in a worktree raises RuntimeError"
        junctioned = config.paths.recordings
        for (npy_path,) in rows:
            source = (REPO_ROOT / npy_path).resolve()
            assert any(source.is_relative_to(d) for d in junctioned), \
                f"{npy_path} is not covered by any junctioned directory"
            assert source.is_file(), f"{npy_path} does not exist on disk"

        current = init_db(str(tmp_path / "current.sqlite"))
        expected = {r[0] for r in current.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        actual = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert expected <= actual, f"fixture schema is behind init_db(): missing {expected - actual}"
    finally:
        conn.close()


def test_config_hash_is_stable_and_content_sensitive(tmp_path):
    a = tmp_path / "a.toml"
    b = tmp_path / "b.toml"
    a.write_text(SHIPPED.read_text(encoding="utf-8"), encoding="utf-8")
    b.write_text(SHIPPED.read_text(encoding="utf-8").replace("concurrent = 3", "concurrent = 4"),
                 encoding="utf-8")

    first = load_config(a, repo_root=REPO_ROOT)
    again = load_config(a, repo_root=REPO_ROOT)
    other = load_config(b, repo_root=REPO_ROOT)

    assert first.config_hash == again.config_hash
    assert first.config_hash.startswith("sha256:")
    assert first.config_hash != other.config_hash


def test_wall_clock_stop_resolves_to_the_next_occurrence_of_that_time():
    config = load_config(SHIPPED, repo_root=REPO_ROOT)

    started = datetime(2026, 8, 15, 21, 30)
    assert config.wall_clock_stop_at(started) == datetime(2026, 8, 16, 7, 0)

    # Started after the stop time on the same day — still the next 07:00.
    started = datetime(2026, 8, 16, 8, 0)
    assert config.wall_clock_stop_at(started) == datetime(2026, 8, 17, 7, 0)


def test_a_missing_section_is_an_error_not_a_default(tmp_path):
    partial = tmp_path / "partial.toml"
    partial.write_text("[ceilings]\nconcurrent = 3\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(partial, repo_root=REPO_ROOT)


def test_an_unknown_size_is_an_error(tmp_path):
    config = load_config(SHIPPED, repo_root=REPO_ROOT)

    with pytest.raises(ConfigError, match="XL"):
        config.budget_minutes("XL")


# ------------------------------------------- what the night is allowed to cost


def test_the_shipped_config_waits_out_a_usage_window_not_fifteen_minutes():
    """`max_backoff_seconds = 900` was the value run-20260818-2244 met: a plan
    usage cap resets in *hours*, and a fifteen-minute ceiling guarantees the
    runner gives up long before the environment recovers."""
    config = load_config(REPO_ROOT / "orchestrator" / "config.toml", repo_root=REPO_ROOT)

    assert config.rate_limit.max_usage_wait_seconds >= 4 * 3600
    assert config.rate_limit.usage_reset_grace_seconds > 0, (
        "waking exactly on the stated boundary races the reset")


def test_the_shipped_config_asks_the_cli_for_structured_output():
    """No `--output-format` is why five runs produced no cost data at all."""
    config = load_config(REPO_ROOT / "orchestrator" / "config.toml", repo_root=REPO_ROOT)

    assert config.agent.output_format in ("json", "stream-json")


def test_the_shipped_config_spreads_the_burn_rather_than_bursting_it():
    """The cap is tokens per rolling window, not wall-clock. Three concurrent
    agents do not cost less than one — they spend the same budget three times
    faster, which is how a 20-hour dispatch window became a 6.5-hour burst that
    overran a single usage window and took the whole night with it."""
    config = load_config(REPO_ROOT / "orchestrator" / "config.toml", repo_root=REPO_ROOT)

    assert config.ceilings.concurrent <= 2
    assert config.ceilings.opus <= config.ceilings.concurrent


def test_a_missing_usage_setting_takes_a_safe_default_rather_than_failing(tmp_path):
    """These keys arrived after five runs had already been recorded. An old
    config must still load, or `--resume` cannot read its own run."""
    source = (REPO_ROOT / "orchestrator" / "config.toml").read_text(encoding="utf-8")
    stripped = "\n".join(
        line for line in source.splitlines()
        if not line.startswith(("max_usage_wait_seconds", "usage_reset_grace_seconds",
                                "output_format", "max_budget_usd"))
    )
    path = tmp_path / "config.toml"
    path.write_text(stripped, encoding="utf-8")

    config = load_config(path, repo_root=REPO_ROOT)

    assert config.rate_limit.max_usage_wait_seconds > 0
    assert config.agent.output_format
