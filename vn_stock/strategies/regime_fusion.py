"""
Regime + Fusion strategy for Vietnamese stocks (Long only).

Uses regime classification (bull/bear/sideways) + smart money concepts
(order blocks, FVG, supply/demand zones) to generate Long signals.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

from .regime import RegimeClassifier, RegimeInputs
from .rules import get_rules_for_regime
from .technical import (
    order_blocks,
    fair_value_gaps,
    supply_demand_zones,
    price_at_ob,
    price_at_fvg,
    price_at_zone,
    OBType,
)
from .volume import volume_confirmation


class RegimeFusionSignalType(Enum):
    LONG = "long"
    NEUTRAL = "neutral"


@dataclass
class RegimeFusionResult:
    signal: RegimeFusionSignalType
    regime: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str = ""


def regime_fusion_signal(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    classifier: Optional[RegimeClassifier] = None,
    require_volume_confirmation: bool = False,
    ob_lookback: int = 50,
    fvg_lookback: int = 30,
    zone_lookback: int = 50,
) -> RegimeFusionResult:
    """
    Compute regime + fusion signal at the latest bar. Long-only for VN stocks.
    """
    if classifier is None:
        classifier = RegimeClassifier()

    if len(close) < 50:
        return RegimeFusionResult(
            signal=RegimeFusionSignalType.NEUTRAL,
            regime="sideways",
            reason="insufficient_data",
        )

    regime = classifier.classify(
        RegimeInputs(close=close, high=high, low=low)
    )
    rules = get_rules_for_regime(regime)
    last_close = float(close[-1])

    obs = order_blocks(open_, high, low, close, lookback=ob_lookback)
    fvgs = fair_value_gaps(high, low, lookback=fvg_lookback)
    zones = supply_demand_zones(open_, high, low, close, lookback=zone_lookback)

    vol_ok = not require_volume_confirmation or volume_confirmation(volume, idx=-1, period=20)

    if rules.allow_long and vol_ok:
        for ob in reversed(obs):
            if ob.ob_type == OBType.BULLISH and price_at_ob(last_close, ob):
                stop_pct = rules.stop_pct or 0.02
                tp_pct = rules.take_profit_pct
                return RegimeFusionResult(
                    signal=RegimeFusionSignalType.LONG,
                    regime=regime.value,
                    stop_loss=ob.low,
                    take_profit=last_close * (1 + tp_pct) if tp_pct else None,
                    reason="bull_ob",
                )
        for fvg in reversed(fvgs):
            if fvg.fvg_type == OBType.BULLISH and price_at_fvg(last_close, fvg):
                stop_pct = rules.stop_pct or 0.02
                tp_pct = rules.take_profit_pct
                return RegimeFusionResult(
                    signal=RegimeFusionSignalType.LONG,
                    regime=regime.value,
                    stop_loss=fvg.bottom,
                    take_profit=last_close * (1 + tp_pct) if tp_pct else None,
                    reason="bull_fvg",
                )
        for z in reversed(zones):
            if z.is_demand and price_at_zone(last_close, z):
                stop_pct = rules.stop_pct or 0.02
                tp_pct = rules.take_profit_pct
                return RegimeFusionResult(
                    signal=RegimeFusionSignalType.LONG,
                    regime=regime.value,
                    stop_loss=z.bottom,
                    take_profit=last_close * (1 + tp_pct) if tp_pct else None,
                    reason="demand_zone",
                )

    return RegimeFusionResult(
        signal=RegimeFusionSignalType.NEUTRAL,
        regime=regime.value,
        reason="no_zone",
    )
