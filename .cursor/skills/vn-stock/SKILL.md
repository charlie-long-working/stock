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
| **Swing 1D + bản tin 1W** | launchd `com.cursor.swing-vn` | T2–T6 16:00 (sau intel 15:30, chờ tối đa 25′) | `vn_stock/scripts/run_swing_vn.py` | `~/Library/Logs/swing/vn.log`, `screening/swing_vn_sent.json` |
| ~~Hourly signal~~ | launchd `com.cursor.vn-hourly` | — | `run_hourly_vn_session.py` | **gỡ 15/11/2026** (plist `.disabled`): Mac chỉ chạy nến ngày/tuần |
| News digest | GitHub Actions `vn-news-digest.yml` | T2–T6 7:45 | `vn_stock/scripts/run_vn_news_digest.py` | commit `screening/vn_news_sent.json` |
| ~~VN Hourly GHA~~ | `vn-hourly-telegram.yml` | — | — | **disabled** (vnstock không cài được) |

launchd: plist nguồn `deploy/swing-vn.plist` → `~/Library/LaunchAgents/com.cursor.swing-vn.plist`.
Bật/tắt: `launchctl bootstrap|bootout gui/$(id -u) ~/Library/LaunchAgents/com.cursor.swing-vn.plist`.

**Swing 1D/1W** (`run_swing_vn`): đọc kho giá điều chỉnh `data/intel/ohlcv_adj/` (không gọi API), 100 mã intel, chỉ lệnh MUA:
`macd_rsi_atr` (MACD hist cắt lên 0 + RSI<70, SL 1,5×ATR / TP 2,5×ATR — tốt nhất backtest VN30 toàn mẫu, ngoài mẫu ≈ hoà sau phí)
và `macd_signed` long-only (chỉ báo khi setup mới). Lọc GTGD TB20 ≥ 10 tỷ; kèm điểm intel (★ ≥80), EMA20/50, regime, xu hướng tuần.
Bản tin 1W (W-FRI) gửi một lần khi tuần đóng. Format/dedupe dùng chung `Trading-bot/botdown/swing_common.py`.
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

## Tin tức & test (cập nhật 15/11/2026)

- `data_loaders/vn_news.py`: KBS + Google News `site:vietstock.vn` + RSS công khai **CafeF** (chứng khoán, doanh nghiệp, tài chính–ngân hàng), **Tin nhanh chứng khoán**, **VnEconomy** (`PRESS_FEEDS`, mỗi feed tải 1 lần/tiến trình, UA ghi rõ bot đọc tin). Tin theo mã khớp mã **hoặc tên công ty** (`ALIASES`), loại cụm gây nhầm (`EXCLUDE`, vd "FPT Retail" ≠ FPT). Thêm nguồn = 1 dòng trong `PRESS_FEEDS`.
- Test offline: `PYTHONPATH="$PWD:$PWD/../Trading-bot" .venv/bin/python -m unittest discover -s tests -t .` — `test_vn_news.py`, `test_swing_vn.py` (+ test intel/ohlcv của Stock Intelligence).

## Setup nền giá / phân kỳ / mua-bán chủ động / sổ lệnh (15/11/2026)

- **Mua/bán chủ động** `vn_stock/tape/`: KBS intraday (1 request/mã, tổng tick = KL ngày, kiểm `reconciled`), lưu `data/tape/daily.csv` + tick thô `raw/<ngày>.csv.gz` (180 ngày). Chạy trong job swing-vn sau Stock Intelligence (~6 phút); chạy bù: `run_tape_collect`. KHÔNG dedupe theo `id` (KBS trùng id cho lệnh khớp giống nhau). Chỉ là bối cảnh tới khi đủ ≥120 phiên để kiểm chứng.
- **Setup** `vn_stock/setups/`: `base_breakout` (nền N∈{20,40,60}, co biến động, cạn volume so với TRƯỚC nền, phá nền rvol/CLV), `divergence` (bọc `div_macd_rsi`, biết sau 5 nến), `exits.py` (một engine thoát cho cả backtest và sổ lệnh — T+2: bán được chiều phiên e+2), `sizing.py` (% vốn = 1% / rủi ro, trần 20%, 5 mã), `ledger.py` (sổ lệnh giấy, mức giá tương đối nên đúng cả khi điều chỉnh cổ tức), `live.py`.
- **Backtest** `run_setup_backtest`: 97 mã, phí/thuế/trượt giá, T+2, chọn tham số chỉ trên train<2022 + validate 2022–2023, ngoài mẫu 2024+, 11 ngưỡng đạt chuẩn → `setups/config.json` (ship/watch/off, commit) + `docs/BACKTEST_SETUPS_<ngày>.md`. Kết quả 15/11: phá nền **WATCH** (PF 1,05), phân kỳ **OFF** (PF 0,74), `macd_rsi_atr` đang live **OFF** (PF 0,78, −0,63%/lệnh sau phí).
- **Module mới KHÔNG import `vn_stock/intel/*`** (code chưa commit của phiên khác) — chỉ đọc file dữ liệu `data/intel/...`.
- Test: `test_tape.py`, `test_setups.py` (có test chống nhìn trước), `test_setup_backtest.py`, `test_ledger.py` (có test đối chiếu live = backtest), `test_swing_vn.py`.
- **Từ 15/11/2026 `macd_rsi_atr` chỉ còn ở danh sách THEO DÕI** (kết luận "off" trong `setups/config.json`): `run_swing_vn` chuyển mọi chiến lược trong `LIVE.LEGACY_NAMES` có verdict ≠ ship sang THEO DÕI (không mức giá, không vào sổ lệnh). `macd_signed` (chỉ MUA) đã backtest 15/11 (sửa lỗi nhìn trước: swing chỉ dùng khi đủ 2 nến xác nhận — 19% tín hiệu có SL khác nếu không sửa): ngoài mẫu PF 0,72, −0,80%/lệnh → OFF → **từ 15/11/2026 cũng chỉ ở danh sách THEO DÕI** (người dùng duyệt). Hiện bot cổ phiếu không còn chiến lược nào gửi lệnh MUA; chạy lại `run_setup_backtest` mỗi tháng — chiến lược nào đạt `ship` sẽ tự gửi lại lệnh MUA.
