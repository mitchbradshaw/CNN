"""
wm_status.py
=============
Completeness check for a v1 window-matrix artifact, as an exit code.

This is the interface the generated SLURM chain script resubmits on. The
hand-written `HPC/Preprocessing/wm_job.sh` decides whether to resubmit by
grepping `--status` output for the string "not started" or a "N / M"
fraction:

    if printf '%s\\n' "$STATUS_OUT" | grep -qE "(not started|[0-9]+ / [0-9]+)"; then
        sbatch "$(pwd)/HPC/Preprocessing/wm_job.sh"

Combined with the old builder's use of NaN to mean both "not yet computed"
and "computed, and the answer is NaN", one reliably-failing window made that
condition true forever and the chain resubmitted itself until someone
noticed (WINDOW_MATRIX_UI_PROMPT.md §0.2). An exit code derived from the
artifact's own `computed` mask cannot drift the way a grepped string can.

Exit codes
----------
  0  complete — nothing left to do, stop the chain
  1  incomplete — resubmit
  2  no artifact yet — resubmit (the first job has not produced one)
  3  usage/read error — stop the chain rather than looping on a broken path

Usage
-----
  python Pipelines/window_matrix_build/wm_status.py --artifact PATH
  python Pipelines/window_matrix_build/wm_status.py --artifact PATH --quiet
"""

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

import argparse
import os
import sys

import numpy as np

from Working.database import window_matrix_store as store


def artifact_progress(path):
    """`(n_computed, n_cells, complete)` for a v1 artifact."""
    loaded = store.load_wm(path, mmap=False)
    computed = np.asarray(loaded["computed"], dtype=bool)
    return int(computed.sum()), int(computed.size), bool(loaded["complete"])


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--artifact", required=True, help="Path to the v1 .npz artifact")
    p.add_argument("--quiet", action="store_true", help="Exit code only, no output")
    args = p.parse_args()

    if not os.path.isfile(args.artifact):
        if not args.quiet:
            print(f"no artifact yet at {args.artifact} — work remains")
        sys.exit(2)

    try:
        done, total, complete = artifact_progress(args.artifact)
    except Exception as exc:
        print(f"could not read {args.artifact}: {exc}", file=sys.stderr)
        sys.exit(3)

    if not args.quiet:
        pct = 100.0 * done / total if total else 100.0
        state = "COMPLETE" if complete else "INCOMPLETE"
        print(f"{state}  {done:,} / {total:,} cells ({pct:.1f} %)  {args.artifact}")

    sys.exit(0 if complete else 1)


if __name__ == "__main__":
    main()
