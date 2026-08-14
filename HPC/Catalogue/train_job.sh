#!/bin/bash
# =============================================================================
#  SLURM job script for Working/Catalogue/cnn/cnn_rangapur.py
#  Submit from the repo root with:  sbatch HPC/Catalogue/train_job.sh
# =============================================================================

# ── Job metadata ──────────────────────────────────────────────────────────────
#SBATCH --job-name=eeg_cnn_train
#SBATCH --output=logs/train_%j.out      # stdout  (%j = job ID)
#SBATCH --error=logs/train_%j.err       # stderr
#SBATCH --mail-type=END,FAIL            # email on finish or failure
#SBATCH --mail-user=s4699158@rangpur.compute.eait.uq.edu.au    # ← change this

# ── Resources ─────────────────────────────────────────────────────────────────
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8              # DataLoader workers + overhead
#SBATCH --time=00:15:00                # wall-clock limit (HH:MM:SS)

# ── GPU ───────────────────────────────────────────────────────────────────────
#SBATCH --gres=gpu:a100               # 1 GPU; change to gpu:a100:1 etc. if needed
#SBATCH --partition=gpu                # ← change to your cluster's GPU partition name

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

# ── Create log dir if it doesn't exist ───────────────────────────────────────
mkdir -p logs models metrics

# ── Load modules (adjust to your HPC's module system) ────────────────────────
# Run `module avail` on your HPC to find the right names
module purge
module load cuda/12.1          # ← adjust CUDA version

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
python -m Working.Catalogue.cnn.cnn_rangapur --image_type GADF

# To train only one image type:
#   python -m Working.Catalogue.cnn.cnn_rangapur --image_type GASF ...

# To resume a previously interrupted job:
#   python -m Working.Catalogue.cnn.cnn_rangapur --resume ...

# ── Done ──────────────────────────────────────────────────────────────────────
echo "========================================"
echo "Finished     : $(date)"
echo "========================================"
