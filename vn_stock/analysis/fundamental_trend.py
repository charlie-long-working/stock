"""
Fundamental trend analysis for Vietnamese stocks.

Computes quality scores based on:
  - Profitability: ROE, ROA, net margin, gross margin
  - Growth: revenue growth, profit growth (YoY)
  - Financial health: debt/equity, current ratio
  - Cash flow: operating CF, free CF
  - Valuation: P/E, P/B, EPS

Trend scoring: each metric is scored 0-1, weighted, aggregated to overall score.
Trend: "up" (score >= 0.65), "stable" (0.4-0.65), "down" (< 0.4).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from vn_stock.data_loaders.vn_fundamentals import compute_ratios


@dataclass
class FundamentalScore:
    symbol: str
    overall_score: float = 0.0
    trend: str = "unknown"
    profitability_score: float = 0.0
    growth_score: float = 0.0
    health_score: float = 0.0
    cashflow_score: float = 0.0
    valuation_score: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)


THRESHOLDS = {
    "roe": {"good": 0.15, "ok": 0.08, "bad": 0.0},
    "roa": {"good": 0.08, "ok": 0.03, "bad": 0.0},
    "net_margin": {"good": 0.15, "ok": 0.05, "bad": 0.0},
    "gross_margin": {"good": 0.30, "ok": 0.15, "bad": 0.0},
    "revenue_growth": {"good": 0.15, "ok": 0.05, "bad": -0.05},
    "profit_growth": {"good": 0.20, "ok": 0.05, "bad": -0.10},
    "debt_to_equity": {"good": 0.5, "ok": 1.5, "bad": 3.0},
    "current_ratio": {"good": 2.0, "ok": 1.2, "bad": 0.8},
    "pe": {"good": 12, "ok": 20, "bad": 35},
    "pb": {"good": 1.5, "ok": 3.0, "bad": 5.0},
}

WEIGHTS = {
    "profitability": 0.25,
    "growth": 0.25,
    "health": 0.20,
    "cashflow": 0.15,
    "valuation": 0.15,
}


def _score_metric(value: Optional[float], thresholds: dict, higher_is_better: bool = True) -> float:
    """Score a single metric 0-1."""
    if value is None:
        return 0.5

    if higher_is_better:
        if value >= thresholds["good"]:
            return 1.0
        elif value >= thresholds["ok"]:
            return 0.7
        elif value >= thresholds["bad"]:
            return 0.4
        else:
            return 0.1
    else:
        if value <= thresholds["good"]:
            return 1.0
        elif value <= thresholds["ok"]:
            return 0.7
        elif value <= thresholds["bad"]:
            return 0.4
        else:
            return 0.1


def analyze_fundamentals(
    symbol: str,
    current_price: Optional[float] = None,
    data_root: Optional[Path] = None,
) -> FundamentalScore:
    """
    Analyze fundamental health of a Vietnamese stock.
    Returns FundamentalScore with overall score, trend, and detailed metrics.

    data_root: sector bundle root (loads fundamentals from data_root/fundamentals/).
    """
    ratios = compute_ratios(symbol, current_price, data_root=data_root)
    result = FundamentalScore(symbol=symbol, metrics=ratios)

    # --- Profitability ---
    roe_score = _score_metric(ratios.get("roe"), THRESHOLDS["roe"])
    roa_score = _score_metric(ratios.get("roa"), THRESHOLDS["roa"])
    margin_score = _score_metric(ratios.get("net_margin"), THRESHOLDS["net_margin"])
    gross_score = _score_metric(ratios.get("gross_margin"), THRESHOLDS["gross_margin"])

    profitability_scores = [s for s in [roe_score, roa_score, margin_score, gross_score] if s != 0.5]
    result.profitability_score = sum(profitability_scores) / len(profitability_scores) if profitability_scores else 0.5

    if ratios.get("roe") is not None and ratios["roe"] > 0.20:
        result.flags.append("ROE cao (>20%)")
    if ratios.get("roe") is not None and ratios["roe"] < 0.05:
        result.flags.append("ROE thap (<5%)")

    # --- Growth ---
    rev_growth_score = _score_metric(ratios.get("revenue_growth"), THRESHOLDS["revenue_growth"])
    profit_growth_score = _score_metric(ratios.get("profit_growth"), THRESHOLDS["profit_growth"])

    growth_scores = [s for s in [rev_growth_score, profit_growth_score] if s != 0.5]
    result.growth_score = sum(growth_scores) / len(growth_scores) if growth_scores else 0.5

    if ratios.get("revenue_growth") is not None and ratios["revenue_growth"] > 0.25:
        result.flags.append("Tang truong DT manh (>25%)")
    if ratios.get("profit_growth") is not None and ratios["profit_growth"] < -0.20:
        result.flags.append("Loi nhuan giam manh (>20%)")

    # --- Financial health ---
    de_score = _score_metric(ratios.get("debt_to_equity"), THRESHOLDS["debt_to_equity"], higher_is_better=False)
    cr_score = _score_metric(ratios.get("current_ratio"), THRESHOLDS["current_ratio"])

    health_scores = [s for s in [de_score, cr_score] if s != 0.5]
    result.health_score = sum(health_scores) / len(health_scores) if health_scores else 0.5

    de = ratios.get("debt_to_equity")
    if de is not None and de > 2.0:
        if de > 5.0:
            result.flags.append(f"D/E={de:.1f} (cao, binh thuong neu ngan hang)")
        else:
            result.flags.append(f"D/E={de:.1f}")
    if ratios.get("current_ratio") is not None and ratios["current_ratio"] < 1.0:
        result.flags.append("Current ratio < 1 (rui ro thanh khoan)")

    # --- Cash flow ---
    cf_scores = []
    ocf = ratios.get("operating_cashflow")
    fcf = ratios.get("free_cashflow")
    if ocf is not None:
        cf_scores.append(1.0 if ocf > 0 else 0.2)
        if ocf < 0:
            result.flags.append("CF kinh doanh am")
    if fcf is not None:
        cf_scores.append(1.0 if fcf > 0 else 0.3)
        if fcf > 0:
            result.flags.append("FCF duong")

    result.cashflow_score = sum(cf_scores) / len(cf_scores) if cf_scores else 0.5

    # --- Valuation ---
    val_scores = []
    pe = ratios.get("pe")
    pb = ratios.get("pb")
    eps = ratios.get("eps")

    if pe is not None and pe > 0:
        val_scores.append(_score_metric(pe, THRESHOLDS["pe"], higher_is_better=False))
        if pe < 10:
            result.flags.append(f"P/E thap ({pe:.1f})")
        elif pe > 30:
            result.flags.append(f"P/E cao ({pe:.1f})")

    if pb is not None and pb > 0:
        val_scores.append(_score_metric(pb, THRESHOLDS["pb"], higher_is_better=False))
        if pb < 1:
            result.flags.append(f"P/B < 1 ({pb:.2f})")
        elif pb > 4:
            result.flags.append(f"P/B cao ({pb:.2f})")

    if eps is not None and eps > 0:
        result.flags.append(f"EPS: {eps:,.0f} VND")

    result.valuation_score = sum(val_scores) / len(val_scores) if val_scores else 0.5

    # --- Overall ---
    result.overall_score = (
        WEIGHTS["profitability"] * result.profitability_score +
        WEIGHTS["growth"] * result.growth_score +
        WEIGHTS["health"] * result.health_score +
        WEIGHTS["cashflow"] * result.cashflow_score +
        WEIGHTS["valuation"] * result.valuation_score
    )

    if result.overall_score >= 0.65:
        result.trend = "up"
    elif result.overall_score >= 0.40:
        result.trend = "stable"
    else:
        result.trend = "down"

    return result


def batch_analyze(
    symbols: List[str],
    prices: Optional[Dict[str, float]] = None,
    data_root: Optional[Path] = None,
) -> List[FundamentalScore]:
    """Analyze fundamentals for multiple symbols."""
    results = []
    for symbol in symbols:
        price = prices.get(symbol) if prices else None
        try:
            score = analyze_fundamentals(symbol, current_price=price, data_root=data_root)
            results.append(score)
        except Exception as e:
            print(f"[fundamental] Error analyzing {symbol}: {e}")
    return sorted(results, key=lambda x: x.overall_score, reverse=True)


def format_score_report(score: FundamentalScore) -> str:
    """Format a FundamentalScore as readable text."""
    m = score.metrics
    lines = [
        f"=== {score.symbol} | Xu huong: {score.trend.upper()} | Score: {score.overall_score:.2f} ===",
        f"  Profitability: {score.profitability_score:.2f}  |  Growth: {score.growth_score:.2f}",
        f"  Health:        {score.health_score:.2f}  |  Cash Flow: {score.cashflow_score:.2f}",
        f"  Valuation:     {score.valuation_score:.2f}",
        "",
    ]

    if m.get("roe") is not None:
        lines.append(f"  ROE: {m['roe']*100:.1f}%")
    if m.get("roa") is not None:
        lines.append(f"  ROA: {m['roa']*100:.1f}%")
    if m.get("net_margin") is not None:
        lines.append(f"  Net Margin: {m['net_margin']*100:.1f}%")
    if m.get("revenue_growth") is not None:
        lines.append(f"  Revenue Growth: {m['revenue_growth']*100:+.1f}%")
    if m.get("profit_growth") is not None:
        lines.append(f"  Profit Growth: {m['profit_growth']*100:+.1f}%")
    if m.get("debt_to_equity") is not None:
        lines.append(f"  Debt/Equity: {m['debt_to_equity']:.2f}")
    if m.get("current_ratio") is not None:
        lines.append(f"  Current Ratio: {m['current_ratio']:.2f}")
    if m.get("pe") is not None:
        lines.append(f"  P/E: {m['pe']:.1f}")
    if m.get("pb") is not None:
        lines.append(f"  P/B: {m['pb']:.2f}")
    if m.get("eps") is not None:
        lines.append(f"  EPS: {m['eps']:,.0f}")
    if m.get("operating_cashflow") is not None:
        lines.append(f"  Operating CF: {m['operating_cashflow']:,.0f}")
    if m.get("free_cashflow") is not None:
        lines.append(f"  Free CF: {m['free_cashflow']:,.0f}")

    if score.flags:
        lines.append("")
        lines.append("  Flags: " + " | ".join(score.flags))

    return "\n".join(lines)
