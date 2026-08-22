#!/usr/bin/env bash
# Hourly VN session wrapper for cron / launchd (Asia/Ho_Chi_Minh).
# Example crontab (local clock = ICT):
#   5 8-14 * * 1-5  /Users/namnguyen/Documents/Cursor/stock/deploy/run_hourly_vn.sh
set -euo pipefail

STOCK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TB_ROOT="$(cd "$STOCK_ROOT/../Trading-bot" && pwd)"
LOG_DIR="$STOCK_ROOT/vn_stock/data/screening/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/hourly_vn_$(date +%Y%m%d).log"

export PYTHONPATH="$STOCK_ROOT:$TB_ROOT"
export TZ="Asia/Ho_Chi_Minh"

cd "$STOCK_ROOT"
{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  .venv/bin/python -m vn_stock.scripts.run_hourly_vn_session "$@"
  echo
} >>"$LOG" 2>&1
