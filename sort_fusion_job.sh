#!/bin/bash
# =============================================================================
#  SLURM job script for cnn_prediction.py
#  Submit with:  sbatch sort_fusion_job.sh
# =============================================================================

# ── Job metadata ──────────────────────────────────────────────────────────────
#SBATCH --job-name=sort_fusion
#SBATCH --output=logs/fusionsort_%j.out      # stdout  (%j = job ID)
#SBATCH --error=logs/fusionsort_%j.err       # stderr

# ── Resources ─────────────────────────────────────────────────────────────────
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8              # DataLoader workers + overhead
#SBATCH --time=00:15:00                # wall-clock limit (HH:MM:SS)

# ── GPU ───────────────────────────────────────────────────────────────────────
#SBATCH --gres=gpu:a100               # ← change to your cluster's GPU partition name

# =============================================================================

# Exit immediately if any command fails
set -euo pipefail

# ── Logging helpers ───────────────────────────────────────────────────────────
echo "========================================"
echo "Job ID       : $SLURM_JOB_ID"
echo "Job name     : $SLURM_JOB_NAME"
echo "Node         : $(hostname)"
echo "Started      : $(date)"
echo "Working dir  : $(pwd)"
echo "========================================"

# ── Load modules (adjust to your HPC's module system) ────────────────────────
# Run `module avail` on your HPC to find the right names
module purge
module load cuda/12.2        

# ── Activate conda environment ────────────────────────────────────────────────
# If conda isn't on PATH by default in batch jobs, source it explicitly:
source ~/miniconda3/etc/profile.d/conda.sh    # ← adjust path if using Anaconda
# or: source ~/anaconda3/etc/profile.d/conda.sh

conda activate torch_env  # ← change to your conda environment name

echo "Python       : $(which python)"
echo "Python ver   : $(python --version)"
echo "Torch ver    : $(python -c 'import torch; print(torch.__version__)')"
echo "CUDA avail   : $(python -c 'import torch; print(torch.cuda.is_available())')"
echo "GPU          : $(python -c 'import torch; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")')"
echo "========================================"

# ── Run training ──────────────────────────────────────────────────────────────
python cnn_prediction.py

# ── Done ──────────────────────────────────────────────────────────────────────
echo "========================================"
echo "Finished     : $(date)"
echo "========================================"