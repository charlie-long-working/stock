#!/usr/bin/env python3
"""Kiểm tra máy hiện tại (VPS, mini PC, Mac) có gọi được các nguồn dữ liệu mà bot đang dùng hay không.

Chỉ dùng thư viện chuẩn Python 3.8+, không cần cài gì, không cần token hay .env. Mỗi nguồn chỉ gọi 1 lần.
Không gửi tin Telegram: kiểm tra Telegram bằng một token giả (bot0) và chỉ xem máy có tới được api.telegram.org.

Dùng trên VPS (chỉ cần copy một file này):
    python3 check_vps.py                       # in bảng kết quả
    python3 check_vps.py --save vps.json       # lưu kết quả để so sánh
    python3 check_vps.py --baseline mac.json   # đánh dấu nguồn chạy được ở máy mốc mà ở đây không
    python3 check_vps.py --no-ip               # không tra IP/quốc gia (ipinfo.io)

Nếu chạy trong repo daily-brief, danh sách RSS lấy từ config/sources.toml; không có thì dùng danh sách sẵn bên dưới.
Mã thoát: 0 = mọi nguồn bắt buộc đều chạy được; 1 = có nguồn bắt buộc lỗi.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIMEOUT = 15
MAX_BYTES = 256 * 1024          # chỉ đọc phần đầu phản hồi, đủ để nhận biết nội dung
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
VCI_HEADERS = {"Referer": "https://trading.vietcap.com.vn/", "Origin": "https://trading.vietcap.com.vn",
               "Content-Type": "application/json", "Accept": "application/json"}

# Danh sách RSS dự phòng khi không đọc được config/sources.toml (đồng bộ ngày 15/11/2026).
FALLBACK_RSS = [
    ("VnExpress – Thời sự", "https://vnexpress.net/rss/thoi-su.rss"),
    ("VnExpress – Kinh doanh", "https://vnexpress.net/rss/kinh-doanh.rss"),
    ("VnEconomy – Tài chính", "https://vneconomy.vn/tai-chinh.rss"),
    ("Tuổi Trẻ – Kinh doanh", "https://tuoitre.vn/rss/kinh-doanh.rss"),
    ("Báo Chính phủ", "https://baochinhphu.vn/rss"),
    ("Vietstock – Cổ phiếu", "https://vietstock.vn/830/chung-khoan/co-phieu.rss"),
    ("BBC – Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("Google News – Reuters", "https://news.google.com/rss/search?q=site:reuters.com&hl=en-US&gl=US&ceid=US:en"),
]


# ---------------------------------------------------------------- kiểm tra nội dung
def _json(body: bytes):
    return json.loads(body.decode("utf-8", "replace"))


def v_telegram(status, body):
    # Token giả → Telegram trả 401/404 dạng JSON {"ok":false,...}: nghĩa là máy TỚI ĐƯỢC Telegram.
    d = _json(body)
    return ("ok" in d), f"tới được API (HTTP {status} với token giả – đúng như mong đợi)"


def v_vci_chart(status, body):
    d = _json(body)
    if isinstance(d, list) and d and isinstance(d[0], dict):
        n = len(d[0].get("c") or d[0].get("close") or [])
        return n > 0, f"{n} nến ngày FPT"
    return False, f"dữ liệu lạ: {str(d)[:80]}"


def v_list_nonempty(label):
    def f(status, body):
        d = _json(body)
        items = d if isinstance(d, list) else (d.get("data") or d.get("result") or d.get("list") or [])
        if isinstance(items, dict):
            items = list(items.values())
        return bool(items), f"{len(items)} {label}"
    return f


def v_vnd(status, body):
    d = _json(body)
    rows = d.get("data") or []
    return bool(rows), f"{len(rows)} chỉ số FPT"


def v_yahoo(status, body):
    d = _json(body)
    res = ((d.get("chart") or {}).get("result") or [None])[0]
    if not res:
        return False, f"lỗi: {str((d.get('chart') or {}).get('error'))[:80]}"
    closes = [c for c in (((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []) if c]
    return bool(closes), f"{len(closes)} giá đóng cửa, cuối {closes[-1]:.2f}" if closes else "không có giá"


def v_contains(*needles, label="dữ liệu"):
    def f(status, body):
        t = body.decode("utf-8", "replace")
        hit = [n for n in needles if n.lower() in t.lower()]
        return bool(hit), (f"có {label}" if hit else f"không thấy {label} – có thể là trang chặn/captcha: {_snippet(t)}")
    return f


def v_rss(status, body):
    t = body.decode("utf-8", "replace")
    n = len(re.findall(r"<item[\s>]", t)) + len(re.findall(r"<entry[\s>]", t))
    return n > 0, (f"{n} bài" if n else f"không có bài – {_snippet(t)}")


def v_binance_klines(status, body):
    d = _json(body)
    return isinstance(d, list) and len(d) > 0, f"{len(d) if isinstance(d, list) else 0} nến BTCUSDT"


def v_bybit(status, body):
    d = _json(body)
    rows = (d.get("result") or {}).get("list") or []
    return bool(rows), f"{len(rows)} nến (retCode {d.get('retCode')})"


def v_okx(status, body):
    d = _json(body)
    return bool(d.get("data")), f"{len(d.get('data') or [])} nến (code {d.get('code')})"


def v_gate(status, body):
    d = _json(body)
    return isinstance(d, list) and len(d) > 0, f"{len(d) if isinstance(d, list) else 0} mốc OI"


def v_cmc(status, body):
    d = _json(body)
    q = (d.get("data") or {}).get("quotes") or []
    return bool(q), f"{len(q)} ngày dữ liệu vốn hoá toàn thị trường"


def v_json_prefix(status, body):
    t = body[:200].decode("utf-8", "replace").lstrip()
    return t.startswith("{") or t.startswith("["), "trả JSON" if t[:1] in "{[" else _snippet(t)


def v_pypi(status, body):
    t = body.decode("utf-8", "replace")
    return "pandas" in t.lower(), "tải được danh mục gói"


def _snippet(t: str) -> str:
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return (t[:70] + "…") if len(t) > 70 else (t or "trống")


# ---------------------------------------------------------------- danh sách nguồn
def rss_sources() -> list:
    cfg = Path(__file__).resolve().parent.parent / "config" / "sources.toml"
    if not cfg.exists():
        return FALLBACK_RSS
    out = []
    for block in cfg.read_text(encoding="utf-8").split("[[source]]")[1:]:
        fmt = re.search(r'^format\s*=\s*"([^"]+)"', block, re.M)
        url = re.search(r'^url\s*=\s*"([^"]+)"', block, re.M)
        name = re.search(r'^name\s*=\s*"([^"]+)"', block, re.M)
        off = re.search(r"^enabled\s*=\s*false", block, re.M)
        if url and fmt and fmt.group(1) == "rss" and not off:
            out.append((name.group(1) if name else url.group(1), url.group(1)))
    return out or FALLBACK_RSS


def build_checks() -> list:
    now = int(time.time())
    today = datetime.now(timezone.utc).date()
    C = []

    def add(group, name, url, check, *, method="GET", payload=None, headers=None, critical=False, used_by=""):
        C.append(dict(group=group, name=name, url=url, check=check, method=method, payload=payload,
                      headers=headers or {}, critical=critical, used_by=used_by))

    g = "Telegram"
    add(g, "api.telegram.org", "https://api.telegram.org/bot0/getMe", v_telegram, critical=True,
        used_by="mọi bot gửi tin")

    g = "Chứng khoán VN"
    add(g, "VCI – nến ngày (vnstock Quote)", "https://trading.vietcap.com.vn/api/chart/OHLCChart/gap-chart",
        v_vci_chart, method="POST", headers=VCI_HEADERS, critical=True,
        payload={"timeFrame": "ONE_DAY", "symbols": ["FPT"], "to": now, "countBack": 10},
        used_by="quét 100 mã, tín hiệu theo giờ, trang tĩnh")
    add(g, "VCI – bảng giá (price_board)", "https://trading.vietcap.com.vn/api/price/symbols/getList",
        v_list_nonempty("mã"), method="POST", headers=VCI_HEADERS, critical=True,
        payload={"symbols": ["FPT", "VCB"]}, used_by="quét 100 mã, /stock")
    add(g, "KBS – danh sách VN100", "https://kbbuddywts.kbsec.com.vn/iis-server/investment/index/100/stocks",
        v_list_nonempty("mã"), critical=True, used_by="dựng danh sách 100 mã, nguồn dự phòng giá")
    add(g, "VNDirect finfo – chỉ số tài chính",
        "https://api-finfo.vndirect.com.vn/v4/ratios?" + urllib.parse.urlencode(
            {"q": "code:FPT~ratioCode:PRICE_TO_EARNINGS,PRICE_TO_BOOK", "size": 10}),
        v_vnd, critical=True, used_by="BCTC, định giá trong quét 100 mã")

    g = "Vàng, bạc, tỷ giá"
    add(g, "Yahoo – GC=F (vàng COMEX)",
        "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF?range=5d&interval=1d", v_yahoo, critical=True,
        used_by="bản tin vàng, trang tĩnh, tín hiệu vàng")
    add(g, "Yahoo – VND=X (USD/VND)",
        "https://query1.finance.yahoo.com/v8/finance/chart/VND%3DX?range=5d&interval=1d", v_yahoo,
        used_by="quy đổi giá vàng")
    add(g, "Vietcombank – tỷ giá XML", "https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx",
        v_contains("Exrate", label="bảng tỷ giá"), used_by="bản tin vàng/tỷ giá")
    add(g, "SJC – giá vàng XML", "https://sjc.com.vn/xml/tygiavang.xml",
        v_contains("<city", "<item", "ratelist", label="bảng giá SJC"), used_by="giá SJC (đang lỗi cả trên Mac)")
    add(g, "OKX – XAU-USDT", "https://www.okx.com/api/v5/market/candles?instId=XAU-USDT-SWAP&bar=1D&limit=5",
        v_okx, used_by="tín hiệu vàng (nguồn dự phòng)")

    g = "Crypto"
    add(g, "Binance spot – nến", "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=5",
        v_binance_klines, used_by="nến BTC/ETH (nguồn 1)")
    add(g, "Binance data-api", "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=5",
        v_binance_klines, used_by="nến BTC/ETH (dự phòng)")
    add(g, "Binance futures (fapi)", "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1d&limit=5",
        v_binance_klines, used_by="OI, funding")
    add(g, "Bybit – nến", "https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=D&limit=5",
        v_bybit, used_by="nến/funding (dự phòng)")
    add(g, "Gate.io – OI", "https://api.gateio.ws/api/v4/futures/usdt/contract_stats?contract=BTC_USDT&interval=1h&limit=5",
        v_gate, used_by="OI khi Binance/Bybit bị chặn")
    add(g, "OKX – BTC", "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1D&limit=5", v_okx,
        used_by="dự phòng")
    s, e = (today - timedelta(days=7)).isoformat(), today.isoformat()
    add(g, "CoinMarketCap – vốn hoá (USDT.D)",
        "https://api.coinmarketcap.com/data-api/v3/global-metrics/quotes/historical?" + urllib.parse.urlencode(
            {"time_start": s, "time_end": e, "interval": "1d", "count": 10}),
        v_cmc, headers={"Referer": "https://coinmarketcap.com/", "Accept": "application/json"}, used_by="USDT.D")
    add(g, "DefiLlama – USDT", "https://stablecoins.llama.fi/stablecoin/1", v_json_prefix, used_by="USDT.D")

    g = "Tin tức (RSS)"
    for name, url in rss_sources():
        add(g, name, url, v_rss, used_by="bản tin, tab tin tức")

    g = "Cài đặt"
    add(g, "PyPI", "https://pypi.org/simple/pandas/", v_pypi, used_by="pip install khi dựng máy")
    add(g, "GitHub", "https://github.com/", v_contains("github", label="trang GitHub"), used_by="git clone/pull")
    return C


# ---------------------------------------------------------------- chạy
def run_one(c: dict) -> dict:
    headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "vi,en;q=0.8"}
    headers.update(c["headers"])
    data = json.dumps(c["payload"]).encode() if c["payload"] is not None else None
    req = urllib.request.Request(c["url"], data=data, headers=headers, method=c["method"])
    t0 = time.time()
    r = {k: c[k] for k in ("group", "name", "critical", "used_by")}
    r["host"] = urllib.parse.urlparse(c["url"]).hostname
    status, body = None, b""
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as resp:
            status, body = resp.status, resp.read(MAX_BYTES)
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            body = e.read(MAX_BYTES)
        except Exception:
            body = b""
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, socket.gaierror):
            r.update(result="DNS", note=f"không phân giải được tên miền ({reason}) – thường do nhà mạng/DNS chặn")
        elif isinstance(reason, (socket.timeout, TimeoutError)):
            r.update(result="TIMEOUT", note=f"quá {TIMEOUT}s – có thể bị chặn ở tầng mạng")
        elif isinstance(reason, ConnectionResetError):
            r.update(result="RESET", note="kết nối bị ngắt – dấu hiệu chặn ở tầng mạng")
        elif isinstance(reason, ConnectionRefusedError):
            r.update(result="REFUSED", note="bị từ chối kết nối")
        elif isinstance(reason, ssl.SSLError):
            r.update(result="SSL", note=f"lỗi SSL: {str(reason)[:80]}")
        else:
            r.update(result="NET", note=f"{type(reason).__name__}: {str(reason)[:80]}")
    except (socket.timeout, TimeoutError):
        r.update(result="TIMEOUT", note=f"quá {TIMEOUT}s khi đọc dữ liệu")
    except Exception as e:
        r.update(result="NET", note=f"{type(e).__name__}: {str(e)[:80]}")
    r["ms"] = int((time.time() - t0) * 1000)
    r["http"] = status
    if "result" in r:
        return r
    # Telegram với token giả trả 401/404 là kết quả mong đợi.
    expected_error = c["check"] is v_telegram and status in (401, 404)
    if status in (403, 451) and not expected_error:
        r.update(result="BLOCKED", note=f"HTTP {status} – nguồn chặn IP/khu vực này: {_snippet(body.decode('utf-8', 'replace'))}")
        return r
    if status == 429:
        r.update(result="LIMIT", note="HTTP 429 – bị giới hạn tần suất (IP trung tâm dữ liệu hay gặp với Yahoo)")
        return r
    try:
        ok, note = c["check"](status, body)
    except Exception as e:
        ok, note = False, f"không đọc được nội dung ({type(e).__name__}): {_snippet(body.decode('utf-8', 'replace'))}"
    if status == 404 and not expected_error:
        ok, note = False, "HTTP 404 – địa chỉ không còn (nguồn đã đổi), không phải do chặn IP"
    elif status and status >= 400 and not expected_error:
        ok = False
        note = f"HTTP {status}: {note}"
    r.update(result="OK" if ok else "BAD", note=note)
    return r


def ip_info() -> dict:
    try:
        req = urllib.request.Request("https://ipinfo.io/json", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            d = json.loads(resp.read(MAX_BYTES))
        return {k: d.get(k) for k in ("ip", "city", "country", "org")}
    except Exception as e:
        return {"error": f"{type(e).__name__}"}


def width(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Kiểm tra máy này gọi được các nguồn dữ liệu của bot hay không.")
    ap.add_argument("--save", help="lưu kết quả JSON vào file này")
    ap.add_argument("--baseline", help="file JSON đã lưu ở máy mốc (vd Mac) để so sánh")
    ap.add_argument("--no-ip", action="store_true", help="không tra IP/quốc gia qua ipinfo.io")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)

    checks = build_checks()
    info = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "host": socket.gethostname(),
            "python": sys.version.split()[0]}
    if not a.no_ip:
        info.update(ip_info())
    print(f"Máy: {info['host']} · Python {info['python']} · {info['time']}")
    if not a.no_ip:
        print(f"IP: {info.get('ip')} · {info.get('city')}, {info.get('country')} · {info.get('org')}")
    print(f"Đang kiểm tra {len(checks)} nguồn (mỗi nguồn 1 lần, timeout {TIMEOUT}s)…\n")

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        results = list(ex.map(run_one, checks))

    base = {}
    if a.baseline:
        try:
            for r in json.loads(Path(a.baseline).read_text(encoding="utf-8"))["results"]:
                base[(r["group"], r["name"])] = r["result"]
        except Exception as e:
            print(f"(không đọc được baseline: {e})\n")

    icon = {"OK": "✅", "BAD": "⚠️ ", "BLOCKED": "⛔", "LIMIT": "⏳"}
    group = None
    for r in results:
        if r["group"] != group:
            group = r["group"]
            print(f"── {group} " + "─" * max(0, 60 - len(group)))
        mark = icon.get(r["result"], "❌")
        crit = "*" if r["critical"] else " "
        diff = ""
        b = base.get((r["group"], r["name"]))
        if b == "OK" and r["result"] != "OK":
            diff = "  ← máy mốc chạy được, máy này KHÔNG"
        elif b and b != "OK" and r["result"] == "OK":
            diff = "  ← máy mốc lỗi, máy này được"
        print(f" {mark} {crit}{width(r['name'], 34):<34} {r['result']:<8} {r['ms']:>6} ms  {width(r['note'], 70)}{diff}")

    crit_fail = [r for r in results if r["critical"] and r["result"] != "OK"]
    print("\n* = nguồn bắt buộc. Kết luận:")
    by_group = {}
    for r in results:
        by_group.setdefault(r["group"], []).append(r)
    for gname, rs in by_group.items():
        ok = sum(r["result"] == "OK" for r in rs)
        bad_crit = [r["name"] for r in rs if r["critical"] and r["result"] != "OK"]
        status = "ĐƯỢC" if not bad_crit and ok else ("THIẾU NGUỒN BẮT BUỘC: " + ", ".join(bad_crit) if bad_crit else "LỖI")
        print(f"  • {gname}: {ok}/{len(rs)} chạy được – {status}")
    if crit_fail:
        print("\n❌ Máy này CHƯA hợp để chạy bot: có nguồn bắt buộc lỗi (xem dấu *). Đừng trả tiền thuê dài hạn.")
    else:
        print("\n✅ Mọi nguồn bắt buộc đều chạy được. Nguồn phụ lỗi chỉ làm thiếu một phần (bot có dự phòng).")
    print("Lưu ý: chỉ là 1 lần gọi. Nguồn có thể chặn khi gọi nhiều (vd quét 100 mã) – nên chạy lại vài lần trong ngày.")

    if a.save:
        Path(a.save).write_text(json.dumps({"info": info, "results": results}, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        print(f"Đã lưu: {a.save}")
    return 1 if crit_fail else 0


if __name__ == "__main__":
    sys.exit(main())
