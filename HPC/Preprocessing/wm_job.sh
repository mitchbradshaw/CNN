#!/bin/bash
# =============================================================================
#  wm_job.sh  —  SLURM batch script for Pipelines/window_matrix_build/build_window_matrix.py
#
#  Computes Catch22, entropy, CNN and RF features over the full recording.
#  The Python script checkpoints via the v1 artifact's `computed` mask and
#  exits after 19 minutes so it fits inside this 20-minute job slot.  This
#  script resubmits itself as a new job if there is still work remaining,
#  chaining jobs until all stages are complete.
#
#  Resubmit decision (WINDOW_MATRIX_UI_PROMPT.md §0.2): this used to grep
#  `--status` output for "not started" or a partial "N / M" fraction. That
#  string match could never distinguish "not yet computed" from "computed,
#  and the answer legitimately is NaN" — the old builder wrote NaN for
#  BOTH — so a window whose feature function reliably raised (a flat
#  segment with no matching template, a channel gap, ...) was retried on
#  every resumed job forever, and this script resubmitted the chain
#  indefinitely, burning the allocation until someone noticed and
#  `scancel`'d it. The fix lives in the storage format (an explicit
#  `computed` boolean mask, separate from the values) and in
#  `wm_status.py`'s EXIT CODE, derived from that mask, which is what this
#  script checks below instead. This is not an arbitrary style preference —
#  see WINDOW_MATRIX_UI_PROMPT.md §0.2 for the full account of why the old
#  form was actually wrong, not just less elegant.
#
#  First submit:   sbatch HPC/Preprocessing/wm_job.sh
#  Check progress: python Pipelines/window_matrix_build/build_window_matrix.py --status
#  Cancel chain:   scancel <job-id>
# =============================================================================

# ── Job metadata ──────────────────────────────────────────────────────────────
#SBATCH --job-name=wm_build
#SBATCH --chdir=/home/Student/s4699158/CNN
#SBATCH --output=/home/Student/s4699158/CNN/logs/wm_%j.out
#SBATCH --error=/home/Student/s4699158/CNN/logs/wm_%j.err
#SBATCH --mail-type=FAIL
#SBATCH --mail-user=s4699158@rangpur.compute.eait.uq.edu.au

# ── Resources ─────────────────────────────────────────────────────────────────
#SBATCH --time=00:20:00          # must be >= TIMEOUT_MIN + ~1 min cleanup margin
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4        # feeds aeon / sklearn parallel threads
#SBATCH --mem=16G
#SBATCH --gres=gpu:a100          # needed for CNN stages; remove for CPU-only run
#SBATCH --partition=gpu

# =============================================================================
set -uo pipefail

mkdir -p logs

# Chain position, incremented on each resubmit. Capped so a bug that always
# reports incomplete terminates instead of looping forever — the same cap
# `Working.hpc.job_export.export_wm_job`'s generated scripts carry, kept in
# sync here by hand since this script (unlike a generated one) isn't
# regenerated from that module.
CHAIN_INDEX="${1:-1}"
MAX_CHAIN=12

echo "========================================"
echo "Job ID       : $SLURM_JOB_ID"
echo "Job name     : $SLURM_JOB_NAME"
echo "Node         : $SLURMD_NODENAME"
echo "Chain        : $CHAIN_INDEX / $MAX_CHAIN"
echo "Started      : $(date)"
echo "Working dir  : $(pwd)"
echo "========================================"

# ── Environment ───────────────────────────────────────────────────────────────
module load cuda/12.2

source ~/miniconda3/etc/profile.d/conda.sh
conda activate torch_env

echo "Python       : $(which python)"
echo "Python ver   : $(python --version)"
echo "Torch ver    : $(python -c 'import torch; print(torch.__version__)')"
echo "CUDA avail   : $(python -c 'import torch; print(torch.cuda.is_available())')"
if python -c 'import torch; exit(0 if torch.cuda.is_available() else 1)' 2>/dev/null; then
    echo "GPU          : $(python -c 'import torch; print(torch.cuda.get_device_name(0))')"
fi
echo "========================================"

# Resolved BEFORE the build runs — it's the same deterministic path
# build_window_matrix.py itself computes and writes to, so `wm_status.py`
# below checks the artifact this exact invocation just produced, not a
# guessed or independently-reconstructed filename.
ARTIFACT_PATH="$(python Pipelines/window_matrix_build/build_window_matrix.py --print-artifact-path)"
echo "Artifact     : $ARTIFACT_PATH"

# ── Run window matrix builder ─────────────────────────────────────────────────
# The script checkpoints its `computed` mask continuously (persisted to the
# artifact by `build_window_matrix`'s stage runners) and exits cleanly when
# TIMEOUT_MIN (19) is reached. Re-running resumes automatically from the
# artifact's own mask, never from `isnan(values)`.
python Pipelines/window_matrix_build/build_window_matrix.py --timeout 19

echo ""
echo "========================================"
echo "Run finished : $(date)"
echo "========================================"

# ── Auto-resubmit if work remains ────────────────────────────────────────────
# EXIT CODE from wm_status.py, not a grepped string (see the header comment
# for why the old form was a real bug, not just a style choice):
#   0 = complete, stop.   1 = incomplete, resubmit.
#   2 = no artifact yet, resubmit.   >=3 = read/usage error, stop.
python Pipelines/window_matrix_build/wm_status.py --artifact "$ARTIFACT_PATH"
STATUS=$?

if [ "$STATUS" -eq 0 ]; then
    echo ""
    echo ">>> All stages complete — job chain finished."
elif [ "$STATUS" -ge 3 ]; then
    echo ""
    echo ">>> Could not read the artifact (exit $STATUS) — stopping the chain rather than looping on a broken path."
    exit "$STATUS"
elif [ "$CHAIN_INDEX" -ge "$MAX_CHAIN" ]; then
    echo ""
    echo ">>> Work remains but the chain cap ($MAX_CHAIN) is reached — stopping."
    echo ">>> Resubmit manually if this is expected: sbatch $(pwd)/HPC/Preprocessing/wm_job.sh 1"
else
    NEXT=$((CHAIN_INDEX + 1))
    echo ""
    echo ">>> Work remaining — submitting job $NEXT / $MAX_CHAIN in chain..."
    sbatch "$(pwd)/HPC/Preprocessing/wm_job.sh" "$NEXT"
    echo ">>> Submitted.  Monitor with: squeue -u $USER"
fi

echo "========================================"
echo "Finished     : $(date)"
echo "========================================"
