# stock — VN equities

Vietnamese stocks (`vn_stock`), Pine scripts (`pines/`), ICT hourly Telegram.

| Sibling | Role |
|---------|------|
| `Trading-bot/` | Crypto / OI / OKX |
| `real-estate/` | Vietnam property + FRED (VRE dashboard) |

## Layout

| Path | Role |
|------|------|
| `vn_stock/` | Crawl, screen, backtest, hourly Telegram |
| `pines/` | TradingView Pine |
| `.github/workflows/vn-hourly-telegram.yml` | ICT session alerts |
| `deploy/` | Hourly GHA notes |

## Quick commands

```bash
cd /Users/namnguyen/Documents/Cursor/stock
source .venv/bin/activate
export PYTHONPATH="/Users/namnguyen/Documents/Cursor/stock:/Users/namnguyen/Documents/Cursor/Trading-bot"

python -m vn_stock.scripts.run_hourly_vn_session --force --dry-run
python -m vn_stock.scripts.screen_bluechip_macd_buy
```

Secrets for Actions: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Hourly may need `TB_CHECKOUT_TOKEN` if Trading-bot is private.
