#!/usr/bin/env python3
"""
Thu thập mua/bán chủ động phiên gần nhất cho các mã Stock Intelligence (chạy tay / chạy bù).

Bình thường job swing-vn (16:00) tự gọi bước này sau khi Stock Intelligence xong.
Chạy bù trước 09:00 phiên sau vẫn lấy được phiên trước (KBS trả phiên gần nhất).
Không chạy song song với `run_intel_scan` (chung giới hạn 20 request/phút của vnstock).

  PYTHONPATH="$PWD:$PWD/../Trading-bot" .venv/bin/python -m vn_stock.scripts.run_tape_collect --symbols VCB,HPG,SSI --dry-run
  ... --force            # lấy lại cả mã đã có
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

STOCK_ROOT = Path(__file__).resolve().parents[2]
if str(STOCK_ROOT) not in sys.path:
    sys.path.insert(0, str(STOCK_ROOT))

from vn_stock import DATA_DIR  # noqa: E402
from vn_stock.tape import collect as C  # noqa: E402
from vn_stock.tape.metrics import daily_leaders, format_leaders  # noqa: E402


def universe() -> list[str]:
    try:
        d = json.loads((DATA_DIR / "intel" / "latest.json").read_text(encoding="utf-8"))
        syms = sorted(s["symbol"] for s in d.get("stocks", []))
        if syms:
            return syms
    except (OSError, ValueError, KeyError):
        pass
    return sorted(p.stem for p in (DATA_DIR / "intel" / "ohlcv_adj").glob("*.csv")
                  if p.stem not in ("VNINDEX", "VN30", "HNXINDEX"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols")
    ap.add_argument("--session", help="mặc định: phiên gần nhất đã kết thúc")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="tổng hợp và in, không ghi file")
    args = ap.parse_args()

    syms = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else universe()
    session = args.session or C.expected_session()
    if args.dry_run:
        for s in syms:
            ticks, pages = C.fetch_ticks(s)
            if len(ticks) == 0:
                print(f"{s}: không có tick")
                continue
            ref, adv = C._ref_from_adjusted(s, ticks["time"].iloc[-1].strftime("%Y-%m-%d"))
            r = C.aggregate(ticks, s, ref_volume=ref, large_thr_bn=C.large_threshold_bn(adv), pages=pages)
            chk = f"{r['total_vol'] / ref:.4f}" if ref else "—"
            print(f"{s} {r['date']} mua CĐ {r['buy_vol']:,} · bán CĐ {r['sell_vol']:,} · ATO {r['ato_vol']:,} · "
                  f"ATC {r['atc_vol']:,} · nar {r['nar']:+.3f} · tổng/KL ngày {chk} · lô lớn ≥{r['large_thr_bn']} tỷ "
                  f"mua {r['large_buy_value_bn']:.1f}/bán {r['large_sell_value_bn']:.1f} tỷ · {r['n_ticks']} tick")
        return 0

    rows, errors = C.collect(syms, session, force=args.force)
    for s, e in sorted(errors.items()):
        print(f"  ! {s}: {e}")
    tb, ts = daily_leaders(C.load_daily(), session)
    msg = format_leaders(session, tb, ts)
    if msg:
        print(msg)
    return 0 if rows or not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
