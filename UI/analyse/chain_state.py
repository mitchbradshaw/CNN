"""
chain_state.py
================
Headless representation of an analysis chain under construction — steps,
ordering, parameters, side-input bindings, and which blocks may be added
next. `UI.analyse.chain_render` (ticket 29) is the only thing that renders
this; everything here is testable without a browser and imports no UI
library.

`ChainState` does not compute type compatibility itself — every "can this
block go here" question is answered by `Working.chain_validation` (ticket
13), the one function the rest of the system agrees to use. It does not
invent a second recipe serialiser either: `to_recipe`/`from_recipe` go
through `Working.recipes.make_recipe`, the existing seam.

Step shape
----------
Each step is a plain dict::

    {
        "stage": <str>,       # one of Working.recipes.STAGES
        "algorithm": <str>,
        "params": <dict>,
        "side_inputs": {
            "<name>": {"source_kind": "root_signal"} |
                      {"source_kind": "earlier_step", "step_index": <int>} |
                      {"source_kind": "library_exemplar", ...},
            ...
        },
    }

`side_inputs` is composition-time bookkeeping local to this model — the
recipe schema (`Working.recipes.make_recipe`) does not yet carry bindings
(that lands with the side-input ticket), so `to_recipe`/`from_recipe` only
round-trip `stage`/`algorithm`/`params`.
"""

from Adapters.registry import discover_adapters, get_adapter, list_adapters
from Working.chain_validation import ROOT_SIGNAL_KIND, check_step_compatibility, validate_recipe_steps
from Working.recipes import make_recipe


class ChainStateError(ValueError):
    """Raised when an operation would silently produce an invalid chain —
    e.g. removing a step a later step's side-input is bound to, with no
    safe rebind available."""


class ChainState:
    def __init__(self, recording_id, span=None, steps=None):
        discover_adapters()
        self.recording_id = recording_id
        self.span = span
        self.steps = steps if steps is not None else []
        self.is_valid = True
        self.invalid_reason = ""
        self._revalidate()

    # ── construction from a recipe ──────────────────────────────────────

    @classmethod
    def from_recipe(cls, recipe):
        """The reverse of `to_recipe`: a fresh `ChainState` from a recipe
        dict. Side-input bindings are not part of the recipe schema yet, so
        every step comes back with an empty `side_inputs`."""
        steps = [
            {
                "stage": step["stage"],
                "algorithm": step["algorithm"],
                "params": dict(step["params"]),
                "side_inputs": {},
            }
            for step in recipe["steps"]
        ]
        span = tuple(recipe["span"]) if recipe["span"] is not None else None
        return cls(recording_id=recipe["recording_id"], span=span, steps=steps)

    def to_recipe(self):
        """A well-formed recipe via `Working.recipes.make_recipe` — raises
        `ValueError` exactly when `make_recipe` would (e.g. an invalid
        chain, or no steps)."""
        plain_steps = [
            {"stage": s["stage"], "algorithm": s["algorithm"], "params": s["params"]}
            for s in self.steps
        ]
        return make_recipe(self.recording_id, plain_steps, self.span)

    # ── editing: add, remove, reorder — each revalidates ────────────────

    def add_step(self, stage, algorithm, params=None, side_inputs=None, index=None):
        """Insert a new step at `index` (default: append). Revalidates the
        chain afterwards; does not raise on an incompatible addition — the
        caller can check `is_valid`/`invalid_reason`, or consult
        `available_blocks()` beforehand to avoid it."""
        step = {
            "stage": stage,
            "algorithm": algorithm,
            "params": dict(params or {}),
            "side_inputs": dict(side_inputs or {}),
        }
        if index is None:
            self.steps.append(step)
        else:
            self.steps.insert(index, step)
        self._revalidate()

    def remove_step(self, index, force=False):
        """Remove the step at `index`.

        Any later step's side-input bound to an earlier step (source_kind
        `"earlier_step"`) that pointed past `index` is rebound to its new
        position — removal shifts everything after it down by one. A
        binding pointing exactly at the step being removed cannot be
        silently rebound: by default this raises `ChainStateError` naming
        the break, leaving the chain unchanged; with `force=True` the
        binding is cleared instead.
        """
        if not 0 <= index < len(self.steps):
            raise IndexError(f"No step at index {index}")

        broken = self._bindings_bound_to(index)
        if broken and not force:
            named = ", ".join(f"step {i} side-input '{name}'" for i, name in broken)
            raise ChainStateError(
                f"Removing step {index} ('{self.steps[index]['algorithm']}') would break "
                f"bound side-input(s): {named}. Pass force=True to clear them."
            )

        del self.steps[index]
        for step in self.steps:
            for name, binding in list(step["side_inputs"].items()):
                if binding.get("source_kind") != "earlier_step":
                    continue
                step_index = binding["step_index"]
                if step_index == index:
                    del step["side_inputs"][name]
                elif step_index > index:
                    binding["step_index"] = step_index - 1
        self._revalidate()

    def reorder(self, new_order):
        """Reorder steps according to `new_order`, a permutation of the
        current step indices (`new_order[i]` is the old index of the step
        that ends up at position `i`). `"earlier_step"` bindings are
        rebound to follow their target step to its new position."""
        if sorted(new_order) != list(range(len(self.steps))):
            raise ValueError(
                f"new_order must be a permutation of range({len(self.steps)}), got {new_order}"
            )
        old_to_new = {old: new for new, old in enumerate(new_order)}
        self.steps = [self.steps[old_index] for old_index in new_order]
        for step in self.steps:
            for binding in step["side_inputs"].values():
                if binding.get("source_kind") == "earlier_step":
                    binding["step_index"] = old_to_new[binding["step_index"]]
        self._revalidate()

    # ── what can be added next ──────────────────────────────────────────

    def available_blocks(self):
        """Every registered block, with the `(bool, reason)` that
        `Working.chain_validation.check_step_compatibility` returns for
        feeding it from the current chain tail. Does not compute
        compatibility itself."""
        producing_kind = self._tail_kind()
        return [
            (block,) + check_step_compatibility(producing_kind, block)
            for block in list_adapters()
        ]

    # ── internals ────────────────────────────────────────────────────────

    def _tail_kind(self):
        if not self.steps:
            return ROOT_SIGNAL_KIND
        last = self.steps[-1]
        try:
            return get_adapter(f"{last['stage']}.{last['algorithm']}").output_kind
        except KeyError:
            return ROOT_SIGNAL_KIND

    def _revalidate(self):
        plain_steps = [
            {"stage": s["stage"], "algorithm": s["algorithm"], "params": s["params"]}
            for s in self.steps
        ]
        self.is_valid, self.invalid_reason = validate_recipe_steps(plain_steps)

    def _bindings_bound_to(self, index):
        """[(step_index, side_input_name), ...] for every side-input bound
        to `steps[index]`'s output via `source_kind="earlier_step"`."""
        found = []
        for i, step in enumerate(self.steps):
            if i == index:
                continue
            for name, binding in step["side_inputs"].items():
                if binding.get("source_kind") == "earlier_step" and binding.get("step_index") == index:
                    found.append((i, name))
        return found
