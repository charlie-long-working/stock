# VN hourly trading session

Mỗi giờ **T2–T6, 8:05–14:05** (ICT): cập nhật nến → quét tín hiệu → Telegram nếu có lệnh.

## Chạy thử ngay

```bash
cd /Users/namnguyen/Documents/Cursor/stock
export PYTHONPATH="$PWD:$PWD/../Trading-bot"
.venv/bin/python -m vn_stock.scripts.run_hourly_vn_session --force --dry-run
# Gửi Telegram thật (trong phiên hoặc --force):
.venv/bin/python -m vn_stock.scripts.run_hourly_vn_session --force
# Heartbeat mỗi giờ kể cả khi 0 signal:
.venv/bin/python -m vn_stock.scripts.run_hourly_vn_session --heartbeat
```

## Lên lịch (chọn 1)

### A) cron (đơn giản)

```bash
crontab -e
```

Thêm (máy để giờ Việt Nam):

```
5 8-14 * * 1-5  /Users/namnguyen/Documents/Cursor/stock/deploy/run_hourly_vn.sh
```

Log: `vn_stock/data/screening/logs/hourly_vn_YYYYMMDD.log`

### B) launchd (macOS, máy thức khi mở phiên)

```bash
cp /Users/namnguyen/Documents/Cursor/stock/deploy/vn-hourly.plist \
   ~/Library/LaunchAgents/com.cursor.vn-hourly.plist
launchctl load ~/Library/LaunchAgents/com.cursor.vn-hourly.plist
# gỡ: launchctl unload ~/Library/LaunchAgents/com.cursor.vn-hourly.plist
```

## Output

| File | Ý nghĩa |
|------|---------|
| `vn_stock/data/screening/hourly_vn_snapshot.json` | Snapshot mới nhất (coverage + ideas) |
| `vn_stock/data/screening/hourly_vn_YYYYMMDD_HHMM.json` | Lưu lịch sử từng lần chạy |
| Telegram | Chỉ khi có **tier1/tier2** mới trong ngày (dedupe) |

## Tín hiệu

- Engine: `botdown` MACD+RSI TP10%/SL4% + EMA20/50 (import, không sửa crypto)
- **tier1:** hist cắt lên 0 + RSI < OB + EMA bull  
- **tier2:** bull + RSI 30–48 + hist đang hồi (chưa cross)

Cần `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` trong `stock/.env`.
