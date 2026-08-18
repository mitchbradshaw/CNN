"""
One auto-generated control per `ParamSpec`. Adding an algorithm is a new
file in `Adapters/` and no UI change at all, which is only true while this
stays driven entirely off the spec.
"""

import panel as pn


def _humanize_param_name(name):
    """"seconds_per_symbol" -> "Seconds per symbol" (Part 7, Part 3 item
    6) — short enough not to truncate mid-word; the long explanation
    moves to the widget's `description` tooltip instead of living in the
    label text itself."""
    return name.replace("_", " ").capitalize()


def _widget_for_param(p):
    """Build the auto-generated control for one ParamSpec. `description`
    (Part 7, Part 3 item 6) renders as a small hover-help icon next to a
    SHORT label, rather than the long explanation being crammed into the
    label text itself — the previous
    "seconds_per_symbol — Live when segment_mode='seconds_per_symbol'"
    labels truncated mid-word in the sidebar."""
    name = _humanize_param_name(p.name)
    if p.type is bool:
        # pn.widgets.Checkbox has no `description` param (unlike every
        # other widget type here) in this Panel version — the long
        # explanation, if any, stays appended to the label for booleans
        # only, since there's nowhere else to put it.
        return pn.widgets.Checkbox(name=f"{name} — {p.description}" if p.description else name, value=p.default)
    if p.choices is not None:
        return pn.widgets.Select(name=name, options=list(p.choices), value=p.default, description=p.description)
    if p.type is int:
        kwargs = {}
        if p.min is not None:
            kwargs["start"] = int(p.min)
        if p.max is not None:
            kwargs["end"] = int(p.max)
        return pn.widgets.IntInput(name=name, value=p.default, description=p.description, **kwargs)
    if p.type is float:
        kwargs = {}
        if p.min is not None:
            kwargs["start"] = float(p.min)
        if p.max is not None:
            kwargs["end"] = float(p.max)
        return pn.widgets.FloatInput(name=name, value=p.default, description=p.description, **kwargs)
    return pn.widgets.TextInput(name=name, value=str(p.default), description=p.description)
