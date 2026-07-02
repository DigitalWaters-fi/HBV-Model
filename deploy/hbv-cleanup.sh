#!/bin/bash
# Daily cleanup: delete output dirs for completed jobs older than 30 days.
# Install: sudo cp deploy/hbv-cleanup.sh /etc/cron.daily/hbv-cleanup
#          sudo chmod +x /etc/cron.daily/hbv-cleanup
set -e

API="http://localhost:8000"
DAYS=${HBV_CLEANUP_DAYS:-30}

result=$(curl -sf -X DELETE "${API}/admin/cleanup?days=${DAYS}" \
         -H "X-User: admin" 2>/dev/null || echo '{"error":"curl failed"}')

echo "[hbv-cleanup] $(date '+%Y-%m-%d') result: ${result}"
