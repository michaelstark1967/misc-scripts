#!/usr/bin/env bash
set -euo pipefail

# Default schedule: daily at 03:00
CRON_SCHEDULE="${CRON_SCHEDULE:-0 3 * * *}"

CRON_FILE=/etc/cron.d/alkira-cron
LOG_FILE=/app/alkira-reports/cron.log

# Write the cron file using the schedule from env
cat > "$CRON_FILE" <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

# Cron job generated at container start
$CRON_SCHEDULE root cd /app/alkira-reports && /bin/bash -lc './run_aggregate_and_email.sh >> $LOG_FILE 2>&1'
EOF

chmod 0644 "$CRON_FILE"
crontab "$CRON_FILE"

# Ensure log file exists
mkdir -p /app/alkira-reports
touch "$LOG_FILE"
chmod 644 "$LOG_FILE"

# Start cron in foreground
exec /usr/sbin/cron -f
