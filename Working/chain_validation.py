"""
chain_validation.py
=====================
One function that answers "can this output type feed this block, and if
not, why not" (PRD "Type checking"). It is consumed at two layers — at
composition, `Working.recipes.make_recipe` rejects an invalid chain before
it is ever hashed or run; at execution, `Working.execution.execute_recipe`
rejects one before the first step runs. Both callers go through
`validate_recipe_steps` below rather than inlining their own compatibility
check, so the two layers cannot drift apart.

The chain's root is always the recording's raw signal, so a step's
"producing type" starts as `ROOT_SIGNAL_KIND` and becomes each step's own
declared `output_kind` for the step after it. A block's declared
`input_kind=None` (see `Adapters.base.AdapterSpec`) means "wants the root
signal", and `ROOT_SIGNAL_KIND` is `"signal"` — the same string as the
`Signal` interchange type — so this module doesn't need a separate
legacy/typed mapping table.
"""

from Adapters.registry import discover_adapters, get_adapter

ROOT_SIGNAL_KIND = "signal"


def check_step_compatibility(producing_kind, block):
    """Can `producing_kind` (a string — the previous step's declared
    `output_kind`, or `ROOT_SIGNAL_KIND` for the chain's root) feed `block`
    (an `AdapterSpec`) as its primary input?

    Returns `(bool, str)`: whether it's compatible, and — when it isn't —
    a reason naming both `producing_kind` and what `block` expects, and
    stating what would close the gap, so a researcher can learn the type
    system from it rather than being told "incompatible".
    """
    expected_kind = block.input_kind or ROOT_SIGNAL_KIND
    if producing_kind == expected_kind:
        return True, ""
    return False, (
        f"'{block.name}' expects a '{expected_kind}' input, but the "
        f"previous step produces a '{producing_kind}'. Insert a step that "
        f"turns a '{producing_kind}' into a '{expected_kind}' before "
        f"'{block.name}', or reorder the chain so a '{expected_kind}'-"
        f"producing step feeds it directly."
    )


def validate_chain(specs):
    """Walk an ordered list of `AdapterSpec` as a chain would run them —
    starting from the chain's root signal — and check every step-to-step
    transition with `check_step_compatibility`.

    Returns `(bool, str)`: `(True, "")` if the whole chain validates, or
    the first incompatibility found otherwise.
    """
    producing_kind = ROOT_SIGNAL_KIND
    for spec in specs:
        ok, reason = check_step_compatibility(producing_kind, spec)
        if not ok:
            return False, reason
        producing_kind = spec.output_kind
    return True, ""


def validate_recipe_steps(steps):
    """`validate_chain`, but for a recipe's `steps` list (dicts with
    `stage`/`algorithm`, as built by `Working.recipes.make_recipe`) rather
    than a list of already-resolved specs — the one seam both `make_recipe`
    and `Working.execution.execute_recipe` call, per the ticket's rule that
    no caller may inline its own compatibility check.

    A step naming an algorithm the registry doesn't know can't be type-
    checked — that is a different failure (an unknown adapter), surfaced
    when something actually tries to resolve it — so validation stops at
    that point and treats the chain checked so far as valid.
    """
    discover_adapters()
    specs = []
    for step in steps:
        name = f"{step['stage']}.{step['algorithm']}"
        try:
            specs.append(get_adapter(name))
        except KeyError:
            break
    return validate_chain(specs)
