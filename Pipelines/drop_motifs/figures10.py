"""
figures10.py
=============
Task 4's pooled figure set, plus Task 5's three result figures.

Every function returns `(path, info)` and the caller writes `info` to a
JSON beside the PNG. That is a hard rule for this run: a figure may state
no number that is not in its own JSON, so a reader can check a caption
against the data without re-running anything.

What is different from drop_motifs9's set
-----------------------------------------
  leaf ticks are coloured by SPECIES, not by channel;
  a family panel carries a species-composition bar, not a channel one;
  the rose's panel 3 is LABELLED AS DETECTOR GEOMETRY rather than shown as
    a finding, because round one's block-shuffle null reproduced it
    (rho -0.866 observed against -0.860 null, p = 0.248);
  ALL_atlas.png is new.

No hue is cycled and no axis is doubled. Every species-coded figure
carries a legend, and species is never encoded by colour alone.
"""

import numpy as np
from matplotlib import colors as mcolors
from matplotlib import pyplot as plt
from matplotlib.ticker import FixedLocator, FuncFormatter
from scipy.cluster.hierarchy import dendrogram

from Pipelines.drop_motifs import style10, style73, tree10
from Working.Detection.drop_motifs import cluster

FIGSIZE_PAGE = (11.7, 8.3)          # A4 landscape
FIGSIZE_TALL = (11.7, 14.0)


def _save(fig, path):
    path = str(path)
    # No `bbox_inches="tight"`. Every figure here places its axes with
    # explicit fractions so panels line up with their composition bars and
    # leader lines; a tight bounding box re-crops after that layout is
    # decided and pulls the two apart.
    fig.savefig(path, dpi=200, facecolor="white")
    plt.close(fig)
    return path


def _species_counts(rows):
    out = {}
    for row in rows:
        out[row["species"]] = out.get(row["species"], 0) + 1
    return out


# ---------------------------------------------------------------------------
# ALL_atlas.png - the figure the paper most needs
# ---------------------------------------------------------------------------

def atlas_entries(trees_by_corpus, cut="fine"):
    """Every family medoid from every corpus, ordered by NATIVE duration.

    Per corpus rather than from the pooled tree, because "every family
    medoid from every corpus" is the question: a pooled coarse cut gives
    four shapes and hides that each corpus resolves into its own families
    at its own scale. Each corpus is clustered on its own and contributes
    its medoids to one ordered sequence.
    """
    entries = []
    for corpus, tree in trees_by_corpus.items():
        if tree is None:
            continue
        labels = tree[cut]
        rows, features = tree["rows"], tree["features"]
        for family, index in tree10.medoids(features, labels).items():
            row = rows[index]
            members = [r for r, lab in zip(rows, labels) if int(lab) == family]
            entries.append({
                "corpus": corpus,
                "family": int(family),
                "n": len(members),
                "event_id": row["event_id"],
                "species": row["species"],
                "fs": float(row["fs"]),
                "native_fall_s": float(row["fall_duration_s"]),
                "native_depth_mv": abs(float(row["drop_depth_mv"])),
                "n_samples_in_fall": int(row["n_samples_in_fall"]),
                "median_fall_s": float(np.median(
                    [float(r["fall_duration_s"]) for r in members])),
                "median_depth_mv": float(np.median(
                    [abs(float(r["drop_depth_mv"])) for r in members])),
                "median_samples": float(np.median(
                    [int(r["n_samples_in_fall"]) for r in members])),
                "feature": features[index],
            })
    entries.sort(key=lambda e: e["native_fall_s"])
    return entries


def plot_atlas(trees_by_corpus, path, *, title, cut="fine"):
    """Every family medoid from every corpus, z-normalised onto one axis.

    Ordered by NATIVE fall duration, so the reading direction is three
    orders of magnitude of absolute scale, and annotated with the native
    duration, native amplitude and species each medoid actually has. That
    is the whole argument in one picture: the shapes are drawn on a common
    normalised axis because they are comparable AS SHAPES, and the numbers
    beside them say how far apart they are AS MEASUREMENTS.

    The medoid is a real member, never a mean. A mean of z-normalised
    vectors is not a waveform any event has and must not be drawn as one.

    A log strip along the bottom places every medoid on the duration axis,
    so "three orders of magnitude" is shown rather than asserted.
    """
    style10.apply_style()
    entries = atlas_entries(trees_by_corpus, cut=cut)
    if not entries:
        return None, {"reason": "no medoids"}

    n = len(entries)
    cols = 6
    rows_n = int(np.ceil(n / cols))
    fig = plt.figure(figsize=(11.7, 1.62 * rows_n + 3.2))

    left, right = 0.045, 0.985
    top, bottom = 0.880, 0.215
    cell_w = (right - left) / cols
    cell_h = (top - bottom) / rows_n

    for i, entry in enumerate(entries):
        r, c = divmod(i, cols)
        ax = fig.add_axes([left + c * cell_w + 0.008,
                           top - (r + 1) * cell_h + 0.055 * cell_h + 0.030,
                           cell_w - 0.016, cell_h * 0.50])
        colour = style10.colour_of(entry["species"])
        t = np.linspace(0.0, 1.0, len(entry["feature"]))
        ax.plot(t, entry["feature"], color=colour,
                linestyle=style10.dash_of(entry["species"]),
                lw=style10.style7.LW_MEDOID)
        ax.axhline(0.0, color=style10.style7.RULE_COLOUR, lw=0.5, alpha=0.35)
        ax.set_xticks([])
        ax.set_yticks([])
        for side in ("top", "right", "bottom", "left"):
            ax.spines[side].set_visible(False)
        fall = entry["native_fall_s"]
        fall_text = f"{fall:.1f} s" if fall < 100 else f"{fall:.0f} s"
        ax.set_title(f"{entry['corpus']} F{entry['family']}  n={entry['n']}",
                     fontsize=6.6, pad=2.5, color="0.25")
        ax.text(0.5, -0.10,
                f"{fall_text}   {entry['native_depth_mv']:.3f} mV\n"
                f"{entry['n_samples_in_fall']} samples @ {entry['fs']:g} Hz",
                transform=ax.transAxes, ha="center", va="top",
                fontsize=6.3, color="0.35", linespacing=1.35)

    # The duration axis itself, so the range is shown and not asserted.
    strip = fig.add_axes([left + 0.02, 0.095, right - left - 0.04, 0.052])
    falls = np.asarray([e["native_fall_s"] for e in entries])
    for entry in entries:
        strip.plot([entry["native_fall_s"]], [0.5],
                   marker=style10.marker_of(entry["species"]),
                   color=style10.colour_of(entry["species"]),
                   markersize=6, alpha=0.85, linestyle="none")
    strip.set_xscale("log")
    strip.set_ylim(0, 1)
    strip.set_yticks([])
    strip.set_xlabel("native fall duration of each medoid (s, log) - the "
                     "reading direction of the grid above", fontsize=8)
    strip.grid(True, axis="x", color="0.88", lw=0.6)
    strip.set_axisbelow(True)
    for side in ("top", "right", "left"):
        strip.spines[side].set_visible(False)

    decades = float(np.log10(falls.max() / max(falls.min(), 1e-9)))
    fig.suptitle(title, fontsize=11.5, y=0.988)
    fig.text(0.5, 0.955,
             f"{n} family medoids from {len(trees_by_corpus)} corpora, each "
             f"z-normalised to 200 points on a common axis; every "
             f"annotation is a NATIVE measurement. Duration spans "
             f"{decades:.1f} orders of magnitude "
             f"({falls.min():g} s to {falls.max():g} s).",
             ha="center", va="top", fontsize=8.2, color="0.3")
    fig.legend(handles=style10.species_handles(), loc="lower center",
               ncol=3, frameon=False, fontsize=8,
               bbox_to_anchor=(0.5, 0.010))

    info = {
        "cut": cut,
        "n_medoids": n,
        "corpora": list(trees_by_corpus),
        "native_fall_range_s": [float(falls.min()), float(falls.max())],
        "orders_of_magnitude": decades,
        "native_depth_range_mv": [
            float(min(e["native_depth_mv"] for e in entries)),
            float(max(e["native_depth_mv"] for e in entries))],
        "samples_in_fall_range": [
            int(min(e["n_samples_in_fall"] for e in entries)),
            int(max(e["n_samples_in_fall"] for e in entries))],
        "per_corpus_cophenetic": {
            c: (t["cophenetic"] if t else None)
            for c, t in trees_by_corpus.items()},
        "medoids": [{k: v for k, v in e.items() if k != "feature"}
                    for e in entries],
    }
    return _save(fig, path), info


# ---------------------------------------------------------------------------
# ALL_dendrogram.png
# ---------------------------------------------------------------------------

def plot_dendrogram(tree, path, *, title):
    """The full Ward tree on a RANKED merge axis, leaves coloured by species.

    The merge axis is ranked rather than linear, as drop_motifs7.3
    established: Ward heights on a pooled store span two orders of
    magnitude and a linear axis compresses every structural merge into a
    hairline at the origin. The transform is applied as a matplotlib
    FUNCTION SCALE after the tree is drawn, so the tick LABELS stay in
    real merge-distance units and only their spacing changes - the axis
    is an ordering with real distances attached, and it says so.

    NOT truncated. The first version of this figure ranked the heights
    itself and then truncated to the last 40 merges, which are ranks
    3471-3510 out of 3510 - a slice one percent deep, drawn as a comb of
    forty identical uprights. Ranking and truncating do not compose:
    truncation keeps the TOP of the tree, and ranking is what spreads the
    bottom out to where it can be seen.
    """
    style10.apply_style()
    Z, rows, labels = tree["Z"], tree["rows"], tree["coarse"]

    fig = plt.figure(figsize=FIGSIZE_PAGE)
    ax = fig.add_axes([0.075, 0.34, 0.895, 0.545])

    family_of_leaf = {i: int(v) for i, v in enumerate(labels)}
    n_leaves = len(rows)

    def link_colour(node):
        """A link is a family's colour only if it is inside one family."""
        stack, leaves = [node], []
        while stack:
            k = stack.pop()
            if k < n_leaves:
                leaves.append(k)
            else:
                stack.extend(int(v) for v in Z[k - n_leaves, :2])
        families = {family_of_leaf[i] for i in leaves}
        if len(families) == 1:
            _, cmap = style10.style7.family_ramp(sorted(families)[0] - 1)
            return mcolors.to_hex(cmap(0.62))
        return "0.62"

    dendrogram(Z, orientation="top", ax=ax, no_labels=True,
               link_color_func=link_colour)
    for line in ax.get_lines():
        line.set_linewidth(style10.style7.LW_TREE)

    # Applied AFTER the tree is drawn: every link is a vertical or a
    # horizontal segment, so a monotone map of y moves the vertices
    # without bending anything between them.
    forward, inverse = style73.rank_scale_functions(Z[:, 2])
    ax.set_yscale("function", functions=(forward, inverse))
    ticks = style73.merge_ticks(Z[:, 2])
    if ticks:
        ax.yaxis.set_major_locator(FixedLocator(ticks))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.2g}"))
    ax.set_ylabel("Ward merge distance\n(ranked axis, real labels)",
                  fontsize=9)
    ax.set_title(f"{title}\n{style10.cophenetic_note(tree['cophenetic'])}",
                 fontsize=11)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.set_xticks([])

    # Every leaf, in the tree's own order, coloured by species: the
    # species mix of the whole store under the tree that produced it.
    order = np.asarray(dendrogram(Z, no_plot=True)["leaves"], dtype=int)
    rug = fig.add_axes([0.075, 0.275, 0.895, 0.045])
    boundaries = [style10.colour_of(rows[leaf]["species"]) for leaf in order]
    rug.imshow([[mcolors.to_rgb(c) for c in boundaries]], aspect="auto",
               interpolation="nearest")
    rug.set_xticks([]); rug.set_yticks([])
    rug.set_title("every leaf, in tree order, coloured by species",
                  fontsize=8, color="0.3", pad=3)

    # Family panels on leader lines, each with a species-composition bar.
    families = sorted(set(int(v) for v in labels))
    panel_w = 0.895 / max(len(families), 1)
    summaries = []
    medoid_index = tree10.medoids(tree["features"], labels)
    t = np.linspace(0, 1, tree["features"].shape[1])
    for i, family in enumerate(families):
        index = [j for j, lab in enumerate(labels) if int(lab) == family]
        ax_p = fig.add_axes([0.075 + i * panel_w + 0.010, 0.105,
                             panel_w - 0.020, 0.115])
        step = max(1, len(index) // 80)
        for j in index[::step]:
            ax_p.plot(t, tree["features"][j],
                      color=style10.colour_of(rows[j]["species"]),
                      lw=0.35, alpha=0.22)
        ax_p.plot(t, tree["features"][medoid_index[family]], color="0.12",
                  lw=style10.style7.LW_MEDOID)
        ax_p.set_xticks([]); ax_p.set_yticks([])
        for side in ("top", "right", "left", "bottom"):
            ax_p.spines[side].set_visible(False)
        summary = tree10.summarise_family(rows, labels, family)
        ax_p.set_title(
            f"F{family}  n={summary['n']}\n"
            f"{summary['median_depth_mv']:.3f} mV   "
            f"{summary['median_fall_s']:g} s   "
            f"{summary['median_fall_samples']:g} smp", fontsize=7.5)

        bar = fig.add_axes([0.075 + i * panel_w + 0.010, 0.072,
                            panel_w - 0.020, 0.020])
        style10.composition_bar(bar, summary["species"])
        summaries.append(summary)

    fig.legend(handles=style10.species_handles(counts=_species_counts(rows)),
               loc="lower center", ncol=3, frameon=False, fontsize=8,
               bbox_to_anchor=(0.5, 0.005))

    info = {"n_motifs": tree["n"], "n_input": tree["n_input"],
            "cophenetic_r": tree["cophenetic"], "coarse_k": tree["coarse_k"],
            "fine_k": tree["fine_k"], "merge_axis": "ranked, not truncated",
            "merge_height_range": [float(Z[:, 2].min()), float(Z[:, 2].max())],
            "dropped": tree["dropped"],
            "species_counts": _species_counts(rows),
            "families": summaries}
    return _save(fig, path), info


# ---------------------------------------------------------------------------
# ALL_families.png
# ---------------------------------------------------------------------------

def plot_families(tree, path, *, title):
    """Every motif by family, both cuts, with species composition.

    EACH CUT GETS ITS OWN ROW WIDTH. The first version laid both cuts on
    one 10-column grid, so the 4-family coarse cut used four narrow slots
    and left six empty while its titles ran into each other. A cut with
    four families gets four full-width panels; a cut with ten gets ten.

    Composition is a BAR, not a line of text. At ten panels across, three
    "species:count" pairs per panel is wider than the panel and the labels
    overlap - and the bar is the same encoding the dendrogram's family
    panels use, so the two figures read the same way.
    """
    style10.apply_style()
    rows, features = tree["rows"], tree["features"]
    cuts = (("coarse", tree["coarse"]), ("fine", tree["fine"]))
    t = np.linspace(0, 1, features.shape[1])

    fig = plt.figure(figsize=(FIGSIZE_PAGE[0], 8.0))
    info = {"n_motifs": tree["n"], "cophenetic_r": tree["cophenetic"],
            "cuts": {}}

    left, right = 0.035, 0.985
    row_tops = (0.845, 0.415)
    panel_h, bar_h = 0.235, 0.020

    for r, (name, labels) in enumerate(cuts):
        families = sorted(set(int(v) for v in labels))
        info["cuts"][name] = []
        medoid_index = tree10.medoids(features, labels)
        width = (right - left) / max(len(families), 1)
        top = row_tops[r]

        for c, family in enumerate(families):
            index = [j for j, lab in enumerate(labels) if int(lab) == family]
            ax = fig.add_axes([left + c * width + 0.006, top - panel_h,
                               width - 0.012, panel_h])
            step = max(1, len(index) // 80)
            for j in index[::step]:
                ax.plot(t, features[j],
                        color=style10.colour_of(rows[j]["species"]),
                        lw=0.35, alpha=0.22)
            ax.plot(t, features[medoid_index[family]], color="0.12",
                    lw=style10.style7.LW_MEDOID)
            ax.set_xticks([]); ax.set_yticks([])
            for side in ("top", "right", "left", "bottom"):
                ax.spines[side].set_visible(False)
            summary = tree10.summarise_family(rows, labels, family)
            size = 8.0 if len(families) <= 5 else 6.6
            ax.set_title(
                f"{name[0].upper()}{family}  n={summary['n']}\n"
                f"{summary['median_depth_mv']:.3f} mV\n"
                f"{summary['median_fall_s']:g} s   "
                f"{summary['median_fall_samples']:g} smp",
                fontsize=size, linespacing=1.3)

            bar = fig.add_axes([left + c * width + 0.006,
                                top - panel_h - 0.030, width - 0.012, bar_h])
            style10.composition_bar(bar, summary["species"])
            info["cuts"][name].append(summary)

        fig.text(left, top + 0.055,
                 f"{name} cut - {len(families)} families",
                 fontsize=9.5, color="0.25", ha="left", va="bottom")

    fig.suptitle(f"{title}\n{style10.cophenetic_note(tree['cophenetic'])}",
                 fontsize=11, y=0.985)
    fig.legend(handles=style10.species_handles(counts=_species_counts(rows)),
               loc="lower center", ncol=3, frameon=False, fontsize=8,
               bbox_to_anchor=(0.5, 0.02))
    return _save(fig, path), info


# ---------------------------------------------------------------------------
# ALL_rose.png
# ---------------------------------------------------------------------------

def _angles(rows, snippets, *, scale="pooled", field="max_slope_mv_s"):
    """Per-event fall angle, via `gradients` and never via a bare arctan.

    `gradients.py` makes the point this function exists to obey: `arctan`
    takes a DIMENSIONLESS argument, and a slope of -0.73 mV/s has no angle
    until something states how many millivolts equal one second on the
    page. Writing `arctan(slope)` picks that reference silently and by
    accident, and it is exactly what the first version of this figure did
    - it produced a median fall angle of -0.04 degrees for sp385, because
    an unreferenced slope of a few hundredths lands flat against an
    implicit 1 mV/s.

    `scale="pooled"` is used here rather than drop_motifs9's `raw`,
    because this run's corpora span three orders of magnitude of slope and
    a fixed 1 mV/s reference would put every reishi event within a degree
    of flat and every oyster event near vertical - which would make the
    rose a picture of the corpora's amplitudes, not of their shapes. A
    pooled reference states one number for the whole figure and reports
    it in the caption.

    Returns `(angles_deg, slopes_mv_s, kept_rows, caption)`.
    """
    from Working.Detection.drop_motifs import gradients as G

    usable = [r for r in rows if r["event_id"] in snippets]
    data = G.rose_data(usable, snippets, scale=scale, field=field,
                       split_by="span_key")
    if not len(data.get("angles", [])):
        return np.array([]), np.array([]), [], ""
    angles = np.rad2deg(np.asarray(data["angles"], dtype=float))
    slopes = np.asarray([g[field] for g in data["gradients"]], dtype=float)
    kept = list(usable)
    # A fall of one sample has no measurable slope and lands at an angle
    # set by the sample spacing rather than by the event, so it is
    # excluded here as it was in drop_motifs9.
    keep = np.asarray([int(r["n_samples_in_fall"]) >= 2 for r in kept])
    return (angles[keep], slopes[keep],
            [r for r, k in zip(kept, keep) if k], data.get("caption", ""))


def plot_rose(rows, path, *, title, control_note, snippets=None):
    """Five panels. Panel 3 is LABELLED as detector geometry, not shown as
    a finding: round one's block-shuffle null reproduced it (observed
    Spearman rho -0.866 against a null median of -0.860, p = 0.248), so it
    is a property of the measurement - slope is depth over duration - and
    not of the mycelium.
    """
    from scipy.stats import spearmanr
    style10.apply_style()

    angles, slopes, kept, caption = _angles(rows, snippets or {})
    if not len(angles):
        return None, {"reason": "no usable events"}
    depth = np.asarray([abs(float(r["drop_depth_mv"])) for r in kept])
    fall = np.asarray([float(r["fall_duration_s"]) for r in kept])
    species = [r["species"] for r in kept]
    present = [s for s in style10.SPECIES_ORDER if s in set(species)]

    fig = plt.figure(figsize=(FIGSIZE_PAGE[0], 8.6))
    info = {"n": int(len(angles)), "control_note": control_note,
            "angle_reference": caption,
            "species_present": present}

    # 1. rose by species
    ax1 = fig.add_subplot(2, 3, 1, projection="polar")
    edges = np.linspace(-np.pi / 2, 0.0, 19)
    for name in present:
        sel = np.asarray([s == name for s in species])
        ax1.hist(np.radians(angles[sel]), bins=edges,
                 color=style10.colour_of(name), alpha=0.55,
                 label=style10.SPECIES_LABEL[name])
    ax1.set_title("1. fall angle by species", fontsize=9)
    ax1.set_thetamin(-90); ax1.set_thetamax(0)

    # 2. rose by drop depth (terciles)
    ax2 = fig.add_subplot(2, 3, 2, projection="polar")
    qs = np.quantile(depth, [0, 1 / 3, 2 / 3, 1.0])
    for i in range(3):
        sel = (depth >= qs[i]) & (depth <= qs[i + 1])
        ax2.hist(np.radians(angles[sel]), bins=edges, alpha=0.5,
                 color=style10.style7.family_ramp(i)[1](0.62),
                 label=f"{qs[i]:.2f}-{qs[i + 1]:.2f} mV")
    ax2.set_title("2. fall angle by drop depth", fontsize=9)
    ax2.set_thetamin(-90); ax2.set_thetamax(0)
    ax2.legend(fontsize=6, loc="lower left", bbox_to_anchor=(-0.3, -0.20),
               frameon=False)

    # 3. depth vs angle - DETECTOR GEOMETRY
    ax3 = fig.add_subplot(2, 3, 3)
    for name in present:
        sel = np.asarray([s == name for s in species])
        ax3.scatter(depth[sel], angles[sel], s=5, alpha=0.35,
                    color=style10.colour_of(name),
                    marker=style10.marker_of(name))
    rho, p = spearmanr(depth, angles)
    ax3.set_xscale("log")
    ax3.set_xlabel("drop depth (mV, log)")
    ax3.set_ylabel("fall angle (deg)")
    ax3.set_title(f"3. DETECTOR GEOMETRY, not a finding\nrho = {rho:.3f}",
                  fontsize=9)
    style10.readable_grey(fig, ax3)
    info["depth_angle_spearman_rho"] = float(rho)
    info["depth_angle_p"] = float(p)

    # 4. the control: duration ~ depth^b
    ax4 = fig.add_subplot(2, 3, 4)
    ok = (depth > 0) & (fall > 0)
    b, a = np.polyfit(np.log10(depth[ok]), np.log10(fall[ok]), 1)
    ax4.scatter(depth[ok], fall[ok], s=5, alpha=0.3, color="0.35")
    grid = np.logspace(np.log10(depth[ok].min()), np.log10(depth[ok].max()), 50)
    ax4.plot(grid, 10 ** a * grid ** b, color=style10.style7.MEAN_COLOUR,
             lw=style10.style7.LW_MEDOID)
    ax4.set_xscale("log"); ax4.set_yscale("log")
    ax4.set_xlabel("drop depth (mV, log)")
    ax4.set_ylabel("fall duration (s, log)")
    ax4.set_title(f"4. the control: exponent b = {b:.3f}", fontsize=9)
    style10.readable_grey(fig, ax4)
    info["control_exponent_b"] = float(b)

    # 5. fall angle by species, as a between-corpus question
    ax5 = fig.add_subplot(2, 3, 5)
    data, labels = [], []
    for name in present:
        sel = np.asarray([s == name for s in species])
        data.append(angles[sel])
        labels.append(name)
    bp = ax5.boxplot(data, tick_labels=labels, patch_artist=True, widths=0.55)
    for patch, name in zip(bp["boxes"], present):
        patch.set_facecolor(style10.colour_of(name))
        patch.set_alpha(0.55)
    ax5.set_ylabel("fall angle (deg)")
    ax5.set_title("5. the same measurement, between species", fontsize=9)
    ax5.tick_params(axis="x", labelsize=7)
    style10.readable_grey(fig, ax5)
    info["angle_by_species"] = {
        name: {"n": int(len(d)), "median_deg": float(np.median(d)),
               "iqr_deg": [float(np.percentile(d, 25)),
                           float(np.percentile(d, 75))],
               "median_slope_mv_s": float(np.median(
                   slopes[np.asarray([s == name for s in species])]))}
        for name, d in zip(present, data)}

    ax6 = fig.add_subplot(2, 3, 6)
    ax6.set_axis_off()
    ax6.text(0.0, 1.0, control_note + "\n\nANGLE REFERENCE: " + caption,
             va="top", ha="left", fontsize=7.5, wrap=True, color="0.2",
             transform=ax6.transAxes)

    fig.suptitle(title, fontsize=11)
    fig.legend(handles=style10.species_handles(
        species=present, counts=_species_counts(kept)),
        loc="lower center", ncol=3, frameon=False, fontsize=8)
    fig.subplots_adjust(top=0.90, bottom=0.10, hspace=0.45, wspace=0.34)
    return _save(fig, path), info
