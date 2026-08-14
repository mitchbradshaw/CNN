"""
run_seed_search.py
==================
Adversarial benchmark for the three seeded-motif matchers in
`sax_seed_search.py`, plus negative controls and a real-data run.

    python "Experimentation/Detection experiments/run_seed_search.py"
    python "Experimentation/Detection experiments/run_seed_search.py" --quick
    python "Experimentation/Detection experiments/run_seed_search.py" --no-show --skip-real

What it does, in order
----------------------
1. MINDIST lower-bound verification. This gates everything else: a violated
   bound means the symbol-distance table is wrong and no number below means
   anything.
2. Synthetic adversarial signal: one motif embedded 12 times on a drifting
   baseline, varying in amplitude, time-warp, PAA phase, and SNR, plus 3
   structurally-different decoys designed to look similar but not be similar.
3. The same benchmark run twice - once on the raw drifting signal, once
   detrended. This is the headline comparison, not a side note: with global
   cutlines on a drift-dominated channel a 10-minute motif quantises into 2-3
   of the 8 symbols, because the alphabet is spent describing DC level rather
   than shape. See `detrend`.
4. Precision/recall per matcher, per distortion axis, per SNR; wall clock.
   Marginals are conditional slices of a factorial design, so "recall vs SNR"
   varies only SNR.
5. A baseline-offset experiment: the same motif riding six DC levels. Not one
   of the three requested axes, but on this signal it is the one that decides
   whether any of it works.
6. Negative controls: pure noise, and a phase-randomised surrogate of the real
   channel, which preserves the power spectrum and so is a far harder null.
7. Real data: an "interesting" 10-minute labelled window from the annotations
   database, used as a seed against its own channel, scored against the rest
   of the human labels.

Nothing is saved unless --save-dir is passed. Run from the repo root.
"""

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
# Makes `Working.*` / `Pipelines.*` importable when this file is run directly.
# Walks up to the directory containing Working/, so it survives future moves.
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))
if str(_Path(__file__).resolve().parent) not in _sys.path:
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

import argparse
import time
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from Working.database.schema import get_connection
from Working.database.queries import list_annotations, get_recording_by_id
from Working.Preprocessing.manage_data.load_data import load_raw_data

from multiscale_sax import MultiScaleSAX
from sax_seed_search import (
    Seed, search, verify_mindist_lower_bound, plot_mindist_bound,
    sensible_scales, MATCHERS,
)

FS = 1.0
MOTIF_LEN = 600                 # 10 minutes at 1 Hz - the project's window size
SCALES = (8, 1024)
ALPHABET = 8
SEARCH_SCALES = [8, 16, 32, 64]
MAX_RESULTS = 40
PREC_AT = 12                    # = number of planted instances

# Factorial design. Each distortion axis is varied with the other two held at
# their reference values, so the marginals below are clean slices rather than
# a confounded average.
#   reference cell = amp 1.0, warp 1.0, snr 20 dB  (idx 0)
#            amp   warp  snr_dB   label
INSTANCES = [
    (1.00, 1.00, 20.0, "reference"),
    (1.00, 1.00, 12.0, "snr"),
    (1.00, 1.00,  6.0, "snr"),
    (1.00, 1.00,  3.0, "snr"),
    (0.50, 1.00, 20.0, "amp"),
    (2.00, 1.00, 20.0, "amp"),
    (0.70, 1.00,  6.0, "amp+snr"),
    (1.00, 0.70, 20.0, "warp"),
    (1.00, 0.85, 20.0, "warp"),
    (1.00, 1.20, 20.0, "warp"),
    (1.00, 1.40, 20.0, "warp"),
    (1.00, 1.20,  6.0, "warp+snr"),
]
REF_AMP, REF_WARP, REF_SNR = 1.00, 1.00, 20.0

COLOURS = {"exact": "#b3402f", "mindist": "#3b6ea5", "edit": "#2f6f4f"}
MARKS = {"exact": "s--", "mindist": "o-", "edit": "^-"}


# ──────────────────────────────────────────────────────────────────────────────
#  Preprocessing
# ──────────────────────────────────────────────────────────────────────────────

def detrend(x, window):
    """
    Subtract a centred moving average - a crude high-pass.

    Why this is the headline knob, not a tweak
    -------------------------------------------
    MultiScaleSAX learns one set of cutlines from the whole recording. On a
    channel whose variance is almost entirely slow drift (the measured lag-1
    autocorrelation of M2 CH2 is 0.9999978), those cutlines end up describing
    where the drift currently sits. A 10-minute motif then occupies 2-3 of the
    8 symbols, and WHICH 2-3 depends on the baseline it happens to ride - so
    the same shape at a different DC level gets a different symbol string, and
    flat background at the same level gets the SAME string. Motif search then
    ranks flat regions above real occurrences.

    Removing the local mean at roughly the motif's own timescale makes the
    cutlines describe local shape instead. This belongs in the preprocessing
    stage, not inside the encoder - which is why it lives here and is applied
    to the signal before `MultiScaleSAX` ever sees it.

    `window` should be on the order of the motif length: much shorter and it
    eats the motif itself; much longer and it leaves the drift in.
    """
    window = int(window)
    if window < 3:
        return np.asarray(x, dtype=float).copy()
    x = np.asarray(x, dtype=float)
    k = np.ones(window) / window
    # Edge-pad with the endpoint values so the filter does not manufacture a
    # ramp at the boundaries.
    pad = np.r_[np.full(window // 2, x[0]), x, np.full(window - window // 2 - 1, x[-1])]
    return x - np.convolve(pad, k, mode="valid")[:len(x)]


def rolling_z(x, window):
    """
    Subtract the rolling mean AND divide by the rolling std.

    `detrend` removes the drift's LEVEL; this also removes its local SCALE, so
    what reaches the encoder is local shape alone. On the real channel this is
    what finally gets the alphabet used properly: a 10-minute seed goes from
    2.5 of 8 symbols under `detrend(600)` to 6.9 of 8 here, because the
    cutlines stop being spent on how far the recording has wandered.

    It is the closest this global-cutline encoder can get to classic SAX's
    per-subsequence z-normalisation without abandoning a single shared
    alphabet - and a shared alphabet is the thing that makes symbols
    comparable across scales and channels at all.

    Caveat worth stating: dividing by a rolling std amplifies quiet stretches,
    so a flat region becomes as "structured" as a real event. That is a real
    cost, and it is why this is offered alongside `detrend` rather than
    replacing it.
    """
    window = int(window)
    if window < 3:
        return np.asarray(x, dtype=float).copy()
    x = np.asarray(x, dtype=float)
    k = np.ones(window) / window

    def _pad(a):
        return np.r_[np.full(window // 2, a[0]), a, np.full(window - window // 2 - 1, a[-1])]

    mu = np.convolve(_pad(x), k, mode="valid")[:len(x)]
    var = np.convolve(_pad((x - mu) ** 2), k, mode="valid")[:len(x)]
    # Floor the divisor relative to the global scale so a genuinely flat
    # stretch is not blown up into pure amplified noise.
    return (x - mu) / np.maximum(np.sqrt(var), 1e-6 * np.std(x))


PREPROCESSORS = {"raw": lambda x, w: np.asarray(x, dtype=float).copy(),
                 "detrend": detrend,
                 "rolling_z": rolling_z}


# ──────────────────────────────────────────────────────────────────────────────
#  Synthetic signal
# ──────────────────────────────────────────────────────────────────────────────

def base_motif(length=MOTIF_LEN):
    """
    Asymmetric and internally structured: sharp spike, broad bump carrying a
    ripple, then a dip. Asymmetric on purpose - a symmetric motif would match
    its own time-reverse, which is one of the decoys.
    """
    t = np.linspace(0.0, 1.0, length)
    m = (1.00 * np.exp(-((t - 0.18) / 0.045) ** 2)
         + 0.60 * np.exp(-((t - 0.45) / 0.130) ** 2)
         + 0.32 * np.sin(2 * np.pi * 6 * t) * np.exp(-((t - 0.50) / 0.28) ** 2)
         - 0.55 * np.exp(-((t - 0.80) / 0.090) ** 2))
    return m - m.mean()


def warp_motif(m, factor):
    """Resample to `factor` x its length by linear interpolation."""
    n_new = max(4, int(round(len(m) * factor)))
    return np.interp(np.linspace(0, len(m) - 1, n_new), np.arange(len(m)), m)


def decoys(length=MOTIF_LEN):
    """
    Three structures that look like the motif at a glance but are not it:
    the time-reverse (identical power spectrum), a smooth bump of the same
    envelope with no internal structure, and the motif's own blocks reordered
    (identical value distribution).

    They separate "found something the right size" from "found the motif".
    A matcher firing on all three is measuring amplitude and duration only.
    """
    m = base_motif(length)
    t = np.linspace(0.0, 1.0, length)

    rev = m[::-1].copy()
    bump = 1.05 * np.exp(-((t - 0.5) / 0.17) ** 2)
    bump = bump - bump.mean()
    rng = np.random.default_rng(99)
    blocks = m.reshape(12, -1)
    shuffled = blocks[rng.permutation(12)].ravel()
    return [("reversed", rev), ("smooth_bump", bump), ("block_shuffled", shuffled)]


def make_synthetic(n=180_000, drift_std=1.0, floor_noise=0.02, seed=0,
                   instances=INSTANCES, motif_len=MOTIF_LEN):
    """
    Build the adversarial signal and its ground truth.

    The baseline is a random walk plus slow sinusoids, scaled so drift
    dominates the global distribution - deliberately matching the measured
    character of the real channel, because a benchmark on a stationary
    baseline would flatter every matcher and hide the failure that matters.

    A pristine, noise-free copy of the motif is placed first and used as the
    search seed; it is excluded from scoring.

    Returns (x, truth_df, seed_span).
    """
    rng = np.random.default_rng(seed)

    walk = np.cumsum(rng.normal(0, 1, n))
    walk = walk / walk.std() * drift_std
    t = np.arange(n)
    x = (walk
         + 0.30 * drift_std * np.sin(2 * np.pi * t / 47000)
         + 0.15 * drift_std * np.sin(2 * np.pi * t / 9100)
         + rng.normal(0, floor_noise, n))

    m0 = base_motif(motif_len)
    events = []

    n_slots = 1 + len(instances) + 3
    step = n // (n_slots + 1)
    slots = [step * (k + 1) for k in range(n_slots)]

    p0 = slots[0] + int(rng.integers(0, 64))
    x[p0:p0 + motif_len] += m0
    seed_span = (p0, p0 + motif_len)

    for k, (amp, warp, snr_db, axis) in enumerate(instances):
        mk = amp * warp_motif(m0, warp)
        # Phase relative to the PAA grid: forced odd, so no instance is ever
        # aligned with offset 0 at any dyadic scale.
        pos = slots[1 + k] + int(rng.integers(0, 64)) | 1
        noise_std = np.sqrt(np.mean(mk ** 2)) / (10 ** (snr_db / 20.0))
        x[pos:pos + len(mk)] += mk + rng.normal(0, noise_std, len(mk))
        events.append({"kind": "instance", "idx": k, "start": pos,
                       "end": pos + len(mk), "amp": amp, "warp": warp,
                       "snr_db": snr_db, "axis": axis})

    for k, (name, d) in enumerate(decoys(motif_len)):
        pos = slots[1 + len(instances) + k] + int(rng.integers(0, 64))
        x[pos:pos + len(d)] += d
        events.append({"kind": "decoy", "idx": k, "start": pos,
                       "end": pos + len(d), "amp": 1.0, "warp": 1.0,
                       "snr_db": np.nan, "axis": name})

    return x, pd.DataFrame(events), seed_span


def phase_randomised(x, seed=0):
    """
    Surrogate with the same power spectrum but destroyed phase relationships.

    The correct null for a drift-dominated signal: white noise is trivially
    distinguishable from a 1/f-ish channel, so a matcher could score zero false
    hits on white noise purely by preferring smooth things. This keeps the
    smoothness and removes only the structure.
    """
    rng = np.random.default_rng(seed)
    n = len(x)
    f = np.fft.rfft(x - x.mean())
    ph = rng.uniform(0, 2 * np.pi, len(f))
    ph[0] = 0.0
    if n % 2 == 0:
        ph[-1] = 0.0
    out = np.fft.irfft(np.abs(f) * np.exp(1j * ph), n=n)
    return out / out.std() * x.std() + x.mean()


# ──────────────────────────────────────────────────────────────────────────────
#  Scoring
# ──────────────────────────────────────────────────────────────────────────────

def score_hits(hits, truth, tolerance=0.5):
    """
    Attribute each hit to a ground-truth event.

    A hit counts for an event when the hit's CENTRE falls inside the event's
    span, widened by `tolerance` of the event length each side. Centre-based
    rather than IoU-based because the edit matcher deliberately returns spans
    of a different length from the seed; scoring on overlap fraction would
    penalise exactly the behaviour it exists to provide.
    """
    hits = hits.copy()
    hits["hit_kind"] = "false"
    hits["event_idx"] = -1
    hits["axis"] = ""
    if hits.empty:
        return hits, {}

    centre = 0.5 * (hits["start_sample"] + hits["end_sample"])
    found = {}
    for _, ev in truth.iterrows():
        pad = tolerance * (ev["end"] - ev["start"])
        m = (centre >= ev["start"] - pad) & (centre <= ev["end"] + pad)
        hits.loc[m, "hit_kind"] = ev["kind"]
        hits.loc[m, "event_idx"] = ev["idx"]
        hits.loc[m, "axis"] = ev["axis"]
        if ev["kind"] == "instance":
            found[int(ev["idx"])] = bool(m.any())
    return hits, found


def evaluate(hits, truth, n_instances):
    """
    Summarise one hit list.

    Reports precision@k alongside the F1-optimal threshold because plain
    precision over a fixed `max_results` is bounded by n_instances/max_results
    and says more about the cap than about the matcher. precision@12 - "of the
    12 best hits, how many are real" - is the number a user actually
    experiences.
    """
    if hits.empty:
        return {"n_hits": 0, "recall": 0.0, "precision": 0.0, "f1": 0.0,
                "prec_at_k": 0.0, "decoy_hits": 0, "threshold": np.nan,
                "found": {}}

    labelled, _ = score_hits(hits, truth)
    top = labelled.nsmallest(PREC_AT, "distance")
    prec_at_k = float((top["hit_kind"] == "instance").sum()) / max(len(top), 1)

    best = None
    # Candidate thresholds are the realised distances themselves, unrounded:
    # rounding can land just below the true minimum and select nothing.
    for thr in np.unique(labelled["distance"].to_numpy()):
        sub = labelled[labelled["distance"] <= thr]
        if sub.empty:
            continue
        _, found = score_hits(sub, truth)
        tp_events = sum(found.values())
        n_true = int((sub["hit_kind"] == "instance").sum())
        precision = n_true / len(sub)
        recall = tp_events / n_instances
        f1 = (2 * precision * recall / (precision + recall)
              if (precision + recall) > 0 else 0.0)
        if best is None or f1 > best["f1"]:
            best = {"n_hits": len(sub), "recall": recall, "precision": precision,
                    "f1": f1, "prec_at_k": prec_at_k,
                    "decoy_hits": int((sub["hit_kind"] == "decoy").sum()),
                    "threshold": float(thr), "found": found}
    return best


def marginal(truth, found, axis_name):
    """
    Conditional slice of the factorial design: vary one axis, hold the others
    at their reference values. Returns {level: hit(0/1)}.
    """
    out = {}
    for _, ev in truth[truth["kind"] == "instance"].iterrows():
        if axis_name == "snr":
            ok = ev["amp"] == REF_AMP and ev["warp"] == REF_WARP
            level = float(ev["snr_db"])
        elif axis_name == "warp":
            ok = ev["amp"] == REF_AMP and ev["snr_db"] == REF_SNR
            level = float(ev["warp"])
        else:
            ok = ev["warp"] == REF_WARP and ev["snr_db"] == REF_SNR
            level = float(ev["amp"])
        if ok:
            out[level] = 1.0 if found.get(int(ev["idx"]), False) else 0.0
    return out


# ──────────────────────────────────────────────────────────────────────────────
#  Runners
# ──────────────────────────────────────────────────────────────────────────────

def rule(title):
    print("\n" + "=" * 78)
    print(f"  {title}")
    print("=" * 78)


def matcher_kwargs_for(matcher):
    """
    `exact` is run as a full scan so its mismatch RATE is available to the
    threshold sweep. A production exact search sets a small max_hamming and is
    far faster; that variant is timed separately in the speed table.
    """
    return {"max_hamming": 10 ** 6} if matcher == "exact" else {}


def run_matcher(msax, seed, matcher, scales, max_results=MAX_RESULTS,
                offsets="computed"):
    t0 = time.perf_counter()
    hits = search(msax, seed, matcher=matcher, scales=scales, offsets=offsets,
                  max_results=max_results,
                  matcher_kwargs=matcher_kwargs_for(matcher))
    return hits, time.perf_counter() - t0


def build_pyramid(sig, offsets="all"):
    return MultiScaleSAX(sig, fs=FS, method="psax", scales=SCALES,
                         alphabet_size=ALPHABET,
                         cutline_mode="shared_renormalised",
                         offsets=offsets, max_offsets=8, random_state=0)


def one_condition(x, truth, seed_span, tag, scales_wanted=SEARCH_SCALES,
                  verbose=True):
    """Run all three matchers over one preprocessed signal."""
    msax = build_pyramid(x)
    msax.channel = 0
    scales = [s for s in scales_wanted if s in msax.scales]
    seed_scale = scales[min(1, len(scales) - 1)]
    seed = Seed.from_span(msax, seed_span[0], seed_span[1], scale=seed_scale,
                          seed_id=f"motif_{tag}")
    n_inst = int((truth["kind"] == "instance").sum())

    hist = np.bincount(seed.symbols[seed.symbols >= 0], minlength=ALPHABET)
    if verbose:
        print(f"  seed at sps={seed_scale}: {len(seed)} symbols, "
              f"{np.count_nonzero(hist)}/{ALPHABET} of the alphabet used, "
              f"histogram {hist.tolist()}")

    out = {}
    for matcher in MATCHERS:
        hits, secs = run_matcher(msax, seed, matcher, scales)
        ev = evaluate(hits, truth, n_inst)
        ev.update({"matcher": matcher, "secs": secs, "hits": hits})
        out[matcher] = ev
    return {"msax": msax, "seed": seed, "scales": scales, "results": out,
            "n_inst": n_inst, "seed_symbols_used": int(np.count_nonzero(hist))}


def synthetic_benchmark(args):
    rule("SYNTHETIC ADVERSARIAL BENCHMARK")
    n = 60_000 if args.quick else 180_000
    repeats = 1 if args.quick else args.repeats
    print(f"  {repeats} independent signal(s) x {n} samples ({n/3600:.1f} h each)")
    print(f"  12 instances + 3 decoys; seed = a pristine copy, excluded from scoring")
    print(f"  conditions: raw drifting signal, and detrended (moving average "
          f"over {args.detrend_window} samples)")

    conditions = ["raw", f"detrend({args.detrend_window})",
                  f"rolling_z({args.detrend_window})"]
    agg = {c: defaultdict(list) for c in conditions}
    marg = {c: {m: {"snr": defaultdict(list), "warp": defaultdict(list),
                    "amp": defaultdict(list)} for m in MATCHERS}
            for c in conditions}
    keep = {}

    for rep in range(repeats):
        x, truth, seed_span = make_synthetic(n=n, seed=args.seed + rep)
        sigs = {conditions[0]: x,
                conditions[1]: detrend(x, args.detrend_window),
                conditions[2]: rolling_z(x, args.detrend_window)}
        for cond, sig in sigs.items():
            if rep == 0:
                print(f"\n  --- {cond} ---")
            res = one_condition(sig, truth, seed_span, cond,
                                verbose=(rep == 0))
            if rep == 0:
                keep[cond] = {"res": res, "x": sig, "truth": truth,
                              "seed_span": seed_span}
            for m, ev in res["results"].items():
                for k in ("recall", "precision", "f1", "prec_at_k",
                          "decoy_hits", "secs", "threshold"):
                    agg[cond][(m, k)].append(ev[k])
                for ax in ("snr", "warp", "amp"):
                    for lev, v in marginal(truth, ev["found"], ax).items():
                        marg[cond][m][ax][lev].append(v)

    # ── Headline table ────────────────────────────────────────────────────────
    rule("HEADLINE: RAW vs DETRENDED (mean over repeats, at best-F1 threshold)")
    print(f"  {'condition':>18} {'matcher':>8} {'recall':>7} {'prec@12':>8} "
          f"{'F1':>6} {'decoy':>6} {'thr':>7} {'secs':>7}")
    for cond in conditions:
        for m in MATCHERS:
            g = agg[cond]
            print(f"  {cond:>18} {m:>8} "
                  f"{np.mean(g[(m,'recall')]):>7.3f} "
                  f"{np.mean(g[(m,'prec_at_k')]):>8.3f} "
                  f"{np.mean(g[(m,'f1')]):>6.3f} "
                  f"{np.mean(g[(m,'decoy_hits')]):>6.1f} "
                  f"{np.mean(g[(m,'threshold')]):>7.3f} "
                  f"{np.mean(g[(m,'secs')]):>7.2f}")
        print()

    # ── Per-scale, detrended only ─────────────────────────────────────────────
    cond = conditions[1]
    rule(f"PRECISION / RECALL BY SCALE ({cond})")
    x, truth, seed_span = make_synthetic(n=n, seed=args.seed)
    sig = detrend(x, args.detrend_window)
    msax = build_pyramid(sig)
    msax.channel = 0
    scales = [s for s in SEARCH_SCALES if s in msax.scales]
    n_inst = int((truth["kind"] == "instance").sum())
    print(f"  {'matcher':>8} {'sps':>6} {'w':>5} {'recall':>7} {'prec@12':>8} "
          f"{'F1':>6} {'decoy':>6} {'secs':>7}")
    for m in MATCHERS:
        for s in scales:
            sd = Seed.from_span(msax, seed_span[0], seed_span[1], scale=s)
            hits, secs = run_matcher(msax, sd, m, [s])
            ev = evaluate(hits, truth, n_inst)
            print(f"  {m:>8} {s:>6} {len(sd):>5} {ev['recall']:>7.3f} "
                  f"{ev['prec_at_k']:>8.3f} {ev['f1']:>6.3f} "
                  f"{ev['decoy_hits']:>6} {secs:>7.2f}")

    # ── Recovery grid ─────────────────────────────────────────────────────────
    rule(f"RECOVERY BY INSTANCE ({cond}, first repeat)")
    res = keep[cond]["res"]
    tr = keep[cond]["truth"]
    print(f"  {'idx':>3} {'axis':>10} {'amp':>5} {'warp':>5} {'snr':>4}  "
          + " ".join(f"{m:>8}" for m in MATCHERS))
    for _, ev in tr[tr["kind"] == "instance"].iterrows():
        marks = " ".join(
            f"{('HIT' if res['results'][m]['found'].get(int(ev['idx'])) else '.'):>8}"
            for m in MATCHERS)
        print(f"  {int(ev['idx']):>3} {ev['axis']:>10} {ev['amp']:>5.2f} "
              f"{ev['warp']:>5.2f} {ev['snr_db']:>4.0f}  {marks}")

    # ── Conditional marginals ─────────────────────────────────────────────────
    rule(f"CONDITIONAL MARGINALS ({cond}) - one axis varied, others at reference")
    tabs = {}
    for ax, unit in [("snr", "dB"), ("warp", "x"), ("amp", "x")]:
        levels = sorted({l for m in MATCHERS for l in marg[cond][m][ax]})
        tabs[ax] = {m: {l: float(np.mean(marg[cond][m][ax][l]))
                        for l in levels if marg[cond][m][ax][l]}
                    for m in MATCHERS}
        print(f"\n  recall vs {ax} ({unit})")
        print(f"  {'matcher':>8} " + " ".join(f"{l:>7.2f}" for l in levels))
        for m in MATCHERS:
            print(f"  {m:>8} " + " ".join(
                f"{tabs[ax][m].get(l, np.nan):>7.2f}" for l in levels))

    return {"conditions": conditions, "agg": agg, "tabs": tabs, "keep": keep,
            "detrend_window": args.detrend_window}


def baseline_offset_experiment(args):
    """
    The same motif riding six different DC levels, run raw and detrended.

    This is the direct proof of the drift argument: with global cutlines the
    seed's symbols encode its baseline, so copies at other baselines are
    invisible. Detrending should recover them.
    """
    rule("BASELINE-OFFSET EXPERIMENT (global cutlines vs DC level)")
    n = 40_000 if args.quick else 90_000
    rng = np.random.default_rng(5)
    x = rng.normal(0, 0.02, n)
    m0 = base_motif()
    levels = [-2.0, -1.0, -0.3, 0.3, 1.0, 2.0]
    seed_level_idx = 3
    step = n // (len(levels) + 2)
    events = []
    for k, lev in enumerate(levels):
        pos = step * (k + 1) + 37
        x[pos - 300:pos + MOTIF_LEN + 300] += lev
        x[pos:pos + MOTIF_LEN] += m0
        events.append({"kind": "instance", "idx": k, "start": pos,
                       "end": pos + MOTIF_LEN, "amp": 1.0, "warp": 1.0,
                       "snr_db": np.nan, "axis": f"level{lev:+.1f}"})
    truth = pd.DataFrame(events)
    others = [l for i, l in enumerate(levels) if i != seed_level_idx]
    print(f"  seed from the level{levels[seed_level_idx]:+.1f} copy; "
          f"5 others to find at levels {[f'{l:+.1f}' for l in others]}")

    print(f"\n  {'condition':>18} {'matcher':>8} {'seed alphabet':>14} "
          f"{'recall':>7}  found at levels")
    for cond, sig in [("raw", x),
                      (f"detrend({args.detrend_window})", detrend(x, args.detrend_window)),
                      (f"rolling_z({args.detrend_window})", rolling_z(x, args.detrend_window))]:
        msax = build_pyramid(sig)
        msax.channel = 0
        sc = [s for s in SEARCH_SCALES if s in msax.scales]
        ev0 = events[seed_level_idx]
        for matcher in MATCHERS:
            sd = Seed.from_span(msax, ev0["start"], ev0["end"], scale=sc[1])
            used = int(np.count_nonzero(np.bincount(sd.symbols, minlength=ALPHABET)))
            hits, _ = run_matcher(msax, sd, matcher, sc, max_results=30)
            ev = evaluate(hits, truth, len(levels) - 1)
            got = [f"{levels[i]:+.1f}" for i, v in sorted(ev["found"].items())
                   if v and i != seed_level_idx]
            print(f"  {cond:>18} {matcher:>8} {f'{used}/{ALPHABET}':>14} "
                  f"{len(got)/(len(levels)-1):>7.2f}  {got or '-'}")


def negative_controls(args, bench):
    """
    Same seed, same thresholds, on signals containing no motif at all.

    Reported as false hits per hour, which is what decides whether a threshold
    survives 282 hours of real recording: a rate that looks acceptable over 50
    synthetic hours can still bury every real result.
    """
    rule("NEGATIVE CONTROLS (false hits/hour at each matcher's operating threshold)")
    n = 60_000 if args.quick else 180_000
    rng = np.random.default_rng(21)
    cond = bench["conditions"][1]                      # detrended thresholds
    seed_span = bench["keep"][cond]["seed_span"]

    controls = {"white_noise": rng.normal(0, 1, n)}
    try:
        real, _ = load_raw_data("M2_concat_fs1_CH2.npy", FS)
        controls["phase_rand_real"] = phase_randomised(real[:n], seed=3)
    except Exception as exc:                                   # noqa: BLE001
        print(f"  (skipping surrogate control: {exc})")

    print(f"  thresholds taken from the {cond} condition")
    print(f"  {'control':>18} {'matcher':>8} {'thr':>7} {'hits':>6} {'per hour':>9}")
    for cname, cx in controls.items():
        cx = detrend(cx, args.detrend_window)
        cms = build_pyramid(cx)
        cms.channel = 0
        sc = [s for s in SEARCH_SCALES if s in cms.scales]
        hours = len(cx) / FS / 3600.0
        for matcher in MATCHERS:
            thr = float(np.mean(bench["agg"][cond][(matcher, "threshold")]))
            # The seed is re-encoded against THIS pyramid's cutlines, exactly
            # as a real cross-recording search would have to do.
            sd = Seed.from_span(cms, seed_span[0], seed_span[1], scale=sc[1])
            hits = search(cms, sd, matcher=matcher, scales=sc, offsets="computed",
                          max_results=10 ** 6,
                          matcher_kwargs=matcher_kwargs_for(matcher),
                          threshold=thr)
            print(f"  {cname:>18} {matcher:>8} {thr:>7.3f} {len(hits):>6} "
                  f"{len(hits)/hours:>9.2f}")


def real_data_run(args):
    """Seed from an 'interesting' labelled 10-minute window in the database."""
    rule("REAL DATA: seed from an 'interesting' labelled 10-minute window")
    db = _REPO_ROOT / "DATA" / "db" / "annotations.sqlite"
    if not db.exists():
        print(f"  SKIPPED: no database at {db}")
        return

    conn = get_connection(str(db))
    rec = get_recording_by_id(conn, args.recording_id)
    if rec is None:
        print(f"  SKIPPED: no recording with id={args.recording_id}")
        return
    npy = _REPO_ROOT / rec["npy_path"]
    if not npy.exists():
        print(f"  SKIPPED: channel file missing: {npy}")
        return

    anns = list(list_annotations(conn, args.recording_id))
    interesting = [a for a in anns
                   if a["verdict"] == "interesting"
                   and (a["end_idx"] - a["start_idx"]) == MOTIF_LEN]
    if not interesting:
        print(f"  SKIPPED: recording {args.recording_id} has no "
              f"{MOTIF_LEN}-sample 'interesting' annotation")
        return

    x = np.load(npy)
    n_not = sum(1 for a in anns if a["verdict"] == "not_interesting")
    print(f"  recording {rec['id']}: {rec['source_file']} CH{rec['channel']}, "
          f"{len(x)} samples ({len(x)/FS/3600:.0f} h)")
    print(f"  {len(interesting)} interesting 10-min windows, {n_not} not-interesting")

    ann = interesting[args.ann_index % len(interesting)]
    s0, s1 = int(ann["start_idx"]), int(ann["end_idx"])
    print(f"  seed = annotation {ann['id']} at [{s0}, {s1}) = {s0/FS/3600:.2f} h")

    lab = defaultdict(list)
    for a in anns:
        if a["verdict"] in ("interesting", "not_interesting"):
            lab[a["verdict"]].append((int(a["start_idx"]), int(a["end_idx"])))

    def label_of(a0, a1):
        c = 0.5 * (a0 + a1)
        for v, spans in lab.items():
            for b0, b1 in spans:
                if b0 <= c < b1:
                    return v
        return "unlabelled"

    # Base rate: what fraction of LABELLED windows are interesting? Any hit
    # rate at or below this is no better than picking labelled windows at
    # random, which is the comparison that makes the numbers mean anything.
    base = len(lab["interesting"]) / max(len(lab["interesting"]) + len(lab["not_interesting"]), 1)
    print(f"  base rate: {base:.3f} of labelled windows are 'interesting'")

    for cond, sig in [("raw", x),
                      (f"detrend({args.detrend_window})", detrend(x, args.detrend_window)),
                      (f"rolling_z({args.detrend_window})", rolling_z(x, args.detrend_window))]:
        msax = build_pyramid(sig)
        msax.channel = int(rec["channel"])
        scales = sensible_scales(msax, s1 - s0)
        seed = Seed.from_span(msax, s0, s1, scale=scales[min(1, len(scales) - 1)],
                              seed_id=f"ann{ann['id']}")
        used = int(np.count_nonzero(np.bincount(seed.symbols, minlength=ALPHABET)))
        print(f"\n  --- {cond} --- scales {scales}, seed uses {used}/{ALPHABET} symbols")
        print(f"  {'matcher':>8} {'hits':>5} {'secs':>7} {'interesting':>12} "
              f"{'not_int':>8} {'unlab':>7} {'hit rate':>9}  top-5 (hours)")
        for matcher in MATCHERS:
            t0 = time.perf_counter()
            hits = search(msax, seed, matcher=matcher, scales=scales,
                          offsets="computed", max_results=25,
                          matcher_kwargs=matcher_kwargs_for(matcher))
            secs = time.perf_counter() - t0
            if hits.empty:
                print(f"  {matcher:>8} {0:>5} {secs:>7.2f}")
                continue
            labels = [label_of(r.start_sample, r.end_sample)
                      for r in hits.itertuples()]
            n_i, n_ni = labels.count("interesting"), labels.count("not_interesting")
            rate = n_i / max(n_i + n_ni, 1)
            top = ", ".join(f"{r.start_sample/FS/3600:.1f}"
                            for r in hits.head(5).itertuples())
            print(f"  {matcher:>8} {len(hits):>5} {secs:>7.2f} {n_i:>12} {n_ni:>8} "
                  f"{labels.count('unlabelled'):>7} {rate:>9.3f}  {top}")

    conn.close()


def speed_table(args, bench):
    """Wall clock on a realistic full-channel search, warm (JIT excluded)."""
    rule("WALL CLOCK: full 282 h real channel, one seed, all sensible scales")
    try:
        x, _ = load_raw_data("M2_concat_fs1_CH2.npy", FS)
    except Exception as exc:                                   # noqa: BLE001
        print(f"  SKIPPED: {exc}")
        return
    sig = detrend(x, args.detrend_window)
    msax = build_pyramid(sig)
    msax.channel = 2
    scales = sensible_scales(msax, MOTIF_LEN)
    seed = Seed.from_span(msax, 400_000, 400_000 + MOTIF_LEN,
                          scale=scales[min(1, len(scales) - 1)])
    print(f"  {len(x)} samples, scales {scales}, "
          f"{sum(len(msax.offsets_for(s)) for s in scales)} (scale, offset) passes")
    print(f"  {'matcher':>8} {'variant':>22} {'secs':>8} {'hits':>6}")
    for matcher in MATCHERS:
        for variant, kw in ([("full scan", {"max_hamming": 10 ** 6}),
                             ("max_hamming=2", {"max_hamming": 2})]
                            if matcher == "exact" else [("-", {})]):
            search(msax, seed, matcher=matcher, scales=scales[:1],
                   offsets="zero", max_results=5, matcher_kwargs=kw)   # warm JIT
            t0 = time.perf_counter()
            hits = search(msax, seed, matcher=matcher, scales=scales,
                          offsets="computed", max_results=25, matcher_kwargs=kw)
            print(f"  {matcher:>8} {variant:>22} "
                  f"{time.perf_counter()-t0:>8.2f} {len(hits):>6}")


# ──────────────────────────────────────────────────────────────────────────────
#  Plots
# ──────────────────────────────────────────────────────────────────────────────

def plot_recall_curves(tabs, figsize=(13, 4.4)):
    """Recall vs SNR, vs time-warp, and vs amplitude - one line per matcher."""
    fig, axes = plt.subplots(1, 3, figsize=figsize, layout="constrained")
    specs = [("snr", "SNR (dB)  -  harder to the left", True),
             ("warp", "time-warp factor", False),
             ("amp", "amplitude factor", False)]
    for ax, (key, xlabel, invert) in zip(axes, specs):
        for m in MATCHERS:
            d = tabs.get(key, {}).get(m, {})
            if not d:
                continue
            xs = sorted(d)
            ax.plot(xs, [d[k] for k in xs], MARKS[m], color=COLOURS[m],
                    label=m, lw=1.8, ms=6)
        if key != "snr":
            ax.axvline(1.0, color="0.5", ls=":", lw=1.2)
        if invert:
            ax.invert_xaxis()
        ax.set_xlabel(xlabel, fontsize=9)
        ax.set_ylabel("recall")
        ax.set_ylim(-0.05, 1.08)
        ax.grid(alpha=0.25, lw=0.5)
        ax.legend(fontsize=8)
        ax.set_title(f"Recall vs {key}", fontsize=10, loc="left")
    return fig


def plot_condition_comparison(agg, conditions, figsize=(9.5, 4.6)):
    """Raw vs detrended, side by side, for recall and precision@12."""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=figsize, layout="constrained")
    w = 0.35
    xs = np.arange(len(MATCHERS))
    for k, cond in enumerate(conditions):
        off = (k - 0.5) * w
        a1.bar(xs + off, [np.mean(agg[cond][(m, "recall")]) for m in MATCHERS],
               width=w, label=cond)
        a2.bar(xs + off, [np.mean(agg[cond][(m, "prec_at_k")]) for m in MATCHERS],
               width=w, label=cond)
    for ax, title in ((a1, "recall"), (a2, f"precision@{PREC_AT}")):
        ax.set_xticks(xs)
        ax.set_xticklabels(list(MATCHERS))
        ax.set_ylim(0, 1.05)
        ax.grid(axis="y", alpha=0.25, lw=0.5)
        ax.legend(fontsize=8)
        ax.set_title(title, fontsize=10, loc="left")
    fig.suptitle("Detrending is the difference between working and not working",
                 fontsize=10, x=0.01, ha="left")
    return fig


def plot_synthetic_overview(x, truth, results, figsize=(13.5, 6.4)):
    n_rows = 1 + len(results)
    fig, axes = plt.subplots(n_rows, 1, figsize=figsize, sharex=True,
                             gridspec_kw={"height_ratios": [2.4] + [1] * len(results)},
                             layout="constrained")
    hrs = np.arange(len(x)) / FS / 3600.0
    ax = axes[0]
    ax.plot(hrs, x, lw=0.4, color="0.25")
    for _, ev in truth.iterrows():
        ax.axvspan(ev["start"] / 3600, ev["end"] / 3600,
                   color="#2f6f4f" if ev["kind"] == "instance" else "#b3402f",
                   alpha=0.18)
    ax.set_ylabel("signal")
    ax.margins(x=0)
    ax.set_title("Synthetic adversarial signal - green = instance, red = decoy",
                 fontsize=10, loc="left")

    for ax, (m, ev) in zip(axes[1:], results.items()):
        for _, e in truth.iterrows():
            ax.axvspan(e["start"] / 3600, e["end"] / 3600,
                       color="#2f6f4f" if e["kind"] == "instance" else "#b3402f",
                       alpha=0.18)
        h = ev["hits"]
        if not h.empty:
            ax.scatter(0.5 * (h["start_sample"] + h["end_sample"]) / 3600,
                       h["distance"], s=16, color=COLOURS[m], zorder=3)
            if np.isfinite(ev["threshold"]):
                ax.axhline(ev["threshold"], color=COLOURS[m], ls=":", lw=1.1)
        ax.set_ylabel(f"{m}\ndistance", fontsize=8)
        ax.grid(alpha=0.2, lw=0.5)
        ax.margins(x=0)
    axes[-1].set_xlabel("time (hours)")
    return fig


# ──────────────────────────────────────────────────────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(description="Seeded SAX motif-search benchmark.")
    p.add_argument("--quick", action="store_true",
                   help="Shorter signals, 1 repeat; for iterating, not for conclusions.")
    p.add_argument("--repeats", type=int, default=3,
                   help="Independent synthetic signals to average over (default 3). "
                        "One instance per design cell, so a single repeat gives "
                        "binary marginals rather than rates.")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--detrend-window", type=int, default=MOTIF_LEN,
                   help="Moving-average window for the detrended condition.")
    p.add_argument("--recording-id", type=int, default=3,
                   help="Annotations DB recording id for the real-data run "
                        "(default 3 = M2_aug_concat_fs1 CH2).")
    p.add_argument("--ann-index", type=int, default=0)
    p.add_argument("--skip-real", action="store_true")
    p.add_argument("--skip-controls", action="store_true")
    p.add_argument("--skip-speed", action="store_true")
    p.add_argument("--no-show", action="store_true")
    p.add_argument("--save-dir", default=None,
                   help="Directory for the figures. Nothing is written without it.")
    args = p.parse_args(argv)

    # ── 1. Lower-bound verification gates everything else ─────────────────────
    rule("MINDIST LOWER-BOUND VERIFICATION")
    xv, _, _ = make_synthetic(n=60_000, seed=args.seed)
    mv = build_pyramid(detrend(xv, args.detrend_window), offsets="zero")
    print(f"  {'sps':>6} {'pairs':>7} {'w':>4} {'violations':>11} {'worst':>10} "
          f"{'tightness':>10} {'p95':>7}")
    vres = []
    for s in mv.scales:
        r = verify_mindist_lower_bound(mv, s, n_pairs=5000, random_state=1)
        vres.append(r)
        print(f"  {s:>6} {r['n_pairs']:>7} {r['w']:>4} {r['n_violations']:>11} "
              f"{r['worst_violation']:>10.5f} {r['ratio_mean']:>10.4f} "
              f"{r['ratio_p95']:>7.3f}")
    total_viol = sum(r["n_violations"] for r in vres)
    assert total_viol == 0, (
        f"MINDIST lower bound VIOLATED in {total_viol} pairs - the symbol "
        f"distance table is wrong. Fix the table; do not add a fudge factor."
    )
    print(f"  -> bound holds on all {sum(r['n_pairs'] for r in vres)} pairs; "
          f"mean tightness {np.mean([r['ratio_mean'] for r in vres]):.3f} "
          f"(1.0 exact; low means weak pruning)")
    figs = {"mindist_bound": plot_mindist_bound(vres)}

    # ── 2-4. Synthetic benchmark ──────────────────────────────────────────────
    bench = synthetic_benchmark(args)
    figs["recall_curves"] = plot_recall_curves(bench["tabs"])
    figs["conditions"] = plot_condition_comparison(bench["agg"],
                                                   bench["conditions"])
    cond = bench["conditions"][1]
    figs["synthetic"] = plot_synthetic_overview(
        bench["keep"][cond]["x"], bench["keep"][cond]["truth"],
        bench["keep"][cond]["res"]["results"])

    # ── 5. Baseline offset ────────────────────────────────────────────────────
    baseline_offset_experiment(args)

    # ── 6. Negative controls ──────────────────────────────────────────────────
    if not args.skip_controls:
        negative_controls(args, bench)

    # ── 7. Real data + speed ──────────────────────────────────────────────────
    if not args.skip_real:
        real_data_run(args)
    if not args.skip_speed:
        speed_table(args, bench)

    if args.save_dir:
        rule("SAVE")
        out = _Path(args.save_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name, fig in figs.items():
            path = out / f"seed_search_{name}.png"
            fig.savefig(path, dpi=140, bbox_inches="tight")
            print(f"  {name:>16} -> {path}")

    if not args.no_show:
        plt.show()
    return bench, figs


if __name__ == "__main__":
    main()
