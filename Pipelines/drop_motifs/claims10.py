"""
claims10.py
============
CLAIMS.md, assembled from the analysis JSONs rather than transcribed.

Round one's ledger existed because a number that is retyped is a number
that drifts: `nulls_v1` found the shipped cophenetic r of 0.681 quoted in
two documents after the store defect behind it had already been measured.
So the VERDICTS here are authored - they are judgements and have to be -
but every number in every row is read out of the file that computed it,
and a row whose source file is missing says so rather than being written
from memory.

Verdicts
--------
    supported      the effect is there and its null does not reproduce it
    bounded        the effect is there, but it is smaller or narrower than
                   the sentence a reader would write from it
    not supported  the measurement does not distinguish the claim from its
                   null
    falsified      the measurement contradicts the claim

Every falsified row carries the sentence the paper should use instead.
That is the row's whole point: a falsified claim with no replacement gets
quietly re-asserted in the next draft.
"""

import json
import os

SUPPORTED = "supported"
BOUNDED = "bounded"
NOT_SUPPORTED = "not supported"
FALSIFIED = "falsified"

_ORDER = (SUPPORTED, BOUNDED, NOT_SUPPORTED, FALSIFIED)


def load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _p(value):
    """A p-value at the resolution the shuffles actually bought."""
    if value is None:
        return "-"
    if value <= 1e-4:
        return f"{value:.1e} (floor)"
    return f"{value:.4f}"


def row(claim, evidence, null, verdict, instead=None):
    return {"claim": claim, "evidence": evidence, "null": null,
            "verdict": verdict, "instead": instead}


def render(rows, title, preamble):
    lines = [f"# {title}", "", preamble, ""]
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in _ORDER}
    lines.append("| verdict | rows |")
    lines.append("|---|---|")
    for verdict in _ORDER:
        lines.append(f"| {verdict} | {counts[verdict]} |")
    lines.append("")

    lines.append("## The ledger")
    lines.append("")
    lines.append("| # | claim | evidence | null / control | verdict |")
    lines.append("|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        mark = ("**" + r["verdict"].upper() + "**"
                if r["verdict"] in (FALSIFIED, NOT_SUPPORTED)
                else r["verdict"])
        lines.append(f"| {i} | {r['claim']} | {r['evidence']} | "
                     f"{r['null']} | {mark} |")
    lines.append("")

    replaced = [(i, r) for i, r in enumerate(rows, 1) if r["instead"]]
    if replaced:
        lines.append("## The sentences the paper should use instead")
        lines.append("")
        lines.append("Every falsified or bounded row that needs different "
                     "wording, with the wording. A falsified claim with no "
                     "replacement gets quietly re-asserted in the next "
                     "draft.")
        lines.append("")
        for i, r in replaced:
            lines.append(f"**Row {i} — {r['verdict']}.** {r['claim']}")
            lines.append("")
            lines.append(f"> {r['instead']}")
            lines.append("")
    return "\n".join(lines)


def write(rows, path, *, title, preamble):
    text = render(rows, title, preamble)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return str(path)
