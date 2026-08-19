"""Load and validate `config.toml`.

Every tuneable in the runner comes from here. A missing section is an error
rather than a default: a run that silently used a ceiling nobody chose is
exactly the 3am surprise this design exists to prevent.
"""

from __future__ import annotations

import hashlib
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


class ConfigError(Exception):
    """`config.toml` is missing, malformed, or internally inconsistent."""


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
