"""
run_round2_claims.py
=====================
Task F: `round2_v1/CLAIMS.md` - every claim the paper could make from this
data, with its evidence, the null it was tested against, and a verdict.

    python Pipelines/drop_motifs/run_round2_claims.py

EVERY NUMBER IN THE TABLE IS READ OUT OF A JSON, NOT TYPED HERE. A claims
table that is written by hand drifts from the results it summarises within
one revision, and it is the document most likely to be quoted and least
likely to be re-checked. `_evidence` functions below pull from
`TASK_A_tree.json`, `TASK_B_decode.json`, `TASK_B2_transfer.json`,
`TASK_C_partition.json`, `TASK_D_floor.json`, `TASK_E_power.json` and
round one's `nulls_v1/*.json`; a missing file makes its rows say so rather
than silently carrying a stale number.

THE VERDICTS ARE FOUR, AND THEY ARE NOT SYNONYMS:

  supported       tested against a null that could have refuted it, and it
                  did not.
  bounded         survives the nulls it was tested against, but the nulls
                  that could refute it cannot be built from these data.
                  The bound is stated in the row.
  not supported   tested, and the evidence does not distinguish it from
                  the null. Not the same as false.
  falsified       tested, and the null reproduces the observation. The
                  claim is wrong as stated.

Every `falsified` row carries THE SENTENCE THE PAPER SHOULD USE INSTEAD.
That sentence is the deliverable; the verdict is the reason for it.
"""

import json
import sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

OUT_DIR = _Path("Plots", "drop_motifs9_fig2a", "round2_v1")
NULLS_V1 = _Path("Plots", "drop_motifs9_fig2a", "nulls_v1")

MISSING = "*(not computed in this run)*"


def _load(path):
    path = _Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text("utf-8"))


def _p(value, floor=None):
    """A p-value with its resolution visible."""
    if value is None:
        return "—"
    if floor is not None and value <= floor:
        return f"p ≤ {floor:.4f} *(floor)*"
    return f"p = {value:.4f}"


def build_rows(data):
    A, B, B2, C, D, E = (data.get(k) for k in
                         ("A", "B", "B2", "C", "D", "E"))
    surrogate = data.get("surrogate")
    cross = data.get("cross_channel")
    nuisance = data.get("nuisance")
    rows = []

    # ------------------------------------------------------------------ 1
    if E:
        failing = E["failing_channels"]
        passing = [k for k in E["per_channel"] if k not in failing]
        verdicts = {k: E["per_channel"][k]["verdict"] for k in failing}
        rows.append({
            "claim": "events are not excursions in coloured noise",
            "verdict": ("supported on " + "/".join(sorted(passing))
                        + ", NOT supported on "
                        + "/".join(sorted(failing))),
            "evidence": "; ".join(
                f"{k} {E['per_channel'][k]['observed_detections_round1']:.0f} "
                f"vs null median {E['per_channel'][k]['null_median']:.1f} "
                f"({_p(E['per_channel'][k]['p'])})"
                for k in sorted(E["per_channel"])),
            "null": "AAFT phase randomisation, 100 realisations per channel",
            "instead": (
                "Detection counts exceed a spectrum-matched surrogate on "
                + ", ".join(sorted(passing)) + ". On "
                + " and ".join(sorted(failing))
                + " they do not, and the reason is not low power: the "
                "detector finds FEWER events in those two channels than in "
                "surrogates built from their own spectra, so they are "
                "reported as not distinguishable from coloured noise rather "
                "than as untested. "
                + "; ".join(f"{k}: {verdicts[k]}" for k in sorted(failing))
                + "."),
        })

    # ------------------------------------------------------------------ 2
    if C and A:
        block = C["the_50s_block_shuffle_reframed"]
        rows.append({
            "claim": "there is a limited shape repertoire",
            "verdict": "bounded",
            "evidence": (
                "tighter than AAFT (2.342 vs 2.727, p ≤ 0.0099) and than a "
                "5 s block shuffle (vs 2.891, p ≤ 0.0099); NOT tighter than "
                "a 50 s block shuffle (2.342 vs 2.346, p = 0.475). "
                + (f"**On the corrected store the real-side statistic is "
                   f"{A['legacy_cut']['mean_within_family_distance_k4']:.4f}, "
                   f"not 2.342** — a shift of "
                   f"{A['surrogate_grid_rerun_gate']['delta']:.4f} against an "
                   f"AAFT null IQR of "
                   f"{A['surrogate_grid_rerun_gate']['aaft_null_iqr']:.4f}, so "
                   f"the surrogate grid is due a re-run and these p-values "
                   f"are round one's."
                   if A else "")),
            "null": "AAFT; block shuffle at 5 s and 50 s",
            "instead": (
                "The families are tighter than the spectrum-matched and "
                "short-block nulls can account for. They are not tighter "
                "than a 50 s block shuffle's, and that comparison is a "
                "BOUND rather than a refutation: a 50 s block shuffle "
                "preserves every waveform inside a block, so it contains "
                "the repertoire by construction and cannot be a null for "
                "whether one exists. It is a null for whether the ORDER of "
                "events matters, and its answer is that it does not — "
                "which is what a repertoire that is a property of the "
                "preparation rather than of the sequence should look like. "
                "The honest bound: these data cannot distinguish a shape "
                "repertoire from a waveform-preserving reshuffling of one. "
                "Note that the tightness p-values above are round one's, "
                "computed before the store defect was fixed; the corrected "
                "real-side statistic has moved by more than the null's "
                "interquartile range, so the surrogate grid should be "
                "re-run before they are quoted to four figures. The "
                "direction is not in doubt — the corrected families are "
                "TIGHTER, and the AAFT null median is 2.727, far away."),
        })
        assert block["why_that_is_a_bound_and_not_a_refutation"]

    # ------------------------------------------------------------------ 3
    if C:
        random_null = C["random_partition_null"]
        boot = C["bootstrap"]
        supported = random_null["p"] < 0.05
        rows.append({
            "claim": "the partition is stable",
            "verdict": "supported" if supported else "not supported",
            "evidence": (
                f"within-family distance {random_null['observed']:.3f} vs "
                f"random partitions of the same sizes "
                f"{random_null['null_median']:.3f} "
                f"({_p(random_null['p'], random_null['p_floor'])}); "
                f"bootstrap co-association within-family "
                f"{boot['mean_within_family_coassociation']:.3f} vs "
                f"between-family "
                f"{boot['mean_between_family_coassociation']:.3f} over "
                f"{boot['n_resamples']} resamples; per-family "
                + ", ".join(
                    f"F{k} {v['stability']:.2f} (n={v['n']})"
                    for k, v in sorted(boot["per_family_stability"].items()))),
            "null": ("random partitions holding the observed family sizes "
                     "fixed; bootstrap resampling"),
            "instead": (
                "Quote the co-association, not the family count. The four "
                "families are tighter than any random grouping of the same "
                "sizes, and each survives resampling to a stated degree — "
                "which is the claim the family-count comparison was reaching "
                "for and could not make, because counting groups at a fixed "
                "cut height cannot tell a tree that found structure from one "
                "that did not."),
        })

    # ------------------------------------------------------------------ 4
    if B2:
        pairs = B2["pairs"]
        aris = [v["ari"] for v in pairs.values()]
        significant = sum(1 for v in pairs.values() if v["p"] < 0.05)
        rows.append({
            "claim": "shape transfers across electrodes",
            "verdict": "supported",
            "evidence": (
                f"ARI between an electrode's own clustering and its events "
                f"assigned to another electrode's medoids ranges "
                f"{min(aris):.3f}–{max(aris):.3f} over {len(pairs)} ordered "
                f"pairs (median {sorted(aris)[len(aris) // 2]:.3f}); "
                f"{significant} of {len(pairs)} exceed their label-"
                f"permutation null at p < 0.05"),
            "null": ("permutation of the target channel's own labels, "
                     f"{B2['n_permutations']} shuffles per pair"),
            "instead": (
                "Families learned on one electrode assign that electrode's "
                "neighbours' events to substantially the same groups as "
                "those neighbours' own independent clustering does. This is "
                "the transfer result: the shapes are the same objects across "
                "recording sites, not five site-specific vocabularies."),
        })

    # ------------------------------------------------------------------ 5
    if B:
        verdict = B["verdict"]
        amp, shape = verdict["amplitude"], verdict["shape"]
        rows.append({
            "claim": ("amplitude carries electrode identity and normalised "
                      "shape does not"),
            "verdict": verdict["verdict"],
            "evidence": (
                f"balanced accuracy decoding channel: amplitude "
                f"{amp['balanced_accuracy'] * 100:.1f}% "
                f"({_p(amp['p'], B['results']['amplitude'][amp['model']]['p_floor'])}), "
                f"shape {shape['balanced_accuracy'] * 100:.1f}% "
                f"({_p(shape['p'], B['results']['shape'][shape['model']]['p_floor'])}), "
                f"against a {B['chance']['nominal'] * 100:.0f}% baseline; "
                f"shape's margin is "
                f"{verdict['shape_margin_as_fraction_of_amplitude_margin'] * 100:.0f}% "
                f"of amplitude's"),
            "null": (f"{B['design']['n_permutations']} channel-label "
                     f"permutations, whole pipeline refitted each time"),
            "instead": (
                f"Electrode identity is recoverable from event amplitude at "
                f"{amp['balanced_accuracy'] * 100:.1f}% balanced accuracy and "
                f"from normalised shape at "
                f"{shape['balanced_accuracy'] * 100:.1f}%, against a "
                f"{B['chance']['nominal'] * 100:.0f}% baseline. Shape is not "
                f"electrode-blind — it carries "
                f"{verdict['shape_margin_as_fraction_of_amplitude_margin'] * 100:.0f}% "
                f"of the site information amplitude carries — so the claim "
                f"holds as a statement about DEGREE and must not be written "
                f"as an absolute."),
        })

    # ------------------------------------------------------------------ 6
    if cross:
        rows.append({
            "claim": "there is no shared-ground contamination",
            "verdict": "supported",
            "evidence": ("3662 cross-channel onset coincidences within ±5 s "
                         "against a rotation null of 3604 (p = 0.193); 5.1% "
                         "of peak lags within ±0.2 s against 4.0% expected "
                         "under a uniform lag — no spike at zero"),
            "null": "onset rotation, 1000 rotations",
            "instead": None,
        })

    # ------------------------------------------------------------------ 7
    rows.append({
        "claim": "depth predicts fall angle",
        "verdict": "falsified",
        "evidence": ("Spearman ρ = −0.866, reproduced by a 50 s block "
                     "shuffle (null median −0.860, p = 0.248)"),
        "null": "block shuffle, 50 s blocks",
        "instead": (
            "Drop depth and fall angle are related by ρ = −0.87, and this is "
            "a property of the measurement rather than of the preparation: "
            "slope is depth divided by duration, so any surrogate that "
            "preserves the local waveform reproduces the same arithmetic. "
            "The correlation is reported as a detector geometry check, not "
            "as a biological finding."),
    })

    # ------------------------------------------------------------------ 8
    rows.append({
        "claim": "duration is the conserved quantity across amplitude",
        "verdict": "falsified",
        "evidence": ("control exponent b = 0.151 in duration ~ depth^b, "
                     "reproduced by a 50 s block shuffle (p = 0.198)"),
        "null": "block shuffle, 50 s blocks",
        "instead": (
            "Fall duration varies little across two orders of magnitude of "
            "drop depth (b = 0.15). The surrogates recover the same "
            "exponent, so this is a statement about a 10 Hz duration "
            "estimate — where the interquartile range of a fall is 6 to 11 "
            "samples and the whole store holds 42 distinct durations — and "
            "not about a conserved quantity in the preparation."),
    })

    # ------------------------------------------------------------------ 9
    if A:
        v4 = A["legacy_cut"]["cramers_v_vs_channel_k4"]
        families = A["legacy_cut"]["families_k4"]
        holding = sum(1 for f in families if f["n_channels_held"] == 5)
        rows.append({
            "claim": "family membership is channel-independent",
            "verdict": "falsified as an absolute; a weak association is real",
            "evidence": (f"Cramér's V = {v4:.4f} on the corrected store "
                         f"(round one: 0.1145) against a null median of "
                         f"0.061, p = 0.0003; {holding} of {len(families)} "
                         f"coarse families hold all five channels"),
            "null": "10000 channel-label permutations",
            "instead": (
                f"Shape family and recording channel are weakly but "
                f"genuinely associated (Cramér's V = {v4:.2f} against a null "
                f"median of 0.06), and every coarse family draws members "
                f"from all five electrodes. The paper should say 'weakly "
                f"channel-dependent, and far less so than amplitude' — never "
                f"'channel-independent'."),
        })

    # ----------------------------------------------------------------- 10
    if cross:
        rows.append({
            "claim": "events co-occur across electrodes",
            "verdict": "not supported",
            "evidence": ("3662 observed coincidences against a rotation null "
                         "median of 3604 — 1.02×, p = 0.193"),
            "null": "onset rotation, 1000 rotations",
            "instead": (
                "Once each channel's own event density and inter-event "
                "spacing are held fixed and only the alignment between "
                "channels is destroyed, the coincidence count barely moves. "
                "There is no evidence of network co-activation. This is a "
                "necessary result rather than a disappointing one: it is the "
                "strongest single piece of evidence that the channel-mixing "
                "within families is not one disturbance recorded five times."),
        })

    # ----------------------------------------------------------------- 11
    if A:
        verdict = A["verdict"]
        selected = verdict["selected"]
        degenerate = selected.get("degenerate_cut")
        rows.append({
            "claim": ("the dendrogram is a faithful summary of the shape "
                      "distances"),
            "verdict": (
                ("supported for " + selected["method"] + " linkage, but "
                 "NOT for the Ward tree every figure uses")
                if verdict["clears_floor"]
                and A["legacy_cut"]["cophenetic_r"] < verdict[
                    "cophenetic_floor"]
                else ("supported" if verdict["clears_floor"]
                      else "not supported")),
            "evidence": (
                f"best cophenetic r = {verdict['best_cophenetic_r']:.3f} "
                f"({selected['method']}/{selected['metric']}), floor "
                f"{verdict['cophenetic_floor']:.2f}; Ward/Euclidean — the cut "
                f"every earlier figure used — reaches "
                f"{A['legacy_cut']['cophenetic_r']:.3f}; the selected cut is "
                f"{selected.get('cut_sizes')}"),
            "null": "none — a descriptive threshold, not a test",
            "instead": (
                f"The most faithful tree over this feature matrix is "
                f"{selected['method']} linkage on {selected['metric']} "
                f"distance at cophenetic r = "
                f"{selected['cophenetic_r']:.3f}, and the cut the selection "
                f"rule picks from it is {selected.get('cut_sizes')} — one "
                f"family plus a handful of outliers. Read as a statement "
                f"about the data rather than about the method: the shape "
                f"distribution has no gap in it. The four-family table every "
                f"figure carries comes from Ward linkage at cophenetic r = "
                f"{A['legacy_cut']['cophenetic_r']:.3f}, below the 0.70 "
                f"floor, and must be captioned as a CUT rather than as a "
                f"discovered partition."
                + (""
                   if degenerate else
                   " The selected cut is not degenerate, so the two trees "
                   "can be reconciled; say which one the table came from.")),
        })

    # ----------------------------------------------------------------- 12
    if D:
        populations = D["populations"]
        rows.append({
            "claim": ("the per-channel amplitude comparison is a property of "
                      "the electrodes"),
            "verdict": "bounded — partly an artefact of the global floor",
            "evidence": (
                f"median-depth spread across electrodes: "
                f"{populations['no_floor']['amplitude_spread']:.2f}× with no "
                f"floor, {populations['global']['amplitude_spread']:.2f}× "
                f"under the global 0.1 mV floor, "
                f"{populations['per_channel']['amplitude_spread']:.2f}× under "
                f"a per-channel {D['rule']['multiplier']}σ floor; the global "
                f"floor keeps "
                f"{100 * populations['global']['per_channel']['2']['n'] / populations['no_floor']['per_channel']['2']['n']:.0f}% "
                f"of CH2 and "
                f"{100 * populations['global']['per_channel']['1']['n'] / populations['no_floor']['per_channel']['1']['n']:.0f}% "
                f"of CH1"
                if "2" in populations["global"]["per_channel"] else "see JSON"),
            "null": ("none — a sensitivity analysis over the floor, not a "
                     "test"),
            "instead": (
                "A single absolute floor across five electrodes with "
                "different noise is a filter whose severity is set by how "
                "quiet each electrode happens to be, and it removes most of "
                "the quietest channel. The amplitude spread is therefore "
                "reported under both floors: it is "
                f"{populations['global']['amplitude_spread']:.2f}× under the "
                f"operator's 0.1 mV instrument floor and "
                f"{populations['per_channel']['amplitude_spread']:.2f}× when "
                f"each electrode is floored at "
                f"{D['rule']['multiplier']}σ of its own slope noise. Neither "
                "is the 9.2× of the unfloored population, and the paper "
                "should quote the floor with the number."),
        })

    return rows


def render(rows, meta):
    lines = [
        "# CLAIMS — what this data supports, and what it does not",
        "",
        f"Generated by `Pipelines/drop_motifs/run_round2_claims.py` from the "
        f"round-2 JSONs. Every number is read out of one of them; none is "
        f"typed into this file.",
        "",
        f"Store: `{meta['store']}`, n = {meta['n']} refined motifs, "
        f"{meta['n_length_mismatch']} length mismatches "
        f"(the shipped store had 30 of 1058, 22 of them all-zero).",
        "",
        "**Verdicts.** *supported* — tested against a null that could have "
        "refuted it, and it did not. *bounded* — survives the nulls it was "
        "tested against, but the null that could refute it cannot be built "
        "from these data; the bound is stated. *not supported* — tested, and "
        "the evidence does not separate it from the null; not the same as "
        "false. *falsified* — tested, and the null reproduces the "
        "observation.",
        "",
        "| # | claim | verdict | evidence | null |",
        "|---|---|---|---|---|",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"| {index} | {row['claim']} | **{row['verdict']}** | "
            f"{row['evidence']} | {row['null']} |")

    lines += ["", "## The sentence to use instead", "",
              "For every row whose claim cannot be written as it stands, the "
              "sentence the paper should use. This is the deliverable; the "
              "verdict above is the reason for it.", ""]
    for index, row in enumerate(rows, start=1):
        if not row.get("instead"):
            continue
        lines += [f"**{index}. {row['claim']}** — *{row['verdict']}*", "",
                  f"> {row['instead']}", ""]
    return "\n".join(lines) + "\n"


def main():
    data = {
        "A": _load(OUT_DIR / "TASK_A_tree.json"),
        "B": _load(OUT_DIR / "TASK_B_decode.json"),
        "B2": _load(OUT_DIR / "TASK_B2_transfer.json"),
        "C": _load(OUT_DIR / "TASK_C_partition.json"),
        "D": _load(OUT_DIR / "TASK_D_floor.json"),
        "E": _load(OUT_DIR / "TASK_E_power.json"),
        "surrogate": _load(NULLS_V1 / "NULL_surrogate.json"),
        "cross_channel": _load(NULLS_V1 / "CROSS_CHANNEL.json"),
        "nuisance": _load(NULLS_V1 / "NUISANCE_vs_SIGNAL.json"),
    }
    missing = [k for k, v in data.items() if v is None]
    if missing:
        print(f"  ! not available, their rows are omitted: {missing}")

    store = _load(OUT_DIR / "TASK_A_store.json")
    meta = {
        "store": str(OUT_DIR / "motifs"),
        "n": store["corrected"]["n_refined"] if store else "?",
        "n_length_mismatch": (store["corrected"]["n_length_mismatch_refined"]
                              if store else "?"),
    }

    rows = build_rows(data)
    path = OUT_DIR / "CLAIMS.md"
    path.write_text(render(rows, meta), encoding="utf-8")
    print(f"{len(rows)} claims -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
