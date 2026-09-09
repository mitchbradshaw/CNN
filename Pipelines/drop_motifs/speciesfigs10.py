"""
speciesfigs10.py
=================
Task 5's three figures. Each is drawn from the JSON `run_drop10_species.py`
wrote, never from a fresh computation, so a figure cannot state a number
the analysis did not produce.

Every panel that reports an effect also draws its null. That is the
lesson round one paid for: a correlation of -0.866 looked like a finding
for a whole run and turned out to be reproduced at -0.860 by a
waveform-preserving surrogate.
"""

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D

from Pipelines.drop_motifs import style10

FIGSIZE = (11.7, 8.3)


def _save(fig, path):
    path = str(path)
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _v_bar(ax, block, label, colour):
    """One Cramer's V with its permutation null drawn behind it."""
    v = block["cramers_v"]
    ax.barh([label], [v], color=colour, height=0.55, zorder=3)
    ax.plot([block["null_median_v"]], [label], marker="|", markersize=18,
            color="0.25", zorder=4)
    ax.barh([label], [block["null_p95_v"]], color="0.85", height=0.55,
            zorder=1)
    ax.text(v + 0.004, label, f"V={v:.3f}  p={block['permutation_p']:.4f}",
            va="center", fontsize=8, color="0.2")


def plot_species_vs_resolution(data, path, *, title, families=None):
    """5a's question and 5b's control in one figure, as the brief requires.

    Panel A is the whole argument: if family x samples-per-event
    associates more strongly than family x species, the tree is separating
    measurement resolution and no cross-species number is safe.
    """
    style10.apply_style()
    fig = plt.figure(figsize=FIGSIZE)
    info = {"panels": {}}

    subsets = [k for k in ("pooled_all", "matched_rate", "oyster_vs_sp385")
               if k in data]

    # -- A. V(species) against V(samples-per-event), every subset --------
    ax = fig.add_subplot(2, 2, 1)
    rowsA = []
    for subset in subsets:
        for cut in ("coarse", "fine"):
            block = data[subset].get(cut)
            if not block:
                continue
            rowsA.append((f"{subset}\n{cut}", block["species"],
                          block["samples_per_event"]))
    # 5a's extra contrast: matched RATE, different FRAMING. It has no
    # samples-per-event twin in 5b's file, so it is drawn with the species
    # bar alone and the missing twin is stated rather than left blank.
    extra = []
    if families:
        for subset in ("oyster_vs_reishi_1hz",):
            block = families.get(subset)
            if not block:
                continue
            for cut in ("coarse", "fine"):
                if cut in block:
                    extra.append((f"{subset}\n{cut}", block[cut]))
    y = np.arange(len(rowsA))
    width = 0.38
    for i, (label, sp, sa) in enumerate(rowsA):
        ax.barh(i + width / 2, sp["cramers_v"], height=width,
                color=style10.SPECIES_COLOUR[style10.SPECIES_ORDER[0]],
                zorder=3, label="species" if i == 0 else None)
        ax.barh(i - width / 2, sa["cramers_v"], height=width,
                color="#8257C4", zorder=3,
                label="samples per event" if i == 0 else None)
        ax.plot([sp["null_median_v"]], [i + width / 2], marker="|",
                markersize=12, color="0.2", zorder=5)
        ax.plot([sa["null_median_v"]], [i - width / 2], marker="|",
                markersize=12, color="0.2", zorder=5)
    for k, (label, block) in enumerate(extra):
        i = len(rowsA) + k
        ax.barh(i, block["cramers_v"], height=width, color="#0D4F4A",
                zorder=3, label="species (matched rate, other framing)"
                if k == 0 else None)
        ax.plot([block["null_median_v"]], [i], marker="|", markersize=12,
                color="0.2", zorder=5)
    y = np.arange(len(rowsA) + len(extra))
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rowsA] + [e[0] for e in extra],
                       fontsize=7)
    ax.set_xlabel("Cramer's V  (tick = permutation null median)")
    ax.set_title("A. does family track SPECIES or RESOLUTION?", fontsize=9.5)
    ax.legend(fontsize=6.5, frameon=False, loc="lower right")
    style10.readable_grey(fig, ax)
    info["panels"]["A_extra"] = [
        {"subset_cut": label, "V_species": b["cramers_v"],
         "p_species": b["permutation_p"],
         "null_median_v": b["null_median_v"]}
        for label, b in extra]
    info["panels"]["A"] = [
        {"subset_cut": label,
         "V_species": sp["cramers_v"], "p_species": sp["permutation_p"],
         "V_samples": sa["cramers_v"], "p_samples": sa["permutation_p"],
         "samples_dominates": bool(sa["cramers_v"] > sp["cramers_v"])}
        for label, sp, sa in rowsA]

    # -- B. decoding samples-per-event from the normalised shape ---------
    ax = fig.add_subplot(2, 2, 2)
    labels, values, chances, nulls, ps = [], [], [], [], []
    for subset in subsets:
        d = data[subset].get("decode_samples_from_shape", {})
        if "balanced_accuracy" not in d:
            continue
        labels.append(subset)
        values.append(d["balanced_accuracy"])
        chances.append(d["chance"])
        nulls.append(d["null_p95"])
        ps.append(d["permutation_p"])
    x = np.arange(len(labels))
    ax.bar(x, values, color="#8257C4", width=0.55, zorder=3)
    for i, (c, n95, p) in enumerate(zip(chances, nulls, ps)):
        ax.plot([i - 0.32, i + 0.32], [c, c], color="0.25", lw=1.2, zorder=5)
        ax.plot([i - 0.32, i + 0.32], [n95, n95], color="#B00", lw=1.0,
                ls=(0, (3, 2)), zorder=5)
        ax.text(i, values[i] + 0.012, f"p={p:.3f}", ha="center", fontsize=7.5)
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_ylabel("balanced accuracy")
    ax.set_title("B. can a 200-point z-normalised vector say how many\n"
                 "samples built it?   (solid = chance, dashed = null p95)",
                 fontsize=9.5)
    style10.readable_grey(fig, ax)
    info["panels"]["B"] = [
        {"subset": l, "balanced_accuracy": v, "chance": c, "null_p95": n,
         "permutation_p": p}
        for l, v, c, n, p in zip(labels, values, chances, nulls, ps)]

    # -- C. the three poolings -------------------------------------------
    ax = fig.add_subplot(2, 2, 3)
    poolings = data.get("three_poolings", {})
    names = [n for n in ("with_10hz_reishi", "with_1hz_reishi", "with_both")
             if n in poolings]
    bottoms = np.zeros(len(names))
    mixed_fraction = []
    for name in names:
        table = poolings[name]["coarse"]
        n_families = len(table)
        n_mixed = sum(1 for fam in table.values() if len(fam) > 1)
        mixed_fraction.append(n_mixed / n_families if n_families else 0.0)
    ax.bar(np.arange(len(names)), mixed_fraction, color="#2E9E95",
           width=0.55, zorder=3)
    for i, name in enumerate(names):
        table = poolings[name]["coarse"]
        ax.text(i, mixed_fraction[i] + 0.02,
                f"{sum(1 for f in table.values() if len(f) > 1)}"
                f"/{len(table)}\nn={poolings[name]['n']}",
                ha="center", fontsize=7.5)
    ax.set_xticks(np.arange(len(names)))
    ax.set_xticklabels(names, fontsize=7.5)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("fraction of coarse families holding >1 species")
    ax.set_title("C. the three poolings - which should the paper quote?",
                 fontsize=9.5)
    style10.readable_grey(fig, ax)
    info["panels"]["C"] = [
        {"pooling": n, "n": poolings[n]["n"],
         "cophenetic_r": poolings[n]["cophenetic"],
         "n_families": len(poolings[n]["coarse"]),
         "n_mixed_families": sum(1 for f in poolings[n]["coarse"].values()
                                 if len(f) > 1),
         "mixed_fraction": f}
        for n, f in zip(names, mixed_fraction)]

    # -- D. the verdict, in words -----------------------------------------
    ax = fig.add_subplot(2, 2, 4)
    ax.set_axis_off()
    lines = ["THE CONFOUND CONTROL, read before panel A's species bars:", ""]
    for row in info["panels"]["A"]:
        verdict = ("RESOLUTION dominates" if row["samples_dominates"]
                   else "species dominates")
        lines.append(f"  {row['subset_cut'].replace(chr(10), ' / '):28s}  "
                     f"V(sp)={row['V_species']:.3f}  "
                     f"V(smp)={row['V_samples']:.3f}   {verdict}")
    if info["panels"].get("A_extra"):
        lines += ["", "5a's extra contrast - MATCHED RATE, DIFFERENT FRAMING:"]
        for row in info["panels"]["A_extra"]:
            lines.append(f"  {row['subset_cut'].replace(chr(10), ' / '):28s}  "
                         f"V(sp)={row['V_species']:.3f}  "
                         f"p={row['p_species']:.4f}")
    lines += ["", "Species is perfectly confounded with sampling rate between",
              "reishi and the other two. A feature vector is 200 points",
              "resampled from the event's own samples, so a 7-sample reishi",
              "event is 96% interpolation and a 150-sample oyster event is a",
              "decimation. Where samples-per-event associates more strongly",
              "than species, the tree is separating measurement resolution",
              "and the cross-species reading is NOT safe."]
    ax.text(0.0, 1.0, "\n".join(lines), va="top", ha="left", fontsize=7.5,
            family="monospace", color="0.15", transform=ax.transAxes)

    fig.suptitle(title, fontsize=11.5)
    fig.subplots_adjust(top=0.90, hspace=0.42, wspace=0.28)
    return _save(fig, path), info


def plot_decode_species(data, path, *, title):
    """5c: balanced accuracy by representation, with permutation nulls."""
    style10.apply_style()
    subsets = [k for k in ("matched_rate", "pooled_all") if k in data]
    fig = plt.figure(figsize=(FIGSIZE[0], 4.4 + 3.0 * len(subsets)))
    info = {"subsets": {}}

    order = ["absolute scale", "normalised shape", "both", "resolution alone"]
    colours = ["#2F7FBF", "#D4813A", "#14532D", "#8A8A8A"]

    for s, subset in enumerate(subsets):
        block = data[subset]["representations"]
        ax = fig.add_subplot(len(subsets), 2, 2 * s + 1)
        rows = []
        for i, name in enumerate(order):
            result = block.get(name, {})
            if "balanced_accuracy" not in result:
                continue
            ax.barh(i, result["balanced_accuracy"], color=colours[i],
                    height=0.55, zorder=3)
            ax.plot([result["null_p95"]] * 2, [i - 0.3, i + 0.3],
                    color="#B00", lw=1.0, ls=(0, (3, 2)), zorder=5)
            ax.plot([result["chance"]] * 2, [i - 0.34, i + 0.34],
                    color="0.2", lw=1.3, zorder=5)
            ax.text(result["balanced_accuracy"] + 0.008, i,
                    f"{result['balanced_accuracy']:.3f}  "
                    f"p={result['permutation_p']:.4f}",
                    va="center", fontsize=8)
            rows.append({"representation": name, **{
                k: result[k] for k in ("balanced_accuracy", "chance",
                                       "null_median", "null_p95",
                                       "permutation_p", "n", "n_features")}})
        ax.set_yticks(range(len(order)))
        ax.set_yticklabels(order, fontsize=8)
        ax.set_xlim(0, 1.05)
        ax.set_xlabel("balanced accuracy")
        ax.set_title(f"{subset}   (solid = chance, dashed = permutation "
                     f"null p95)", fontsize=9.5)
        style10.readable_grey(fig, ax)
        info["subsets"][subset] = {"representations": rows,
                                   "n": data[subset]["n"]}

        # confusion matrices, stacked
        ax2 = fig.add_subplot(len(subsets), 2, 2 * s + 2)
        best = block.get("absolute scale", {})
        matrix = np.asarray(best.get("confusion", [[0]]), dtype=float)
        classes = best.get("classes", [])
        with np.errstate(invalid="ignore"):
            norm = matrix / np.clip(matrix.sum(axis=1, keepdims=True), 1, None)
        im = ax2.imshow(norm, cmap="Blues", vmin=0, vmax=1)
        ax2.set_xticks(range(len(classes)))
        ax2.set_xticklabels(classes, fontsize=8, rotation=30, ha="right")
        ax2.set_yticks(range(len(classes)))
        ax2.set_yticklabels(classes, fontsize=8)
        for i in range(norm.shape[0]):
            for j in range(norm.shape[1]):
                ax2.text(j, i, f"{norm[i, j]:.2f}", ha="center", va="center",
                         fontsize=8,
                         color="white" if norm[i, j] > 0.55 else "0.15")
        ax2.set_xlabel("predicted"); ax2.set_ylabel("true")
        ax2.set_title("confusion, ABSOLUTE SCALE", fontsize=9.5)
        fig.colorbar(im, ax=ax2, fraction=0.046, pad=0.04)
        info["subsets"][subset]["confusion_absolute_scale"] = {
            "classes": classes, "matrix": matrix.astype(int).tolist()}

    fig.suptitle(title, fontsize=11.5)
    fig.subplots_adjust(top=0.90, hspace=0.55, wspace=0.32)
    return _save(fig, path), info


def plot_transfer(data, path, *, title, medoids_by_species=None):
    """5d: the species x species ARI matrix, and the medoids themselves."""
    style10.apply_style()
    subsets = [k for k in ("matched_rate", "pooled_all") if k in data]
    fig = plt.figure(figsize=(FIGSIZE[0], 4.6 * len(subsets) + 1.2))
    info = {"subsets": {}}

    for s, subset in enumerate(subsets):
        matrix = data[subset]["ari_matrix"]
        names = matrix["species"]
        grid = np.full((len(names), len(names)), np.nan)
        for i, a in enumerate(names):
            for j, b in enumerate(names):
                grid[i, j] = matrix["matrix"][a][b].get("ari", np.nan)

        ax = fig.add_subplot(len(subsets), 2, 2 * s + 1)
        im = ax.imshow(grid, cmap="PuBuGn", vmin=-0.1, vmax=1.0)
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, fontsize=8, rotation=30, ha="right")
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names, fontsize=8)
        for i in range(len(names)):
            for j in range(len(names)):
                cell = matrix["matrix"][names[i]][names[j]]
                text = ("-" if i == j
                        else f"{cell.get('ari', float('nan')):.3f}\n"
                             f"p={cell.get('permutation_p', float('nan')):.3f}")
                ax.text(j, i, text, ha="center", va="center", fontsize=7.5,
                        color="white" if grid[i, j] > 0.55 else "0.15")
        ax.set_xlabel("assigned to B (rows = A's medoids)")
        ax.set_title(f"{subset}: adjusted Rand index, A's shapes on B",
                     fontsize=9.5)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

        ax2 = fig.add_subplot(len(subsets), 2, 2 * s + 2)
        surrogate = data[subset].get("surrogate", {})
        pairs = sorted(surrogate)
        obs = [surrogate[p].get("median_nearest_distance", np.nan)
               for p in pairs]
        sur = [surrogate[p].get("surrogate_median", np.nan) for p in pairs]
        x = np.arange(len(pairs))
        ax2.bar(x - 0.2, obs, width=0.38, color="#2E9E95", label="real B",
                zorder=3)
        ax2.bar(x + 0.2, sur, width=0.38, color="0.75",
                label="phase-randomised B", zorder=3)
        ax2.set_xticks(x)
        ax2.set_xticklabels(pairs, fontsize=7, rotation=30, ha="right")
        ax2.set_ylabel("median distance to nearest A-medoid")
        ax2.set_title("the partition-free check\n(lower = A's shapes "
                      "describe B)", fontsize=9.5)
        ax2.legend(fontsize=7.5, frameon=False)
        style10.readable_grey(fig, ax2)

        info["subsets"][subset] = {
            "species": names,
            "ari": {a: {b: matrix["matrix"][a][b] for b in names}
                    for a in names},
            "surrogate": surrogate,
        }

    fig.suptitle(title, fontsize=11.5)
    fig.subplots_adjust(top=0.90, hspace=0.55, wspace=0.30)
    return _save(fig, path), info
