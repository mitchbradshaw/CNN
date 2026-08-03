#!/bin/bash
# =============================================================================
#  wm_job.sh  —  SLURM batch script for Pipelines/window_matrix_build/build_window_matrix.py
#
#  Computes Catch22, entropy, CNN and RF features over the full recording.
#  The Python script checkpoints every 50 windows and exits after 19 minutes
#  so it fits inside this 20-minute job slot.  This script automatically
#  resubmits itself as a new job if there is still work remaining, chaining
#  jobs until all stages are complete.
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

echo "========================================"
echo "Job ID       : $SLURM_JOB_ID"
echo "Job name     : $SLURM_JOB_NAME"
echo "Node         : $SLURMD_NODENAME"
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

# ── Run window matrix builder ─────────────────────────────────────────────────
# The script saves progress after every BATCH_SIZE (50) windows and exits
# cleanly when TIMEOUT_MIN (19) is reached.  Re-running resumes automatically.
python Pipelines/window_matrix_build/build_window_matrix.py --timeout 19

echo ""
echo "========================================"
echo "Run finished : $(date)"
echo "========================================"

# ── Auto-resubmit if work remains ────────────────────────────────────────────
# Parse --status output for any incomplete stage (shows "not started" or
# a partial fraction like "500 / 1500").  If found, queue the next job.
STATUS_OUT=$(python Pipelines/window_matrix_build/build_window_matrix.py --status 2>&1)
printf '%s\n' "$STATUS_OUT"

if printf '%s\n' "$STATUS_OUT" | grep -qE "(not started|[0-9]+ / [0-9]+)"; then
    echo ""
    echo ">>> Work remaining — submitting next job in chain..."
    sbatch "$(pwd)/HPC/Preprocessing/wm_job.sh"
    echo ">>> Submitted.  Monitor with: squeue -u $USER"
else
    echo ""
    echo ">>> All stages complete — job chain finished."
fi

echo "========================================"
echo "Finished     : $(date)"
echo "========================================"
