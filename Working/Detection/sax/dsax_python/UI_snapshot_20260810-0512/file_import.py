"""
file_import.py
================
UI wrapper for bringing a new recording in without touching the filesystem
by hand. All the actual file-reading / atomic-write / DB-registration logic
lives in `Pipelines.materialize_channels.materialize_channels` (headless,
reusable) — this module is just the Panel form on top of it: a file picker,
detected-channel-count/fs fields the user must confirm or override, a
progress bar, and a status message. Nothing here assumes 16 channels or
fs=1 — those are only ever pre-filled *suggestions*.
"""

import os
import tempfile

import panel as pn

from Pipelines.materialize_channels.materialize_channels import (
    detect_channel_count,
    materialize_arbitrary_file,
)

ACCEPTED_EXTENSIONS = (".mat", ".csv")


class FileImportPanel:
    def __init__(self, conn, on_imported=None):
        self.conn = conn
        self.on_imported = on_imported or []  # callables invoked after a successful import
        self._tmp_path = None

        self.file_input = pn.widgets.FileInput(accept=",".join(ACCEPTED_EXTENSIONS))
        self.file_input.param.watch(self._on_file_selected, "value")

        self.detected_info = pn.pane.Markdown("*Choose a .mat or .csv file to begin.*")
        self.n_channels_input = pn.widgets.IntInput(name="Channel count (confirm/override)", value=16, start=1)
        self.fs_input = pn.widgets.FloatInput(name="Sample rate fs (confirm/override)", value=1.0, start=0.0)

        self.progress = pn.indicators.Progress(name="Progress", value=0, max=100, visible=False)
        self.status = pn.pane.Markdown("")
        self.import_button = pn.widgets.Button(
            name="Materialize + register", button_type="primary", disabled=True,
        )
        self.import_button.on_click(self._on_import)

    def _on_file_selected(self, event):
        self.status.object = ""
        self.import_button.disabled = True
        filename = self.file_input.filename
        if not filename:
            return
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ACCEPTED_EXTENSIONS:
            self.detected_info.object = f"**Unsupported file type {ext!r}.** Expected .mat or .csv."
            return

        # Write the uploaded bytes to a temp file so the existing
        # scipy.io.loadmat / h5py / pandas readers (path-based) can be
        # reused unchanged.
        if self._tmp_path and os.path.isfile(self._tmp_path):
            os.remove(self._tmp_path)
        fd, self._tmp_path = tempfile.mkstemp(suffix=ext)
        with os.fdopen(fd, "wb") as f:
            f.write(event.new)
        # Preserve the original filename (not the temp one) for provenance —
        # materialize_arbitrary_file derives source_file from the path it's
        # given, so point it at a temp copy that *looks* like the original.
        renamed = os.path.join(os.path.dirname(self._tmp_path), filename)
        os.replace(self._tmp_path, renamed)
        self._tmp_path = renamed

        try:
            suggested_channels = detect_channel_count(self._tmp_path)
        except Exception as e:
            self.detected_info.object = f"**Could not read {filename!r}: {e}**"
            return

        self.n_channels_input.value = suggested_channels
        size_mb = len(event.new) / 1e6
        self.detected_info.object = (
            f"**{filename}** ({size_mb:.1f} MB). Suggested channel count: "
            f"**{suggested_channels}** — confirm or override both fields below, "
            "then materialize. Nothing is written until you click the button."
        )
        self.import_button.disabled = False

    def _on_import(self, _event=None):
        self.status.object = ""
        if not self._tmp_path:
            self.status.object = "**No file selected.**"
            return
        n_channels = self.n_channels_input.value
        fs = self.fs_input.value
        if n_channels < 1 or fs <= 0:
            self.status.object = "**Channel count and fs must both be positive.**"
            return

        self.progress.visible = True
        self.progress.value = 0
        self.progress.max = n_channels

        def _progress(done, total):
            self.progress.value = done

        try:
            summary = materialize_arbitrary_file(
                self.conn, self._tmp_path, n_channels, fs, progress_callback=_progress,
            )
        except Exception as e:
            self.status.object = f"**Import failed, nothing was registered: {e}**"
            self.progress.visible = False
            return

        self.status.object = (
            f"Imported **{summary['stem']}**: {summary['n_channels']} channels, "
            f"{summary['n_samples']} samples each, dtype={summary['dtype']}, fs={summary['fs']}. "
            "Now available in the Source file / Channel dropdowns."
        )
        self.progress.visible = False
        os.remove(self._tmp_path)
        self._tmp_path = None
        self.import_button.disabled = True
        self.file_input.value = None
        for cb in self.on_imported:
            cb()

    def layout(self):
        return pn.Column(
            pn.pane.Markdown(
                "### Import a new recording\n"
                "Select a `.mat` or `.csv` file. Each channel is written as its own "
                "`.npy` (never a single `.npz` — that can't be memory-mapped, which "
                "would break the viewer's paging) plus a `manifest.json`, and "
                "registered in `recordings` only once every channel has been "
                "written successfully."
            ),
            self.file_input,
            self.detected_info,
            pn.Row(self.n_channels_input, self.fs_input),
            self.progress,
            self.import_button,
            self.status,
            sizing_mode="stretch_width",
        )
