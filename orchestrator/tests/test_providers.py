"""Routing each agent to the model provider that should serve it.

Ticket agents run on DeepSeek; review and fix stay on Claude. That split only
works if the provider is chosen *per agent*, because the CLI takes its endpoint
from the environment and one exported `ANTHROPIC_BASE_URL` would silently move
every agent at once.

Two failure modes drive most of what is tested here, and neither announces
itself:

- DeepSeek's Anthropic-compatible endpoint **silently maps an unrecognised
  model name onto `deepseek-v4-flash`** rather than rejecting it. So a config
  that routes `claude-sonnet-5` to DeepSeek does not fail -- it quietly runs
  the cheap model and reports the expensive name. `model_prefix` exists to make
  that combination refuse to load.
- An `ANTHROPIC_BASE_URL` already exported in the operator's shell is inherited
  by every child process. The Claude-backed agents must therefore *clear* it,
  not merely decline to set it.
"""

from pathlib import Path

import pytest

from orchestrator.config import ConfigError, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED = REPO_ROOT / "orchestrator" / "config.toml"

TIER_MODELS_DEEPSEEK = (
    'haiku   = "deepseek-v4-flash"\n'
    'sonnet  = "deepseek-v4-flash"\n'
    'opus    = "deepseek-v4-pro"'
)
TIER_MODELS_CLAUDE = (
    'haiku   = "claude-haiku-4-5"\n'
    'sonnet  = "claude-sonnet-5"\n'
    'opus    = "claude-opus-5"'
)
TIER_ROUTING_DEEPSEEK = (
    'haiku   = "deepseek"\n'
    'sonnet  = "deepseek"\n'
    'opus    = "deepseek"'
)
TIER_ROUTING_ANTHROPIC = (
    'haiku   = "anthropic"\n'
    'sonnet  = "anthropic"\n'
    'opus    = "anthropic"'
)


def _config_with(tmp_path, *substitutions):
    """The shipped config with `(old, new)` substitutions, loaded from a copy.

    Takes pairs rather than one replacement because moving a tier between
    providers usually means changing the model name too -- otherwise the prefix
    guard rejects the combination before the test reaches what it meant to
    check.
    """
    text = SHIPPED.read_text(encoding="utf-8")
    for old, new in substitutions:
        assert old in text, f"anchor not found in shipped config: {old!r}"
        text = text.replace(old, new, 1)
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return load_config(path, repo_root=REPO_ROOT)


# ── Routing ─────────────────────────────────────────────────────────────────


def test_ticket_tiers_go_to_deepseek_and_review_stays_on_claude():
    config = load_config(SHIPPED, repo_root=REPO_ROOT)

    for tier in ("haiku", "sonnet", "opus"):
        assert config.provider_for(tier).name == "deepseek", \
            f"ticket tier {tier!r} should be served by DeepSeek"
    for key in ("review", "fix"):
        assert config.provider_for(key).name == "anthropic", \
            f"{key!r} is the quality floor and must stay on Claude"


def test_an_unlisted_key_falls_back_to_the_default_provider():
    config = load_config(SHIPPED, repo_root=REPO_ROOT)
    assert config.provider_for("review").name == config.providers_default


# ── The environment handed to each agent ────────────────────────────────────


def test_a_deepseek_agent_gets_the_endpoint_and_the_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-value")
    config = load_config(SHIPPED, repo_root=REPO_ROOT)

    env = config.agent_env("opus")
    assert env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-test-value"


def test_a_claude_agent_clears_an_inherited_base_url(monkeypatch):
    """The operator exports ANTHROPIC_BASE_URL for their own DeepSeek use; the
    review agent inherits it and silently reviews on the cheap model. Declining
    to set the variable is not enough -- it has to be removed."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-value")
    config = load_config(SHIPPED, repo_root=REPO_ROOT)

    env = config.agent_env("review")
    assert "ANTHROPIC_BASE_URL" not in env


def test_a_claude_agent_does_not_inherit_the_deepseek_token(monkeypatch):
    """The other half of the leak. The ticket agent before it was handed
    ANTHROPIC_AUTH_TOKEN; if that survives into the reviewer's environment the
    DeepSeek key is sent to Anthropic, which fails closed but noisily."""
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-deepseek-leaked")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-value")
    config = load_config(SHIPPED, repo_root=REPO_ROOT)

    assert "ANTHROPIC_AUTH_TOKEN" not in config.agent_env("review")


def test_a_claude_agent_keeps_the_rest_of_the_environment(monkeypatch):
    monkeypatch.setenv("SOME_UNRELATED_VAR", "kept")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-value")
    config = load_config(SHIPPED, repo_root=REPO_ROOT)

    assert config.agent_env("review")["SOME_UNRELATED_VAR"] == "kept"


def test_a_missing_key_is_not_silently_passed_as_empty(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = load_config(SHIPPED, repo_root=REPO_ROOT)

    env = config.agent_env("opus")
    assert env.get("ANTHROPIC_AUTH_TOKEN") != "", \
        "an empty key reads as authentication failure forty minutes into a run"


# ── Refusing a misrouted model ──────────────────────────────────────────────


def test_a_model_that_does_not_match_its_providers_prefix_refuses(tmp_path):
    """The load-bearing guard: DeepSeek would accept `claude-opus-5` and
    silently serve deepseek-v4-flash, so nothing downstream could detect it."""
    with pytest.raises(ConfigError) as excinfo:
        _config_with(tmp_path, ('opus    = "deepseek-v4-pro"',
                                'opus    = "claude-opus-5"'))
    message = str(excinfo.value)
    assert "opus" in message and "deepseek" in message


def test_a_deepseek_model_routed_to_anthropic_refuses(tmp_path):
    with pytest.raises(ConfigError) as excinfo:
        _config_with(tmp_path, ('review  = "claude-sonnet-5"',
                                'review  = "deepseek-v4-pro"'))
    assert "review" in str(excinfo.value)


def test_an_unknown_provider_name_refuses(tmp_path):
    with pytest.raises(ConfigError) as excinfo:
        _config_with(tmp_path, ('opus    = "deepseek"', 'opus    = "nonesuch"'))
    assert "nonesuch" in str(excinfo.value)


# ── Startup credential check ────────────────────────────────────────────────


def test_missing_credentials_names_the_unset_variable(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = load_config(SHIPPED, repo_root=REPO_ROOT)

    assert "DEEPSEEK_API_KEY" in config.missing_credentials()


def test_nothing_is_missing_once_the_key_is_exported(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-value")
    config = load_config(SHIPPED, repo_root=REPO_ROOT)

    assert config.missing_credentials() == ()


def test_only_providers_actually_in_use_are_checked(monkeypatch, tmp_path):
    """An unused provider block is documentation, not a requirement. Demanding
    its key would refuse every run over a provider nothing routes to."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = _config_with(
        tmp_path,
        (TIER_MODELS_DEEPSEEK, TIER_MODELS_CLAUDE),
        (TIER_ROUTING_DEEPSEEK, TIER_ROUTING_ANTHROPIC),
    )

    assert config.missing_credentials() == ()


# ── The env actually reaches the subprocess ─────────────────────────────────


def test_run_agent_hands_the_env_to_the_subprocess(monkeypatch, tmp_path):
    """Everything above is inert if `run_agent` lets the child inherit the
    parent environment instead. This is the wire."""
    from orchestrator import agent as agent_module

    captured = {}

    class _FakePopen:
        def __init__(self, argv, **kwargs):
            captured["env"] = kwargs.get("env")
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(agent_module.subprocess, "Popen", _FakePopen)

    agent_module.run_agent(
        ["claude"], cwd=tmp_path, prompt="hi", model="deepseek-v4-pro",
        budget_minutes=1, env={"ANTHROPIC_BASE_URL": "https://example.invalid"},
    )

    assert captured["env"] is not None, "the child inherited the parent environment"
    assert captured["env"]["ANTHROPIC_BASE_URL"] == "https://example.invalid"
