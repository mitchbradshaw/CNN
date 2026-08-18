"""
The surrogate noise-floor estimate: how big a per-segment rise appears with
no trend present. Meaningless for amplitude-domain encodings, so it is
hidden rather than shown inapplicable.
"""

import threading
import time

import panel as pn

from Adapters.detection_sax_dsax import (
    NOISE_FLOOR_MAX_SAMPLES, NOISE_FLOOR_RATIO_ALERT, noise_floor_surrogate_count,
)

from Working.Detection.sax.dsax_python.dsax import (
    same_band_halfwidth, same_fraction_under_halfwidth, working_domain_array,
)
from Working.Detection.sax.dsax_python.trend_estimators import surrogate_same_halfwidth

from UI.plots import cutline_domain
from UI.analyse.ui_thread import _run_on_ui_thread


class NoiseFloorMixin:
    """The surrogate noise-floor estimate and its background worker."""

    def _build_noise_floor_widgets(self):
        # ── Noise-floor estimate (dSAX Phase D) ──────────────────────────
        # Hidden for amplitude-domain encodings: a surrogate half-width is
        # a statement about a delta distribution and has no meaning for a
        # PAA one.
        self.enc_noise_floor_button = pn.widgets.Button(
            name="Estimate noise floor", button_type="default",
            description=(
                "Draws phase-randomised surrogates of this exact span and measures how big a "
                "per-segment rise appears with NO trend present. Surrogate COUNT is reduced on "
                "long spans (never the span itself, which would change the spectrum the null "
                f"depends on); disabled above {NOISE_FLOOR_MAX_SAMPLES:,} samples."
            ),
        )
        self.enc_noise_floor_alpha = pn.widgets.FloatInput(
            name="alpha", value=0.95, start=0.5, end=0.9999, step=0.01, width=90,
            description=(
                "Quantile of the surrogate |rise| distribution to call the noise floor. "
                "0.95 means 'a rise this big happens by chance in 5% of trend-free segments'. "
                "The right false-positive rate is a scientific choice, not a constant."
            ),
        )
        self.enc_noise_floor_status = pn.pane.Markdown("")

    # ── Noise-floor estimate (dSAX Phase D) ──────────────────────────────

    def _sync_noise_floor_controls(self, x, details):
        """Visible only for a delta-domain encoding, and disabled above the
        span ceiling — a surrogate half-width has no meaning for a PAA
        encoding, and drawing surrogates of a multi-million-sample span is
        not a thing to make someone wait for behind a diagnostic."""
        is_delta = cutline_domain(details) == "delta"
        self.enc_noise_floor_button.visible = is_delta
        self.enc_noise_floor_alpha.visible = is_delta
        self.enc_noise_floor_status.object = ""
        if not is_delta:
            return
        too_long = len(x) > NOISE_FLOOR_MAX_SAMPLES
        no_same_bin = same_band_halfwidth(details) is None
        self.enc_noise_floor_button.disabled = too_long or no_same_bin
        if too_long:
            self.enc_noise_floor_status.object = (
                f"*Noise-floor estimate disabled: this span is {len(x):,} samples, above the "
                f"{NOISE_FLOOR_MAX_SAMPLES:,}-sample limit. Estimate it on a shorter span "
                "of the same channel — the noise floor is a property of the signal, not of "
                "the span length.*"
            )
        elif no_same_bin:
            self.enc_noise_floor_status.object = (
                f"*Noise-floor estimate disabled: alphabet_size="
                f"{details['alphabet_size']} is even, so there is no SAME band to compare a "
                "floor against.*"
            )

    def _on_estimate_noise_floor(self, _event=None):
        """Measure how big a per-segment rise this signal produces with NO
        trend present, and compare it against the band Lloyd-Max learned.

        This is the gap IMPLEMENTATION_NOTES.md 6.3 measured at 3.1x on
        pure noise: Lloyd-Max minimises squared quantisation error against
        the observed delta density, which is a different question from "is
        this rise bigger than noise", and on a trendless signal it will
        happily label half the segments UP or DOWN and score 97% of its
        entropy ceiling doing it.

        Runs on a worker thread — `n_surrogates` FFTs of a long span is
        seconds, and blocking the Bokeh event loop for that would freeze
        every other control on the page with no explanation. NEVER re-runs
        the encoding: it reports a number and, at most, fills in the
        `min_same_halfwidth` control for the user to re-run deliberately.
        """
        if self._last_encoding is None:
            self.enc_noise_floor_status.object = "**Run an encoding first.**"
            return
        x, _t, _symbols, details, _recording = self._last_encoding
        if cutline_domain(details) != "delta":
            return

        alpha = float(self.enc_noise_floor_alpha.value)
        self.enc_noise_floor_button.disabled = True
        self.enc_noise_floor_status.object = "*Computing surrogates ...*"

        def _worker():
            try:
                started = time.time()
                # The half-width must be estimated in the WORKING delta
                # domain, because that is the domain `min_same_halfwidth`
                # is specified in — comparing a raw-domain estimate against
                # a normalised cutline differs by a factor of norm_std,
                # which on a fungal channel is two orders of magnitude.
                working = working_domain_array(x, details)
                sps = int(details["samples_per_symbol"])
                n_surrogates = noise_floor_surrogate_count(len(working))
                surrogate = surrogate_same_halfwidth(
                    working, sps, trend_estimator=details["trend_estimator"],
                    n_surrogates=n_surrogates, alpha=alpha, random_state=0,
                )
                elapsed = time.time() - started
                learned = same_band_halfwidth(details)
                projected, _ = same_fraction_under_halfwidth(details, surrogate)
                payload = {
                    "surrogate": surrogate, "learned": learned, "projected": projected,
                    "n_surrogates": n_surrogates, "elapsed": elapsed, "alpha": alpha,
                    "scale": details.get("delta_scale") or 1.0,
                    "observed": float(details.get("same_fraction_observed", 0.0)),
                }
            except Exception as e:                       # noqa: BLE001
                payload = {"error": repr(e)}
            _run_on_ui_thread(doc, lambda: self._on_noise_floor_finished(payload))

        # Captured on the SERVING thread, before the worker starts — see
        # `_run_on_ui_thread`'s docstring: reading `pn.state.curdoc` from
        # inside the worker returns nothing useful.
        doc = pn.state.curdoc
        self._noise_floor_thread = threading.Thread(target=_worker, daemon=True)
        self._noise_floor_thread.start()

    def _on_noise_floor_finished(self, payload):
        self.enc_noise_floor_button.disabled = False
        if "error" in payload:
            self.enc_noise_floor_status.object = f"**Noise-floor estimate failed:** {payload['error']}"
            return

        surrogate = payload["surrogate"]
        learned = payload["learned"]
        scale = payload["scale"]
        ratio = surrogate / learned if learned else float("inf")

        # The recommendation is stated only in the form the evidence
        # supports: a ratio is a measurement, "your labels are noise" is a
        # conclusion, and only the first is being reported here.
        if ratio >= NOISE_FLOOR_RATIO_ALERT:
            verdict = (
                f"**The learned SAME band is {ratio:.1f}x narrower than the noise floor.** "
                "A large share of the UP/DOWN labels in this encoding are likely to be noise "
                "rather than trend. Consider setting `min_same_halfwidth` below and re-running."
            )
        else:
            verdict = (
                f"The learned SAME band is within {ratio:.2f}x of the noise floor — the UP/DOWN "
                "labels are not obviously attributable to noise at this alpha."
            )

        # Fill the control in, but never re-run: a diagnostic that silently
        # changes the thing it measured is not a diagnostic.
        set_note = ""
        w = self._param_widgets.get("min_same_halfwidth")
        if w is not None and not w.disabled:
            self._suppress_param_watchers = True
            try:
                w.value = float(surrogate)
            finally:
                self._suppress_param_watchers = False
            set_note = (
                f"\n\n`min_same_halfwidth` has been set to **{surrogate:.6g}** "
                "(working delta units). **Re-run for it to take effect** — nothing has been "
                "recomputed."
            )

        self.enc_noise_floor_status.object = (
            f"{verdict}\n\n"
            f"| | working units | raw units |\n|---|---|---|\n"
            f"| learned SAME half-width | {learned:.6g} | {learned * scale:.6g} |\n"
            f"| surrogate half-width (alpha={payload['alpha']:.3g}) | {surrogate:.6g} "
            f"| {surrogate * scale:.6g} |\n"
            f"| ratio surrogate / learned | {ratio:.2f}x | |\n\n"
            f"SAME fraction now **{payload['observed'] * 100:.1f}%**; it would be "
            f"**{payload['projected'] * 100:.1f}%** with the floor imposed. "
            f"({payload['n_surrogates']} surrogates, {payload['elapsed']:.2f}s.)"
            f"{set_note}"
        )
