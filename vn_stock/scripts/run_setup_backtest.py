#!/usr/bin/env python3
"""
Backtest + chọn tham số + ngưỡng đạt chuẩn cho các setup nền giá / phân kỳ (và đối chứng macd_rsi_atr).

Quy trình (chống overfit):
  1. Chạy lưới nhỏ (24 cấu hình) trên toàn bộ lịch sử, nhưng CHỌN chỉ bằng train (<2022) + validate (2022–2023).
  2. Khoá cấu hình đã chọn (hash) vào vn_stock/setups/config.json.
  3. Đánh giá ngoài mẫu (≥ 2024) đúng cấu hình đã khoá: ngưỡng đạt chuẩn → ship | watch | off.
Kết quả: data/research/setups_<stamp>/ (trades.csv, summary.json — gitignored),
         docs/BACKTEST_SETUPS_<date>.md (báo cáo tổng hợp, không có dữ liệu cá nhân), setups/config.json.

  PYTHONPATH="$PWD:$PWD/../Trading-bot" .venv/bin/python -m vn_stock.scripts.run_setup_backtest
  ... --symbols VCB,FPT,HPG --no-report      # chạy nhanh để thử
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

STOCK_ROOT = Path(__file__).resolve().parents[2]
if str(STOCK_ROOT) not in sys.path:
    sys.path.insert(0, str(STOCK_ROOT))

from vn_stock import DATA_DIR  # noqa: E402
from vn_stock.research import setup_backtest as S  # noqa: E402
from vn_stock.setups import features as F  # noqa: E402

CONFIG_PATH = STOCK_ROOT / "vn_stock" / "setups" / "config.json"
OUT_ROOT = DATA_DIR / "research"
DOCS = STOCK_ROOT / "docs"
NAMES = {"base_breakout": "Phá nền giá đi ngang", "div_bull": "Phân kỳ dương MACD/RSI",
         "macd_rsi_atr": "MACD+RSI ATR (đã hạ xuống theo dõi)", "macd_signed": "MACD signed — chỉ MUA (đang chạy live)"}


def evidence_text(g: dict) -> str:
    o = g["oos"]
    if not o.get("n"):
        return "ngoài mẫu 2024+: chưa có lệnh"
    pf = f"{o['pf']:.2f}" if o.get("pf") is not None else "—"
    return (f"ngoài mẫu 2024+ (sau phí, T+2): {o['n']} lệnh, win {o['win'] * 100:.0f}%, PF {pf}, "
            f"TB {o['mean'] * 100:+.2f}%/lệnh — {g['verdict'].upper()}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols")
    ap.add_argument("--no-report", action="store_true", help="không ghi docs/ và setups/config.json")
    ap.add_argument("--random-iter", type=int, default=500)
    args = ap.parse_args()

    t0 = time.time()
    costs = S.load_costs()
    syms = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else F.universe()
    data, feats = {}, {}
    for s in syms:
        df = F.load_adjusted(s)
        if df is not None and len(df) > 300:
            data[s], feats[s] = df, F.add_common(df)
    idx = F.load_adjusted("VNINDEX")
    bearish = F.index_bearish(idx) if idx is not None else None
    idx_close = idx.set_index("time")["close"] if idx is not None else None
    print(f"Dữ liệu: {len(data)} mã · chi phí {costs}")

    configs = {c.id: c for c in S.grid()}
    configs[S.BENCHMARK.id] = S.BENCHMARK
    configs[S.BENCHMARK_SIGNED.id] = S.BENCHMARK_SIGNED
    trades, results = {}, {}
    for k, cfg in configs.items():
        tr = S.run_config(cfg, data, feats, costs, bearish, idx_close)
        trades[k] = tr
        results[k] = {p: S.stats(tr[tr["period"] == p] if len(tr) else tr) for p in ("train", "validate")}
        print(f"  {k:28s} train {results[k]['train']} | validate PF {results[k]['validate'].get('pf')}")

    chosen = {}
    for setup in ("base_breakout", "div_bull"):
        sel = S.select(results, configs, setup)
        fallback = False
        if sel is None:  # không cấu hình nào qua bước chọn → lấy train tốt nhất (đủ mẫu) để báo cáo, tối đa "watch"
            cands = [k for k, c in configs.items() if c.setup == setup and results[k]["train"].get("n", 0) >= 30]
            sel = max(cands, key=lambda k: results[k]["train"].get("mean", -1)) if cands else None
            fallback = True
        if sel:
            chosen[setup] = (sel, fallback)
    chosen["macd_rsi_atr"] = (S.BENCHMARK.id, False)
    chosen["macd_signed"] = (S.BENCHMARK_SIGNED.id, False)

    verdicts = {}
    for setup, (k, fallback) in chosen.items():
        cfg, tr = configs[k], trades[k]
        oos = tr[tr["period"] == "oos"] if len(tr) else tr
        val = tr[tr["period"] == "validate"] if len(tr) else tr
        costs2 = {kk: v * 2 for kk, v in costs.items()}
        tr2 = S.run_config(cfg, data, feats, costs2, bearish, idx_close)
        oos2 = tr2[tr2["period"] == "oos"] if len(tr2) else tr2
        rand = S.random_baseline(oos, data, costs, n_iter=args.random_iter)
        acc, port = S.portfolio(oos)
        g = S.evaluate_gates(oos, val, oos2, rand, port)
        if fallback and g["verdict"] == "ship":
            g["verdict"] = "watch"
            g["note"] = "không cấu hình nào qua bước chọn train/validate"
        g["selected_by"] = ("đối chứng — cấu hình đang chạy live" if setup in ("macd_rsi_atr", "macd_signed")
                            else "dự phòng: không cấu hình nào qua bước chọn train/validate" if fallback
                            else "train/validate")
        g["config"] = cfg.to_dict()
        g["train"], g["validate"] = results[k]["train"], results[k]["validate"]
        g["all_periods_mean_idx_ret"] = (round(float(oos["idx_ret"].dropna().mean()), 5)
                                         if len(oos) and "idx_ret" in oos else None)
        verdicts[setup] = g
        print(f"== {setup}: {g['verdict'].upper()} · {evidence_text(g)}")
        print("   checks:", {c: ("✓" if v else "✗") for c, v in g["checks"].items()})

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out = OUT_ROOT / f"setups_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    pd.concat([t for t in trades.values() if len(t)], ignore_index=True).to_csv(out / "trades.csv", index=False)
    summary = {"generated_at": datetime.now().isoformat(timespec="seconds"), "symbols": len(data), "costs": costs,
               "configs_tested": len(configs) - 2, "periods": {"train_end": S.TRAIN_END, "oos_start": S.OOS_START},
               "gates": S.GATES, "grid": {k: {**configs[k].to_dict(), **results[k]} for k in configs},
               "verdicts": verdicts, "runtime_s": round(time.time() - t0, 1)}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"Kết quả: {out} ({time.time() - t0:.0f}s)")

    if args.no_report:
        return 0
    live = {"frozen_at": summary["generated_at"], "source": f"data/research/setups_{stamp}",
            "setups": {s: {"verdict": g["verdict"], "config": g["config"], "evidence": evidence_text(g)}
                       for s, g in verdicts.items()}}
    CONFIG_PATH.write_text(json.dumps(live, ensure_ascii=False, indent=1), encoding="utf-8")
    write_report(verdicts, summary, results, configs, DOCS / f"BACKTEST_SETUPS_{datetime.now():%Y-%m-%d}.md")
    print(f"Đã ghi {CONFIG_PATH.relative_to(STOCK_ROOT)} và báo cáo docs/")
    return 0


def _pct(x):
    return "—" if x is None else f"{x * 100:+.2f}%"


def write_report(verdicts: dict, summary: dict, results: dict, configs: dict, path: Path) -> None:
    L = [f"# Backtest setup cổ phiếu VN — {summary['generated_at'][:10]}", "",
         f"- {summary['symbols']} mã Stock Intelligence, giá điều chỉnh cổ tức 2012 → nay; chi phí "
         f"phí mua {summary['costs']['fee_buy']:.2%}, phí bán {summary['costs']['fee_sell']:.2%}, "
         f"thuế {summary['costs']['tax_sell']:.2%}, trượt giá {summary['costs']['slippage']:.2%}/chiều; T+2.",
         f"- Chọn tham số chỉ trên train (< {summary['periods']['train_end']}) + validate; ngoài mẫu từ "
         f"{summary['periods']['oos_start']}. Số cấu hình đã thử: **{summary['configs_tested']}**.",
         "- **Thiên lệch sống sót:** danh sách 100 mã của hôm nay áp cho quá khứ → kết quả có xu hướng lạc quan.",
         "", "## Kết luận", "",
         "| Setup | Kết luận | Ngoài mẫu | Train | Validate PF |", "|---|---|---|---|---|"]
    for s, g in verdicts.items():
        o, t = g["oos"], g["train"]
        L.append(f"| {NAMES.get(s, s)} | **{g['verdict'].upper()}** | {o.get('n', 0)} lệnh, win "
                 f"{(o.get('win') or 0) * 100:.0f}%, PF {o.get('pf')}, TB {_pct(o.get('mean'))} | "
                 f"{t.get('n', 0)} lệnh, PF {t.get('pf')}, TB {_pct(t.get('mean'))} | {g['validate'].get('pf')} |")
    L += ["", "SHIP = gửi lệnh MUA có entry/SL/TP và vào sổ lệnh; WATCH = chỉ danh sách theo dõi; OFF = không gửi.", ""]
    for s, g in verdicts.items():
        L += [f"## {NAMES.get(s, s)}", "", f"Cấu hình (`{g['config']['id']}`, chọn bằng {g['selected_by']}):",
              "```json", json.dumps(g["config"], ensure_ascii=False, default=str), "```", "",
              "| Ngưỡng | Đạt |", "|---|---|"]
        L += [f"| {c} | {'✓' if v else '✗'} |" for c, v in g["checks"].items()]
        p = g["portfolio"]
        L += ["", f"- Bootstrap cận dưới 97,5% TB/lệnh: {_pct(g['bootstrap_lb'])} · random p90: {_pct(g['random_p90'])}",
              f"- Danh mục (≤5 vị thế, 1% rủi ro): {p.get('n', 0)} lệnh nhận, CAGR {_pct(p.get('cagr'))}, "
              f"max DD {_pct(p.get('max_dd'))}",
              f"- Tập trung: mã lớn nhất {g['concentration'].get('top_share')} tổng lãi, PF bỏ top 3: "
              f"{g['concentration'].get('pf_ex_top3')}",
              f"- Theo năm (TB/lệnh): {g['oos_by_year']}", ""]
    L += ["## Toàn bộ lưới (train / validate)", "", "| Cấu hình | Train n | Train PF | Train TB | Validate n | Validate PF |",
          "|---|---|---|---|---|---|"]
    for k, r in results.items():
        L.append(f"| `{k}` | {r['train'].get('n', 0)} | {r['train'].get('pf')} | {_pct(r['train'].get('mean'))} | "
                 f"{r['validate'].get('n', 0)} | {r['validate'].get('pf')} |")
    L += ["", "Không phải lời khuyên đầu tư."]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
