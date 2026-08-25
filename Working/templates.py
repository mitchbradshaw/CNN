"""
templates.py
==============
Saved chains with recording and span stripped (ticket 47). A template is a
named list of steps; the step shape mirrors a recipe step, except every
`library_exemplar` side-input binding declares how it should behave when the
template is applied:

    {"source_kind": "library_exemplar", "mode": "carry",
     "source_file": ..., "channel": ..., "start_idx": ..., "end_idx": ...}
    {"source_kind": "library_exemplar", "mode": "rebind"}

`carry` means the exemplar travels with the template — "reapply this exact
search". The binding is stored by content (source file, channel, sample
range) and never by local database id, so it resolves on another machine.
`rebind` means the exemplar is chosen fresh on apply — "reapply this method".

Applying a template asks for a recording, a span and any rebinds, then builds
an ordinary recipe through `Working.recipes.make_recipe`, so the result is
validated exactly like a hand-built recipe and runs through the normal
executor.

No UI imports — cluster-safe and headless-test-safe, same as
`Working.recipes` and `Working.execution`.
"""

import json

from Working.database import runs as R
from Working.recipes import make_recipe

TEMPLATE_VERSION = 1
CARRY = "carry"
REBIND = "rebind"
TEMPLATE_MODES = (CARRY, REBIND)


def _library_exemplar_mode(step_index, side_name, binding, modes):
    mode = modes.get((step_index, side_name))
    if mode not in TEMPLATE_MODES:
        raise ValueError(
            f"Step {step_index}: side-input {side_name!r} is a library_exemplar; "
            f"choose modes[({step_index}, {side_name!r})] = 'carry' or 'rebind'."
        )
    return mode


def template_from_recipe(recipe, name, modes=None):
    """Build a template dict from a recipe, stripping recording and span.

    Parameters
    ----------
    recipe : dict
        A recipe as built by `Working.recipes.make_recipe`.
    name : str
        Template name.
    modes : dict, optional
        Mapping `(step_index, side_input_name)` -> `"carry"` | `"rebind"` for
        every `library_exemplar` binding. `root_signal` and `earlier_step`
        bindings are always structural and travel with the template.
    """
    modes = dict(modes or {})
    steps = []
    for i, step in enumerate(recipe["steps"]):
        side_inputs = {}
        for side_name, binding in (step.get("side_inputs") or {}).items():
            source_kind = binding.get("source_kind")
            if source_kind == "root_signal":
                side_inputs[side_name] = {"source_kind": "root_signal", "mode": CARRY}
            elif source_kind == "earlier_step":
                side_inputs[side_name] = {
                    "source_kind": "earlier_step",
                    "step_index": int(binding["step_index"]),
                    "mode": CARRY,
                }
            elif source_kind == "library_exemplar":
                mode = _library_exemplar_mode(i, side_name, binding, modes)
                if mode == CARRY:
                    side_inputs[side_name] = {
                        "source_kind": "library_exemplar",
                        "mode": CARRY,
                        "source_file": str(binding["source_file"]),
                        "channel": int(binding["channel"]),
                        "start_idx": int(binding["start_idx"]),
                        "end_idx": int(binding["end_idx"]),
                    }
                else:
                    side_inputs[side_name] = {
                        "source_kind": "library_exemplar",
                        "mode": REBIND,
                    }
            else:
                raise ValueError(
                    f"Step {i}: side-input {side_name!r} has unknown "
                    f"source_kind {source_kind!r}."
                )
        steps.append({
            "stage": step["stage"],
            "algorithm": step["algorithm"],
            "params": dict(step.get("params") or {}),
            "side_inputs": side_inputs,
        })
    return {"name": str(name), "steps": steps}


def template_to_json(template):
    """Serialize a template to portable JSON. Carried exemplars are already
    stored by content, so no local database id can leak into the output."""
    return json.dumps(
        {
            "template_version": TEMPLATE_VERSION,
            "name": template["name"],
            "steps": template["steps"],
        },
        indent=2,
        sort_keys=True,
    )


def template_from_json(text):
    """Parse JSON produced by `template_to_json` back into a template dict."""
    data = json.loads(text)
    if data.get("template_version") != TEMPLATE_VERSION:
        raise ValueError(
            f"Unsupported template_version={data.get('template_version')!r}; "
            f"this build understands version {TEMPLATE_VERSION}."
        )
    name = data.get("name")
    steps = data.get("steps")
    if not isinstance(name, str) or not name:
        raise ValueError("Template JSON must carry a non-empty 'name'.")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Template JSON must carry a non-empty 'steps' list.")
    return {"name": name, "steps": steps}


def import_template(conn, text):
    """Parse and persist a template exported by `template_to_json`.

    Returns the saved template as `{"id": int, "name": str, "steps": list}`.
    """
    template = template_from_json(text)
    template_id = R.save_template(conn, template["name"], template["steps"])
    return {"id": template_id, "name": template["name"], "steps": template["steps"]}


def _carried_library_exemplar(conn, binding):
    """A `carry` library_exemplar binding as an ordinary recipe binding.

    The recipe still needs an `entry_id` because `make_recipe`'s
    `library_exemplar` normalisation requires one, but the value is only a
    convenience pointer: recipe hashing strips it and resolution uses the
    content fields. When the local database has a motif entry for the carried
    content, its id is used; otherwise 0 keeps the recipe well-formed.
    """
    entry_id = 0
    if conn is not None:
        local_id = R.find_motif_entry_id_for_content(
            conn,
            binding["source_file"],
            binding["channel"],
            binding["start_idx"],
            binding["end_idx"],
        )
        if local_id is not None:
            entry_id = local_id
    return {
        "source_kind": "library_exemplar",
        "entry_id": entry_id,
        "source_file": binding["source_file"],
        "channel": binding["channel"],
        "start_idx": binding["start_idx"],
        "end_idx": binding["end_idx"],
    }


def apply_template(conn, template, recording_id, span=None, rebinds=None):
    """Construct an ordinary recipe from a template.

    Parameters
    ----------
    conn : sqlite3.Connection
        Used to resolve a carried exemplar's local `entry_id` by content.
        May be None, in which case carried bindings fall back to `entry_id=0`
        (still valid, because resolution and hashing are content-based).
    template : dict
        A template dict as returned by `template_from_recipe`,
        `template_from_json` or `import_template`.
    recording_id : int
        The recording this application will run against.
    span : (int, int), optional
        As in `Working.recipes.make_recipe`.
    rebinds : dict, optional
        Mapping `(step_index, side_input_name)` -> binding for every binding
        declared `rebind`. Each value is a normal recipe-side-input binding.
    """
    rebinds = dict(rebinds or {})
    recipe_steps = []
    for i, step in enumerate(template["steps"]):
        side_inputs = {}
        for name, binding in (step.get("side_inputs") or {}).items():
            source_kind = binding.get("source_kind")
            if source_kind == "root_signal":
                side_inputs[name] = {"source_kind": "root_signal"}
            elif source_kind == "earlier_step":
                side_inputs[name] = {
                    "source_kind": "earlier_step",
                    "step_index": int(binding["step_index"]),
                }
            elif source_kind == "library_exemplar":
                mode = binding.get("mode")
                if mode == CARRY:
                    side_inputs[name] = _carried_library_exemplar(conn, binding)
                elif mode == REBIND:
                    key = (i, name)
                    if key not in rebinds:
                        raise ValueError(
                            f"Template apply: side-input {name!r} on step {i} is "
                            f"declared 'rebind'; supply rebinds[({i}, {name!r})]."
                        )
                    side_inputs[name] = dict(rebinds[key])
                else:
                    raise ValueError(
                        f"Template apply: side-input {name!r} on step {i} has "
                        f"unknown mode {mode!r}; expected 'carry' or 'rebind'."
                    )
            else:
                raise ValueError(
                    f"Template apply: side-input {name!r} on step {i} has "
                    f"unknown source_kind {source_kind!r}."
                )
        recipe_steps.append({
            "stage": step["stage"],
            "algorithm": step["algorithm"],
            "params": dict(step.get("params") or {}),
            "side_inputs": side_inputs,
        })
    return make_recipe(recording_id, recipe_steps, span=span)
