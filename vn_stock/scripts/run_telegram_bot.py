#!/usr/bin/env python3
"""
Bot Telegram thống nhất: VN stock (consensus 2/3 + cơ bản) + BTC crypto consensus.

Cấu hình .env (stock/.env hoặc Trading-bot/.env):
  TELEGRAM_BOT_TOKEN=...
  TELEGRAM_CHAT_ID=...

Chạy từ stock/:
  PYTHONPATH="../Trading-bot:." .venv/bin/python -m vn_stock.scripts.run_telegram_bot --test
  PYTHONPATH="../Trading-bot:." .venv/bin/python -m vn_stock.scripts.run_telegram_bot --combined --dry-run
  PYTHONPATH="../Trading-bot:." .venv/bin/python -m vn_stock.scripts.run_telegram_bot --combined --assets vn,crypto
  PYTHONPATH="../Trading-bot:." .venv/bin/python -m vn_stock.scripts.run_telegram_bot --combined --loop
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set

STOCK_ROOT = Path(__file__).resolve().parents[2]
TB_ROOT = STOCK_ROOT.parent / "Trading-bot"
for p in (str(STOCK_ROOT), str(TB_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from dotenv import load_dotenv
    load_dotenv(STOCK_ROOT / ".env")
    load_dotenv(TB_ROOT / ".env")
except ImportError:
    pass

from vn_stock import DATA_DIR
from vn_stock.analysis.combined_signal import (
    format_combined_telegram,
    get_combined_signals,
    load_live_vn_models,
)
from vn_stock.data_loaders.vn_screener import get_vn30
from vn_stock.notify.telegram import send_message
from vn_stock.scripts.run_telegram_signal import (
    DEFAULT_SYMBOLS,
    MARKET_CLOSE_HOUR,
    MARKET_OPEN_HOUR,
    SCAN_INTERVAL_MINUTES,
    _is_market_hours,
)

CACHE_PATH = DATA_DIR / "screening" / "telegram_sent_cache.json"


def _load_cache() -> Set[str]:
    if not CACHE_PATH.exists():
        return set()
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return set(data.get("keys", []))
    except (json.JSONDecodeError, TypeError):
        return set()


def _save_cache(keys: Set[str], max_keys: int = 500) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    trimmed = sorted(keys)[-max_keys:]
    CACHE_PATH.write_text(
        json.dumps({"updated_at": datetime.now().isoformat(), "keys": trimmed}, indent=2),
        encoding="utf-8",
    )


def _signal_key(asset: str, symbol: str, side: str, tier: str, interval: str) -> str:
    raw = f"{asset}|{symbol}|{side}|{tier}|{interval}|{datetime.now().strftime('%Y-%m-%d')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _vn_symbols(symbols_arg: Optional[str]) -> List[str]:
    if symbols_arg:
        return [s.strip().upper() for s in symbols_arg.split(",") if s.strip()]
    try:
        df = get_vn30(save=True)
        col = next((c for c in ("symbol", "ticker", "Symbol") if c in df.columns), None)
        if col is not None and len(df):
            return sorted({str(s).strip().upper() for s in df[col].tolist()})
    except Exception:
        pass
    return DEFAULT_SYMBOLS


def _format_crypto_telegram(payload: dict) -> Optional[str]:
    c = payload.get("consensus", {})
    side = c.get("side", "none")
    if side == "none":
        return None
    votes = payload.get("votes", [])
    models = ", ".join(v["strategy"] for v in votes if v.get("side") == side)
    tier = c.get("tier", "?")
    conf = c.get("combined_confidence", 0)
    close = payload.get("close", 0)
    sl, tp = c.get("stop_loss"), c.get("take_profit")
    n_models = max(len(votes), 3)

    lines = [
        f"<b>CONSENSUS {side.upper()} BTC</b> (1D)",
        f"Tier: <b>{tier}</b> ({c.get('vote_count', 0)}/{n_models}) | Conf: {conf:.2f}",
        "",
        f"Close: <code>{close:,.2f}</code>",
    ]
    if sl:
        lines.append(f"SL: <code>{sl:,.2f}</code>")
    if tp:
        lines.append(f"TP: <code>{tp:,.2f}</code>")
    liq = payload.get("liquidation_map") or {}
    if liq and not liq.get("error"):
        nl = liq.get("nearest_long_cluster") or {}
        ns = liq.get("nearest_short_cluster") or {}
        lines.extend([
            "",
            "<b>Liq map</b> (vị thế theo giá thanh lý)",
            f"Long gần (dưới): {nl.get('mid', '—')} | Short gần (trên): {ns.get('mid', '—')}",
            f"Bias: {liq.get('vote_side', 'none')} — {liq.get('vote_reason', '')}",
        ])
    lines.extend(["", f"Models: {models}", f"Cutoff: {payload.get('data_cutoff', '2024-01-01')}"])
    return "\n".join(lines)


def scan_crypto_consensus(min_votes: int = 2) -> Optional[dict]:
    from botdown.crypto_consensus import scan_crypto_consensus as _scan
    from botdown.data import load_btc_daily
    from botdown.ml_ops import ModelRegistry

    data = load_btc_daily(TB_ROOT, "spot")
    if data is None:
        return None
    open_time, open_, high, low, close, volume = data
    reg = ModelRegistry(TB_ROOT / "botdown" / "reports" / "model_registry.json")
    has_crypto_reg = any(m.asset_class == "crypto" for m in reg._records.values())
    live = reg.live_models("crypto") if has_crypto_reg else None

    sig = _scan(
        "BTCUSDT", open_time, open_, high, low, close, volume,
        min_votes=min_votes, live_models=live,
    )
    c = sig.consensus
    if c.side == "none":
        return None
    return {
        "symbol": sig.symbol,
        "close": sig.close,
        "data_cutoff": sig.data_cutoff,
        "consensus": {
            "side": c.side,
            "tier": c.tier,
            "vote_count": c.vote_count,
            "combined_confidence": c.combined_confidence,
            "stop_loss": c.stop_loss,
            "take_profit": c.take_profit,
        },
        "votes": [{"strategy": v.strategy, "side": v.side} for v in c.votes],
        "liquidation_map": sig.meta.get("liquidation_map"),
    }


def run_scan(
    assets: List[str],
    vn_symbols: List[str],
    min_votes: int,
    use_combined: bool,
    dry_run: bool,
    update_data: bool,
    dedupe: bool,
) -> int:
    sent = 0
    cache = _load_cache() if dedupe else set()
    new_keys: Set[str] = set()

    if "vn" in assets:
        live = load_live_vn_models()
        signals = get_combined_signals(
            symbols=vn_symbols,
            intervals=["1D"],
            min_tech_votes=min_votes,
            require_consensus=True,
            update_data=update_data,
            live_models=live,
            log_signals=not dry_run,
        )
        for sig in signals:
            key = _signal_key("vn", sig.symbol, "long", sig.consensus_tier, sig.interval)
            if dedupe and key in cache:
                continue
            msg = format_combined_telegram(sig)
            if dry_run:
                print("--- VN ---")
                print(msg.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""))
                sent += 1
                new_keys.add(key)
                continue
            ok, err = send_message(msg)
            if ok:
                sent += 1
                new_keys.add(key)
                print(f"VN sent: {sig.symbol} tier={sig.consensus_tier}")
            else:
                print(f"VN fail {sig.symbol}: {err}", file=sys.stderr)

    if "crypto" in assets:
        payload = scan_crypto_consensus(min_votes=min_votes)
        if payload:
            c = payload["consensus"]
            key = _signal_key("crypto", "BTCUSDT", c["side"], c["tier"], "1D")
            if not (dedupe and key in cache):
                msg = _format_crypto_telegram(payload)
                if msg:
                    if dry_run:
                        print("--- CRYPTO ---")
                        print(msg.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", ""))
                        sent += 1
                        new_keys.add(key)
                    else:
                        ok, err = send_message(msg)
                        if ok:
                            sent += 1
                            new_keys.add(key)
                            print(f"Crypto sent: BTC {c['side']} tier={c['tier']}")
                        else:
                            print(f"Crypto fail: {err}", file=sys.stderr)

    if dedupe and new_keys:
        _save_cache(cache | new_keys)
    return sent


def send_test_message() -> bool:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = (
        f"<b>Bot tín hiệu đã sẵn sàng</b>\n"
        f"Thời gian: {now}\n"
        f"VN: consensus 2/3 + cơ bản\n"
        f"Crypto: BTC consensus 1D\n\n"
        f"<i>Không phải lời khuyên đầu tư.</i>"
    )
    ok, err = send_message(msg)
    if ok:
        print("Test message sent OK.")
    else:
        print(f"Test failed: {err}", file=sys.stderr)
    return ok


def run_loop(assets, vn_symbols, min_votes, use_combined, dry_run, dedupe):
    print(
        f"Loop {SCAN_INTERVAL_MINUTES}m | VN {MARKET_OPEN_HOUR}:00-{MARKET_CLOSE_HOUR}:00 | "
        f"assets={assets} | dedupe={dedupe}"
    )
    while True:
        vn_open = _is_market_hours()
        run_vn = "vn" in assets and vn_open
        run_crypto = "crypto" in assets  # crypto 24/7

        if run_vn or run_crypto:
            now = datetime.now().strftime("%H:%M:%S")
            active = [a for a in assets if (a != "vn" or vn_open)]
            print(f"\n[{now}] Scan {active}...")
            try:
                sent = run_scan(
                    assets=active,
                    vn_symbols=vn_symbols,
                    min_votes=min_votes,
                    use_combined=use_combined,
                    dry_run=dry_run,
                    update_data=run_vn,
                    dedupe=dedupe,
                )
                print(f"[{now}] Sent {sent}")
            except Exception as e:
                print(f"[{now}] Error: {e}", file=sys.stderr)
        else:
            print(f"[{datetime.now().strftime('%H:%M')}] Ngoài giờ VN — chờ crypto-only hoặc giờ mở cửa...")

        time.sleep(SCAN_INTERVAL_MINUTES * 60)


def main() -> None:
    ap = argparse.ArgumentParser(description="Telegram bot VN + Crypto consensus")
    ap.add_argument("--assets", type=str, default="vn,crypto", help="vn,crypto")
    ap.add_argument("--symbols", type=str, default=None, help="VN symbols (default VN30)")
    ap.add_argument("--min-votes", type=int, default=2)
    ap.add_argument("--combined", action="store_true", default=True, help="VN: tech+fund (default on)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--no-update", action="store_true")
    ap.add_argument("--no-dedupe", action="store_true", help="Gửi lại nếu cùng tín hiệu trong ngày")
    ap.add_argument("--test", action="store_true", help="Gửi tin test kết nối Telegram")
    args = ap.parse_args()

    if args.test:
        sys.exit(0 if send_test_message() else 1)

    assets = [a.strip().lower() for a in args.assets.split(",") if a.strip()]
    vn_symbols = _vn_symbols(args.symbols)

    if args.loop:
        run_loop(assets, vn_symbols, args.min_votes, args.combined, args.dry_run, not args.no_dedupe)
        return

    sent = run_scan(
        assets=assets,
        vn_symbols=vn_symbols,
        min_votes=args.min_votes,
        use_combined=args.combined,
        dry_run=args.dry_run,
        update_data=not args.no_update,
        dedupe=not args.no_dedupe,
    )
    if sent == 0:
        print("Không có tín hiệu mới để gửi.")


if __name__ == "__main__":
    main()
