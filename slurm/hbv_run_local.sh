#!/bin/bash
# Local version of hbv_run.sh for Mac testing.
# When USE_DOCKER=1: runs the hbv-compute:local Docker image (closest to HPC Singularity).
# Otherwise:         runs Python from the venv directly (faster for dev).

TOTAL=${SLURM_ARRAY_TASK_COUNT:-1}
TASK=${SLURM_ARRAY_TASK_ID:-0}

mkdir -p "${HBV_OUTPUT_DIR}"
mkdir -p "${HBV_OUTPUT_DIR}/logs"

echo "[LOCAL-SLURM] job=${SLURM_JOB_ID} task=${TASK}/${TOTAL} user=${HBV_USER} started on $(hostname)"

WORKER_ARGS=(
    --job-id     "${HBV_JOB_ID}"
    --task        "${TASK}"
    --total       "${TOTAL}"
    --shapefile   "${HBV_SHAPEFILE}"
    --precip-nc   "${HBV_PRECIP_NC}"
    --et-nc       "${HBV_ET_NC}"
    --temp-nc     "${HBV_TEMP_NC}"
    --urban-path  "${HBV_URBAN_PATH}"
    --agri-path   "${HBV_AGRI_PATH}"
    --para-csv    "${HBV_PARA_PATH}"
    --catchments  "${HBV_CATCHMENT_IDS}"
    --id-col      "${HBV_ID_COL:-TASO_ID}"
)
# --output is appended separately to avoid bash 3 (macOS) array index issues
WORKER_OUTPUT_ARG="--output"

if [[ "${USE_DOCKER:-0}" == "1" ]]; then
    # ── Docker mode — mirrors Singularity on HPC ──────────────────────────
    # Mount all input paths and the output dir into the container.
    # Singularity does the same with --bind on the HPC.
    echo "[LOCAL-SLURM] running via Docker image hbv-compute:local"

    # Collect unique input directories to bind-mount read-only
    EXTRA_MOUNTS=()
    SEEN=""
    for PATH_VAR in "${HBV_SHAPEFILE}" "${HBV_PRECIP_NC}" "${HBV_ET_NC}" \
                    "${HBV_TEMP_NC}" "${HBV_URBAN_PATH}" "${HBV_AGRI_PATH}"; do
        DIR="${PATH_VAR%/*}"
        case ":${SEEN}:" in
            *":${DIR}:"*) ;;   # already added
            *)
                SEEN="${SEEN}:${DIR}"
                [[ -d "$DIR" ]] && EXTRA_MOUNTS+=(-v "${DIR}:${DIR}:ro")
                ;;
        esac
    done

    docker run --rm \
        -v "${HBV_OUTPUT_DIR}:/output" \
        "${EXTRA_MOUNTS[@]}" \
        -e HBV_JOB_ID="${HBV_JOB_ID}" \
        -e HBV_USER="${HBV_USER}" \
        hbv-compute:local \
        "${WORKER_ARGS[@]}" "$WORKER_OUTPUT_ARG" /output

else
    # ── Direct Python mode — fast inner-loop dev ──────────────────────────
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(dirname "$SCRIPT_DIR")"
    PYTHON="${REPO_ROOT}/venv/bin/python"
    WORKER="${REPO_ROOT}/compute/hbv_worker.py"

    "$PYTHON" "$WORKER" "${WORKER_ARGS[@]}" "$WORKER_OUTPUT_ARG" "${HBV_OUTPUT_DIR}"
fi

EXIT_CODE=$?
echo "[LOCAL-SLURM] job=${SLURM_JOB_ID} task=${TASK} finished with exit code ${EXIT_CODE}"

STATUS_FILE="${HBV_OUTPUT_DIR}/.task_${TASK}_done"
if [[ $EXIT_CODE -eq 0 ]]; then
    echo "done" > "$STATUS_FILE"
else
    echo "failed" > "$STATUS_FILE"
fi

exit ${EXIT_CODE}
