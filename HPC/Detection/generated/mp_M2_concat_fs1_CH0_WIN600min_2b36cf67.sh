#!/bin/bash
#SBATCH --job-name=mp_CH0_WIN600min
#SBATCH --chdir=/home/Student/s4699158/CNN
#SBATCH --output=/home/Student/s4699158/CNN/logs/mp_M2_concat_fs1_CH0_WIN600min_2b36cf67_%j.out
#SBATCH --error=/home/Student/s4699158/CNN/logs/mp_M2_concat_fs1_CH0_WIN600min_2b36cf67_%j.err
#SBATCH --time=119:45:00
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

python Pipelines/run_recipe/run_recipe.py --config HPC/Detection/generated/mp_M2_concat_fs1_CH0_WIN600min_2b36cf67.json

echo "========================================"
echo "Finished : $(date)"
echo "========================================"
