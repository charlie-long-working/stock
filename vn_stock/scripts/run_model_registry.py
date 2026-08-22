#!/usr/bin/env python3
"""
Update model registry from VN stock backtests (live window from cutoff).

Chạy từ stock/:
  PYTHONPATH="../Trading-bot:." .venv/bin/python -m vn_stock.scripts.run_model_registry
  PYTHONPATH="../Trading-bot:." .venv/bin/python -m vn_stock.scripts.run_model_registry --symbols VCB,BID,FPT
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STOCK_ROOT = Path(__file__).resolve().parents[2]
TB_ROOT = STOCK_ROOT.parent / "Trading-bot"
for p in (str(STOCK_ROOT), str(TB_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from botdown.ml_ops import ModelRegistry, VN_LIVE_CUTOFF  # noqa: E402
from vn_stock import DATA_DIR  # noqa: E402
from vn_stock.backtest.engine import run_backtest  # noqa: E402
from vn_stock.data_loaders.vn_screener import get_vn30  # noqa: E402


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main() -> None:
    ap = argparse.ArgumentParser(description="VN model registry update")
    ap.add_argument("--symbols", type=str, default=None)
    ap.add_argument("--cutoff", type=str, default=VN_LIVE_CUTOFF)
    args = ap.parse_args()

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        df = get_vn30(save=True)
        col = next((c for c in ("symbol", "ticker", "Symbol") if c in df.columns), None)
        symbols = sorted({str(s).strip().upper() for s in df[col].tolist()}) if col else ["VCB", "FPT", "BID"]

    strategies = ["macd_rsi", "ma_crossover", "regime_fusion"]
    end = _today()
    window = f"{args.cutoff} → {end}"

    registry_path = TB_ROOT / "botdown" / "reports" / "model_registry.json"
    registry = ModelRegistry(registry_path)

    agg: dict = {s: {"wr": [], "ret": [], "n": 0, "dd": []} for s in strategies}

    for sym in symbols:
        for strat in strategies:
            try:
                r = run_backtest(
                    sym,
                    strat,
                    "1D",
                    data_root=DATA_DIR,
                    start_date=args.cutoff,
                    end_date=end,
                )
            except Exception as e:
                print(f"  [{sym}/{strat}] skip: {e}")
                continue
            if r is None or r.num_trades == 0:
                continue
            agg[strat]["wr"].append(r.win_rate)
            agg[strat]["ret"].append(r.total_return_pct)
            agg[strat]["dd"].append(r.max_drawdown_pct)
            agg[strat]["n"] += r.num_trades

    import numpy as np

    for strat in strategies:
        a = agg[strat]
        if not a["wr"]:
            continue
        metrics = {
            "win_rate": float(np.mean(a["wr"])),
            "num_trades": a["n"],
            "return_pct": float(np.mean(a["ret"])),
            "max_drawdown_pct": float(np.max(a["dd"])) if a["dd"] else 0,
        }
        rec = registry.update_from_backtest(f"vn_{strat}", "vn_stock", window, metrics)
        print(f"{rec.model_id}: {rec.status} wr={rec.win_rate_pct:.1f}% trades={rec.num_trades}")

    registry.save()
    out = DATA_DIR / "screening" / "model_registry_snapshot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(registry.path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"\nRegistry: {registry.path}\nSnapshot: {out}")


if __name__ == "__main__":
    main()
