#!/bin/bash
# =============================================================================
#  SLURM job script for Working/Catalogue/cnn/cnn_fusion_prediction.py
#  Submit fresh:   sbatch HPC/Catalogue/train_fusion_prediction_job.sh
#  Resume:         sbatch HPC/Catalogue/train_fusion_prediction_job.sh --resume
# =============================================================================

# ── Job metadata ──────────────────────────────────────────────────────────────
#SBATCH --job-name=fusion_pred_train
#SBATCH --output=logs/fusion_pred_%j.out      # stdout  (%j = job ID)
#SBATCH --error=logs/fusion_pred_%j.err       # stderr

# ── Resources ─────────────────────────────────────────────────────────────────
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8              # matches num_workers=8 in CFG
#SBATCH --time=00:15:00                # wall-clock limit (HH:MM:SS)

# ── GPU ───────────────────────────────────────────────────────────────────────
#SBATCH --gres=gpu:a100

# =============================================================================

# Exit immediately if any command fails
set -euo pipefail

# Pass --resume flag through from sbatch argument: sbatch script.sh --resume
RESUME_FLAG=""
for arg in "$@"; do
    if [ "$arg" = "--resume" ]; then
        RESUME_FLAG="--resume"
    fi
done

# ── Logging helpers ───────────────────────────────────────────────────────────
echo "========================================"
echo "Job ID       : $SLURM_JOB_ID"
echo "Job name     : $SLURM_JOB_NAME"
echo "Node         : $(hostname)"
echo "Started      : $(date)"
echo "Working dir  : $(pwd)"
echo "Resume flag  : ${RESUME_FLAG:-none}"
echo "========================================"

mkdir -p logs

# ── Load modules ──────────────────────────────────────────────────────────────
module purge
module load cuda/12.2

# ── Activate conda environment ────────────────────────────────────────────────
source ~/miniconda3/etc/profile.d/conda.sh
conda activate torch_env

echo "Python       : $(which python)"
echo "Python ver   : $(python --version)"
echo "Torch ver    : $(python -c 'import torch; print(torch.__version__)')"
echo "CUDA avail   : $(python -c 'import torch; print(torch.cuda.is_available())')"
echo "GPU          : $(python -c 'import torch; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")')"
echo "========================================"

# ── Run training ──────────────────────────────────────────────────────────────
python -m Working.Catalogue.cnn.cnn_fusion_prediction $RESUME_FLAG

# ── Done ──────────────────────────────────────────────────────────────────────
echo "========================================"
echo "Finished     : $(date)"
echo "========================================"
