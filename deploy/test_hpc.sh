#!/bin/bash
# =============================================================================
# test_hpc.sh  —  End-to-end smoke test for the HPC backend
# Run on the HPC HEAD NODE after hbv_deploy.sh completes.
#
# Usage:
#   bash deploy/test_hpc.sh [API_URL]
#   bash deploy/test_hpc.sh http://127.0.0.1:8000
# =============================================================================
set -euo pipefail

API="${1:-http://127.0.0.1:8000}"
TEST_USER="test-$(whoami)"
PASS=0; FAIL=0

ok()   { echo -e "  \033[1;32m✔\033[0m $*"; ((PASS++)); }
fail() { echo -e "  \033[1;31m✘\033[0m $*"; ((FAIL++)); }
section() { echo -e "\n\033[1;34m── $* ──\033[0m"; }

section "1. API health"
HTTP=$(curl -sf -o /dev/null -w "%{http_code}" "$API/health" 2>/dev/null || echo "000")
[[ "$HTTP" == "200" ]] && ok "/health → 200" || fail "/health → $HTTP (is uvicorn running?)"

section "2. Upload a small test file"
TMPFILE=$(mktemp /tmp/hbv_test_XXXX.csv)
echo "test,data" > "$TMPFILE"
RESP=$(curl -sf -X POST "$API/upload" \
    -H "X-User: $TEST_USER" \
    -F "file=@$TMPFILE" 2>/dev/null || echo '{}')
rm -f "$TMPFILE"
UPLOAD_PATH=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('path',''))" 2>/dev/null || echo "")
[[ -n "$UPLOAD_PATH" ]] && ok "Upload → $UPLOAD_PATH" || fail "Upload failed: $RESP"

section "3. Check Singularity / Apptainer"
SING=$(command -v apptainer 2>/dev/null || command -v singularity 2>/dev/null || echo "")
SIF="${HBV_SIF:-/data/hbv/hbv-compute.sif}"
[[ -n "$SING" ]]     && ok "$SING found" || fail "Neither apptainer nor singularity found"
[[ -f "$SIF" ]]      && ok "SIF found at $SIF" \
    || fail "SIF not found at $SIF — run: apptainer build $SIF docker-daemon://hbv-compute:local"

if [[ -n "$SING" && -f "$SIF" ]]; then
    section "4. Singularity exec (worker --help)"
    "$SING" exec "$SIF" python /app/hbv_worker.py --help >/dev/null 2>&1 \
        && ok "singularity exec hbv_worker.py --help OK" \
        || fail "singularity exec failed"
else
    section "4. Singularity exec — SKIPPED (SIF missing)"
fi

section "5. sbatch availability"
command -v sbatch >/dev/null && ok "sbatch found" || fail "sbatch not found (not on head node?)"

section "6. NFS layout"
NFS="${NFS_ROOT:-/data/hbv}"
for D in api uploads output logs slurm; do
    [[ -d "$NFS/$D" ]] && ok "$NFS/$D exists" || fail "$NFS/$D missing"
done
[[ -f "$NFS/slurm/hbv_run.sh" ]] && ok "$NFS/slurm/hbv_run.sh exists" \
    || fail "$NFS/slurm/hbv_run.sh missing"

section "7. API service (systemd)"
systemctl is-active --quiet hbv-api 2>/dev/null \
    && ok "hbv-api.service is active" \
    || fail "hbv-api.service is not running — sudo systemctl status hbv-api"

echo ""
echo "══════════════════════════════"
echo "  Passed: $PASS   Failed: $FAIL"
echo "══════════════════════════════"
[[ "$FAIL" -eq 0 ]] && echo -e "\033[1;32mAll checks passed — ready for production.\033[0m" \
    || echo -e "\033[1;31mFix the failures above before testing the full workflow.\033[0m"
