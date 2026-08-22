#!/usr/bin/env python3
"""
Screen VN30 với consensus 2/3 (macd_rsi + ma_crossover + regime_fusion).

Chạy từ stock/:
  PYTHONPATH="../Trading-bot:." .venv/bin/python -m vn_stock.scripts.screen_consensus
  PYTHONPATH="../Trading-bot:." .venv/bin/python -m vn_stock.scripts.screen_consensus --combined
  PYTHONPATH="../Trading-bot:." .venv/bin/python -m vn_stock.scripts.screen_consensus --no-fetch
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

STOCK_ROOT = Path(__file__).resolve().parents[2]
TB_ROOT = STOCK_ROOT.parent / "Trading-bot"
for p in (str(STOCK_ROOT), str(TB_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from botdown.ml_ops import ModelRegistry, VN_LIVE_CUTOFF  # noqa: E402
from vn_stock import DATA_DIR  # noqa: E402
from vn_stock.analysis.combined_signal import get_combined_signals, load_live_vn_models  # noqa: E402
from vn_stock.data_loaders.vn_ohlcv import update_ohlcv  # noqa: E402
from vn_stock.data_loaders.vn_screener import get_vn30  # noqa: E402
from vn_stock.signals.vn_signal import scan_symbol_consensus  # noqa: E402


def _symbols_from_args(symbols_arg: str | None) -> List[str]:
    if symbols_arg:
        return sorted({s.strip().upper() for s in symbols_arg.split(",") if s.strip()})
    df = get_vn30(save=True)
    col = next((c for c in ("symbol", "ticker", "Symbol") if c in df.columns), None)
    if col is None:
        return ["VCB", "FPT", "BID"]
    return sorted({str(s).strip().upper() for s in df[col].tolist()})


def main() -> None:
    ap = argparse.ArgumentParser(description="VN30 consensus 2/3 screen")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--sleep", type=float, default=4.0)
    ap.add_argument("--symbols", type=str, default=None)
    ap.add_argument("--min-votes", type=int, default=2)
    ap.add_argument("--combined", action="store_true", help="Thêm lọc cơ bản")
    ap.add_argument("--min-fund", type=float, default=0.4)
    args = ap.parse_args()

    symbols = _symbols_from_args(args.symbols)
    live = load_live_vn_models()
    print(f"VN30: {len(symbols)} mã | min_votes={args.min_votes}/3 | cutoff={VN_LIVE_CUTOFF}")
    if live:
        print(f"Live models: {', '.join(live)}")

    if not args.no_fetch:
        for sym in symbols:
            try:
                update_ohlcv(sym, "1D", source="VCI", data_root=DATA_DIR)
                time.sleep(max(0.5, args.sleep))
            except Exception as e:
                print(f"  [{sym}] fetch: {e}")

    tier_full: List[Dict[str, Any]] = []
    tier_strong: List[Dict[str, Any]] = []

    if args.combined:
        combined = get_combined_signals(
            symbols=symbols,
            min_tech_votes=args.min_votes,
            min_fundamental_score=args.min_fund,
            update_data=False,
            data_root=DATA_DIR,
            live_models=live,
        )
        for sig in combined:
            row = {
                "symbol": sig.symbol,
                "tier": sig.consensus_tier,
                "votes": sig.vote_count,
                "score": round(sig.combined_score, 3),
                "conf": round(sig.combined_confidence, 3),
                "entry": sig.entry_price,
                "fund": sig.fundamental_score,
            }
            if sig.consensus_tier == "full":
                tier_full.append(row)
            else:
                tier_strong.append(row)
    else:
        for sym in symbols:
            sig = scan_symbol_consensus(
                sym, "1D", min_votes=args.min_votes, data_root=DATA_DIR, live_models=live
            )
            if not sig:
                continue
            c = sig.consensus
            row = {
                "symbol": sym,
                "tier": c.tier,
                "votes": c.vote_count,
                "conf": round(c.combined_confidence, 3),
                "entry": c.entry_price,
                "stop": c.stop_loss,
                "tp": c.take_profit,
                "models": [v.strategy for v in c.votes if v.side == "long"],
            }
            if c.tier == "full":
                tier_full.append(row)
            else:
                tier_strong.append(row)

    out_dir = DATA_DIR / "screening"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "criteria": {
            "consensus": f">= {args.min_votes}/3 long",
            "data_cutoff": VN_LIVE_CUTOFF,
            "combined_fundamental": args.combined,
        },
        "tier_full_3of3": tier_full,
        "tier_strong_2of3": tier_strong,
    }
    out_path = out_dir / "consensus_vn30.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== FULL 3/3 ===")
    for x in tier_full:
        print(f"  {x['symbol']}: conf={x.get('conf')} score={x.get('score', '-')}")
    print("\n=== STRONG 2/3 ===")
    for x in tier_strong:
        print(f"  {x['symbol']}: conf={x.get('conf')} models={x.get('models', '-')}")

    reg = ModelRegistry(TB_ROOT / "botdown" / "reports" / "model_registry.json")
    killed = [m.model_id for m in reg._records.values() if m.asset_class == "vn_stock" and m.status == "killed"]
    if killed:
        print(f"\nKilled (excluded): {', '.join(killed)}")

    print(f"\nĐã ghi {out_path}")


if __name__ == "__main__":
    main()
