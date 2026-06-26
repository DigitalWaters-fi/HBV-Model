#!/bin/bash
# =============================================================================
# hbv_deploy.sh  —  One-shot HPC backend deployment script
#
# Run this on the HPC HEAD NODE as a user with sudo.
# It sets up NFS layout, Python venv, systemd service, and Singularity image.
#
# Usage:
#   bash deploy/hbv_deploy.sh [--rebuild-sif]
#
# Options:
#   --rebuild-sif   Force rebuild of the Singularity image even if it exists.
#                   Takes ~10 minutes on first run.
# =============================================================================
set -euo pipefail

# ── Config — edit these if your cluster differs ───────────────────────────
HBV_USER="${HBV_USER:-hbv}"          # system user that runs the API
HBV_GROUP="${HBV_GROUP:-hbv}"
NFS_ROOT="${NFS_ROOT:-/data/hbv}"    # must be on shared NFS (all nodes)
REPO_DIR="${REPO_DIR:-/opt/hbv/repo}"
VENV_DIR="${VENV_DIR:-/opt/hbv/venv}"
API_PORT="${API_PORT:-8000}"
SIF_PATH="${SIF_PATH:-$NFS_ROOT/hbv-compute.sif}"
REBUILD_SIF="${1:-}"

log()  { echo -e "\033[1;32m[HBV-DEPLOY]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
err()  { echo -e "\033[1;31m[ERROR]\033[0m $*" >&2; exit 1; }

# ── 0. Preflight ──────────────────────────────────────────────────────────
log "=== HBV backend deployment ==="
log "NFS_ROOT=$NFS_ROOT  REPO=$REPO_DIR"

command -v python3  >/dev/null || err "python3 not found — load the python module first"
command -v sbatch   >/dev/null || warn "sbatch not found — are you on the head node?"
command -v apptainer >/dev/null || command -v singularity >/dev/null \
    || warn "apptainer/singularity not found — SIF build step will fail"

SING=$(command -v apptainer 2>/dev/null || command -v singularity 2>/dev/null || echo "")

# ── 1. System user ────────────────────────────────────────────────────────
log "1/8  Ensuring system user '$HBV_USER'…"
if ! id "$HBV_USER" &>/dev/null; then
    sudo useradd --system --no-create-home --shell /bin/false "$HBV_USER"
fi

# ── 2. NFS directory layout ───────────────────────────────────────────────
log "2/8  Creating NFS directory layout at $NFS_ROOT …"
sudo mkdir -p \
    "$NFS_ROOT/api" \
    "$NFS_ROOT/uploads" \
    "$NFS_ROOT/output" \
    "$NFS_ROOT/logs" \
    "$NFS_ROOT/slurm"

sudo chown -R "${HBV_USER}:${HBV_GROUP}" "$NFS_ROOT"
sudo chmod -R 770 "$NFS_ROOT"
# Compute nodes write to output/ — make it world-writable within the group
sudo chmod g+s "$NFS_ROOT/output"
sudo chmod g+s "$NFS_ROOT/logs"

# ── 3. Copy Slurm script ──────────────────────────────────────────────────
log "3/8  Installing Slurm script…"
sudo cp slurm/hbv_run.sh "$NFS_ROOT/slurm/hbv_run.sh"
sudo chmod 755 "$NFS_ROOT/slurm/hbv_run.sh"
sudo chown "${HBV_USER}:${HBV_GROUP}" "$NFS_ROOT/slurm/hbv_run.sh"

# ── 4. Python virtualenv for the API ─────────────────────────────────────
log "4/8  Setting up Python venv at $VENV_DIR …"
sudo mkdir -p "$(dirname "$VENV_DIR")"
sudo chown "${HBV_USER}:${HBV_GROUP}" "$(dirname "$VENV_DIR")"

if [[ ! -d "$VENV_DIR" ]]; then
    sudo -u "$HBV_USER" python3 -m venv "$VENV_DIR"
fi

log "    Installing API requirements…"
sudo -u "$HBV_USER" "$VENV_DIR/bin/pip" install --quiet --upgrade pip
sudo -u "$HBV_USER" "$VENV_DIR/bin/pip" install --quiet -r api/requirements-api.txt

# ── 5. Install repo code ──────────────────────────────────────────────────
log "5/8  Placing repo at $REPO_DIR …"
sudo mkdir -p "$REPO_DIR"
sudo chown "${HBV_USER}:${HBV_GROUP}" "$REPO_DIR"
# Rsync only the code (skip venv, data, notebooks)
sudo rsync -a --delete \
    --exclude='venv/' --exclude='*.ipynb' --exclude='local_output/' \
    --exclude='local_uploads/' --exclude='output_csv_files/' \
    --exclude='Data-folder/' --exclude='__pycache__/' \
    --exclude='.git/' --exclude='*.tif' --exclude='*.nc' \
    . "$REPO_DIR/"
sudo chown -R "${HBV_USER}:${HBV_GROUP}" "$REPO_DIR"

# ── 6. Build Singularity image ────────────────────────────────────────────
log "6/8  Building Singularity/Apptainer image…"
if [[ -z "$SING" ]]; then
    warn "    No singularity/apptainer found — skipping SIF build."
    warn "    Build manually:  apptainer build $SIF_PATH docker-daemon://hbv-compute:local"
    warn "    OR transfer the .sif from your Mac:  scp /path/to/hbv-compute.sif hpc-head:$SIF_PATH"
elif [[ -f "$SIF_PATH" && "$REBUILD_SIF" != "--rebuild-sif" ]]; then
    log "    $SIF_PATH already exists — skip (use --rebuild-sif to force rebuild)"
else
    log "    This takes ~5-10 min on first run…"
    # Option A: build from the Dockerfile using Docker daemon on the head node
    if command -v docker &>/dev/null; then
        docker build -f Dockerfile.hpc -t hbv-compute:local . \
            && sudo "$SING" build "$SIF_PATH" docker-daemon://hbv-compute:local
    else
        # Option B: build directly from Dockerfile (requires fakeroot or --sandbox)
        sudo "$SING" build --fakeroot "$SIF_PATH" Dockerfile.hpc \
            || warn "    SIF build failed — transfer it from your Mac instead."
    fi
    sudo chown "${HBV_USER}:${HBV_GROUP}" "$SIF_PATH"
fi

# Update hbv_run.sh with actual SIF path
sudo sed -i "s|^SIF=.*|SIF=$SIF_PATH|" "$NFS_ROOT/slurm/hbv_run.sh"

# ── 7. systemd service ────────────────────────────────────────────────────
log "7/8  Installing systemd service…"
sudo cp deploy/hbv-api.service /etc/systemd/system/hbv-api.service
# Patch venv path and repo path into service file
sudo sed -i "s|/opt/hbv/venv|$VENV_DIR|g"  /etc/systemd/system/hbv-api.service
sudo sed -i "s|/opt/hbv/repo|$REPO_DIR|g"  /etc/systemd/system/hbv-api.service
sudo sed -i "s|User=hbv|User=$HBV_USER|g"  /etc/systemd/system/hbv-api.service
sudo sed -i "s|Group=hbv|Group=$HBV_GROUP|g" /etc/systemd/system/hbv-api.service
sudo sed -i "s|/data/hbv|$NFS_ROOT|g"      /etc/systemd/system/hbv-api.service

sudo systemctl daemon-reload
sudo systemctl enable  hbv-api
sudo systemctl restart hbv-api
sleep 3
if sudo systemctl is-active --quiet hbv-api; then
    log "    hbv-api service is RUNNING on port $API_PORT"
else
    err "    hbv-api failed to start — check: sudo journalctl -u hbv-api -n 50"
fi

# ── 8. Smoke test ─────────────────────────────────────────────────────────
log "8/8  Smoke-testing /health …"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${API_PORT}/health")
if [[ "$HTTP" == "200" ]]; then
    log "    /health returned 200 ✔"
else
    warn "    /health returned $HTTP — service may still be starting"
fi

log ""
log "=== Deployment complete ==="
log ""
log "Next steps:"
log "  1. Confirm NFS is mounted on all compute nodes at $NFS_ROOT"
log "  2. Test Singularity:  $SING exec $SIF_PATH python /app/hbv_worker.py --help"
log "  3. Set HBV_API_URL in your JupyterHub image to http://<HEAD_NODE_IP>:$API_PORT"
log "     (or https://<domain> if you set up nginx)"
log "  4. Optional: set up nginx TLS with deploy/nginx-hbv.conf"
log ""
log "Monitor the API:"
log "  sudo journalctl -u hbv-api -f"
log ""
log "Submit a test job:"
log "  curl -X POST http://127.0.0.1:$API_PORT/submit \\"
log "    -H 'X-User: testuser' -H 'Content-Type: application/json' \\"
log "    -d '{\"catchment_ids\":[\"12345\"],\"shapefile_path\":\"/data/hbv/uploads/.../file.shp\",\"precipitation_nc\":\"\",\"evapotranspiration_nc\":\"\",\"temperature_nc\":\"\",\"urban_land_path\":\"\",\"agricultural_land_path\":\"\"}'"
