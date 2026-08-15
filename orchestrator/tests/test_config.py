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
