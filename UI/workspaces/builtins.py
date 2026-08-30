"""
The surfaces that predate the four-workspace split.

`UI/viewer/layout.py` used to name these directly in its `pn.Tabs` call. They
are listed here instead so the shell has nothing ticket-specific left in it,
and so a later ticket moving one of them edits this table rather than the
frozen assembly.

Kept free of imports from `UI.workspaces` on purpose: the registry imports this
module to seed itself, and an import back the other way would close the loop.
The factories take the `ViewerApp` and read attributes off it, so they need no
imports at all.
"""

#: The Analyse section whose surface wants the full width — the sidebar
#: collapses to a ribbon while it is active (ticket 70). Named here, beside the
#: table that defines the label, because the sidebar keys its default off the
#: STRING: with the literal duplicated in both places, renaming the section
#: would silently stop the sidebar collapsing and no test would fail.
CHAIN_BUILDER_SECTION = "Chain builder"

#: `(workspace, label, factory)`, in the order they mount. The label is what a
#: workspace with more than one section shows on its sub-tab, so it is user-
#: facing text, not an identifier.
BUILTIN_SECTIONS = (
    # Analyse holds the run panel first so that `activate_workspace("Analyse",
    # "Run algorithm")` lands on it. Ticket 34 folded run history into Analyse
    # as a sidebar (registered via `workspaces.register_sidebar`), so it is no
    # longer a section here.
    ("Analyse", "Run algorithm", lambda app: app.run_panel.layout()),
    # Ticket 29: the chain builder. `ChainBuilder` is instantiated in
    # `UI/viewer/app.py`, same as `run_panel` above -- this table only ever
    # reads the attribute off `app`, per its own docstring.
    ("Analyse", CHAIN_BUILDER_SECTION, lambda app: app.chain_builder.layout()),
    ("Review", "Candidate queue", lambda app: app.review_surface.layout()),
    ("Library", "Motif browser", lambda app: app.motif_browser.layout()),
)
