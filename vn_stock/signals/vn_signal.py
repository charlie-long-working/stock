"""
Real-time signal scanner for Vietnamese stocks.

Scans OHLCV through 3 strategies; supports per-strategy confidence + 2/3 consensus.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

from vn_stock.data_loaders.vn_ohlcv import load_ohlcv_arrays, update_ohlcv
from vn_stock.strategies.macd_rsi import macd_rsi_signal, MACDRSIParams, MACDRSISignalType
from vn_stock.strategies.ma_crossover import ma_crossover_signal, MACrossParams, MACrossSignalType
from vn_stock.strategies.regime_fusion import regime_fusion_signal, RegimeFusionSignalType

STOCK_ROOT = Path(__file__).resolve().parents[2]
TB_ROOT = STOCK_ROOT.parent / "Trading-bot"
if TB_ROOT.is_dir() and str(TB_ROOT) not in sys.path:
    sys.path.insert(0, str(TB_ROOT))

from botdown.ml_ops import (  # noqa: E402
    ConsensusResult,
    StrategyVote,
    VN_LIVE_CUTOFF,
    ma_cross_confidence,
    macd_rsi_confidence,
    regime_fusion_confidence,
    resolve_consensus,
)


@dataclass
class VNSignalResult:
    symbol: str
    interval: str
    strategy: str
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str = ""
    regime: str = ""
    confidence: float = 0.0


@dataclass
class VNConsensusSignal:
    symbol: str
    interval: str
    consensus: ConsensusResult
    data_cutoff: str = VN_LIVE_CUTOFF


def _macd_vote(symbol: str, interval: str, high, low, close, cur_price: float) -> StrategyVote:
    res = macd_rsi_signal(high, low, close)
    side = "long" if res.signal == MACDRSISignalType.LONG else "none"
    conf = macd_rsi_confidence(res.macd_hist, res.rsi, side=side) if side == "long" else 0.0
    return StrategyVote(
        strategy="macd_rsi",
        side=side,
        confidence=conf,
        reason=res.reason,
        entry_price=cur_price,
        stop_loss=res.stop_loss,
        take_profit=res.take_profit,
    )


def _ma_vote(symbol: str, interval: str, high, low, close, volume, cur_price: float) -> StrategyVote:
    params = MACrossParams()
    res = ma_crossover_signal(high, low, close, volume, params)
    side = "long" if res.signal == MACrossSignalType.LONG else "none"
    avg_vol = float(np.mean(volume[-params.volume_period:])) if len(volume) >= params.volume_period else 1.0
    conf = ma_cross_confidence(res.fast_ma, res.slow_ma, cur_price, float(volume[-1]), avg_vol) if side == "long" else 0.0
    return StrategyVote(
        strategy="ma_crossover",
        side=side,
        confidence=conf,
        reason=res.reason,
        entry_price=cur_price,
        stop_loss=res.stop_loss,
        take_profit=res.take_profit,
    )


def _fusion_vote(open_, high, low, close, volume, cur_price: float) -> StrategyVote:
    res = regime_fusion_signal(open_, high, low, close, volume)
    side = "long" if res.signal == RegimeFusionSignalType.LONG else "none"
    conf = regime_fusion_confidence(res.regime, res.reason) if side == "long" else 0.0
    return StrategyVote(
        strategy="regime_fusion",
        side=side,
        confidence=conf,
        reason=res.reason,
        entry_price=cur_price,
        stop_loss=res.stop_loss,
        take_profit=res.take_profit,
        extra={"regime": res.regime},
    )


def scan_symbol_votes(
    symbol: str,
    interval: str = "1D",
    strategies: Optional[List[str]] = None,
    update_data: bool = False,
    data_root: Optional[Path] = None,
) -> List[StrategyVote]:
    """All strategy votes (including 'none') for consensus."""
    if strategies is None:
        strategies = ["macd_rsi", "ma_crossover", "regime_fusion"]

    if update_data:
        update_ohlcv(symbol, interval, data_root=data_root)

    data = load_ohlcv_arrays(symbol, interval, data_root=data_root)
    if data is None:
        return []
    _, open_, high, low, close, volume = data
    if len(close) < 50:
        return []

    cur_price = float(close[-1])
    votes: List[StrategyVote] = []
    if "macd_rsi" in strategies:
        votes.append(_macd_vote(symbol, interval, high, low, close, cur_price))
    if "ma_crossover" in strategies:
        votes.append(_ma_vote(symbol, interval, high, low, close, volume, cur_price))
    if "regime_fusion" in strategies:
        votes.append(_fusion_vote(open_, high, low, close, volume, cur_price))
    return votes


def scan_symbol_consensus(
    symbol: str,
    interval: str = "1D",
    strategies: Optional[List[str]] = None,
    min_votes: int = 2,
    update_data: bool = False,
    data_root: Optional[Path] = None,
    live_models: Optional[List[str]] = None,
) -> Optional[VNConsensusSignal]:
    votes = scan_symbol_votes(symbol, interval, strategies, update_data, data_root)
    if not votes:
        return None
    if live_models is not None:
        allowed = set(live_models)
        # registry stores vn_macd_rsi; votes use macd_rsi
        def _allowed(name: str) -> bool:
            return name in allowed or f"vn_{name}" in allowed or f"crypto_{name}" in allowed
        votes = [v for v in votes if _allowed(v.strategy)]
    consensus = resolve_consensus(votes, min_votes=min_votes, direction="long")
    if consensus.side != "long":
        return None
    return VNConsensusSignal(symbol=symbol, interval=interval, consensus=consensus)


def scan_symbol(
    symbol: str,
    interval: str = "1D",
    strategies: List[str] = None,
    update_data: bool = False,
    data_root: Optional[Path] = None,
) -> List[VNSignalResult]:
    """Long signals only (backward compatible)."""
    if strategies is None:
        strategies = ["macd_rsi", "ma_crossover", "regime_fusion"]

    votes = scan_symbol_votes(symbol, interval, strategies, update_data, data_root)
    out: List[VNSignalResult] = []
    for v in votes:
        if v.side != "long":
            continue
        extra = v.extra or {}
        out.append(VNSignalResult(
            symbol=symbol,
            interval=interval,
            strategy=v.strategy,
            entry_price=v.entry_price,
            stop_loss=v.stop_loss,
            take_profit=v.take_profit,
            reason=v.reason,
            regime=str(extra.get("regime", "")),
            confidence=v.confidence,
        ))
    return out


def scan_signals(
    symbols: List[str],
    intervals: List[str] = None,
    strategies: List[str] = None,
    update_data: bool = False,
    data_root: Optional[Path] = None,
    consensus: bool = False,
    min_votes: int = 2,
    live_models: Optional[List[str]] = None,
) -> List:
    if intervals is None:
        intervals = ["1D"]
    if strategies is None:
        strategies = ["macd_rsi", "ma_crossover", "regime_fusion"]

    if consensus:
        results: List[VNConsensusSignal] = []
        for symbol in symbols:
            for interval in intervals:
                try:
                    sig = scan_symbol_consensus(
                        symbol, interval, strategies, min_votes, update_data, data_root, live_models
                    )
                    if sig:
                        results.append(sig)
                except Exception as e:
                    print(f"[scan] Error {symbol} {interval}: {e}")
        return results

    all_signals: List[VNSignalResult] = []
    for symbol in symbols:
        for interval in intervals:
            try:
                all_signals.extend(scan_symbol(symbol, interval, strategies, update_data, data_root))
            except Exception as e:
                print(f"[scan] Error scanning {symbol} {interval}: {e}")
    return all_signals


def format_signal_telegram(sig: VNSignalResult) -> str:
    def _fmt(x: float) -> str:
        if x >= 1000:
            return f"{x:,.0f}"
        return f"{x:,.2f}"

    lines = [
        f"<b>LONG {sig.symbol}</b> ({sig.interval})",
        f"Entry: <code>{_fmt(sig.entry_price)}</code>",
    ]
    if sig.stop_loss:
        lines.append(f"SL: <code>{_fmt(sig.stop_loss)}</code>")
    if sig.take_profit:
        lines.append(f"TP: <code>{_fmt(sig.take_profit)}</code>")
    lines.append(f"Strategy: {sig.strategy}")
    if sig.confidence:
        lines.append(f"Conf: {sig.confidence:.2f}")
    if sig.reason:
        lines.append(f"Reason: {sig.reason}")
    if sig.regime:
        lines.append(f"Regime: {sig.regime}")
    return "\n".join(lines)


def format_consensus_telegram(sig: VNConsensusSignal) -> str:
    c = sig.consensus

    def _fmt(x: float) -> str:
        if x >= 1000:
            return f"{x:,.0f}"
        return f"{x:,.2f}"

    strat_list = ", ".join(v.strategy for v in c.votes if v.side == "long")
    lines = [
        f"<b>CONSENSUS LONG {sig.symbol}</b> ({sig.interval})",
        f"Tier: <b>{c.tier}</b> ({c.vote_count}/3) | Conf: {c.combined_confidence:.2f}",
        "",
        f"Entry: <code>{_fmt(c.entry_price)}</code>",
    ]
    if c.stop_loss:
        lines.append(f"SL: <code>{_fmt(c.stop_loss)}</code>")
    if c.take_profit:
        lines.append(f"TP: <code>{_fmt(c.take_profit)}</code>")
    lines.extend(["", f"Models: {strat_list}", f"Cutoff train: {sig.data_cutoff}"])
    return "\n".join(lines)
