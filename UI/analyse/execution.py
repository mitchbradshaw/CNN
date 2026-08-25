"""
Running a recipe: building its steps, executing it on a background thread,
reporting progress, and gathering everything the display needs *inside* the
worker's connection before handing back to the UI thread.
"""

import threading

import numpy as np
import panel as pn

from Adapters.registry import get_adapter

from Working.database import queries as q
from Working.database import runs as R
from Working.database.schema import init_db
from Working.config import ENCODING_RECOMPUTE_MAX_SAMPLES
from Working.encoding_cache import read_encoding_file
from Working.execution import RecipeCancelled, RecipeExecutionError, execute_recipe
from Working.recipes import make_recipe, recipe_summary

from UI.plots import symbol_letters, symbols_to_string
from UI.analyse.ui_thread import _run_on_ui_thread


class ExecutionMixin:
    """Recipe execution, cancellation and progress. Mixed into `RunPanel`."""

    def _build_run_widgets(self):
        self.run_button = pn.widgets.Button(name="Run", button_type="primary")
        self.cancel_button = pn.widgets.Button(name="Cancel", button_type="danger", disabled=True)
        self.status = pn.pane.Markdown("")
        self.duration_pane = pn.pane.Markdown("")

    # ── Run / cancel ─────────────────────────────────────────────────────

    def _build_steps(self):
        """Part 6, 2e: prepend a preprocessing step ahead of whatever
        algorithm is selected, when the user has picked one — a REAL
        recipe step (not baked into the SAX/any other adapter), so the
        recipe hash covers it and Run History shows what actually ran.
        Used by a real Run, and by the auto-preview path (Part 4c), so
        the two can never silently diverge on what a run consists of."""
        stage = self.stage_select.value
        algorithm_full = self.algorithm_select.value  # e.g. "detection.sax_csax"
        algorithm_short = algorithm_full.split(".", 1)[1]
        params = self._current_params()
        steps = []
        if self.preprocess_select.value != "none":
            steps.append({
                "stage": "preprocessing", "algorithm": "detrend",
                "params": {"mode": self.preprocess_select.value, "window_s": self.preprocess_window.value},
            })
        steps.append({"stage": stage, "algorithm": algorithm_short, "params": params})
        return steps

    def _on_run(self, _event=None):
        self.status.object = ""
        self.motif_status.object = ""
        self._last_step_results = {}  # per-stage results as they land (T24)
        if self._thread is not None and self._thread.is_alive():
            self.status.object = "**A run is already in progress.**"
            return

        try:
            span = self._current_span()
        except ValueError as e:
            self.status.object = f"**{e}**"
            return

        recipe = make_recipe(self.app._recording_id, self._build_steps(), span=span)
        self._last_recipe = recipe
        self._last_recording = self.app._recording_id

        self._cancel_event.clear()
        self.run_button.disabled = True
        self.cancel_button.disabled = False
        self.status.object = f"Running {recipe_summary(recipe)} ..."

        db_path = self.conn.execute("PRAGMA database_list").fetchone()[2] or None
        doc = pn.state.curdoc  # captured here, on the serving thread

        def _worker():
            # A worker thread must never touch `self.conn` (or any
            # sqlite3.Row/Connection it produced) — SQLite connections are
            # thread-affined. This thread opens its own, reads whatever
            # plain data the UI update will need, and closes it before
            # handing off — only plain dicts/arrays cross the thread
            # boundary, never live DB objects.
            def on_progress(i, n, s, a):
                def _update():
                    self.status.object = f"Running step {i + 1}/{n}: {s}.{a} ..."
                _run_on_ui_thread(doc, _update)

            # Each stage's typed result is handed to the UI thread the moment
            # it lands, so the run surface can render per-stage results as
            # they complete rather than waiting for the whole run (T24).
            def on_step_result(i, result):
                def _update():
                    self._last_step_results[i] = result
                    self.status.object = f"Step {i + 1} complete: {result.output_kind}"
                _run_on_ui_thread(doc, _update)

            try:
                out = execute_recipe(
                    recipe, db_path=db_path, on_progress=on_progress,
                    should_cancel=self._cancel_event.is_set,
                    on_step_result=on_step_result,
                )
                conn_w = init_db(db_path)
                try:
                    display_data = self._gather_display_data(conn_w, out, recipe)
                finally:
                    conn_w.close()
                _run_on_ui_thread(doc, lambda: self._on_run_finished(out, display_data))
            except RecipeCancelled:
                _run_on_ui_thread(doc, lambda: self._on_run_cancelled())
            except RecipeExecutionError as e:
                _run_on_ui_thread(doc, lambda: self._on_run_failed(str(e)))

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def _gather_display_data(self, conn_w, out, recipe):
        """Runs on the worker thread with its own connection `conn_w`.
        Returns a plain (no live DB objects) dict describing what the UI
        thread needs to render.

        The last step's adapter spec (not `out["result"]`, which is None
        for a reused run) tells us the *actual* output kind regardless of
        whether anything was recomputed. Span-set outputs are persisted
        (`detections`), so a reused run can still show them; `signal`/
        `encoding` outputs are not persisted anywhere the UI can cheaply
        re-read, so a reused run reports that rather than fabricating a
        stale or recomputed preview.
        """
        last_step = recipe["steps"][-1]
        spec = get_adapter(f"{last_step['stage']}.{last_step['algorithm']}")
        result = out["result"]

        if spec.output_kind == "spanset":
            dets = R.list_detections(conn_w, out["run_id"])
            return {"kind": "spanset", "detections": [dict(d) for d in dets]}

        # Not every adapter that reaches here is SAX-shaped (a details dict +
        # x/t + a discrete symbol array). `detection.matrix_profile` and
        # `preprocessing.window_matrix` are also routed to the generic path
        # -- a continuous/tabular result with its own dedicated exploration
        # UI (the Motif browser tab), not the SAX 4-panel view. T08 remapped
        # their `output_kind` from the legacy 'encoding' to 'scores'/
        # 'windowset' respectively; `_gather_generic_encoding_display_data`
        # reads the persisted artifact from disk either way, so the routing
        # here only needs to keep recognising them by kind. Same
        # `algorithm_short.startswith("sax_")` convention
        # `_persist_sax_encoding`'s caller already uses below to keep
        # SAX-only behaviour SAX-only.
        if spec.output_kind in ("encoding", "scores", "windowset"):
            if last_step["algorithm"].startswith("sax_"):
                return self._gather_encoding_display_data(conn_w, out, recipe, spec, result)
            return self._gather_generic_encoding_display_data(conn_w, out, recipe, spec, result)

        if result is None:  # reused signal run — nothing to re-show cheaply
            return {"kind": "reused_no_preview"}

        if spec.output_kind == "signal":
            recording = q.get_recording_by_id(conn_w, recipe["recording_id"])
            span = recipe["span"]
            start, end = (0, recording["n_samples"]) if span is None else span
            return {
                "kind": "signal",
                "recording": dict(recording),
                "result_x": result.value.x,
                # A Signal carries `fs` but no absolute offset, so the axis is
                # rebuilt from the span the same way `execution._load_signal`
                # builds it — the plot is drawn against the channel, not
                # against zero.
                "result_t": np.arange(start, end) / recording["fs"],
            }

        return {"kind": None}

    def _gather_encoding_display_data(self, conn_w, out, recipe, spec, result):
        """Part 6, 3a. A REUSED encoding run has `result=None` (nothing
        recomputed) — but an encoding is cheap (well under a second even
        at ~63k samples), so re-run just this step for spans under
        `ENCODING_RECOMPUTE_MAX_SAMPLES` rather than showing nothing.
        Above that, fall back to the cached STRING alone (no detail
        panels — the array/`details` a fresh recompute would need aren't
        persisted anywhere cheap to re-read), with an explicit note why.
        """
        span = recipe["span"]
        recording = q.get_recording_by_id(conn_w, recipe["recording_id"])
        start, end = (0, recording["n_samples"]) if span is None else span
        n = end - start

        if result is None and n <= ENCODING_RECOMPUTE_MAX_SAMPLES:
            x_full = np.load(recording["npy_path"], mmap_mode="r")
            x = np.asarray(x_full[start:end])
            t = np.arange(start, end) / recording["fs"]
            # Replay any preprocessing step(s) that preceded the SAX step,
            # so the recomputed encoding matches what the real run
            # actually encoded, not the raw span.
            for step in recipe["steps"][:-1]:
                step_spec = get_adapter(f"{step['stage']}.{step['algorithm']}")
                step_params = step_spec.validate_params(step["params"])
                step_result = step_spec.run(x, t, recording["fs"], **step_params)
                x = step_result.value.x
            params = spec.validate_params(recipe["steps"][-1]["params"])
            result = spec.run(x, t, recording["fs"], **params)

        if result is not None:
            algorithm_short = recipe["steps"][-1]["algorithm"]
            if algorithm_short.startswith("sax_"):  # Part 6, 4e
                self._persist_sax_encoding(conn_w, recording, recipe, out, result.value.values,
                                           algorithm_short, result.meta["details"])
            return {
                "kind": "encoding", "recording": dict(recording),
                "x": result.meta["encoded_x"], "t": result.meta["encoded_t"],
                "symbols": result.value.values,
                "details": result.meta["details"],
            }

        cached = R.get_encoding_by_hash(conn_w, out["config_hash"])
        if cached is not None:
            try:
                return {"kind": "encoding_cached_only",
                        "string": read_encoding_file(cached["path"]),
                        # Carried through so `_show_encoding_string_only` can
                        # name the alphabet — there is no `details` there.
                        "encoding_type": cached["encoding_type"],
                        "n_samples": n}
            except Exception:
                pass
        return {"kind": "encoding_too_large", "n_samples": n}

    def _gather_generic_encoding_display_data(self, conn_w, out, recipe, spec, result):
        """For 'encoding' adapters that are NOT SAX-shaped — currently
        just `detection.matrix_profile`. These have no `details`/x/t
        triplet to hand to the SAX 4-panel view (Part 6); matrix profile
        has its own dedicated exploration UI instead (the Motif browser
        tab, reading the v2 artifact this adapter's `persist` hook already
        wrote — see `Adapters.detection_matrix_profile`).

        Unlike SAX, recomputing a matrix profile just for a preview is NOT
        cheap (it's the same O(n^2)-ish cost as the run itself), so —
        unlike `_gather_encoding_display_data` — a reused run is never
        silently re-run here; it just reports `reused=True`.
        """
        artifacts = R.list_artifacts(conn_w, out["run_id"])
        artifact_path = next((a["path"] for a in artifacts if a["kind"] == "encoding"), None)

        summary = None
        if artifact_path is not None:
            try:
                from Working.database.matrix_profile_store import load_mp
                data = load_mp(artifact_path, mmap=True)
                mp_arr = np.asarray(data["mp"])
                finite = mp_arr[np.isfinite(mp_arr)]
                summary = {
                    "n": int(len(mp_arr)), "m": int(data["m"]), "backend": str(data["backend"]),
                    "approx": bool(data["approx"]),
                    "min": float(finite.min()) if len(finite) else None,
                    "mean": float(finite.mean()) if len(finite) else None,
                    "max": float(finite.max()) if len(finite) else None,
                }
            except Exception:
                summary = None

        return {
            "kind": "generic_encoding", "run_id": out["run_id"],
            "artifact_path": artifact_path, "summary": summary, "reused": result is None,
        }

    def _persist_sax_encoding(self, conn_w, recording, recipe, out, symbols, algorithm_short,
                              details=None):
        """Part 6, 4e: persist the run's symbol string through
        `Working.encoding_cache` with `encoding_type` "sax_csax" /
        "sax_psax" / "sax_dsax" — so `_find_sax_string_for_span` (already
        written to look for exactly this) picks it up automatically the
        moment a detection or a manual selection over the SAME span is
        saved as a motif, with no further wiring needed there. Skips
        silently if already cached (`get_or_compute_encoding`'s own
        cache-hit path) — a reused run recomputed here for display doesn't
        need a duplicate write.

        `encoding_type` needed no extension for dSAX: it is already
        DERIVED from the recipe's own `algorithm` short name by the caller,
        so `detection.sax_dsax` becomes "sax_dsax" without a special case.

        `details` (2026-08, dSAX) supplies the alphabet, so the cached
        `.txt` holds the SAME string the run panel displays. Without it a
        dSAX run would persist "abcba..." while the UI showed "USDSU..." —
        two spellings of one encoding, and a morphology regex saved
        against one would silently not match the other.
        """
        from Working.encoding_cache import get_or_compute_encoding
        span = recipe["span"]
        start, end = (0, recording["n_samples"]) if span is None else span
        letters = symbol_letters(details) if details is not None else None
        get_or_compute_encoding(
            conn_w, recording, algorithm_short, out["config_hash"],
            lambda: (symbols_to_string(symbols, letters), start, end),
        )

    def _on_cancel(self, _event=None):
        self._cancel_event.set()
        self.status.object = "Cancelling after the current step finishes ..."

    def _on_run_finished(self, out, display_data):
        self.run_button.disabled = False
        self.cancel_button.disabled = True
        self._last_run_result = out

        last_step = self._last_recipe["steps"][-1]
        spec = get_adapter(f"{last_step['stage']}.{last_step['algorithm']}")
        self.save_plot_button.disabled = spec.plot is None
        self.save_plot_status.object = ""

        reused_note = " (reused an identical prior run — not recomputed)" if out["reused"] else ""
        total_s = sum(out["step_timings"].values()) if out["step_timings"] else 0.0
        self.status.object = f"Done{reused_note}. run_id={out['run_id']}"
        self.duration_pane.object = (
            f"**Duration:** {total_s:.3f}s"
            + ("" if not out["step_timings"] else " (" + ", ".join(
                f"step {i}: {t:.3f}s" for i, t in sorted(out["step_timings"].items(), key=lambda kv: int(kv[0]))
            ) + ")")
        )

        # Part 6, 4f: the Encoding section is hidden entirely (not shown
        # empty) whenever the last run's output isn't an encoding.
        self.encoding_section.visible = display_data["kind"] in (
            "encoding", "encoding_cached_only", "encoding_too_large",
        )

        if display_data["kind"] == "spanset":
            self._show_detections(display_data["detections"])
        elif display_data["kind"] == "signal":
            self._show_before_after(display_data["recording"], display_data["result_x"], display_data["result_t"])
        elif display_data["kind"] == "encoding":
            self._show_encoding(display_data["x"], display_data["t"], display_data["symbols"],
                                 display_data["details"], display_data["recording"])
        elif display_data["kind"] == "encoding_cached_only":
            self.status.object += (
                f"  |  span is {display_data['n_samples']:,} samples, above the "
                f"{ENCODING_RECOMPUTE_MAX_SAMPLES:,}-sample recompute limit — showing the cached "
                "symbol string only, no detail panels."
            )
            self._show_encoding_string_only(display_data["string"],
                                            display_data.get("encoding_type"))
        elif display_data["kind"] == "encoding_too_large":
            self.status.object += (
                f"  |  span is {display_data['n_samples']:,} samples, above the "
                f"{ENCODING_RECOMPUTE_MAX_SAMPLES:,}-sample recompute limit, and no cached "
                "encoding was found for this exact recipe — nothing to show."
            )
            self.encoding_section.visible = False
        elif display_data["kind"] == "reused_no_preview":
            self.status.object += (
                "  |  no new preview to show for a reused run — see the Run History "
                "tab for this run's prior artifacts, or change a parameter to recompute."
            )
        elif display_data["kind"] == "generic_encoding":
            reused_note2 = " (reused an identical prior run)" if display_data["reused"] else ""
            summary = display_data["summary"]
            if summary is not None:
                approx_note = " approx" if summary["approx"] else ""
                self.status.object += (
                    f"  |  profile: n={summary['n']:,} m={summary['m']} "
                    f"backend={summary['backend']}{approx_note}  "
                    f"min={summary['min']:.4f} mean={summary['mean']:.4f} max={summary['max']:.4f}"
                    f"{reused_note2}. See the **Motif browser** tab to explore it."
                )
            elif display_data["artifact_path"] is not None:
                self.status.object += (
                    f"  |  saved to {display_data['artifact_path']}{reused_note2}. "
                    "See the **Motif browser** tab to explore it."
                )
            else:
                self.status.object += (
                    f"  |  no artifact was registered for this run{reused_note2} — nothing to show."
                )
        self._update_motif_button_states()

    def _on_run_cancelled(self):
        self.run_button.disabled = False
        self.cancel_button.disabled = True
        self.status.object = "**Cancelled.**"

    def _on_run_failed(self, message):
        self.run_button.disabled = False
        self.cancel_button.disabled = True
        self.status.object = f"**Failed:** {message}"
