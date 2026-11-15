#!/usr/bin/env bash
# Điều khiển bot local: install | uninstall | start | stop | restart | status | logs [n]
#
# Hai chế độ:
# - Đã `install`: launchd (LaunchAgent của riêng user, không cần sudo) giữ bot chạy. Bot tự chạy khi
#   đăng nhập/bật máy và tự khởi động lại nếu bị crash. start/stop/restart đi qua launchctl.
# - Chưa install: chạy tiến trình nền tách khỏi terminal, PID ở var/bot.pid. Không tự chạy lại sau reboot.
# Dùng lại Python của repo stock (đã có vnstock 3.5.0, yfinance, pandas).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${BRIEF_PYTHON:-$ROOT/../stock/.venv/bin/python}"
PIDFILE="$ROOT/var/bot.pid"
OUT="$ROOT/var/logs/bot.out"
# launchd không được mở file trong ~/Documents (quyền riêng tư macOS) -> log stdout của launchd để ở ~/Library/Logs
LD_OUT="$HOME/Library/Logs/daily-brief/bot.out"
LABEL="local.daily-brief.bot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
mkdir -p "$ROOT/var/logs"

installed() { [[ -f "$PLIST" ]]; }
loaded() { launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; }
ld_pid() { launchctl print "$DOMAIN/$LABEL" 2>/dev/null | awk '/^\tpid = /{print $3}'; }
alive() { [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

manual_stop() {
  if ! alive; then rm -f "$PIDFILE"; return 0; fi
  pid=$(cat "$PIDFILE"); kill -TERM "$pid"
  for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
  kill -0 "$pid" 2>/dev/null && { echo "Chưa dừng sau 10s, gửi SIGKILL"; kill -9 "$pid"; }
  rm -f "$PIDFILE"; echo "Đã dừng bot (tiến trình nền)."
}

check_started() {
  sleep 5
  if [[ -n "$(ld_pid)" ]]; then
    echo "Bot đang chạy dưới launchd (PID $(ld_pid)). Log: var/logs/bot.log"
  else
    echo "Bot chưa chạy – xem $LD_OUT và var/logs/bot.log."
    echo "Nếu log trống: macOS có thể đang chặn Python đọc ~/Documents (xem README, mục launchd)."; exit 1
  fi
}

write_plist() {
  mkdir -p "$HOME/Library/LaunchAgents" "$(dirname "$LD_OUT")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>-m</string><string>brief</string><string>bot</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>BRIEF_SUPERVISED</key><string>1</string>
    <key>PYTHONPATH</key><string>$ROOT</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <!-- Chỉ khởi động lại khi thoát lỗi (crash, mất mạng lúc khởi động). Lỗi cấu hình/xung đột thoát 0 -> không lặp. -->
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$LD_OUT</string>
  <key>StandardErrorPath</key><string>$LD_OUT</string>
</dict>
</plist>
EOF
  plutil -lint "$PLIST" >/dev/null
}

case "${1:-status}" in
  install)
    [[ -x "$PY" ]] || { echo "Không thấy Python: $PY"; exit 1; }
    manual_stop
    loaded && launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    write_plist
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "Đã cài LaunchAgent: $PLIST"
    check_started
    ;;
  uninstall)
    loaded && launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"; echo "Đã gỡ LaunchAgent. Bot đã dừng và sẽ không tự chạy khi bật máy."
    ;;
  start)
    if installed; then
      if loaded; then launchctl kickstart "$DOMAIN/$LABEL"; else launchctl bootstrap "$DOMAIN" "$PLIST"; fi
      check_started; exit 0
    fi
    if alive; then echo "Bot đang chạy (PID $(cat "$PIDFILE"))."; exit 0; fi
    [[ -x "$PY" ]] || { echo "Không thấy Python: $PY"; exit 1; }
    cd "$ROOT"
    # Tách hẳn khỏi terminal/phiên hiện tại (session mới) để không bị dừng theo cửa sổ.
    "$PY" - "$PY" "$OUT" "$PIDFILE" <<'PYEOF'
import subprocess, sys
py, out, pidfile = sys.argv[1:4]
p = subprocess.Popen([py, "-m", "brief", "bot"], stdout=open(out, "w"), stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, start_new_session=True)
open(pidfile, "w").write(str(p.pid))
PYEOF
    sleep 4
    if alive; then echo "Đã khởi động bot (PID $(cat "$PIDFILE")). Log: var/logs/bot.log"; else echo "Bot thoát ngay – xem $OUT và var/logs/bot.log"; exit 1; fi
    ;;
  stop)
    if installed; then
      if loaded; then launchctl bootout "$DOMAIN/$LABEL"; echo "Đã dừng bot (launchd). Sẽ tự chạy lại ở lần đăng nhập/bật máy sau, hoặc khi gõ: $0 start"
      else echo "Bot không chạy."; fi
      exit 0
    fi
    if alive; then manual_stop; else echo "Bot không chạy."; rm -f "$PIDFILE"; fi
    ;;
  restart)
    if installed && loaded; then launchctl kickstart -k "$DOMAIN/$LABEL"; check_started; exit 0; fi
    "$0" stop; "$0" start
    ;;
  status)
    if installed; then
      echo "Chế độ: launchd ($PLIST)"
      if [[ -n "$(ld_pid)" ]]; then echo "Đang chạy: PID $(ld_pid)"; ps -o pid,ppid,etime,command -p "$(ld_pid)"
      elif loaded; then echo "Đã nạp nhưng không chạy:"; launchctl print "$DOMAIN/$LABEL" | grep -E 'state|last exit' || true
      else echo "Không chạy (đã dừng bằng stop)."; fi
    elif alive; then echo "Chế độ: tiến trình nền (chưa install launchd)"; echo "Đang chạy: PID $(cat "$PIDFILE")"; ps -o pid,ppid,etime,command -p "$(cat "$PIDFILE")"
    else echo "Không chạy."; fi
    ;;
  logs) tail -n "${2:-40}" "$ROOT/var/logs/bot.log" ;;
  *) echo "Dùng: $0 {install|uninstall|start|stop|restart|status|logs [n]}"; exit 2 ;;
esac
