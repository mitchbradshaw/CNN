"""The command line. `--plan` and `--status` must not touch git at all."""

from pathlib import Path

import pytest

from orchestrator.run import _apply_ceiling_overrides, _parse_args, main

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_plan_prints_a_schedule_and_dispatches_nothing(capsys):
    before = _head_sha()

    code = main(["--plan"])

    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("RUN PLAN")
    assert "NOT DISPATCHED" in out
    assert _head_sha() == before, "--plan must not touch git"


def test_a_ceiling_override_reaches_the_run_loop_not_just_the_plan():
    """The run loop reads `config.ceilings`. An override that only reached the
    planner would print one schedule and execute a different one."""
    from orchestrator.config import load_config

    config = load_config(REPO_ROOT / "orchestrator" / "config.toml", repo_root=REPO_ROOT)
    args = _parse_args(["--run", "--ceiling", "1", "--opus-ceiling", "1"])

    overridden = _apply_ceiling_overrides(config, args)

    assert overridden.ceilings.concurrent == 1
    assert overridden.ceilings.opus == 1


def test_no_override_leaves_the_config_object_alone():
    from orchestrator.config import load_config

    config = load_config(REPO_ROOT / "orchestrator" / "config.toml", repo_root=REPO_ROOT)
    args = _parse_args(["--plan"])

    assert _apply_ceiling_overrides(config, args) is config


def test_the_ceiling_override_changes_the_printed_plan(capsys):
    main(["--plan", "--ceiling", "1"])
    narrow = capsys.readouterr().out
    main(["--plan", "--ceiling", "3"])
    wide = capsys.readouterr().out

    assert "ceiling 1," in narrow
    assert "ceiling 3," in wide
    assert narrow.count("wave") > wide.count("wave")


def test_a_mode_is_required():
    with pytest.raises(SystemExit):
        _parse_args([])


def test_the_modes_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        _parse_args(["--plan", "--run"])


def _head_sha() -> str:
    from orchestrator.gitops import Git
    return Git(REPO_ROOT).rev_parse("HEAD")
