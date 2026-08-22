# Báo cáo chiến lược VN: MACD + RSI + Ichimoku

**Ngày:** 2026-08-23  
**Phạm vi:** 10 mã bluechip (VCB, BID, TCB, FPT, HPG, MWG, MSN, GAS, VHM, VNM)  
**Khung thời gian:** 1W · 1D · 4H · 1H  
**Lưu ý:** Backtest lịch sử, long-only, không phải khuyến nghị mua/bán.

---

## 1. Tóm tắt nhanh

**Playbook đề xuất (ổn định nhất):**

| Bước | Khung | Điều kiện |
|------|-------|-----------|
| Bias | **1W** | Giá trên mây Ichimoku (bull) hoặc EMA20 > EMA50 |
| Entry | **1D** | MACD hist cắt lên 0 **và** RSI < 70 **và** giá trên mây bull |
| Timing | H4 / H1 | Chỉ refine điểm vào, **không** trade standalone |
| Exit | — | ATR SL 1.5× / TP 2.5× **hoặc** TP 10% / SL 4% (+ lọc EMA) |

**Confluence** (MACD+RSI ∩ mây Ichimoku) trên full sample 1D: **9/10 mã dương**, avg return **+33.4%**, win rate **~50%**, max DD trung bình **~13.6%**.

---

## 2. Dữ liệu đã dùng

| Mã | 1D bars | 1W | 1H | 4H (từ 1H) |
|----|---------|----|----|------------|
| VCB | 1 732 | 362 | 3 338 | 1 472 |
| BID | 1 732 | 362 | 3 338 | 1 472 |
| TCB | 1 732 | 362 | 3 339 | 1 472 |
| FPT | 1 732 | 362 | 3 339 | 1 472 |
| HPG | 3 763 | 787 | 3 339 | 1 472 |
| MWG | 3 026 | 632 | 3 339 | 1 472 |
| MSN | 3 765 | 787 | 3 339 | 1 472 |
| GAS | 3 561 | 744 | 3 339 | 1 472 |
| VHM | 3 479 | 772 | 3 339 | 1 472 |
| VNM | 3 765 | 787 | 3 339 | 1 472 |

- Nguồn OHLCV: vnstock (VCI), lưu tại `stock/vn_stock/data/ohlcv/{MÃ}/`
- **4H** không có API native → resample từ nến **1H**
- Engine: `vn_stock` ATR exit (SL 1.5×ATR, TP 2.5×ATR), long-only

---

## 3. Xếp hạng ổn định (full sample, ≥5 lệnh)

Không so với buy-hold dài hạn (bull market làm alpha âm dù strategy lãi). Tiêu chí: tỷ lệ mã dương, win rate, drawdown.

| Hạng | Strategy × TF | % mã lãi | Avg return | Win % | Avg max DD | Nhận xét |
|------|---------------|----------|------------|-------|------------|----------|
| 1 | **Ichimoku × 1D** | 80% (8/10) | +28.1% | 44.5 | **13.5%** | Ít lệnh, DD thấp — ổn định nhất |
| 2 | **MACD+RSI × 1D** | 70% (7/10) | **+90.3%** | 44.7 | 31.6% | Lãi cao hơn, DD lớn hơn |
| 3 | MACD+RSI × 1H | 70% (7/10) | +23.2% | 41.9 | 16.2% | Intraday; nhiễu hơn 1D |
| 4 | Ichimoku × 4H | 50% | +7.7% | 40.7 | 7.7% | DD thấp nhưng edge mỏng |
| 5 | MACD+RSI × 4H | 60% | +19.5% | 42.5 | 17.6% | Trung bình |
| 6 | Ichimoku × 1H | 40% | +4.7% | 40.4 | 9.1% | Không đủ ổn để primary |

**1W:** quá ít tín hiệu (thường 0–3 lệnh/mã) → dùng làm **bias**, không backtest standalone.

---

## 4. Chi tiết 1D theo mã

### 4.1 MACD + RSI (ATR exit)

Entry: hist cắt lên 0 + RSI < 70.

| Mã | Return | Win % | Max DD | Số lệnh |
|----|--------|-------|--------|---------|
| HPG | +334.8% | 49.5 | 24.3% | 109 |
| MWG | +162.6% | 48.9 | 24.7% | 92 |
| TCB | +143.6% | 56.2 | 21.1% | 48 |
| GAS | +137.1% | 45.4 | 27.8% | 97 |
| VCB | +97.6% | 51.1 | 17.0% | 47 |
| FPT | +68.3% | 47.7 | 17.8% | 44 |
| VHM | +43.1% | 42.6 | 38.5% | 61 |
| BID | −13.7% | 36.2 | 44.1% | 47 |
| VNM | −16.8% | 35.5 | 44.7% | 110 |
| MSN | −53.2% | 33.6 | 56.1% | 110 |

### 4.2 Ichimoku (TK cross + mây bull, ATR exit)

| Mã | Return | Win % | Max DD | Số lệnh |
|----|--------|-------|--------|---------|
| GAS | +91.0% | 59.3 | 8.4% | 27 |
| MWG | +80.1% | 63.0 | 11.7% | 27 |
| HPG | +47.4% | 50.0 | 20.8% | 30 |
| TCB | +36.0% | 61.1 | 7.9% | 18 |
| FPT | +20.4% | 50.0 | 8.4% | 14 |
| VHM | +13.3% | 36.4 | 9.9% | 22 |
| MSN | +11.6% | 45.8 | 13.2% | 24 |
| VNM | +6.6% | 41.4 | 21.5% | 29 |
| BID | −9.7% | 20.0 | 17.1% | 10 |
| VCB | −15.5% | 17.6 | 16.3% | 17 |

### 4.3 Confluence (MACD+RSI ∩ mây Ichimoku)

| Mã | Return | Win % | Max DD | Số lệnh |
|----|--------|-------|--------|---------|
| GAS | +82.0% | 60 | 13.2% | 25 |
| MWG | +59.3% | 50 | 14.8% | 38 |
| VHM | +57.4% | 62 | 10.8% | 21 |
| TCB | +56.6% | 62 | 7.8% | 16 |
| HPG | +38.3% | 46 | 22.2% | 39 |
| VCB | +32.6% | 67 | 6.1% | 12 |
| FPT | +12.1% | 42 | 6.3% | 19 |
| MSN | +7.1% | 42 | 17.4% | 24 |
| VNM | +4.0% | 41 | 16.9% | 32 |
| BID | −15.1% | 25 | 20.0% | 12 |

**Trung bình:** +33.4% · win 50% · DD 13.6% · **9/10 mã dương**

---

## 5. Cửa sổ 2022 → nay (sau chu kỳ tăng lãi suất)

Môi trường khó hơn (sideway / bear xen kẽ). Kết quả 1D ATR:

| Strategy | % mã lãi | Avg return | Med return | Win % | Avg DD |
|----------|----------|------------|------------|-------|--------|
| MACD+RSI | 60% (6/10) | +10.4% | +7.7% | 40 | 26.7% |
| Ichimoku | 70% (7/10) | +7.4% | +6.7% | **47** | **9.1%** |
| Confluence | 50% (5/10) | +6.4% | −1.1% | 45 | 9.5% |

→ Giai đoạn gần đây **Ichimoku 1D** vẫn là lựa chọn bảo thủ hơn (win cao, DD thấp). Confluence lọc chặt hơn nên ít lệnh / lợi nhuận trung bình thấp hơn trong cửa sổ này.

---

## 6. Biến thể botdown: TP 10% / SL 4% (1D, long-only)

| Mode | Avg return | Win % | % mã lãi | Ghi chú |
|------|------------|-------|----------|---------|
| Không EMA | +95.8% | 38% | 9/10 | Return cao, DD một số mã rất lớn (VNM ~62%) |
| **Có EMA 20/50** | +80.1% | 42% | 7/10 | Ít lệnh hơn, DD trung bình thấp hơn — **khuyến nghị nếu dùng % exit** |

Ví dụ VCB + EMA: **+27.4%**, 17 lệnh, win 41%, DD **8%** (vs hold +62%).

---

## 7. Lãi suất ngân hàng Việt Nam (NHNN)

Cập nhật file: `Trading-bot/vre/data/vietnam/interest_rates.csv`  
Snapshot tới **2026-08-01** (mức điều hành giữ từ **19/6/2023** — QĐ 1123/QĐ-NHNN):

| Chỉ tiêu | Mức (%/năm) | Ghi chú |
|----------|-------------|---------|
| Tái cấp vốn | **4.5** | Policy rate chính |
| Tái chiết khấu | **3.0** | |
| Cho vay qua đêm / bù trừ | **5.0** | |
| Trần TG không KH / < 1 tháng | **0.5** | QĐ 2411/QĐ-NHNN |
| Trần TG 1 – < 6 tháng | **4.75** | QTD/TCVM: 5.25 |
| TG ≥ 6 tháng | Thị trường | NH tự ấn định |

**Ý nghĩa cho cổ phiếu:** LS điều hành thấp và ổn định từ giữa 2023 → môi trường **risk-on** tương đối hỗ trợ định giá; vẫn cần lọc kỹ thuật vì cổ phiếu đơn lẻ phân hóa mạnh (MSN/BID yếu trong nhiều setup).

---

## 8. Kết luận vận hành

1. **Primary setup:** Confluence **1D** (MACD+RSI + mây Ichimoku) khi **1W** đang bull.  
2. **Nếu muốn đơn giản / bảo thủ:** chỉ **Ichimoku 1D** (ít lệnh, DD thấp).  
3. **Nếu muốn active hơn:** **MACD+RSI 1D** + EMA filter + TP/SL % cố định.  
4. **Tránh:** trade thuần **H1/H4** không có bias cao hơn.  
5. **Macro:** theo dõi nếu NHNN đổi lãi suất điều hành — đây là regime shift quan trọng.

---

## 9. File liên quan

| File | Nội dung |
|------|----------|
| `stock/vn_stock/data/screening/mtf_macd_ichimoku_report.json` | JSON đầy đủ (coverage, ranking, window 2022) |
| `stock/vn_stock/data/screening/mtf_macd_ichimoku_backtest.csv` | Toàn bộ kết quả mã × strategy × TF |
| `stock/vn_stock/data/screening/regime_strategy_mix_report.json` | Mix theo regime + CAGR |
| `stock/vn_stock/data/screening/regime_strategy_mix_cagr_matrix.csv` | Ma trận CAGR %/năm |
| `stock/vn_stock/data/screening/regime_strategy_mix_ann_simple_matrix.csv` | Ma trận lợi nhuận năm đơn giản |
| `stock/vn_stock/strategies/ichimoku.py` | Logic Ichimoku |
| `stock/vn_stock/scripts/run_mtf_macd_ichimoku.py` | Script crawl + so sánh |
| `stock/vn_stock/scripts/run_regime_strategy_mix.py` | Script mix regime |

Chạy lại:

```bash
cd stock
export PYTHONPATH="$PWD:$PWD/../Trading-bot"
.venv/bin/python -m vn_stock.scripts.run_mtf_macd_ichimoku --no-fetch
.venv/bin/python -m vn_stock.scripts.run_regime_strategy_mix
```

---

## 10. Mix strategy theo regime (up / side / down) + %/năm

### 10.1 Định nghĩa regime (1D, từng mã)

| Regime | Điều kiện | % số nến (TB 10 mã) |
|--------|-----------|---------------------|
| **Uptrend** | EMA20 > EMA50 và close > EMA50 | **49.3%** |
| **Sideways** | Không up cũng không down | **14.8%** |
| **Downtrend** | EMA20 < EMA50 và close < EMA50 | **35.9%** |

### 10.2 Các mix

| Mix | Uptrend | Sideways | Downtrend |
|-----|---------|----------|-----------|
| **mix_A** | MACD+RSI | Confluence | Không vào mới (+đóng nếu đang long) |
| **mix_B** | Ichimoku | MACD+RSI | Flat |
| **mix_C** | Confluence | Ichimoku | Flat |
| Standalone | Chỉ entry khi bar thuộc regime đó (cột regime) | | |

Exit chung: ATR SL 1.5× / TP 2.5×.

### 10.3 Ma trận **CAGR compound trung bình (%/năm)**

Cùng horizon full-sample từng mã (so cột công bằng). Ô regime = chỉ tính lệnh **vào** khi đang ở regime đó; mã 0 lệnh = 0%.

| Regime ↓ \\ Strategy → | macd_rsi | ichimoku | confluence | mix_A | mix_B | mix_C |
|------------------------|----------|----------|------------|-------|-------|-------|
| **uptrend** | **+2.36** | +2.15 | +2.22 | — | — | — |
| **sideways** | **+0.77** | +0.04 | +0.33 | — | — | — |
| **downtrend** | **+2.06** | 0.00* | −0.02 | — | — | — |
| **all** (cả chu kỳ) | **+5.16** | +2.19 | +2.50 | +2.55 | **+2.76** | +2.16 |

\*Ichimoku gần như không cho long khi đang downtrend (lọc mây) → ~0 lệnh.

### 10.4 Ma trận **lợi nhuận năm đơn giản** (total% ÷ số năm)

Dễ đọc hơn; không compound.

| Regime ↓ \\ Strategy → | macd_rsi | ichimoku | confluence | mix_A | mix_B | mix_C |
|------------------------|----------|----------|------------|-------|-------|-------|
| **uptrend** | **+3.24** | +2.82 | +2.70 | — | — | — |
| **sideways** | **+0.92** | +0.04 | +0.36 | — | — | — |
| **downtrend** | **+2.61** | 0.00 | −0.02 | — | — | — |
| **all** | **+8.69** | +2.88 | +3.09 | +3.50 | **+3.71** | +2.65 |

### 10.5 Kèm risk (hàng `all`)

| Strategy | CAGR %/y | Ann. simple %/y | Avg total ret | Win % | Avg max DD | % mã lãi |
|----------|----------|-----------------|---------------|-------|------------|----------|
| macd_rsi | **+5.16** | **+8.69** | +88.6% | 45 | **31.4%** | 70 |
| mix_B | +2.76 | +3.71 | +38.5% | 43 | 17.9% | 70 |
| mix_A | +2.55 | +3.50 | +40.5% | 45 | 18.2% | 70 |
| confluence | +2.50 | +3.09 | +33.4% | **50** | **13.6%** | **90** |
| ichimoku | +2.19 | +2.88 | +32.6% | 48 | 13.6% | 80 |
| mix_C | +2.16 | +2.65 | +27.0% | 47 | 14.3% | 80 |

### 10.6 Đọc kết quả mix

1. **CAGR thuần:** `macd_rsi` thắng mọi regime và cả chu kỳ — nhưng DD cao (~31%).
2. **Sideways:** edge mỏng; `macd_rsi` vẫn nhỉnh (+0.8%/y), Ichimoku gần như chết tín hiệu.
3. **Downtrend:** chỉ `macd_rsi` còn vào lệnh có ý nghĩa; Ichimoku/confluence gần như đứng ngoài (đúng thiết kế bảo thủ).
4. **Trong các mix:** `mix_B` (up→Ichimoku, side→MACD, down→flat) CAGR all tốt nhất trong nhóm mix (**+2.76%/y**), DD vừa phải hơn MACD thuần.
5. **Risk-adjusted / ổn định:** vẫn ưu tiên **confluence** hoặc **mix_C** (DD ~14%, win cao hơn).

**Gợi ý vận hành theo regime:**

| Regime | Ưu tiên lợi nhuận | Ưu tiên ổn định |
|--------|-------------------|-----------------|
| Uptrend | MACD+RSI | Confluence / Ichimoku |
| Sideways | MACD+RSI (size nhỏ) | Confluence hoặc đứng ngoài |
| Downtrend | MACD+RSI có SL chặt **hoặc cash** | Cash / không long mới |