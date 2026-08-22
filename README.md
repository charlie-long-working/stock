# stock — VN equities + VRE

Vietnamese stocks (`vn_stock`), Pine scripts (`pines/`), and the VRE real-estate/macro dashboard (`vre/`).

Crypto live alerts and OKX bots live in **`Trading-bot`** (separate repo).

## Layout

| Path | Role |
|------|------|
| `vn_stock/` | Crawl, screen, backtest, hourly Telegram |
| `pines/` | TradingView Pine |
| `vre/` | Vietnam RE + FRED macro dashboard (CSV under `vre/data/`) |
| `.github/workflows/vn-hourly-telegram.yml` | ICT session alerts |
| `.github/workflows/update-vre-data.yml` | Weekly FRED refresh |

## Quick commands

```bash
cd /Users/namnguyen/Documents/Cursor/stock
source .venv/bin/activate
export PYTHONPATH="/Users/namnguyen/Documents/Cursor/stock:/Users/namnguyen/Documents/Cursor/Trading-bot"

# VN hourly (local)
python -m vn_stock.scripts.run_hourly_vn_session --force --dry-run

# VRE dashboard
streamlit run vre/app.py
```

Secrets for Actions: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`; VRE needs `FRED_API_KEY`. Hourly may need `TB_CHECKOUT_TOKEN` if Trading-bot is private.
