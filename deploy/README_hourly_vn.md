# VN hourly trading session

Mỗi giờ **T2–T6, 8:05–14:05** (giờ VN): cập nhật nến 1H/1D (dựng 4H) → quét `macd_signed` (MACD+ long / MACD− short) → Telegram khi có ý tưởng mới trong ngày.

**Đang chạy bằng launchd trên Mac** (`com.cursor.vn-hourly`). Workflow GitHub `vn-hourly-telegram.yml` đã tắt vì vnstock không còn trên PyPI — xem `GITHUB_ACTIONS_VN_HOURLY.md` (lưu trữ).

## Chạy thử ngay

```bash
cd /Users/namnguyen/Documents/Cursor/stock
export PYTHONPATH="$PWD:$PWD/../Trading-bot"
.venv/bin/python -m vn_stock.scripts.run_hourly_vn_session --force --dry-run
.venv/bin/python -m vn_stock.scripts.run_hourly_vn_session --force            # gửi thật
.venv/bin/python -m vn_stock.scripts.run_hourly_vn_session --heartbeat        # gửi cả khi 0 tín hiệu
```

Flags: `--symbols`, `--intervals 1D,1H`, `--delay 3.5`, `--no-fetch`, `--force` (bỏ check giờ), `--dry-run`, `--heartbeat`, `--open-hour 8`, `--close-hour 15` (hoặc env `VN_SESSION_OPEN/CLOSE`).

## launchd (đang dùng)

`deploy/vn-hourly.plist` gọi thẳng `.venv/bin/python -m vn_stock.scripts.run_hourly_vn_session` với `PYTHONPATH` và `TZ=Asia/Ho_Chi_Minh`.

```bash
cp deploy/vn-hourly.plist ~/Library/LaunchAgents/com.cursor.vn-hourly.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cursor.vn-hourly.plist
launchctl kickstart gui/$(id -u)/com.cursor.vn-hourly        # chạy ngay 1 lần
launchctl print gui/$(id -u)/com.cursor.vn-hourly | grep -E "state|last exit"
launchctl bootout gui/$(id -u)/com.cursor.vn-hourly          # gỡ
tail -f ~/Library/Logs/vn-hourly/hourly.log
```

Mac ngủ đúng giờ → launchd chạy bù **một** lần khi thức, không chạy lại từng giờ bị lỡ.

## cron (thay thế)

```
5 8-14 * * 1-5  /Users/namnguyen/Documents/Cursor/stock/deploy/run_hourly_vn.sh
```

Log: `vn_stock/data/screening/logs/hourly_vn_YYYYMMDD.log`. Không bật song song với launchd.

## Output

| File | Ý nghĩa |
|------|---------|
| `vn_stock/data/screening/hourly_vn_snapshot.json` | Snapshot mới nhất (coverage + ideas) |
| `vn_stock/data/screening/hourly_vn_YYYYMMDD_HHMM.json` | Lịch sử từng lần chạy (gitignored) |
| `vn_stock/data/screening/hourly_vn_sent.json` | Dedupe ý tưởng đã gửi trong ngày |
| Telegram | Chỉ khi có tier1/tier2 mới |

## Tín hiệu (`vn_stock/strategies/macd_signed.py`)

- **MACD+ (long)** / **MACD− (short)**: cross, tiếp diễn, đảo chiều; tier1 / tier2.
- Vào lệnh theo vùng; **SL = swing + ATR**, **TP = 2R**. Không dùng TP10%/SL4% cố định.
- Lệnh short chỉ mang tính tham khảo xu hướng: nhà đầu tư cá nhân trên HOSE gần như không bán khống được.

Cần `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` trong `stock/.env`.
