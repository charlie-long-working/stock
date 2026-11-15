# stock — cổ phiếu Việt Nam

Package `vn_stock`: crawl giá (vnstock), screen VN30, backtest đa chiến lược, tín hiệu hourly MACD+/MACD− và digest tin Vietstock lên Telegram; Pine scripts cho TradingView.

| Repo anh em | Vai trò |
|-------------|---------|
| `../Trading-bot/` | Crypto / OI / OKX; cung cấp engine `botdown` cho một số script ở đây |
| `../precious-metals/` | Vàng / bạc |
| `../real-estate/` | BĐS VN + FRED (dashboard VRE) |
| `../daily-brief/` | Bot bản tin sáng/chiều (dùng `vn_stock` để lấy giá) |

## Đang chạy

| Job | Ở đâu | Lịch (giờ VN) | Ghi chú |
|-----|-------|---------------|---------|
| Tín hiệu nến ngày + bản tin tuần | launchd `com.cursor.swing-vn` trên Mac | T2–T6 16:00 | Chỉ lệnh MUA; `macd_rsi_atr` + `macd_signed`. Log `~/Library/Logs/swing/vn.log` |
| ~~Tín hiệu hourly~~ | launchd `com.cursor.vn-hourly` | — | Gỡ 15/11/2026 (Mac chỉ chạy nến ngày/tuần) |
| Digest tin Vietstock | GitHub Actions `vn-news-digest.yml` | T2–T6 7:45 | Không cần token Vietstock. Commit cache tin đã gửi |
| VN Hourly trên GitHub | `vn-hourly-telegram.yml` | — | **Đã tắt**: vnstock không còn trên PyPI |

Cài lại launchd: `cp deploy/swing-vn.plist ~/Library/LaunchAgents/com.cursor.swing-vn.plist && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cursor.swing-vn.plist`
Tắt: `launchctl bootout gui/$(id -u)/com.cursor.swing-vn`
Chạy thử: `PYTHONPATH="$PWD:$PWD/../Trading-bot" .venv/bin/python -m vn_stock.scripts.run_swing_vn --dry-run --wait-min 0`

Env (`.env`, xem `.env.example`): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Tuỳ chọn `VN_SESSION_OPEN` / `VN_SESSION_CLOSE`.

## Cấu trúc

| Path | Vai trò |
|------|---------|
| `vn_stock/data_loaders/` | Giá (`vn_ohlcv`), danh sách mã (`vn_screener`), BCTC (`vn_fundamentals`, đang hỏng), tin (`vn_news`), lãi suất, OI phái sinh |
| `vn_stock/strategies/` | `macd_signed`, `macd_rsi`, `ma_crossover`, `ichimoku`, `div_macd_rsi`, `regime_fusion`, … |
| `vn_stock/backtest/engine.py` | Engine backtest long/short, T+2 |
| `vn_stock/analysis/`, `signals/` | Consensus 2/3 + gate cơ bản |
| `vn_stock/notify/telegram.py` | Gửi Telegram |
| `vn_stock/scripts/` | CLI (bảng dưới) |
| `vn_stock/data/` | `ohlcv/` (chỉ local, không trong git), `fundamentals/`, `screening/`, `sectors/` |
| `pines/` | 7 Pine script |
| `deploy/` | launchd plist, cron wrapper, ghi chú |

## Scripts

Chạy từ `stock/`:

```bash
export PYTHONPATH="$PWD:$PWD/../Trading-bot"
PY=.venv/bin/python
```

[botdown] = cần `../Trading-bot` trên PYTHONPATH.

| Script | Làm gì | Ví dụ |
|--------|--------|-------|
| `run_hourly_vn_session` | Cập nhật 1H/1D, quét MACD+/MACD−, gửi ý tưởng mới | `$PY -m vn_stock.scripts.run_hourly_vn_session --force --dry-run` |
| `run_vn_news_digest` | Tin Vietstock theo mã + nhận định thị trường + P/E·P/B·ROE | `$PY -m vn_stock.scripts.run_vn_news_digest --dry-run --days 3` |
| `crawl_daily` | OHLCV 1D/1W/1H, top100, BCTC (thứ 2) | `$PY -m vn_stock.scripts.crawl_daily --no-h1` |
| `crawl_bat_dong_san` | Bundle ngành BĐS | `$PY -m vn_stock.scripts.crawl_bat_dong_san --analyze-only` |
| `run_backtest` | Backtest đa chiến lược / khung | `$PY -m vn_stock.scripts.run_backtest --symbols VCB,FPT --strategies macd_signed --timeframes 1D` |
| `run_backtest_crypto` | Engine VN trên dữ liệu Yahoo | `$PY -m vn_stock.scripts.run_backtest_crypto --ticker BTC-USD --fetch` |
| `run_mtf_macd_ichimoku` | MACD+RSI vs Ichimoku W/D/H4/H1 | `$PY -m vn_stock.scripts.run_mtf_macd_ichimoku --symbols VCB --no-fetch` |
| `run_regime_strategy_mix` | Phối chiến lược theo regime | `$PY -m vn_stock.scripts.run_regime_strategy_mix --symbols VCB,FPT` |
| `analyze_vn30_fundamentals` | Định giá VN30 qua VNDIRECT Finfo | `$PY -m vn_stock.scripts.analyze_vn30_fundamentals` |
| `run_crypto_engines_on_vn` [botdown] | Engine crypto trên mã VN | `$PY -m vn_stock.scripts.run_crypto_engines_on_vn` |
| `run_vn30_strategy_arena` [botdown] | Xếp hạng chiến lược trên VN30 | `$PY -m vn_stock.scripts.run_vn30_strategy_arena` |
| `run_vn30_winrate_t2` [botdown] | Tìm win-rate cao với T+2 | `$PY -m vn_stock.scripts.run_vn30_winrate_t2` |
| `screen_bluechip_macd_buy` [botdown] | Screen VN30 tier1/tier2 | `$PY -m vn_stock.scripts.screen_bluechip_macd_buy --no-fetch` |
| `screen_consensus` [botdown] | Consensus 2/3 VN30 | `$PY -m vn_stock.scripts.screen_consensus --no-fetch --combined` |
| `run_model_registry` [botdown] | Cập nhật model registry | `$PY -m vn_stock.scripts.run_model_registry` |
| `run_telegram_bot` [botdown] | Bot VN + BTC consensus (cũ) | `$PY -m vn_stock.scripts.run_telegram_bot --combined --dry-run` |
| `run_telegram_signal` [botdown] | Bot tín hiệu VN (cũ) | `$PY -m vn_stock.scripts.run_telegram_signal --dry-run` |

## Hạn chế đã biết

- **vnstock bị gỡ khỏi PyPI**: `pip install -r requirements.txt` lỗi trên máy mới / CI. `.venv` local (vnstock 3.5.0) là bản chạy được.
- **BCTC qua vnstock hỏng** (VCI và KBS). Cache `vn_stock/data/fundamentals/` dừng ở Q4/2025, chỉ 5 mã có số liệu.
- Bot hourly gửi cả lệnh **short**; trên HOSE nhà đầu tư cá nhân gần như không bán khống được.
- `vietnam_rates.py` còn trỏ đường dẫn cũ trong Trading-bot.

Không phải lời khuyên đầu tư.

## Nguồn tin của digest

Vietstock (KBS + Google News), CafeF, Tin nhanh chứng khoán, VnEconomy — RSS công khai, không cần token, không vượt chặn bot. Mỗi tin ghi `[nguồn]`. Danh sách: `PRESS_FEEDS` trong `vn_stock/data_loaders/vn_news.py`.

## Test

```bash
PYTHONPATH="$PWD:$PWD/../Trading-bot" .venv/bin/python -m unittest discover -s tests -t .
```
Offline (dữ liệu giả, mock mạng/Telegram): `tests/test_vn_news.py`, `tests/test_swing_vn.py`, cùng test của Stock Intelligence.
