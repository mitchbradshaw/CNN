"""
workspaces/__init__.py
======================
The registration point for workspace content.

The shell in `UI/viewer/layout.py` is frozen. Eight tickets mount into it, and
if each one edited the assembly they would each conflict with the other seven.
So the shell asks this module what belongs in a workspace instead of naming it,
and a ticket adding a surface registers it here and never touches the shell.

Registration is by *factory*, not by built pane. A pane belongs to one
`ViewerApp`; this registry is module state and outlives every instance of it,
so holding built panes would hand a second app the first app's widgets --
which in a Panel process means two documents sharing one set of models. The
factory takes the app and is called once per app, at layout time.

A workspace with one section renders that section directly; with several it
renders sub-tabs; with none it renders a placeholder saying so. The placeholder
matters: a workspace that renders `None` is the silently-blank-pane failure
this codebase has hit twice, and it looks identical to a workspace that is
merely empty.
"""

import panel as pn

from UI.workspaces.analyse.compare import CompareSurface
from UI.workspaces.analyse.export import RunGroupExporter
from UI.workspaces.builtins import BUILTIN_SECTIONS

#: The four workspaces, in the order the shell presents them. Admin is a group
#: rather than a workspace and is assembled by the shell, so it is not here.
WORKSPACES = ("Explore", "Analyse", "Review", "Library")

_EMPTY_NOTICE = (
    "### {workspace}\n\n"
    "*Nothing is mounted here yet.*"
)

#: `{workspace: [(label, factory), ...]}`, insertion-ordered.
_REGISTRY = {}

#: `{workspace: factory}` — a persistent sidebar rendered to the LEFT of a
#: workspace's section tabs (ticket 34: Analyse's run-history sidebar).
#: Factored out of the section registry because a sidebar is not a section:
#: it has no sub-tab, it is always visible within the workspace, and it is
#: never a duplicate of a tab the user could have selected.
_SIDEBARS = {}


class UnknownWorkspace(KeyError):
    """Raised for a workspace name that is not one of `WORKSPACES`.

    A typo would otherwise register content into a workspace nobody renders,
    and the only symptom would be a surface that never appears.
    """


def register(workspace, label, factory):
    """Mount `factory` into `workspace` under `label`.

    `factory` is called as `factory(app)` at layout time and must return a
    Panel object -- never `None`.
    """
    if workspace not in WORKSPACES:
        raise UnknownWorkspace(
            f"{workspace!r} is not a workspace; expected one of {list(WORKSPACES)}"
        )
    sections_ = _REGISTRY.setdefault(workspace, [])
    if any(existing == label for existing, _ in sections_):
        raise ValueError(
            f"{workspace!r} already has a section labelled {label!r} -- two tickets "
            f"have registered the same surface, which is a merge collision rather "
            f"than a second surface"
        )
    sections_.append((label, factory))


def sections(workspace):
    """The `(label, factory)` pairs registered into `workspace`, in order."""
    if workspace not in WORKSPACES:
        raise UnknownWorkspace(
            f"{workspace!r} is not a workspace; expected one of {list(WORKSPACES)}"
        )
    return tuple(_REGISTRY.get(workspace, ()))


def register_sidebar(workspace, factory):
    """Mount `factory` as a persistent sidebar for `workspace`.

    `factory(app)` is called at layout time and must return a Panel object.
    A sidebar is rendered to the left of the workspace's section content
    (tabs, single pane, or placeholder) and is never itself a section.
    """
    if workspace not in WORKSPACES:
        raise UnknownWorkspace(
            f"{workspace!r} is not a workspace; expected one of {list(WORKSPACES)}"
        )
    if workspace in _SIDEBARS:
        raise ValueError(
            f"{workspace!r} already has a sidebar -- two tickets have "
            f"registered one, which is a merge collision"
        )
    _SIDEBARS[workspace] = factory


def build(workspace, app, base=None):
    """Return the pane for `workspace`, built against `app`.

    `base` is content the shell owns and always shows first -- Explore passes
    the viewer that way, so a ticket registering into Explore adds below it
    rather than replacing it.

    A workspace with a registered sidebar renders `pn.Row(sidebar, content)`,
    so the sidebar is always visible alongside the workspace's sections.
    """
    registered = sections(workspace)
    built = [factory(app) for _, factory in registered]

    if base is not None:
        if not built:
            content = base
        else:
            content = pn.Column(base, *built, sizing_mode="stretch_width")
    elif not built:
        content = pn.pane.Markdown(_EMPTY_NOTICE.format(workspace=workspace))
    elif len(built) == 1:
        content = built[0]
    else:
        content = pn.Tabs(
            *((label, pane) for (label, _), pane in zip(registered, built)),
            sizing_mode="stretch_width",
        )

    sidebar_factory = _SIDEBARS.get(workspace)
    if sidebar_factory is not None:
        return pn.Row(sidebar_factory(app), content, sizing_mode="stretch_width")
    return content


def reset():
    """Drop every registration and re-seed the pre-split surfaces.

    For tests, which would otherwise leak one test's registrations into the
    next -- and for them the leak is invisible, because an extra section only
    ever adds a tab.
    """
    _REGISTRY.clear()
    _SIDEBARS.clear()
    for workspace, label, factory in BUILTIN_SECTIONS:
        register(workspace, label, factory)
    register("Analyse", "Compare", lambda app: CompareSurface(app).layout())
    register("Analyse", "Export run group",
             lambda app: RunGroupExporter(app).layout())
    # Ticket 34: run history is Analyse's sidebar, not a section.
    register_sidebar("Analyse", lambda app: app.run_history.layout())


reset()
