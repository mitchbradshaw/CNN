#!/bin/bash
# =============================================================================
#  SLURM job: run CNN scoring on consecutive windows and save WindowMatrix CSV
#  Submit with:  sbatch score_job.sh
# =============================================================================

# ── Job metadata ──────────────────────────────────────────────────────────────
#SBATCH --job-name=eeg_cnn_score
#SBATCH --chdir=/home/s4699158/CNN
#SBATCH --output=/home/s4699158/CNN/logs/score_%j.out
#SBATCH --error=/home/s4699158/CNN/logs/score_%j.err
#SBATCH --mail-type=END,FAIL
#SBATCH --mail-user=s4699158@rangpur.compute.eait.uq.edu.au

# ── Resources ─────────────────────────────────────────────────────────────────
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=00:15:00

# ── GPU ───────────────────────────────────────────────────────────────────────
#SBATCH --gres=gpu:a100
#SBATCH --partition=gpu

# =============================================================================

set -euo pipefail

echo "========================================"
echo "Job ID       : $SLURM_JOB_ID"
echo "Job name     : $SLURM_JOB_NAME"
echo "Node         : $SLURMD_NODENAME"
echo "Started      : $(date)"
echo "Working dir  : $SLURM_SUBMIT_DIR"
echo "========================================"

mkdir -p /home/s4699158/CNN/logs /home/s4699158/CNN/MATRICES

module purge
module load cuda/12.2

source ~/miniconda3/etc/profile.d/conda.sh
conda activate torch_env

echo "Python       : $(which python)"
echo "Torch ver    : $(python -c 'import torch; print(torch.__version__)')"
echo "CUDA avail   : $(python -c 'import torch; print(torch.cuda.is_available())')"
echo "GPU          : $(python -c 'import torch; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")')"
echo "========================================"

python - <<'PYEOF'
import sys, os
sys.path.insert(0, os.path.expanduser("~/CNN"))

import numpy as np
from manage_data.load_data import load_raw_data
from matrix_calc import create_matrix
from cnn.apply_cnn import add_cnn_scores

FS2        = 1.0
TIMESCALE2 = 10          # minutes
MODEL_PATH = "MODELS/fusion_cnn_3.pth"

print(f"Loading signal...")
x2, _ = load_raw_data("M2_concat_fs1.mat", FS2)

window_samples2    = int(TIMESCALE2 * 60 * FS2)
n_windows2         = len(x2) // window_samples2
consecutive_starts = np.arange(n_windows2) * window_samples2

print(f"Signal length : {len(x2):,} samples")
print(f"Window size   : {window_samples2} samples ({TIMESCALE2} min)")
print(f"Windows       : {n_windows2}")

wm2 = create_matrix(consecutive_starts, x2, timescale=TIMESCALE2, fs=FS2)

add_cnn_scores(wm2, model_path=MODEL_PATH, batch_size=64)

out_path = f"MATRICES/M2_concat_fs{FS2:g}_{TIMESCALE2:g}min_{n_windows2}wins_consecutive.csv"
wm2.df.to_csv(out_path)
print(f"Saved → {out_path}")
PYEOF

echo "========================================"
echo "Finished : $(date)"
echo "========================================"
