"""
run_dsax_validation.py
=======================
Headless characterisation run for dSAX. No arguments, no display, no
database, no `Results/` — every signal is synthetic and built in code.

    python "Experimentation/Detection experiments/run_dsax_validation.py"

Writes to `Experimentation/Detection experiments/dsax_validation/`:
  - `<id>_<name>.png`  — one four-panel figure per engineered dataset
  - `metrics.json`     — every number below, machine-readable

What this is FOR, and how it differs from the tests
----------------------------------------------------
`tests/test_dsax_engineered.py` asserts things that must be true. This
script MEASURES things whose value is not known in advance, and which
would be wrong to encode as a pass/fail threshold before anyone has looked
at them. Three of them matter:

1. **Offset sensitivity.** dSAX inherits PAA's segment grid, so shifting
   the analysis window by less than one segment re-cuts every segment and
   can change every symbol. This is a real, structural weakness of the
   whole SAX family and is worse for a trend encoding than for a value one
   (a mean is stable under a small re-cut; a slope near a turning point is
   not). It is reported per dataset, not asserted — except for a very loose
   overall floor at 0.5, which exists purely so a catastrophic regression
   still fails the run rather than quietly printing a bad number.

2. **Estimator comparison.** The flip rates behind
   `test_13_fitted_estimators_flip_less_than_endpoints_under_noise`,
   printed as actual numbers so the size of the effect is visible and not
   just its sign.

3. **Lloyd-Max vs. the noise floor.** The one genuinely open question in
   the design. Lloyd-Max minimises squared quantisation error against the
   observed delta density; `surrogate_same_halfwidth` answers the entirely
   different question "how big a rise would this signal produce with no
   trend at all". On pure noise the two disagree by construction — the
   MSE-optimal answer splits the noise into three tidy bins and calls a
   third of it UP. How FAR they disagree determines whether
   `min_same_halfwidth` needs to become the default rather than an option.

The dataset definitions are imported from `tests/test_dsax_engineered.py`
rather than duplicated, so the figures and metrics here describe byte-for-
byte the same arrays the assertions run against.
"""

import json
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import matplotlib
matplotlib.use("Agg")           # before pyplot is imported anywhere
import matplotlib.pyplot as plt
import numpy as np

from Adapters._sax_common import encoding_diagnostics
from Working.Detection.sax.dsax_python.dsax import dsax, dsax_letters, plot_trend_encoding
from Working.Detection.sax.dsax_python.trend_estimators import (
    TREND_ESTIMATORS, surrogate_same_halfwidth)

from tests.test_dsax_engineered import (ENGINEERED, NOISE, NOISE_SPS,
                                        ROBUSTNESS_REPEATS, ROBUSTNESS_SPS,
                                        _flip_rates, _dim_ratio, encode)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dsax_validation")

# Loose enough that only a catastrophic bug trips it (see module docstring):
# this is a measurement, not an acceptance criterion.
MIN_OVERALL_OFFSET_AGREEMENT = 0.5

# Beyond this many candidate offsets, sample evenly rather than testing all
# of them — the statistic is a mean over offsets and converges long before
# a 100-point sweep, and the large-n datasets are the expensive ones.
MAX_OFFSETS = 40


def _jsonable(obj):
    """numpy scalars/arrays are not JSON-serialisable; `json.dump` fails on
    them with a bare TypeError that says nothing useful about which key."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


# -- 1. per-dataset figures + occupancy diagnostics ------------------------

def run_datasets():
    rows = {}
    for ds in ENGINEERED:
        x = ds["x"]
        fs = ds["fs"]
        sps = ds["sps"]
        t = np.arange(len(x), dtype=float) / fs

        symbols, details = encode(x, sps, **ds["kwargs"])
        diag = encoding_diagnostics(symbols, details["alphabet_size"])

        path = os.path.join(OUT_DIR, f"{ds['id']:02d}_{ds['name']}.png")
        fig = plot_trend_encoding(x, t, symbols, details, path=path)
        plt.close(fig)

        string = dsax_letters(symbols, details["alphabet_size"])
        rows[ds["name"]] = {
            "id": ds["id"],
            "expectation": ds["expectation"],
            "n_samples": len(x),
            "fs": fs,
            "samples_per_symbol": details["samples_per_symbol"],
            "n_symbols": details["n_symbols"],
            "alphabet_size": details["alphabet_size"],
            "threshold_mode": details["threshold_mode"],
            "trend_estimator": details["trend_estimator"],
            # Long strings are not useful in a JSON file and make it
            # unreadable; the PNG is the artefact for those.
            "string": string if len(string) <= 200 else string[:200] + "...",
            "histogram": diag["histogram"],
            "occupancy_entropy_bits": diag["occupancy_entropy_bits"],
            "occupancy_entropy_ceiling_bits": diag["occupancy_entropy_ceiling_bits"],
            "occupancy_entropy_fraction": diag["occupancy_entropy_fraction"],
            "self_transition_rate": diag["self_transition_rate"],
            "same_fraction_observed": details["same_fraction_observed"],
            "delta_mean_raw": details["delta_mean_raw"],
            "cutlines_raw": details["cutlines_raw"],
            "cutlines_degenerate": details["cutlines_degenerate"],
            "figure": os.path.basename(path),
        }
    return rows


# -- 2. offset sensitivity -------------------------------------------------

def offset_sensitivity():
    """Shift each signal by 1..sps-1 samples, re-encode, and compare.

    The comparison is element-wise from segment 0: segment i of the shifted
    signal covers samples [s + i*sps, s + (i+1)*sps), against [i*sps,
    (i+1)*sps) unshifted. That is the honest alignment — it asks "if the
    span I selected had started a fraction of a segment later, would I have
    got the same string?", which is exactly the question a researcher
    dragging a viewport is implicitly asking.
    """
    per_dataset = {}
    for ds in ENGINEERED:
        x = ds["x"]
        sps = ds["sps"]
        base, _ = encode(x, sps, **ds["kwargs"])

        candidates = np.arange(1, sps)
        if len(candidates) > MAX_OFFSETS:
            candidates = np.unique(
                np.linspace(1, sps - 1, MAX_OFFSETS).round().astype(int))

        agreements = []
        for shift in candidates:
            shifted = x[int(shift):]
            if len(shifted) // sps < 2:
                continue
            got, _ = encode(shifted, sps, **ds["kwargs"])
            m = min(len(got), len(base))
            agreements.append(float(np.mean(got[:m] == base[:m])))

        per_dataset[ds["name"]] = {
            "id": ds["id"],
            "samples_per_symbol": sps,
            "n_offsets_tested": len(agreements),
            "mean_agreement": float(np.mean(agreements)) if agreements else None,
            "min_agreement": float(np.min(agreements)) if agreements else None,
            "max_agreement": float(np.max(agreements)) if agreements else None,
        }

    means = [v["mean_agreement"] for v in per_dataset.values()
             if v["mean_agreement"] is not None]
    return {
        "per_dataset": per_dataset,
        "overall_mean_agreement": float(np.mean(means)) if means else None,
        "note": ("Measurement, not a pass/fail criterion. See the module "
                 "docstring and IMPLEMENTATION_NOTES.md 'Known limitations'."),
    }


# -- 3. estimator comparison ----------------------------------------------

def estimator_comparison():
    rates = _flip_rates()
    baseline = rates["endpoints"]
    return {
        "signal": ("slow sinusoid whose per-segment rise sweeps through the "
                   "+/-1.0 range against a 0.5 threshold, plus N(0, 0.2) noise"),
        "samples_per_symbol": ROBUSTNESS_SPS,
        "repeats": ROBUSTNESS_REPEATS,
        "flip_rate": {k: float(v) for k, v in rates.items()},
        "flip_rate_relative_to_endpoints": {
            k: (float(v / baseline) if baseline else None) for k, v in rates.items()
        },
    }


# -- 4. Lloyd-Max vs. the noise floor -------------------------------------

def lloydmax_vs_noise_floor():
    """Both half-widths are reported in the NORMALISED delta domain, which
    is the domain `min_same_halfwidth` is specified in when
    `normalize=True`. The surrogate estimate is therefore taken on the
    z-normalised signal, not the raw one — comparing a raw-domain
    half-width against a normalised-domain cutline would be exactly the
    units error the whole `delta_scale` discipline exists to prevent.
    """
    symbols, details = encode(NOISE, NOISE_SPS, threshold_mode="learned")
    learned_halfwidth = float((details["cutlines"][1] - details["cutlines"][0]) / 2.0)

    normalised = (NOISE - NOISE.mean()) / NOISE.std()
    surrogate_halfwidth = surrogate_same_halfwidth(
        normalised, NOISE_SPS, trend_estimator="ols_slope",
        n_surrogates=50, alpha=0.95, random_state=20260809,
    )

    # What the encoding would look like if the noise floor were imposed.
    injected, injected_details = encode(
        NOISE, NOISE_SPS, threshold_mode="learned",
        min_same_halfwidth=surrogate_halfwidth,
    )

    return {
        "signal": f"white Gaussian noise, {len(NOISE)} samples, sps={NOISE_SPS}",
        "domain": "normalised delta units (rise per segment, z-scored signal)",
        "learned_same_halfwidth": learned_halfwidth,
        "learned_same_fraction": float(details["same_fraction_observed"]),
        "learned_histogram": encoding_diagnostics(symbols, 3)["histogram"],
        "surrogate_same_halfwidth_alpha95": float(surrogate_halfwidth),
        "surrogate_over_learned_ratio": (
            float(surrogate_halfwidth / learned_halfwidth) if learned_halfwidth else None),
        "same_fraction_if_noise_floor_injected": float(
            injected_details["same_fraction_observed"]),
        "histogram_if_noise_floor_injected": encoding_diagnostics(injected, 3)["histogram"],
    }


# -- 5. sanity: the encoder is well-defined at every alphabet size --------

def alphabet_sweep():
    """Cheap breadth check that nothing in the cutline pipeline is
    hard-wired to k=3 — the symmetrisation fold behaves differently for odd
    and even alphabets, so both are exercised."""
    out = {}
    for k in (2, 3, 4, 5, 7, 8):
        symbols, details = encode(NOISE[:24000], NOISE_SPS, alphabet_size=k,
                                  threshold_mode="learned")
        diag = encoding_diagnostics(symbols, k)
        out[str(k)] = {
            "cutlines": details["cutlines"],
            "strictly_ascending": bool(np.all(np.diff(details["cutlines"]) > 0))
            if len(details["cutlines"]) > 1 else True,
            "symmetric": bool(np.allclose(details["cutlines"], -details["cutlines"][::-1])),
            "zero_symbol": details["zero_symbol"],
            "occupancy_entropy_fraction": diag["occupancy_entropy_fraction"],
            "histogram": diag["histogram"],
        }
    return out


# -- main ------------------------------------------------------------------

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    started = time.time()

    print("dSAX validation run")
    print("=" * 78)
    print(f"output dir: {OUT_DIR}")

    print("\n[1/5] encoding datasets and writing figures ...")
    datasets = run_datasets()

    print("[2/5] offset sensitivity sweep ...")
    offsets = offset_sensitivity()

    print("[3/5] estimator flip-rate comparison ...")
    estimators = estimator_comparison()

    print("[4/5] Lloyd-Max vs. surrogate noise floor ...")
    noise_floor = lloydmax_vs_noise_floor()

    print("[5/5] alphabet-size sweep ...")
    alphabets = alphabet_sweep()

    metrics = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": round(time.time() - started, 2),
        "estimators_available": list(TREND_ESTIMATORS),
        "datasets": datasets,
        "offset_sensitivity": offsets,
        "estimator_comparison": estimators,
        "lloydmax_vs_noise_floor": noise_floor,
        "alphabet_sweep": alphabets,
    }
    metrics_path = os.path.join(OUT_DIR, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as fh:
        json.dump(_jsonable(metrics), fh, indent=2)

    # -- console summary (ASCII only: the repo's console is cp1252) -------
    print("\n" + "=" * 78)
    print("DATASETS")
    print("=" * 78)
    print(f"{'id':>3}  {'name':<22} {'nsym':>5} {'entropy':>13} {'selftrans':>9}  string")
    for name, row in sorted(datasets.items(), key=lambda kv: kv[1]["id"]):
        entropy = (f"{row['occupancy_entropy_bits']:.2f}/"
                   f"{row['occupancy_entropy_ceiling_bits']:.2f}")
        shown = row["string"] if len(row["string"]) <= 30 else row["string"][:27] + "..."
        print(f"{row['id']:>3}  {name:<22} {row['n_symbols']:>5} {entropy:>13} "
              f"{row['self_transition_rate'] * 100:>8.1f}%  {shown}")

    print("\n" + "=" * 78)
    print("OFFSET SENSITIVITY  (symbol agreement after shifting by 1..sps-1 samples)")
    print("=" * 78)
    for name, row in sorted(offsets["per_dataset"].items(), key=lambda kv: kv[1]["id"]):
        if row["mean_agreement"] is None:
            continue
        print(f"{row['id']:>3}  {name:<22} mean {row['mean_agreement']:.3f}   "
              f"min {row['min_agreement']:.3f}   max {row['max_agreement']:.3f}   "
              f"(sps={row['samples_per_symbol']}, {row['n_offsets_tested']} offsets)")
    print(f"\n  OVERALL mean agreement: {offsets['overall_mean_agreement']:.3f}")
    print("  This is a measurement of a known structural weakness, not a score.")

    print("\n" + "=" * 78)
    print("ESTIMATOR ROBUSTNESS  (symbol-flip rate vs. the noiseless truth)")
    print("=" * 78)
    for est in TREND_ESTIMATORS:
        rate = estimators["flip_rate"][est]
        rel = estimators["flip_rate_relative_to_endpoints"][est]
        print(f"  {est:<18} {rate * 100:6.2f}%   ({rel:.2f}x endpoints)")

    print("\n" + "=" * 78)
    print("LLOYD-MAX vs. NOISE FLOOR  (white noise, normalised delta units)")
    print("=" * 78)
    nf = noise_floor
    print(f"  learned SAME half-width         : {nf['learned_same_halfwidth']:.4f}")
    print(f"  surrogate half-width (alpha=.95): {nf['surrogate_same_halfwidth_alpha95']:.4f}")
    print(f"  ratio surrogate/learned         : {nf['surrogate_over_learned_ratio']:.2f}x")
    print(f"  SAME fraction, learned          : {nf['learned_same_fraction'] * 100:.1f}%")
    print(f"  SAME fraction, noise floor      : "
          f"{nf['same_fraction_if_noise_floor_injected'] * 100:.1f}%")
    print("  Read this as: on a signal with NO trend anywhere, MSE-optimal")
    print("  Lloyd-Max still labels the above non-SAME fraction as UP or DOWN.")

    print("\n" + "=" * 78)
    print(f"metrics written to {metrics_path}")
    print(f"{len(datasets)} figures written to {OUT_DIR}")
    print(f"elapsed {metrics['elapsed_s']} s")

    overall = offsets["overall_mean_agreement"]
    if overall is None or overall <= MIN_OVERALL_OFFSET_AGREEMENT:
        print(f"\nFAILED: overall offset agreement {overall} <= "
              f"{MIN_OVERALL_OFFSET_AGREEMENT} - this is a catastrophic-bug guard, "
              "not a quality bar.")
        raise SystemExit(1)
    print("\nOK")


if __name__ == "__main__":
    main()
