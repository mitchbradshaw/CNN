#!/bin/bash
# =============================================================================
#  SLURM job: run CNN scoring on consecutive windows and save WindowMatrix CSV
#  Submit from the repo root with:  sbatch HPC/Catalogue/score_job.sh
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

# Analysis logic lives in Pipelines/cnn_scoring/score_windows.py — this script
# only sets up the environment and invokes it.
python Pipelines/cnn_scoring/score_windows.py \
    --file       M2_concat_fs1.mat \
    --model      MODELS/fusion_cnn_3.pth \
    --timescale  10 \
    --fs         1.0 \
    --batch_size 64

echo "========================================"
echo "Finished : $(date)"
echo "========================================"
