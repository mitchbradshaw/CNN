"""
base.py
========
Shared types for the adapter registry. An adapter is the ONLY place that
knows a given `Working/` function's real signature — everything else
(the UI run panel, `execute_recipe`, SLURM job generation in the next
part) talks to adapters through this uniform shape, never to the wrapped
function directly.

Adding an algorithm later means writing one new adapter file (see
`Adapters/README.md`-style docstrings at the top of any existing adapter
for the pattern) and registering it — zero changes anywhere else.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import Working.types as _interchange_types

# The interchange types that gate which pipeline blocks may connect. The list
# is owned by `Working.types` (ticket 01; see `docs/PIPELINE_PRD.md` "Type
# system") and read from there rather than repeated here, so the adapter
# vocabulary cannot drift from the types it names. Lower-cased to match the
# existing string-vocabulary convention below.
TYPE_KINDS = tuple(name.lower() for name in _interchange_types.__all__)

# What a side input may be bound to at chain-composition time (PRD "Chain
# shape"): the chain's own root signal, an earlier step's output, or a
# library exemplar.
SOURCE_KINDS = ("root_signal", "earlier_step", "library_exemplar")

# `output_kind` must be one of the seven interchange types (see
# `Working.types`). There is no separate legacy vocabulary.
OUTPUT_KINDS = TYPE_KINDS


@dataclass
class ParamSpec:
    """One tunable parameter, enough to auto-generate a UI control from.

    Attributes
    ----------
    name : str
        Keyword name, passed to the adapter's `run` function.
    type : type
        int, float, str, or bool. Drives which widget the UI builds.
    default : Any
    description : str
        Short, shown as a tooltip/help text next to the generated control.
    choices : list, optional
        For str params — a dropdown instead of free text.
    min, max : float, optional
        For int/float params — a bounded slider/spinner instead of a
        bare text box. None means unbounded on that side.
    """

    name: str
    type: type
    default: Any
    description: str = ""
    choices: Optional[list] = None
    min: Optional[float] = None
    max: Optional[float] = None


@dataclass
class SideInputSpec:
    """One additional typed input a step may declare, beyond its primary
    input (see `AdapterSpec.input_kind`) — e.g. a clustering adapter's
    primary input is a `WindowSet`, but it may also declare a `signal`
    side input bound to a library exemplar to cluster against. Binding a
    side input to an actual value happens at chain-composition time; this
    only declares what type is expected and what it may be bound to.

    Attributes
    ----------
    name : str
        Keyword name the adapter's `run` function receives the bound value
        under (mirrors `ParamSpec.name`).
    type_kind : str
        One of `TYPE_KINDS` — the interchange type this side input expects.
    sources : list[str]
        Non-empty subset of `SOURCE_KINDS` naming what this side input may
        be bound to at composition time.
    """

    name: str
    type_kind: str
    sources: list

    def __post_init__(self):
        if self.type_kind not in TYPE_KINDS:
            raise ValueError(
                f"Side-input '{self.name}': type_kind must be one of {TYPE_KINDS}, "
                f"got {self.type_kind!r}"
            )
        if not self.sources:
            raise ValueError(f"Side-input '{self.name}': sources must be non-empty")
        bad = [s for s in self.sources if s not in SOURCE_KINDS]
        if bad:
            raise ValueError(
                f"Side-input '{self.name}': sources must be a subset of {SOURCE_KINDS}, "
                f"got invalid {bad}"
            )


@dataclass
class AdapterResult:
    """Uniform output wrapper regardless of `output_kind`.

    Only the field(s) matching `output_kind` are populated; the others
    stay at their default. `meta` always carries at least `elapsed_s`
    (filled in by whoever calls `run`, not the adapter itself, so timing
    is measured uniformly rather than each adapter timing itself slightly
    differently).
    """

    output_kind: str
    x: Any = None            # 'signal': the processed array
    t: Any = None            # 'signal': matching timestamps
    intervals: Optional[list] = None   # legacy carrier: [(start, end[, score]), ...]
    encoding: Any = None     # 'encoding': array, string, or other value
    value: Any = None        # a typed object from `Working.types` (ticket 01)
    meta: dict = field(default_factory=dict)


@dataclass
class AdapterSpec:
    """Everything the rest of the system needs to know about one algorithm.

    Attributes
    ----------
    name : str
        Unique registry key, "<stage>.<short_name>", e.g. "preprocessing.lowpass".
    display_name : str
        Human-readable label for the UI.
    stage : str
        One of `Working.recipes.STAGES`.
    params : list[ParamSpec]
    run : callable(x, t, fs, **params) -> AdapterResult
        Always called with the full (x, t, fs) triple regardless of
        whether the underlying function needs all three — the adapter
        decides what to actually forward. This is the "map (x, t, params)
        onto the underlying function" the brief asks for; that mapping
        lives entirely inside `run`, nowhere else.
    output_kind : str
        One of the seven `TYPE_KINDS` (the contents of `OUTPUT_KINDS`). The
        legacy `intervals` output vocabulary is gone; `signal` and
        `encoding` survive as the type names they already coincided with.
    input_kind : str, optional
        One of `TYPE_KINDS`, or None meaning "root signal" — the primary
        input this step expects. Every existing adapter takes the raw
        (x, t, fs) signal, so None is the correct value for all of them and
        is also the default.
    side_inputs : list[SideInputSpec]
        Additional typed inputs beyond the primary one, e.g. a clustering
        step's library exemplar. Bound to an actual value at chain-
        composition time (PRD "Chain shape"); declared here only. Empty
        list (the default, and every existing adapter) means "no side
        inputs".
    estimate : callable(x, t, fs, **params) -> float, optional
        Predicted runtime in seconds for the span about to be analysed,
        used to warn before a long run. None (the default, and every
        existing adapter) means "counts as free".
    plot : callable(x, t, result, **params) -> matplotlib.figure.Figure, optional
        None if this algorithm has no natural single-run visualisation.
    max_span_samples : int, optional
        Declared, not enforced here — `Working.execution.execute_recipe`
        checks `len(x) <= max_span_samples` before calling `run` and
        refuses with a clear message otherwise. None means unbounded.
        Set this on any O(n^2)-or-worse encoding (e.g. Gramian/recurrence)
        so the guard is real and can't be forgotten per-call-site.
    description : str
        Longer description, shown in the run panel / adapter listing.
    recommend : callable(x, t, fs) -> dict, optional
        Suggested param VALUES for the span about to be analysed (2026-08,
        Part 2a) — e.g. "how many seconds per symbol" depends on how long
        the span is, so a fixed default is wrong for most spans. Returns a
        dict of {param_name: value} overriding `ParamSpec.default` for
        whichever params it wants to (a subset is fine). None means "no
        span-aware defaults" — every existing adapter keeps its plain
        static `ParamSpec.default`s.
    derive : callable(x, t, fs, params) -> list[(label, value, severity)], optional
        Read-only diagnostic rows to show BESIDE the parameter controls,
        recomputed live as the user edits them, without running anything —
        e.g. "Symbols produced: 256" from a "seconds per symbol" control a
        human can't otherwise picture the effect of. `severity` is one of
        `""`, `"warn"`, `"error"` for styling. Deliberately NOT part of
        `ParamSpec`: a `ParamSpec` means "a tunable input" and mixing a
        read-only readout into that list would make `validate_params`
        reject it as an "unknown param" (or, if given a matching name,
        silently accept it as tunable, which it isn't). None means no
        derived readout.
    persist : callable(conn, run_id, config_hash, recording, span_start, span_end, params, result) -> str | None, optional
        Opt-in hook for an 'encoding' step whose output should be written
        to disk and registered as an `artifacts(kind='encoding')` row
        automatically, with no separate UI action or import step —
        `Working.execution.execute_recipe` calls this (if set) right after
        a successful 'encoding' step and inserts the returned path via
        `Working.database.runs.insert_artifact`. None (the default, and
        every existing adapter) means "caching this output is a separate,
        explicit decision" per `execute_recipe`'s normal contract. Matrix
        profile sets this so a headless `run_recipe.py` invocation (e.g.
        an HPC job, MATRIX_PROFILE_UI_PROMPT.md §5) produces a browsable
        artifact on its own.
    """

    name: str
    display_name: str
    stage: str
    params: list
    run: Callable
    output_kind: str
    input_kind: Optional[str] = None
    side_inputs: list = field(default_factory=list)
    estimate: Optional[Callable] = None
    plot: Optional[Callable] = None
    max_span_samples: Optional[int] = None
    description: str = ""
    recommend: Optional[Callable] = None
    derive: Optional[Callable] = None
    persist: Optional[Callable] = None

    def __post_init__(self):
        if self.output_kind not in OUTPUT_KINDS:
            raise ValueError(
                f"Adapter '{self.name}': output_kind must be one of {OUTPUT_KINDS}, "
                f"got {self.output_kind!r}"
            )
        if self.input_kind is not None and self.input_kind not in TYPE_KINDS:
            raise ValueError(
                f"Adapter '{self.name}': input_kind must be one of {TYPE_KINDS} or None, "
                f"got {self.input_kind!r}"
            )

    def validate_params(self, raw_params=None):
        """Fill in defaults, coerce types, and check choices/range.

        Returns a fresh dict — never mutates `raw_params`. Raises
        ValueError on an unknown parameter name, a str outside `choices`,
        or a numeric value outside [min, max].
        """
        raw_params = raw_params or {}
        known = {p.name for p in self.params}
        unknown = set(raw_params) - known
        if unknown:
            raise ValueError(f"Adapter '{self.name}': unknown param(s) {sorted(unknown)}")

        out = {}
        for p in self.params:
            val = raw_params[p.name] if p.name in raw_params else p.default
            if p.type is bool:
                val = bool(val)
            elif p.type in (int, float):
                val = p.type(val)
                if p.min is not None and val < p.min:
                    raise ValueError(
                        f"Adapter '{self.name}': {p.name}={val} is below min {p.min}"
                    )
                if p.max is not None and val > p.max:
                    raise ValueError(
                        f"Adapter '{self.name}': {p.name}={val} is above max {p.max}"
                    )
            elif p.type is str:
                val = str(val)
            # choices applies regardless of type (e.g. an int enum like
            # max_order in {1, 2}), so it's checked once, after coercion.
            if p.choices is not None and val not in p.choices:
                raise ValueError(
                    f"Adapter '{self.name}': {p.name}={val!r} must be one of {p.choices}"
                )
            out[p.name] = val
        return out
