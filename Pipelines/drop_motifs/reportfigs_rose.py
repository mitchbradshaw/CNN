"""
reportfigs_rose.py
===================
Report figure 2: `ROSE_scale.pdf`, fall angle and normalised drop shape by
species.

This plate exists as a hand-assembly. `Plots/drop_motifs12b/rose_scale.png`
was cut out of two figures and pasted together - the top row of
`S2_1_fall_angle` and the right-hand column of `S2_2_scale_collapse` - and
that composite is the one the report wants. Drawn here as ONE figure
rather than re-cut, so it has a single layout, a single type scale, and
regenerates from the store without anybody reaching for an image editor.

Nothing about the content changes. The roses are `figures11_s2._rose` on
the same 18 angular bins over -90 to 0 degrees, each on its own radial
scale for that function's stated reason - the species counts differ by a
factor of three and a shared ceiling would draw the smallest as a smear at
the origin. The lower row is `figures12b_s2`'s normalised panel: every
event's own samples, both axes normalised per event, from -0.5 to 1.5
fall-fractions, with the pointwise median over it.

What the two rows are for, together
-----------------------------------
The top row is the measurement in absolute terms: how steep the fall is,
in degrees against a pooled reference slope. The species separate on it.
The bottom row is the same events with duration and amplitude divided out.
They stop separating. That pairing is the figure's whole argument and it
is why the two rows belong on one plate.

Rule 3 removed two things the source figures carried: the store path and
event count footer, and the sentence about `max_slope_raw` units. Both are
in the JSON written beside the PDF.
"""

import numpy as np
from matplotlib import gridspec

from Pipelines.drop_motifs import (config11, drawing_rules, figures11_s2,
                                   figures12b_s2, reportstyle, store11)

# The lower row's sample size, `figures12b_s2.N_SAMPLE`. Seeded per species
# by `config11.rng_for`, so adding a species cannot reshuffle another
# species' draw and the plate reproduces.
N_SAMPLE = figures12b_s2.N_SAMPLE

ALPHA_SAMPLE = figures12b_s2.ALPHA_SAMPLE
LW_SAMPLE = figures12b_s2.LW_SAMPLE
LW_MEDIAN = figures12b_s2.LW_MEDIAN
Z_QUANTILE = figures12b_s2.Z_QUANTILE


def plot_rose_and_scale(rows, snippets, path, *, title="Fall angle and "
                        "normalised drop shape by species",
                        n_sample=N_SAMPLE, proof_png=None):
    """Top: one fall-angle rose per species. Bottom: the same species'
    drops with both axes normalised per event.

    No suptitle: rule 3 keeps it off the plate, and `title` travels to the
    manifest instead. Each panel keeps its own small title - that is a
    label distinguishing one panel from its neighbours, not the figure's
    title - and the band above the grid is sized for those, not for a
    suptitle nobody draws.
    """
    from matplotlib import pyplot as plt

    reportstyle.apply_style()
    grouped = store11.by_species(rows)
    species = list(grouped)
    if not species:
        return None, {"reason": "no species in store"}
    resolved = config11.resolve(species)

    reference = store11.pooled_reference_mv_s(rows)
    angles = {name: np.array([store11.fall_angle_rad(r, reference)
                              for r in own], dtype=float)
              for name, own in grouped.items()}

    n_col = len(species)
    fig = plt.figure(figsize=(3.5 * n_col + 0.9, 7.5))
    # Three rows and not two: the angle reference is a row of its own
    # rather than a label floated at a figure fraction. An angle is
    # `arctan(slope / reference)` and says nothing without it, and a
    # caption positioned by fraction drifts onto a panel the moment the
    # layout changes - `figures11_s2`'s finding, kept.
    # `top` used to leave the suptitle a band of its own; with no suptitle
    # it is sized for the polar panels' own titles instead. A polar axes
    # reports a bounding box the size of its square cell, but it DRAWS a
    # quarter circle in the lower-left of that cell and hangs its title
    # over the empty upper part, so this still cannot be pushed to 1.0 -
    # `figures11_s2`'s finding, kept.
    outer = gridspec.GridSpec(3, 1, figure=fig, height_ratios=[1.0, 0.09, 1.0],
                              hspace=0.36, top=0.965, bottom=0.100,
                              left=0.075, right=0.975)
    top = gridspec.GridSpecFromSubplotSpec(1, n_col, subplot_spec=outer[0],
                                           wspace=0.36)
    bottom = gridspec.GridSpecFromSubplotSpec(1, n_col, subplot_spec=outer[2],
                                              wspace=0.34)

    manifest = {
        "title": title,
        "n_total": len(rows),
        "angle_reference_mv_s": float(reference),
        "angle_reference_rule": "pooled median |max_slope|, all species",
        "max_slope_unit": store11.MAX_SLOPE_UNIT_NOTE,
        "n_angle_bins": figures11_s2.N_ANGLE_BINS,
        "angle_range_deg": [-90, 0],
        "radial_scale": "per panel; the species counts differ by a factor "
                        "of three and a shared ceiling draws the smallest "
                        "as a smear at the origin",
        "normalised_axis": [drawing_rules.PHASE_LO, drawing_rules.PHASE_HI],
        "resampling": "none; every waveform is the event's own samples at "
                      "its own times",
        "sample_target": int(n_sample),
        "species": {},
    }

    for index, name in enumerate(species):
        own = grouped[name]
        colour = resolved[name]["colour"]
        label = resolved[name]["label"]

        # -- the rose ------------------------------------------------------
        rose = fig.add_subplot(top[0, index], projection="polar")
        counts = figures11_s2._rose(rose, angles[name], colour)
        rose.set_title(f"{label}  (n = {len(angles[name]):,})",
                       fontsize=reportstyle.FS_TITLE, pad=10.0)
        rose.tick_params(labelsize=reportstyle.FS_TICK)

        # -- the same species, normalised ---------------------------------
        ax = fig.add_subplot(bottom[0, index])
        drawn = figures12b_s2._sample(own, n=n_sample, species=name)
        phase_traces, phase_rows = drawing_rules.phase_block(drawn, snippets)
        for phase, z in phase_traces:
            ax.plot(phase, z, color=colour, lw=LW_SAMPLE, alpha=ALPHA_SAMPLE,
                    zorder=2)
        if phase_traces:
            axis = np.linspace(drawing_rules.PHASE_LO, drawing_rules.PHASE_HI,
                               400)
            ax.plot(axis, figures12b_s2._phase_median(phase_traces, axis),
                    color=colour, lw=LW_MEDIAN, zorder=4)
            # One trace reaching z = -6 otherwise sets the height for a
            # sample whose median excursion is 2.8. `figures12b_s2`'s rule.
            pooled = np.concatenate([z for _p, z in phase_traces])
            span = float(np.quantile(np.abs(pooled), Z_QUANTILE))
            ax.set_ylim(-span * 1.05, span * 1.05)
        ax.set_xlim(drawing_rules.PHASE_LO, drawing_rules.PHASE_HI)
        # Fixed, and not left to the locator. At 8 pt the automatic
        # 0.25 step puts seven labels under a 3 in panel and they touch;
        # these five are the axis's own landmarks - the onset at 0 and
        # the trough at 1 - plus its ends.
        ax.set_xticks([-0.5, 0.0, 0.5, 1.0, 1.5])
        for at, alpha in ((0.0, 0.55), (1.0, 0.35)):
            ax.axvline(at, color=reportstyle.RULE_COLOUR, ls="--", lw=0.9,
                       alpha=alpha, zorder=1)
        ax.set_title(f"{label} - normalised  (n = {len(phase_rows):,})",
                     fontsize=reportstyle.FS_TITLE)
        ax.set_xlabel("fall-fractions from onset\n"
                      "(0 the onset, 1 the trough)",
                      fontsize=reportstyle.FS_LABEL)
        ax.set_ylabel("amplitude (z of the fall)",
                      fontsize=reportstyle.FS_LABEL)
        ax.grid(alpha=reportstyle.GRID_ALPHA, lw=0.5)

        manifest["species"][name] = {
            "label": label,
            "n_in_store": len(own),
            "n_angles": int(len(angles[name])),
            "rose_counts": counts.tolist(),
            "rose_radial_max": int(counts.max()) if counts.size else 0,
            "median_angle_deg": float(np.median(np.rad2deg(angles[name]))),
            "median_max_slope_mv_s": float(np.median(
                [store11.max_slope_mv_s(r) for r in own])),
            "median_depth_mv": float(np.median(
                [abs(float(r["drop_depth_mv"])) for r in own])),
            "n_normalised_drawn": len(phase_rows),
            "seed": config11.seed_for(name),
        }

    reference_ax = fig.add_subplot(outer[1])
    reference_ax.set_axis_off()
    reference_ax.text(0.5, 0.5,
                      f"45° = {reference:.3g} mV/s "
                      f"(pooled median steepest slope)",
                      transform=reference_ax.transAxes, ha="center",
                      va="center", fontsize=reportstyle.FS_ANNOT,
                      color="0.30")

    manifest["type_sizes_outside_band"] = reportstyle.check_type_sizes(fig)
    return reportstyle.save(fig, path, proof_png=proof_png), manifest
