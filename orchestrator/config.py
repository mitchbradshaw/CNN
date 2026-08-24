"""Load and validate `config.toml`.

Every tuneable in the runner comes from here. A missing section is an error
rather than a default: a run that silently used a ceiling nobody chose is
exactly the 3am surprise this design exists to prevent.
"""

from __future__ import annotations

import hashlib
import os
import tomllib
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

#: One definition, re-exported. `Ceilings` used to be declared here *and* in
#: scheduler.py; the runtime passed this one to `schedule()` while the tests
#: exercised that one, so a field added to either was invisible to the other.
from .scheduler import Ceilings  # noqa: F401 — re-exported for callers

REQUIRED_SECTIONS = (
    "run", "ceilings", "budgets", "models", "paths",
    "agent", "suite", "retries", "review", "overlap", "circuit_breaker",
    "rate_limit",
)

#: Ticket-agent tier names in cheapest-first order.
#: `model_cap` in config.toml is one of these strings. A ticket whose model
#: tier is to the right of the cap is downgraded to the cap tier.
#: "review" and "fix" are not tier names — they bypass the cap entirely.
TIER_ORDER: tuple[str, ...] = ("haiku", "sonnet", "opus")


#: Model keys that are routed to a provider: the three ticket tiers plus the
#: two agents that are costed separately.
ROUTED_KEYS: tuple[str, ...] = TIER_ORDER + ("review", "fix")


class ConfigError(Exception):
    """`config.toml` is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class Provider:
    """Where one agent's model is served from.

    `model_prefix` is not decoration. DeepSeek's Anthropic-compatible endpoint
    **silently remaps an unrecognised model name onto `deepseek-v4-flash`**
    rather than rejecting it, so a config that sends `claude-sonnet-5` there
    gets a successful run of the wrong model under the right name -- invisible
    in the transcript, invisible in the cost column, invisible in review
    quality until someone reads the findings. Refusing the combination at load
    time is the only place it can be caught.
    """

    name: str
    base_url: str | None = None
    #: Where the secret is READ from -- an env var the operator exports.
    api_key_env: str | None = None
    #: Where the secret is WRITTEN to for the CLI. Not ANTHROPIC_API_KEY:
    #: a stored Claude subscription OAuth credential shadows that variable,
    #: so the CLI sends the subscription token to the third-party endpoint
    #: and gets a 401 naming a key nobody configured. Measured, not guessed.
    credential_env: str = "ANTHROPIC_AUTH_TOKEN"
    model_prefix: str | None = None


#: Used when `config.toml` predates the provider sections -- `--resume` has to
#: keep reading the config its run started under, and the test harness names
#: its stand-in models whatever it likes.
#:
#: Deliberately carries no `model_prefix`. The prefix guard protects a routing
#: decision; where nothing is routed there is nothing to protect, and enforcing
#: it would reject every config written before this section existed.
_IMPLICIT_PROVIDERS = {"anthropic": Provider(name="anthropic")}


@dataclass(frozen=True)
class Paths:
    repo_root: Path
    tickets: Path
    runs: Path
    worktrees: Path
    claude_md: Path
    coding_standards: Path
    fixture_db: Path
    fixture_db_dest: str
    recordings: tuple[Path, ...]


@dataclass(frozen=True)
class AgentConfig:
    cli: tuple[str, ...]
    extra_args: tuple[str, ...]
    stall_minutes: int
    launch_stagger_seconds: float = 0.0
    #: `text` keeps the old behaviour and reports no cost. `stream-json` is what
    #: buys the `tokens` column the spec has always asked for, and it survives a
    #: kill: one JSON line per turn means a killed agent still leaves a
    #: transcript, where `json` leaves an empty file.
    output_format: str = "stream-json"
    #: A hard per-agent ceiling the CLI enforces on itself. 0 disables it.
    max_budget_usd: float = 0.0


@dataclass(frozen=True)
class SuiteConfig:
    command: tuple[str, ...]
    timeout_minutes: int


@dataclass(frozen=True)
class RetryConfig:
    infrastructure: int
    infrastructure_backoff_seconds: int
    stall: int


@dataclass(frozen=True)
class ReviewConfig:
    skill: str
    max_rounds: int
    blocking_severities: tuple[str, ...]
    followups_file: str
    timeout_minutes: int
    default_severity: str


@dataclass(frozen=True)
class OverlapConfig:
    include_private: bool
    ignore_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class CircuitBreakerConfig:
    consecutive_quarantines: int
    quarantine_fraction: float
    flaky_weight: float


@dataclass(frozen=True)
class RateLimitConfig:
    concurrent_signature: int
    fast_exit_seconds: int
    initial_backoff_seconds: int
    max_backoff_seconds: int
    #: The ceiling on a wait the *transcript asked for*, as opposed to one this
    #: module guessed at. `max_backoff_seconds` bounds the blind exponential
    #: backoff and stays small; a plan usage cap names its own reset time and
    #: that reset is hours away, so honouring it needs its own, larger bound.
    max_usage_wait_seconds: int = 6 * 3600
    #: Waking at the exact second the window is said to reopen races the reset.
    usage_reset_grace_seconds: int = 120


@dataclass(frozen=True)
class Config:
    source: Path
    config_hash: str
    base_branch: str
    branch_prefix: str
    ticket_branch_prefix: str
    wall_clock_stop: time
    ceilings: Ceilings
    budgets: dict[str, int]
    models: dict[str, str]
    paths: Paths
    agent: AgentConfig
    suite: SuiteConfig
    retries: RetryConfig
    review: ReviewConfig
    overlap: OverlapConfig
    circuit_breaker: CircuitBreakerConfig
    rate_limit: RateLimitConfig
    #: Defaulted so a config written before provider routing still loads.
    providers: dict = None
    providers_default: str = "anthropic"
    model_providers: dict = None

    def budget_minutes(self, size: str) -> int:
        try:
            return self.budgets[size.upper()]
        except KeyError:
            raise ConfigError(f"no budget configured for size {size!r}") from None

    def model_id(self, model: str) -> str:
        """Return the API model string for `model`, applying `model_cap` if set.

        `model` is either a ticket tier name ("haiku", "sonnet", "opus") or a
        special key ("review", "fix"). The cap only applies to tier names —
        review and fix are looked up directly so their explicit config values
        are always honoured.

        Cap semantics: if the requested tier sits above the cap in TIER_ORDER,
        the cap tier is used instead. "haiku" caps everything to haiku; "sonnet"
        caps opus→sonnet but leaves haiku and sonnet unchanged.
        """
        effective = model
        if model in TIER_ORDER:
            cap = self.models.get("model_cap")
            if cap and cap in TIER_ORDER:
                if TIER_ORDER.index(model) > TIER_ORDER.index(cap):
                    effective = cap
        try:
            return self.models[effective]
        except KeyError:
            raise ConfigError(f"no model id configured for {effective!r}") from None

    def _effective_key(self, model: str) -> str:
        """The key whose model actually runs, after `model_cap`.

        Provider lookup has to apply the same cap `model_id` does, or a capped
        opus ticket would be handed the opus provider while running the sonnet
        model.
        """
        if model in TIER_ORDER:
            cap = self.models.get("model_cap")
            if cap and cap in TIER_ORDER and TIER_ORDER.index(model) > TIER_ORDER.index(cap):
                return cap
        return model

    def provider_for(self, model: str) -> Provider:
        """The provider serving `model` -- a tier name, "review", or "fix"."""
        providers = self.providers or _IMPLICIT_PROVIDERS
        mapping = self.model_providers or {}
        name = mapping.get(self._effective_key(model), self.providers_default)
        try:
            return providers[name]
        except KeyError:
            raise ConfigError(f"no provider configured named {name!r}") from None

    def agent_env(self, model: str) -> dict:
        """The full environment for one agent's CLI process.

        A complete mapping rather than a set of overrides, because the decisive
        case is *removal*: an `ANTHROPIC_BASE_URL` exported in the operator's
        shell is inherited by every child, so the Claude-backed agents have to
        clear it rather than merely decline to set it. Leaving it would send
        the reviewer to the same cheap endpoint as the ticket agent, and the
        only symptom would be worse findings.
        """
        provider = self.provider_for(model)
        env = dict(os.environ)
        # Both variables select a provider, so both are cleared before either is
        # set. Leaving ANTHROPIC_AUTH_TOKEN in place would send the DeepSeek key
        # to Anthropic on the very next agent; leaving ANTHROPIC_BASE_URL would
        # send the reviewer to DeepSeek. ANTHROPIC_API_KEY is deliberately left
        # alone -- an operator who authenticates Claude that way still can.
        env.pop("ANTHROPIC_BASE_URL", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        if provider.base_url:
            env["ANTHROPIC_BASE_URL"] = provider.base_url
        if provider.api_key_env:
            key = os.environ.get(provider.api_key_env)
            # An empty value is worse than an absent one: it reads as an
            # authentication failure rather than a missing configuration.
            if key:
                env[provider.credential_env] = key
        return env

    def missing_credentials(self) -> tuple:
        """Env vars named by providers actually in use, but not set.

        Checked at startup because the alternative is discovering it per agent,
        forty minutes in, as an exit code that looks like a stalled ticket.
        """
        seen, missing = set(), []
        for key in ROUTED_KEYS:
            provider = self.provider_for(key)
            if provider.name in seen:
                continue
            seen.add(provider.name)
            if provider.api_key_env and not os.environ.get(provider.api_key_env):
                missing.append(provider.api_key_env)
        return tuple(missing)

    def wall_clock_stop_at(self, started: datetime) -> datetime:
        """The next occurrence of the configured stop time, at or after `started`."""
        candidate = datetime.combine(started.date(), self.wall_clock_stop,
                                     tzinfo=started.tzinfo)
        if candidate <= started:
            candidate += timedelta(days=1)
        return candidate


def _require(data: dict, section: str, key: str, source: Path):
    try:
        return data[section][key]
    except KeyError:
        raise ConfigError(f"{source}: missing `{section}.{key}`") from None


def _parse_time(raw: str, source: Path) -> time:
    try:
        hour, _, minute = raw.partition(":")
        return time(int(hour), int(minute))
    except (ValueError, TypeError):
        raise ConfigError(f"{source}: `run.wall_clock_stop` must be HH:MM, got {raw!r}") from None


def load_config(path: Path | str, *, repo_root: Path | str) -> Config:
    path = Path(path)
    repo_root = Path(repo_root).resolve()
    if not path.is_file():
        raise ConfigError(f"{path}: no such config file")

    raw_bytes = path.read_bytes()
    try:
        data = tomllib.loads(raw_bytes.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from None

    missing = [s for s in REQUIRED_SECTIONS if s not in data]
    if missing:
        raise ConfigError(f"{path}: missing section(s) {missing}")

    budgets = {str(k).upper(): int(v) for k, v in data["budgets"].items()}
    for size in ("S", "M", "L"):
        if size not in budgets:
            raise ConfigError(f"{path}: `budgets` has no entry for size {size!r}")

    # Validate model_cap if present.
    models_raw = dict(data["models"])
    cap = models_raw.get("model_cap")
    if cap is not None and cap not in TIER_ORDER:
        raise ConfigError(
            f"{path}: `models.model_cap` must be one of {list(TIER_ORDER)}, got {cap!r}"
        )

    # ── Provider routing ────────────────────────────────────────────────
    providers = {
        name: Provider(
            name=name,
            base_url=block.get("base_url"),
            api_key_env=block.get("api_key_env"),
            credential_env=block.get("credential_env", "ANTHROPIC_AUTH_TOKEN"),
            model_prefix=block.get("model_prefix"),
        )
        for name, block in (data.get("providers") or {}).items()
    } or dict(_IMPLICIT_PROVIDERS)

    routing_raw = dict(data.get("model_providers") or {})
    providers_default = routing_raw.pop("default", "anthropic")
    if providers_default not in providers:
        raise ConfigError(
            f"{path}: `model_providers.default` names {providers_default!r}, "
            f"which is not one of {sorted(providers)}"
        )
    for key, name in routing_raw.items():
        if name not in providers:
            raise ConfigError(
                f"{path}: `model_providers.{key}` names provider {name!r}, "
                f"which is not one of {sorted(providers)}"
            )

    # A model must match its provider's prefix. See `Provider.model_prefix`:
    # DeepSeek accepts an unknown name and silently serves deepseek-v4-flash,
    # so this mismatch has no downstream symptom at all.
    for key, model in models_raw.items():
        if key == "model_cap":
            continue
        provider = providers[routing_raw.get(key, providers_default)]
        if provider.model_prefix and not str(model).startswith(provider.model_prefix):
            raise ConfigError(
                f"{path}: `models.{key}` is {model!r} but it is routed to provider "
                f"{provider.name!r}, which serves models starting {provider.model_prefix!r}. "
                f"{provider.name} would accept this and silently serve a different "
                f"model, so it is refused here instead."
            )

    p = data["paths"]

    def resolved(key: str) -> Path:
        return (repo_root / _require(data, "paths", key, path)).resolve()

    paths = Paths(
        repo_root=repo_root,
        tickets=resolved("tickets"),
        runs=resolved("runs"),
        worktrees=resolved("worktrees"),
        claude_md=resolved("claude_md"),
        coding_standards=resolved("coding_standards"),
        fixture_db=resolved("fixture_db"),
        fixture_db_dest=str(_require(data, "paths", "fixture_db_dest", path)),
        recordings=tuple((repo_root / r).resolve() for r in p.get("recordings", [])),
    )

    return Config(
        source=path,
        config_hash="sha256:" + hashlib.sha256(raw_bytes).hexdigest(),
        base_branch=_require(data, "run", "base_branch", path),
        branch_prefix=_require(data, "run", "branch_prefix", path),
        ticket_branch_prefix=_require(data, "run", "ticket_branch_prefix", path),
        wall_clock_stop=_parse_time(_require(data, "run", "wall_clock_stop", path), path),
        ceilings=Ceilings(
            concurrent=int(_require(data, "ceilings", "concurrent", path)),
            opus=int(_require(data, "ceilings", "opus", path)),
            # So the opus sub-ceiling throttles opus spend rather than opus
            # *labels*: under a cap these tickets never launch on opus.
            capped_tier=models_raw.get("model_cap"),
        ),
        budgets=budgets,
        models=models_raw,
        paths=paths,
        agent=AgentConfig(
            cli=tuple(_require(data, "agent", "cli", path)),
            extra_args=tuple(data["agent"].get("extra_args", [])),
            stall_minutes=int(_require(data, "agent", "stall_minutes", path)),
            launch_stagger_seconds=float(data["agent"].get("launch_stagger_seconds", 0.0)),
            # Defaulted rather than required: these keys arrived after five runs
            # had already been recorded, and `--resume` must still be able to
            # read the config those runs started under.
            output_format=str(data["agent"].get("output_format", "stream-json")),
            max_budget_usd=float(data["agent"].get("max_budget_usd", 0.0) or 0.0),
        ),
        suite=SuiteConfig(
            command=tuple(_require(data, "suite", "command", path)),
            timeout_minutes=int(_require(data, "suite", "timeout_minutes", path)),
        ),
        retries=RetryConfig(
            infrastructure=int(_require(data, "retries", "infrastructure", path)),
            infrastructure_backoff_seconds=int(
                _require(data, "retries", "infrastructure_backoff_seconds", path)),
            stall=int(_require(data, "retries", "stall", path)),
        ),
        review=ReviewConfig(
            skill=_require(data, "review", "skill", path),
            max_rounds=int(_require(data, "review", "max_rounds", path)),
            blocking_severities=tuple(_require(data, "review", "blocking_severities", path)),
            followups_file=_require(data, "review", "followups_file", path),
            timeout_minutes=int(_require(data, "review", "timeout_minutes", path)),
            default_severity=_require(data, "review", "default_severity", path),
        ),
        overlap=OverlapConfig(
            include_private=bool(_require(data, "overlap", "include_private", path)),
            ignore_paths=tuple(data["overlap"].get("ignore_paths", [])),
        ),
        providers=providers,
        providers_default=providers_default,
        model_providers=routing_raw,
        circuit_breaker=CircuitBreakerConfig(
            consecutive_quarantines=int(
                _require(data, "circuit_breaker", "consecutive_quarantines", path)),
            quarantine_fraction=float(
                _require(data, "circuit_breaker", "quarantine_fraction", path)),
            flaky_weight=float(_require(data, "circuit_breaker", "flaky_weight", path)),
        ),
        rate_limit=RateLimitConfig(
            concurrent_signature=int(_require(data, "rate_limit", "concurrent_signature", path)),
            fast_exit_seconds=int(_require(data, "rate_limit", "fast_exit_seconds", path)),
            initial_backoff_seconds=int(
                _require(data, "rate_limit", "initial_backoff_seconds", path)),
            max_backoff_seconds=int(_require(data, "rate_limit", "max_backoff_seconds", path)),
            max_usage_wait_seconds=int(
                data["rate_limit"].get("max_usage_wait_seconds", 6 * 3600)),
            usage_reset_grace_seconds=int(
                data["rate_limit"].get("usage_reset_grace_seconds", 120)),
        ),
    )
