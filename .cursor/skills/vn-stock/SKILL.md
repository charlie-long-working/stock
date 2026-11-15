---
name: vn-stock
description: >-
  Vietnamese equities in stock/ (vnstock OHLCV crawl, VN30 screening, multi-strategy
  backtests, hourly MACD+/MACD− Telegram signals via local launchd, Vietstock news
  digest via GitHub Actions, Pine scripts). Use when the user mentions VN30, VCB,
  FPT, vnstock, cổ phiếu, tín hiệu hourly, tin Vietstock, BCTC/P/E, or edits the
  stock repo — not for crypto (trading-bot), gold/silver (precious-metals),
  VRE/property macro (real-estate), or the morning brief bot (daily-brief).
---

# stock (VN equities)

Repo: `Documents/Cursor/stock` (git, **public**: `charlie-long-working/stock`).
Crypto → `trading-bot`. Vàng/bạc → `precious-metals`. BĐS macro → `real-estate`. Bản tin sáng/chiều → `daily-brief`.

## Agent rules

1. Python: `stock/.venv` (3.13, vnstock 3.5.0). `PYTHONPATH="$PWD:$PWD/../Trading-bot"` từ `stock/` — chỉ các script đánh dấu [botdown] cần Trading-bot.
2. **vnstock đã bị gỡ khỏi PyPI** → không `pip install vnstock` được; `.venv` local là bản duy nhất chạy được. Đừng thêm job CI cần vnstock.
3. **vnstock BCTC hỏng** (VCI `KeyError 'data'`, KBS 404). Giá (`Quote`) vẫn chạy. Chỉ số cơ bản thay thế: `scripts/analyze_vn30_fundamentals.py` (VNDIRECT Finfo).
4. Đọc output có sẵn trong `vn_stock/data/screening/` trước khi crawl lại.
5. `vn_stock/data/ohlcv/` **không nằm trong git** (chỉ local) — đừng hứa CI có dữ liệu này.
6. Bot hourly gửi cả **SHORT (MACD−)**: nhà đầu tư cá nhân trên HOSE gần như không bán khống được → nói rõ khi diễn giải tín hiệu.
7. Không gửi Telegram thật khi test: luôn `--dry-run` trừ khi user bảo gửi.

## Live jobs

| Job | Chạy ở đâu | Lịch (ICT) | Entry | Log / state |
|-----|-----------|-----------|-------|-------------|
| Hourly signal | launchd `com.cursor.vn-hourly` (Mac phải thức) | T2–T6 :05, 8h–14h | `vn_stock/scripts/run_hourly_vn_session.py` | `~/Library/Logs/vn-hourly/hourly.log`, `screening/hourly_vn_snapshot.json` |
| News digest | GitHub Actions `vn-news-digest.yml` | T2–T6 7:45 | `vn_stock/scripts/run_vn_news_digest.py` | commit `screening/vn_news_sent.json` |
| ~~VN Hourly GHA~~ | `vn-hourly-telegram.yml` | — | — | **disabled** (vnstock không cài được) |

launchd: plist nguồn `deploy/vn-hourly.plist` → `~/Library/LaunchAgents/com.cursor.vn-hourly.plist`.
Bật/tắt: `launchctl bootstrap|bootout gui/$(id -u) ~/Library/LaunchAgents/com.cursor.vn-hourly.plist`.
Telegram env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (env → `stock/.env` → `../Trading-bot/.env`).

## Map

| Path | Role |
|------|------|
| `vn_stock/data_loaders/` | `vn_ohlcv` (Quote VCI→KBS, 4H resample), `vn_screener` (VN30/Top100), `vn_fundamentals` (hỏng), `vn_news` (KBS + Google News `site:vietstock.vn`), `vn30f_oi` (probe OI phái sinh), `vietnam_rates`, `crypto_ohlcv` |
| `vn_stock/strategies/` | `macd_signed` (MACD+/−, swing+ATR, TP 2R), `macd_rsi`, `ma_crossover`, `ichimoku`, `div_macd_rsi`, `regime_fusion` + helpers |
| `vn_stock/backtest/engine.py` | Engine đa chiến lược, long/short, T+2 |
| `vn_stock/analysis/` | `combined_signal` (2/3 vote + gate cơ bản), `fundamental_trend` |
| `vn_stock/signals/vn_signal.py` | Consensus scan + format Telegram |
| `vn_stock/notify/telegram.py` | `send_message()` HTML |
| `vn_stock/scripts/` | Mọi CLI (xem dưới) |
| `vn_stock/data/` | `ohlcv/` (local), `fundamentals/` (cache 03/2026, 5 mã), `screening/`, `sectors/bat_dong_san/`, `top100/` |
| `pines/` | 7 Pine TradingView |
| `deploy/` | launchd plist, cron wrapper, ghi chú |

## Commands

```bash
cd /Users/namnguyen/Documents/Cursor/stock
export PYTHONPATH="$PWD:$PWD/../Trading-bot"
PY=.venv/bin/python
$PY -m vn_stock.scripts.run_hourly_vn_session --force --dry-run --symbols VCB,FPT
$PY -m vn_stock.scripts.run_vn_news_digest --dry-run --symbols VCB,FPT --days 3
$PY -m vn_stock.scripts.crawl_daily --no-h1
$PY -m vn_stock.scripts.run_backtest --symbols VCB,FPT --strategies macd_signed --timeframes 1D
$PY -m vn_stock.scripts.screen_bluechip_macd_buy --no-fetch        # [botdown]
$PY -m vn_stock.scripts.screen_consensus --no-fetch --combined     # [botdown]
$PY -m vn_stock.scripts.analyze_vn30_fundamentals                  # VNDIRECT ratios
```

Script list + flags đầy đủ: `README.md` mục Scripts.

## Gotchas

- `macd_signed.py` + chỉnh sửa `engine.py`/`strategies/__init__.py`/hourly script đang **chưa commit** — commit chung, thiếu `macd_signed.py` là gãy import.
- `vietnam_rates.py` trỏ `Trading-bot/vre/...` (đã chuyển sang `real-estate/vre/data/vietnam/interest_rates.csv`).
- Repo public: đừng commit `.env`, số liệu cá nhân, đường dẫn nhạy cảm.

Không phải lời khuyên đầu tư.
