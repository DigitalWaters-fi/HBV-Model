#!/bin/bash
#SBATCH --job-name=hbv_run
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --output=/data/hbv/logs/%j_%a.out
#SBATCH --error=/data/hbv/logs/%j_%a.err
#SBATCH --partition=hbv
#SBATCH --chdir=/data/hbv
#
# Array size is set by the API: sbatch --array=0-N hbv_run.sh
# All input paths come from environment variables set by the API.

SIF=/data/hbv/hbv-compute.sif
TOTAL=${SLURM_ARRAY_TASK_COUNT}
TASK=${SLURM_ARRAY_TASK_ID}

mkdir -p "${HBV_OUTPUT_DIR}"
mkdir -p /data/hbv/logs

echo "[SLURM] job=${SLURM_JOB_ID} task=${TASK}/${TOTAL} user=${HBV_USER} started on $(hostname)"

apptainer exec "${SIF}" \
    python /app/hbv_worker.py \
    --job-id     "${HBV_JOB_ID}" \
    --task        "${TASK}" \
    --total       "${TOTAL}" \
    --shapefile   "${HBV_SHAPEFILE}" \
    --precip-nc   "${HBV_PRECIP_NC}" \
    --et-nc       "${HBV_ET_NC}" \
    --temp-nc     "${HBV_TEMP_NC}" \
    --urban-path  "${HBV_URBAN_PATH}" \
    --agri-path   "${HBV_AGRI_PATH}" \
    --para-csv    "${HBV_PARA_PATH}" \
    --catchments  "${HBV_CATCHMENT_IDS}" \
    --id-col      "${HBV_ID_COL:-TASO_ID}" \
    --output      "${HBV_OUTPUT_DIR}"

EXIT_CODE=$?
echo "[SLURM] job=${SLURM_JOB_ID} task=${TASK} finished with exit code ${EXIT_CODE}"

# Write status file so API can detect completion without sacct
if [[ $EXIT_CODE -eq 0 ]]; then
    echo '{"ok": 1, "errors": 0, "failed_ids": []}' > "${HBV_OUTPUT_DIR}/task_${TASK}_status.json"
else
    echo '{"ok": 0, "errors": 1, "failed_ids": []}' > "${HBV_OUTPUT_DIR}/task_${TASK}_status.json"
fi

exit ${EXIT_CODE}
