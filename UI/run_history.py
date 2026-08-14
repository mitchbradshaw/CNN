"""
run_history.py
================
The run history browser (5e) — "the single biggest reason I'm building
this": a filterable table of every past run, letting you (a) see
everything tried on a given channel, (b) click a run and reopen its exact
recipe in the run panel to re-run or tweak it, and (c) find the artifacts
it produced.
"""

import json

import pandas as pd
import panel as pn

from Working.database import queries as q
from Working.database import runs as R
from Working.recipes import recipe_summary

TABLE_COLUMNS = ["id", "source_file", "channel", "recipe", "params",
                  "span_start", "span_end", "duration_s", "status",
                  "detections", "artifacts", "started_at"]


class RunHistoryBrowser:
    def __init__(self, app):
        self.app = app
        self.conn = app.conn

        self.filter_recording = pn.widgets.Select(name="Recording (source_file:channel)", options=[])
        self.filter_status = pn.widgets.MultiChoice(
            name="Status", options=["running", "completed", "failed"],
        )
        self.refresh_button = pn.widgets.Button(name="Refresh", button_type="default")
        self.reopen_button = pn.widgets.Button(name="Reopen in Run panel", button_type="primary")
        self.status = pn.pane.Markdown("")
        self.artifacts_pane = pn.pane.Markdown("*Select a run to see its artifacts.*")

        self.table = pn.widgets.Tabulator(
            pd.DataFrame(columns=TABLE_COLUMNS), page_size=15, disabled=True,
            selectable=1, show_index=False, sizing_mode="stretch_width",
        )

        self.filter_recording.param.watch(lambda _e: self._refresh(), "value")
        self.filter_status.param.watch(lambda _e: self._refresh(), "value")
        self.refresh_button.on_click(lambda _e: self._refresh())
        self.reopen_button.on_click(self._on_reopen)
        self.table.param.watch(self._on_row_selected, "selection")

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

    def _on_reopen(self, _event=None):
        self.status.object = ""
        run_id = self._selected_run_id()
        if run_id is None:
            self.status.object = "**Select a run first.**"
            return
        run = R.get_run(self.conn, run_id)
        recipe = R.load_recipe(self.conn, run["config_id"])

        rp = self.app.run_panel
        last_step = recipe["steps"][-1]
        rp.stage_select.value = last_step["stage"]
        rp._on_stage_changed(None)
        adapter_full_name = f"{last_step['stage']}.{last_step['algorithm']}"
        rp.algorithm_select.value = adapter_full_name
        rp._on_algorithm_changed(None)
        for name, widget in rp._param_widgets.items():
            if name in last_step["params"]:
                widget.value = last_step["params"][name]

        # Reflect the run's exact span as a one-off manual selection so
        # re-running (or tweaking a param first) reproduces the same span.
        # `_pending_bounds` lives in the viewer's CURRENT display unit
        # (seconds or hours — see ViewerApp._unit_scale), not necessarily
        # seconds, so divide by that unit's scale, not just fs.
        if run["span_start"] is not None and run["span_end"] is not None:
            rp.span_mode.value = "Selected span"
            fs = self.app._fs or 1.0
            scale = self.app._unit_scale()
            self.app._pending_bounds = (
                run["span_start"] / fs / scale, run["span_end"] / fs / scale,
            )
            self.app._sync_time_fields_from_bounds()
            self.app._update_selection_info()
            self.app._refresh_view()

        if self.app.tabs is not None:
            self.app.tabs.active = 1  # "Run algorithm" tab
        self.status.object = (
            f"Reopened run_id={run_id}'s last step ({adapter_full_name}) in the Run panel."
        )

    def layout(self):
        return pn.Column(
            pn.pane.Markdown(
                "### Run history\n"
                "Everything you've tried, filterable by recording and status. "
                "Select a row to see its artifacts, or reopen it in the run panel "
                "to re-run or tweak a parameter."
            ),
            pn.Row(self.filter_recording, self.filter_status, self.refresh_button),
            self.table,
            pn.Row(self.reopen_button),
            self.status,
            self.artifacts_pane,
            sizing_mode="stretch_width",
        )
