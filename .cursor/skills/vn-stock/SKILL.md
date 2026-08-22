---
name: vn-stock
description: >-
  Vietnamese equities in stock/ (vn_stock crawl/screen/hourly Telegram, pines).
  Use when user mentions VN30, VCB, vnstock, ICT hourly alerts, or editing the stock
  repo — not for crypto (trading-bot) or Vietnam real-estate/VRE (real-estate skill).
---

# stock (VN equities)

Repo: `Documents/Cursor/stock`. Crypto → skill `trading-bot`. Bất động sản → skill `real-estate`.

## Agent rules

1. Always use `stock/.venv` + `PYTHONPATH=stock:Trading-bot` when VN scripts need botdown engines.
2. Prefer reading `vn_stock/data/screening/` outputs over re-crawling.
3. Hourly Telegram SoT: `.github/workflows/vn-hourly-telegram.yml` + `vn_stock/scripts/run_hourly_vn_session.py`.
4. Do not put VRE/property code here — that lives in `real-estate/`.

## Map

| Path | Role |
|------|------|
| `vn_stock/scripts/` | Crawl, screen, hourly, backtest CLIs |
| `vn_stock/strategies/` | MACD/RSI, fusion, etc. |
| `vn_stock/data/` | OHLCV, fundamentals, screening JSON |
| `pines/` | TradingView Pine |
| `deploy/` | Hourly GHA notes |

## Commands

```bash
cd /Users/namnguyen/Documents/Cursor/stock
source .venv/bin/activate
export PYTHONPATH="/Users/namnguyen/Documents/Cursor/stock:/Users/namnguyen/Documents/Cursor/Trading-bot"
python -m vn_stock.scripts.run_hourly_vn_session --force --dry-run
python -m vn_stock.scripts.screen_bluechip_macd_buy
```

More VN/crypto cross-backtest notes: skill `trading-vn-crypto`.
