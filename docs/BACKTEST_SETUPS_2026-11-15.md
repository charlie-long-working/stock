# Backtest setup cổ phiếu VN — 2026-11-15

- 97 mã Stock Intelligence, giá điều chỉnh cổ tức 2012 → nay; chi phí phí mua 0.15%, phí bán 0.15%, thuế 0.10%, trượt giá 0.10%/chiều; T+2.
- Chọn tham số chỉ trên train (< 2022-01-01) + validate; ngoài mẫu từ 2024-01-01. Số cấu hình đã thử: **24**.
- **Thiên lệch sống sót:** danh sách 100 mã của hôm nay áp cho quá khứ → kết quả có xu hướng lạc quan.

## Kết luận

| Setup | Kết luận | Ngoài mẫu | Train | Validate PF |
|---|---|---|---|---|
| Phá nền giá đi ngang | **WATCH** | 139 lệnh, win 31%, PF 1.049, TB +0.16% | 120 lệnh, PF 1.914, TB +2.58% | 0.838 |
| Phân kỳ dương MACD/RSI | **OFF** | 109 lệnh, win 25%, PF 0.739, TB -0.90% | 80 lệnh, PF 1.179, TB +0.59% | 0.071 |
| MACD+RSI ATR (đang chạy live) | **OFF** | 2235 lệnh, win 33%, PF 0.78, TB -0.63% | 1961 lệnh, PF 1.105, TB +0.27% | 0.947 |

SHIP = gửi lệnh MUA có entry/SL/TP và vào sổ lệnh; WATCH = chỉ danh sách theo dõi; OFF = không gửi.

## Phá nền giá đi ngang

Cấu hình (`base_breakout-c9943385`, chọn bằng dự phòng: không cấu hình nào qua bước chọn train/validate):
```json
{"id": "base_breakout-c9943385", "setup": "base_breakout", "params": {"bbw_rank_max": 0.6, "drift_frac": 1.0, "dryup_max": 1.0, "height_atr_k": 1.8, "max_height": [[20, 0.18], [40, 0.22], [60, 0.27]], "rvol_min": 2.0}, "exit": {"mode": "B", "tp_r": 2.0, "time_stop": 40, "be_r": 1.0, "trail_atr": 3.0, "use_breakdown": true, "use_bear_div": false, "use_signal_exit": false}, "regime_filter": false}
```

| Ngưỡng | Đạt |
|---|---|
| trades>=60 | ✓ |
| accepted>=40 | ✓ |
| pf>=1.2 | ✗ |
| bootstrap_lb>0 | ✗ |
| beats_random_p90 | ✗ |
| pf_ex_top3>=1 | ✗ |
| symbol_share<=25% | ✗ |
| validate_pf>=1 | ✗ |
| oos_years_positive>=2 | ✓ |
| portfolio_dd<=20% | ✓ |
| pf_2x_costs>=1.05 | ✗ |

- Bootstrap cận dưới 97,5% TB/lệnh: -1.80% · random p90: +1.74%
- Danh mục (≤5 vị thế, 1% rủi ro): 97 lệnh nhận, CAGR -1.85%, max DD -15.80%
- Tập trung: mã lớn nhất 2.106 tổng lãi, PF bỏ top 3: 0.746
- Theo năm (TB/lệnh): {'2024': 0.0171, '2025': 0.00044, '2026': -0.03683}

## Phân kỳ dương MACD/RSI

Cấu hình (`div_bull-c21306f7`, chọn bằng dự phòng: không cấu hình nào qua bước chọn train/validate):
```json
{"id": "div_bull-c21306f7", "setup": "div_bull", "params": {"require_sma200": true, "trigger": "immediate"}, "exit": {"mode": "B", "tp_r": 2.0, "time_stop": 40, "be_r": 1.0, "trail_atr": 3.0, "use_breakdown": true, "use_bear_div": true, "use_signal_exit": false}, "regime_filter": false}
```

| Ngưỡng | Đạt |
|---|---|
| trades>=60 | ✓ |
| accepted>=40 | ✓ |
| pf>=1.2 | ✗ |
| bootstrap_lb>0 | ✗ |
| beats_random_p90 | ✗ |
| pf_ex_top3>=1 | ✗ |
| symbol_share<=25% | ✗ |
| validate_pf>=1 | ✗ |
| oos_years_positive>=2 | ✗ |
| portfolio_dd<=20% | ✓ |
| pf_2x_costs>=1.05 | ✗ |

- Bootstrap cận dưới 97,5% TB/lệnh: -3.00% · random p90: +1.69%
- Danh mục (≤5 vị thế, 1% rủi ro): 74 lệnh nhận, CAGR +0.31%, max DD -11.20%
- Tập trung: mã lớn nhất None tổng lãi, PF bỏ top 3: 0.389
- Theo năm (TB/lệnh): {'2024': -0.00999, '2025': -0.00088, '2026': -0.02083}

## MACD+RSI ATR (đang chạy live)

Cấu hình (`macd_rsi_atr-292a6b8e`, chọn bằng đối chứng — cấu hình đang chạy live):
```json
{"id": "macd_rsi_atr-292a6b8e", "setup": "macd_rsi_atr", "params": {}, "exit": {"mode": "A", "tp_r": 1.6666666666666667, "time_stop": 60, "be_r": 1.0, "trail_atr": 3.0, "use_breakdown": false, "use_bear_div": false, "use_signal_exit": true}, "regime_filter": false}
```

| Ngưỡng | Đạt |
|---|---|
| trades>=60 | ✓ |
| accepted>=40 | ✓ |
| pf>=1.2 | ✗ |
| bootstrap_lb>0 | ✗ |
| beats_random_p90 | ✗ |
| pf_ex_top3>=1 | ✗ |
| symbol_share<=25% | ✗ |
| validate_pf>=1 | ✗ |
| oos_years_positive>=2 | ✗ |
| portfolio_dd<=20% | ✗ |
| pf_2x_costs>=1.05 | ✗ |

- Bootstrap cận dưới 97,5% TB/lệnh: -1.12% · random p90: -0.27%
- Danh mục (≤5 vị thế, 1% rủi ro): 407 lệnh nhận, CAGR -23.80%, max DD -54.90%
- Tập trung: mã lớn nhất None tổng lãi, PF bỏ top 3: 0.758
- Theo năm (TB/lệnh): {'2024': -0.00839, '2025': -0.00053, '2026': -0.0101}

## Toàn bộ lưới (train / validate)

| Cấu hình | Train n | Train PF | Train TB | Validate n | Validate PF |
|---|---|---|---|---|---|
| `base_breakout-948e2575` | 70 | 0.77 | -0.77% | 21 | 0.774 |
| `base_breakout-7a612a13` | 66 | 0.737 | -0.92% | 15 | 0.568 |
| `base_breakout-cd949db0` | 69 | 0.68 | -0.99% | 21 | 1.109 |
| `base_breakout-99449294` | 65 | 0.648 | -1.13% | 15 | 0.526 |
| `base_breakout-be3d82bb` | 48 | 0.621 | -1.38% | 15 | 0.573 |
| `base_breakout-ff8a24d0` | 46 | 0.611 | -1.48% | 11 | 0.456 |
| `base_breakout-836bb294` | 48 | 0.592 | -1.41% | 15 | 0.156 |
| `base_breakout-48103a36` | 46 | 0.551 | -1.62% | 11 | 0.063 |
| `base_breakout-c9e691fe` | 196 | 1.077 | +0.25% | 85 | 0.715 |
| `base_breakout-394c4319` | 186 | 1.072 | +0.24% | 67 | 0.668 |
| `base_breakout-fec0f6c4` | 194 | 1.666 | +1.99% | 81 | 0.979 |
| `base_breakout-8d009044` | 184 | 1.655 | +2.02% | 65 | 0.724 |
| `base_breakout-daa61a47` | 121 | 1.164 | +0.50% | 56 | 0.924 |
| `base_breakout-c6987376` | 117 | 1.165 | +0.52% | 44 | 0.862 |
| `base_breakout-c9943385` | 120 | 1.914 | +2.58% | 53 | 0.838 |
| `base_breakout-98e5b6c6` | 116 | 1.858 | +2.50% | 43 | 0.62 |
| `div_bull-9877c90e` | 80 | 0.936 | -0.19% | 26 | 0.214 |
| `div_bull-c21306f7` | 80 | 1.179 | +0.59% | 26 | 0.071 |
| `div_bull-15ba5694` | 199 | 0.856 | -0.40% | 113 | 0.748 |
| `div_bull-a687c3da` | 196 | 0.949 | -0.17% | 112 | 1.102 |
| `div_bull-8b33d33e` | 23 | 0.833 | -0.46% | 11 | 0.359 |
| `div_bull-117cbdc1` | 23 | 0.402 | -1.66% | 11 | 0.43 |
| `div_bull-e69436d7` | 47 | 0.719 | -0.79% | 32 | 0.541 |
| `div_bull-f02b8632` | 47 | 0.617 | -1.17% | 32 | 0.822 |
| `macd_rsi_atr-292a6b8e` | 1961 | 1.105 | +0.27% | 1405 | 0.947 |

Không phải lời khuyên đầu tư.
