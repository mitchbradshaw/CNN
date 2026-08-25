"""
UI/workspaces/analyse/export.py
=================================
The run-group export action (ticket 45). A completed run group leaves the
tool as a folder a thesis chapter can be written from, without re-running
anything: a manifest (ticket 27's schema), a spans CSV and copied plots.

The headless work lives in `Working/export.py`; this surface only lets the
researcher pick a run group and an output directory, then calls it. It reads
the live database connection off `app` (the same "read the app's live state,
don't duplicate it" contract the other Analyse surfaces use) and never opens
its own connection.
"""

import panel as pn

from Working.export import export_run_group


class RunGroupExporter:
    """The run-group export tab. `app` is read for its live database
    connection only."""

    def __init__(self, app):
        self.app = app
        self.run_group = pn.widgets.Select(
            name="Run group", options=self._group_options(),
        )
        self.out_dir = pn.widgets.TextInput(name="Output directory", value="exports")
        self.export_button = pn.widgets.Button(
            name="Export run group", button_type="primary",
        )
        self.status = pn.pane.Markdown("")
        self.export_button.on_click(self._on_export)

    def layout(self):
        return pn.Column(
            pn.pane.Markdown("### Export run group"),
            pn.pane.Markdown(
                "Exports the run group as a folder containing a manifest, a "
                "spans table as CSV, and copies of its plots."
            ),
            self.run_group,
            self.out_dir,
            self.export_button,
            self.status,
            sizing_mode="stretch_width",
        )

    def _group_options(self):
        """`{label: run_group_id}` for every run group in the database. The
        label shows the run count so a researcher can tell groups apart."""
        conn = getattr(self.app, "conn", None)
        if conn is None:
            return {}
        options = {}
        for group in conn.execute("SELECT id FROM run_groups ORDER BY id"):
            gid = group["id"]
            n = conn.execute(
                "SELECT COUNT(*) FROM runs WHERE run_group_id = ?", (gid,)
            ).fetchone()[0]
            options[f"Run group #{gid} ({n} runs)"] = gid
        return options

    def _on_export(self, _event=None):
        gid = self.run_group.value
        if gid is None:
            self.status.object = "**Select a run group first.**"
            return
        out_dir = self.out_dir.value or "exports"
        try:
            result = export_run_group(self.app.conn, gid, out_dir)
        except Exception as e:
            self.status.object = f"**Export failed:** {e}"
            return
        self.status.object = (
            f"**Exported {len(result['run_ids'])} runs to `{result['out_dir']}`.**"
        )
