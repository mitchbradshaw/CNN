#!/bin/bash
#SBATCH --job-name=eeg_matrix_profile
#SBATCH --chdir=/home/Student/s4699158/CNN
#SBATCH --output=/home/Student/s4699158/CNN/logs/mp_%j.out
#SBATCH --error=/home/Student/s4699158/CNN/logs/mp_%j.err
#SBATCH --time=00:15:00
#SBATCH --gres=gpu:a100
#SBATCH --cpus-per-task=4

echo "========================================"
echo "Job ID       : $SLURM_JOB_ID"
echo "Job name     : $SLURM_JOB_NAME"
echo "Node         : $SLURMD_NODENAME"
echo "Started      : $(date)"
echo "Working dir  : $(pwd)"
echo "========================================"

mkdir -p logs

module load cuda/12.2

source ~/miniconda3/etc/profile.d/conda.sh
conda activate torch_env

python matrix_profiling/run_matrix_profile.py

echo "========================================"
echo "Finished : $(date)"
echo "========================================"
