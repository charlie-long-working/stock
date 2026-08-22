"""
Combined signal: technical 2/3 consensus + fundamental filter ("diem mua dep").

Requires >= min_tech_votes (default 2/3) among macd_rsi, ma_crossover, regime_fusion.
Fundamental score >= min_fundamental_score acts as 4th gate (different model class).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

STOCK_ROOT = Path(__file__).resolve().parents[2]
TB_ROOT = STOCK_ROOT.parent / "Trading-bot"
if TB_ROOT.is_dir() and str(TB_ROOT) not in sys.path:
    sys.path.insert(0, str(TB_ROOT))

from botdown.ml_ops import ModelRegistry, SignalLedger, VN_LIVE_CUTOFF  # noqa: E402

from vn_stock.analysis.fundamental_trend import FundamentalScore, analyze_fundamentals
from vn_stock.signals.vn_signal import (
    scan_symbol_consensus,
    scan_symbol_votes,
    VNConsensusSignal,
)


@dataclass
class CombinedSignal:
    symbol: str
    interval: str
    combined_score: float
    fundamental_trend: str
    fundamental_score: float
    consensus_tier: str
    vote_count: int
    combined_confidence: float
    technical_signals: List = field(default_factory=list)
    entry_price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    best_strategy: str = ""
    reasons: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)
    data_cutoff: str = VN_LIVE_CUTOFF


def get_combined_signals(
    symbols: List[str],
    intervals: List[str] = None,
    strategies: List[str] = None,
    prices: Optional[Dict[str, float]] = None,
    min_fundamental_score: float = 0.4,
    min_tech_votes: int = 2,
    update_data: bool = False,
    data_root: Optional[Path] = None,
    require_consensus: bool = True,
    log_signals: bool = False,
    live_models: Optional[List[str]] = None,
) -> List[CombinedSignal]:
    """
    Scan with 2/3 tech consensus + fundamental gate.

    require_consensus=True (default): need >= min_tech_votes long votes.
    require_consensus=False: legacy OR mode (any 1 strategy + fund).
    """
    if intervals is None:
        intervals = ["1D"]
    if strategies is None:
        strategies = ["macd_rsi", "ma_crossover", "regime_fusion"]

    ledger = None
    if log_signals:
        ledger_path = TB_ROOT / "botdown" / "reports" / "signal_ledger.jsonl"
        ledger = SignalLedger(ledger_path)

    results: List[CombinedSignal] = []

    for symbol in symbols:
        price = prices.get(symbol) if prices else None

        try:
            fund_score = analyze_fundamentals(symbol, current_price=price, data_root=data_root)
        except Exception as e:
            print(f"[combined] Fundamental failed {symbol}: {e}")
            fund_score = FundamentalScore(symbol=symbol, overall_score=0.5, trend="unknown")

        if fund_score.overall_score < min_fundamental_score:
            continue

        for interval in intervals:
            try:
                if require_consensus:
                    vn_sig = scan_symbol_consensus(
                        symbol,
                        interval,
                        strategies,
                        min_votes=min_tech_votes,
                        update_data=update_data,
                        data_root=data_root,
                        live_models=live_models,
                    )
                    if vn_sig is None:
                        continue
                    c = vn_sig.consensus
                    tech_confidence = c.combined_confidence
                    vote_count = c.vote_count
                    tier = c.tier
                    entry = c.entry_price
                    sl, tp = c.stop_loss, c.take_profit
                    long_votes = [v for v in c.votes if v.side == "long"]
                    best_strategy = max(long_votes, key=lambda v: v.confidence).strategy if long_votes else ""
                    reasons = [f"Tech: {v.strategy} conf={v.confidence:.2f}" for v in long_votes]
                else:
                    votes = scan_symbol_votes(symbol, interval, strategies, update_data, data_root)
                    long_votes = [v for v in votes if v.side == "long"]
                    if not long_votes:
                        continue
                    vote_count = len(long_votes)
                    tech_confidence = sum(v.confidence for v in long_votes) / len(strategies)
                    tier = "legacy_or"
                    best = max(long_votes, key=lambda v: v.confidence)
                    entry, sl, tp = best.entry_price, best.stop_loss, best.take_profit
                    best_strategy = best.strategy
                    reasons = [f"Tech: {v.strategy}={v.reason}" for v in long_votes]

                combined_score = 0.6 * tech_confidence + 0.4 * fund_score.overall_score
                if tier == "full":
                    combined_score = min(1.0, combined_score * 1.05)
                elif vote_count == 2:
                    combined_score *= 0.92

                reasons.append(f"Fundamental: {fund_score.trend} ({fund_score.overall_score:.2f})")

                results.append(CombinedSignal(
                    symbol=symbol,
                    interval=interval,
                    combined_score=combined_score,
                    fundamental_trend=fund_score.trend,
                    fundamental_score=fund_score.overall_score,
                    consensus_tier=tier,
                    vote_count=vote_count,
                    combined_confidence=tech_confidence,
                    technical_signals=long_votes if require_consensus else long_votes,
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    best_strategy=best_strategy,
                    reasons=reasons,
                    flags=fund_score.flags,
                ))

                if ledger and require_consensus:
                    ledger.log(
                        asset_class="vn_stock",
                        symbol=symbol,
                        side="long",
                        predicted_confidence=tech_confidence,
                        tier=tier,
                        strategies=[v.strategy for v in long_votes],
                        entry_price=entry,
                    )

            except Exception as e:
                print(f"[combined] Scan failed {symbol} {interval}: {e}")
                continue

    return sorted(results, key=lambda x: x.combined_score, reverse=True)


def load_live_vn_models() -> Optional[List[str]]:
    reg_path = TB_ROOT / "botdown" / "reports" / "model_registry.json"
    if not reg_path.exists():
        return None
    reg = ModelRegistry(reg_path)
    if not any(m.asset_class == "vn_stock" for m in reg._records.values()):
        return None
    return reg.live_models("vn_stock")


def format_combined_telegram(sig: CombinedSignal) -> str:
    def _fmt(x: float) -> str:
        if x >= 1000:
            return f"{x:,.0f}"
        return f"{x:,.2f}"

    if hasattr(sig, "consensus_tier"):
        tier_line = f"Consensus: <b>{sig.consensus_tier}</b> ({sig.vote_count}/3)"
    else:
        tier_line = ""
    trend_emoji = {"up": "\u2191", "stable": "\u2192", "down": "\u2193"}.get(sig.fundamental_trend, "?")

    lines = [
        f"<b>DIEM MUA DEP: {sig.symbol}</b> ({sig.interval})",
        f"Score: <b>{sig.combined_score:.2f}</b> | Conf: {sig.combined_confidence:.2f}",
    ]
    if tier_line:
        lines.append(tier_line)
    lines.extend(["", f"Entry: <code>{_fmt(sig.entry_price)}</code>"])
    if sig.stop_loss:
        lines.append(f"SL: <code>{_fmt(sig.stop_loss)}</code>")
    if sig.take_profit:
        lines.append(f"TP: <code>{_fmt(sig.take_profit)}</code>")
    lines.extend([
        "",
        f"Lead: {sig.best_strategy}",
        f"Fundamental: {trend_emoji} {sig.fundamental_trend} ({sig.fundamental_score:.2f})",
        f"Train cutoff: {sig.data_cutoff}",
    ])
    if sig.flags:
        lines.append(f"Flags: {' | '.join(sig.flags[:3])}")
    return "\n".join(lines)
