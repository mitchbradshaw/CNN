"""
UI/workspaces/analyse/history.py
=================================
The run history browser (5e) — "the single biggest reason I'm building
this": a filterable table of every past run, letting you (a) see everything
tried on a given channel, (b) click a run and reload its exact chain into
the chain builder to re-run or tweak it, and (c) find the artifacts it
produced.

Moved here by ticket 34 (was `UI/run_history.py`) and folded into Analyse as
a sidebar: the standalone "Run history" tab is gone; this is now the sidebar
Analyse renders alongside its section tabs, and Reopen reconstructs the
run's recipe steps in the chain builder (PRD: "a history sidebar that can
reload a past chain").

Ticket 70 makes the sidebar collapsible. Collapsed it is a narrow ribbon with
a control to reopen; expanded it is a fixed width wide enough that the columns
that make history worth having — recipe and params — are the ones that are not
truncated, and the status filter is wide enough to show its selections. The
sidebar defaults to collapsed while the chain builder is the active Analyse
section, so the horizontally scrolling canvas does not fight the table for the
same pixels (PRD user stories 29–32).
"""

import json

import pandas as pd
import panel as pn

from Working.database import queries as q
from Working.database import runs as R
from Working.recipes import recipe_summary

TABLE_COLUMNS = ["id", "name", "source_file", "channel", "recipe", "params",
                  "span_start", "span_end", "duration_s", "status",
                  "detections", "artifacts", "started_at"]


class RunHistoryBrowser:
    #: Expanded width is fixed rather than fitted: column widths are decided in
    #: the browser, so "expands to fit the table" can only be "expands to a
    #: width the table fits in" (T70).
    EXPANDED_WIDTH = 780
    #: The collapsed ribbon: just wide enough for the reopen control.
    RIBBON_WIDTH = 44
    #: Explicit widths so the informative columns — recipe and params — are the
    #: ones that survive the expanded sidebar, and the columns that do get
    #: truncated are the ones nobody reads (T70).
    TABLE_WIDTHS = {
        "id": 50, "name": 110, "source_file": 110, "channel": 60,
        "recipe": 180, "params": 240, "span_start": 70, "span_end": 70,
        "duration_s": 70, "status": 90, "detections": 70, "artifacts": 70,
        "started_at": 110,
    }

    def __init__(self, app):
        self.app = app
        self.conn = app.conn

        self.collapsed = False

        self.filter_recording = pn.widgets.Select(
            name="Recording (source_file:channel)", options=[], width=240,
        )
        self.filter_status = pn.widgets.MultiChoice(
            name="Status", options=["running", "completed", "failed"], width=280,
        )
        self.refresh_button = pn.widgets.Button(name="Refresh", button_type="default")
        self.reopen_button = pn.widgets.Button(name="Reopen in builder", button_type="primary")
        self.status = pn.pane.Markdown("")
        self.artifacts_pane = pn.pane.Markdown("*Select a run to see its artifacts.*")

        self.table = pn.widgets.Tabulator(
            pd.DataFrame(columns=TABLE_COLUMNS), page_size=15, disabled=False,
            selectable=1, show_index=False, sizing_mode="stretch_width",
            layout="fit_columns", widths=self.TABLE_WIDTHS,
            editors={col: ("input" if col == "name" else None)
                     for col in TABLE_COLUMNS},
        )

        self.expand_button = pn.widgets.Button(
            name="☰", width=self.RIBBON_WIDTH, button_type="default",
        )
        self.expand_button.on_click(lambda _e: self._set_collapsed(False))
        self.collapse_button = pn.widgets.Button(
            name="« Collapse", width=90, button_type="default",
        )
        self.collapse_button.on_click(lambda _e: self._set_collapsed(True))

        self.sidebar = pn.Column(width=self.EXPANDED_WIDTH, styles={"overflow-y": "auto"})
        self._render()

        self.filter_recording.param.watch(lambda _e: self._refresh(), "value")
        self.filter_status.param.watch(lambda _e: self._refresh(), "value")
        self.refresh_button.on_click(lambda _e: self._refresh())
        self.reopen_button.on_click(self._on_reopen)
        self.table.param.watch(self._on_row_selected, "selection")
        self.table.on_edit(self._on_name_edited)

        self._refresh_recording_options()
        self._refresh()

    def _refresh_recording_options(self):
        recs = q.list_recordings(self.conn)
        options = {"(all recordings)": None}
        for r in recs:
            options[f"{r['source_file']}:CH{r['channel']:02d}"] = r["id"]
        self.filter_recording.options = options

    def _refresh(self):
        recording_id = self.filter_recording.value
        statuses = self.filter_status.value

        rows = R.list_runs(self.conn, recording_id=recording_id)
        if statuses:
            rows = [r for r in rows if r["status"] in statuses]

        records = []
        for run in rows:
            recording = q.get_recording_by_id(self.conn, run["recording_id"])
            config = R.get_config(self.conn, run["config_id"])
            recipe = json.loads(config["config_json"]) if config else {"steps": []}
            n_dets = len(R.list_detections(self.conn, run["id"]))
            n_arts = len(R.list_artifacts(self.conn, run["id"]))
            all_params = {s["algorithm"]: s["params"] for s in recipe.get("steps", [])}
            records.append({
                "id": run["id"],
                "name": run["name"],
                "source_file": recording["source_file"] if recording else "?",
                "channel": recording["channel"] if recording else "?",
                "recipe": recipe_summary(recipe) if recipe.get("steps") else "?",
                "params": json.dumps(all_params, separators=(",", ":")),
                "span_start": run["span_start"], "span_end": run["span_end"],
                "duration_s": run["duration_s"],
                "status": run["status"],
                "detections": n_dets,
                "artifacts": n_arts,
                "started_at": run["started_at"],
            })
        self.table.value = pd.DataFrame(records, columns=TABLE_COLUMNS)

    def _selected_run_id(self):
        df = self.table.value
        selected = self.table.selection
        if not selected:
            return None
        return int(df.iloc[selected[0]]["id"])

    def _on_row_selected(self, _event):
        run_id = self._selected_run_id()
        if run_id is None:
            self.artifacts_pane.object = "*Select a run to see its artifacts.*"
            return
        artifacts = R.list_artifacts(self.conn, run_id)
        if not artifacts:
            self.artifacts_pane.object = "*No artifacts saved for this run.*"
            return
        lines = [f"- `{a['kind']}` → `{a['path']}`  ({a['created_at']})" for a in artifacts]
        self.artifacts_pane.object = "**Artifacts:**\n" + "\n".join(lines)

    def _on_name_edited(self, event):
        """T67: inline rename from the history table. The name is a label,
        never an identifier — an empty edit clears it back to NULL, and no
        uniqueness is enforced (two runs may share a name)."""
        df = self.table.value
        run_id = int(df.iloc[event.row]["id"])
        value = event.value
        if value in (None, ""):
            value = None
        try:
            R.update_run(self.conn, run_id, name=value)
        except ValueError as e:
            self.table.patch({event.column: [(event.row, event.old)]})
            self.status.object = f"**Edit failed:** {e}"
            return
        self.status.object = f"Renamed run #{run_id}."
        self._refresh()

    def _on_reopen(self, _event=None):
        self.status.object = ""
        run_id = self._selected_run_id()
        if run_id is None:
            self.status.object = "**Select a run first.**"
            return
        run = R.get_run(self.conn, run_id)
        recipe = R.load_recipe(self.conn, run["config_id"])
        if not recipe.get("steps"):
            self.status.object = "**That run has no steps to reload.**"
            return

        # PRD: "a history sidebar that can reload a past chain" — Reopen now
        # reconstructs the run's recipe steps in the chain builder (rather
        # than only restaging the last step in the run panel).
        from UI.analyse.chain_state import ChainState
        builder = self.app.chain_builder
        builder.chain = ChainState.from_recipe(recipe)
        builder._refresh()

        if self.app.tabs is not None:
            self.app.activate_workspace("Analyse", "Chain builder")
        name = run["name"]
        label = f"#{run_id}" if not name else f"{name} (#{run_id})"
        self.status.object = (
            f"Reopened {label}'s chain ({recipe_summary(recipe)}) in the builder."
        )

    def _set_collapsed(self, value):
        """Set the sidebar's collapsed state and re-render it.

        Early-returns when the state is unchanged so the section watcher does
        not re-render on every active-tab event that leaves the state alone.
        """
        if self.collapsed == value:
            return
        self.collapsed = value
        self._render()

    def toggle(self):
        """Flip the sidebar between its collapsed ribbon and expanded width."""
        self._set_collapsed(not self.collapsed)

    def bind_sections(self, tabs):
        """Make the sidebar section-aware: collapsed while the chain builder is
        the active Analyse section, expanded otherwise (T70 user story 31).

        `tabs` is the Analyse workspace's inner `pn.Tabs`. The default is
        applied immediately for the currently active section and re-applied on
        every section change, so a manual toggle within a section is honoured
        until the section changes.
        """
        if not isinstance(tabs, pn.Tabs):
            return

        def _on_section_change(event):
            names = list(tabs._names)
            active = event.new if event.new is not None else 0
            active = max(active, 0)
            self._set_collapsed(names[active] == "Chain builder")

        tabs.param.watch(_on_section_change, "active")
        active = tabs.active if tabs.active is not None else 0
        active = max(active, 0)
        self._set_collapsed(list(tabs._names)[active] == "Chain builder")

    def _render(self):
        """Rebuild the sidebar Column to match `self.collapsed`."""
        if self.collapsed:
            self.sidebar.width = self.RIBBON_WIDTH
            self.sidebar.styles = {}
            self.sidebar.objects = [self.expand_button]
            return

        self.sidebar.width = self.EXPANDED_WIDTH
        self.sidebar.styles = {"overflow-y": "auto"}
        self.sidebar.objects = [
            pn.Row(
                pn.pane.Markdown("### Run history"),
                self.collapse_button,
            ),
            pn.pane.Markdown(
                "Everything you've tried, filterable by recording and status. "
                "Select a row to see its artifacts, or reopen it in the chain "
                "builder to re-run or tweak it."
            ),
            pn.Row(self.filter_recording, self.filter_status, self.refresh_button),
            self.table,
            pn.Row(self.reopen_button),
            self.status,
            self.artifacts_pane,
        ]

    def layout(self):
        return self.sidebar
