#!/bin/bash
#SBATCH --job-name=wm_CH4_WIN10min
#SBATCH --chdir=/home/Student/s4699158/CNN
#SBATCH --output=/home/Student/s4699158/CNN/logs/wm_M2_aug_concat_fs1_CH4_WIN10min_STEP100pct_4133a689_%j.out
#SBATCH --error=/home/Student/s4699158/CNN/logs/wm_M2_aug_concat_fs1_CH4_WIN10min_STEP100pct_4133a689_%j.err
#SBATCH --time=00:20:00
#SBATCH --cpus-per-task=4
#SBATCH --partition=cpu

# Chain position, incremented on each resubmit. Capped at 12 so a
# bug that always reports "incomplete" terminates instead of burning the
# allocation -- the failure mode the hand-written wm_job.sh has today.
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

mkdir -p logs


source ~/miniconda3/etc/profile.d/conda.sh
conda activate aeon-env

# --force on every job in the chain: the recipe and span are identical each
# time (the resume path is baked in from the first export, deliberately, so
# the config hash never changes), so without it execute_recipe would reuse
# the previous job's partial run instead of continuing it.
python Pipelines/run_recipe/run_recipe.py --config HPC/Preprocessing/generated/wm_M2_aug_concat_fs1_CH4_WIN10min_STEP100pct_4133a689.json --force

echo "========================================"
echo "Run finished : $(date)"

python Pipelines/window_matrix_build/wm_status.py --artifact Results/Preprocessing/window_matrix/wm_v1_M2_aug_concat_fs1_CH4_WIN10min_STEP100pct.npz
STATUS=$?

if [ "$STATUS" -eq 0 ]; then
    echo ">>> Matrix complete -- chain finished."
elif [ "$STATUS" -ge 3 ]; then
    echo ">>> Could not read the artifact (exit $STATUS) -- stopping the chain."
    exit "$STATUS"
elif [ "$CHAIN_INDEX" -ge "$MAX_CHAIN" ]; then
    echo ">>> Work remains but the chain cap ($MAX_CHAIN) is reached -- stopping."
    echo ">>> Resubmit manually if this is expected: sbatch HPC/Preprocessing/generated/wm_M2_aug_concat_fs1_CH4_WIN10min_STEP100pct_4133a689.sh 1"
else
    NEXT=$((CHAIN_INDEX + 1))
    echo ">>> Work remains -- submitting job $NEXT of $MAX_CHAIN ..."
    sbatch HPC/Preprocessing/generated/wm_M2_aug_concat_fs1_CH4_WIN10min_STEP100pct_4133a689.sh "$NEXT"
    echo ">>> Submitted. Monitor with: squeue -u $USER"
fi

echo "Finished     : $(date)"
echo "========================================"
