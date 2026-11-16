# Backtest setup cổ phiếu VN — 2026-11-16

- 97 mã Stock Intelligence, giá điều chỉnh cổ tức 2012 → nay; chi phí phí mua 0.15%, phí bán 0.15%, thuế 0.10%, trượt giá 0.10%/chiều; T+2.
- Chọn tham số chỉ trên train (< 2022-01-01) + validate; ngoài mẫu từ 2024-01-01. Số cấu hình đã thử: **48**.
- **Thiên lệch sống sót:** danh sách 100 mã của hôm nay áp cho quá khứ → kết quả có xu hướng lạc quan.

## Kết luận

| Setup | Kết luận | Ngoài mẫu | Train | Validate PF |
|---|---|---|---|---|
| Phá nền giá đi ngang | **WATCH** | 135 lệnh, win 31%, PF 1.074, TB +0.24% | 118 lệnh, PF 1.969, TB +2.70% | 0.838 |
| Phân kỳ dương MACD/RSI | **WATCH** | 33 lệnh, win 27%, PF 1.799, TB +1.83% | 34 lệnh, PF 1.745, TB +1.82% | 0.0 |
| MACD+RSI ATR (đã hạ xuống theo dõi) | **OFF** | 2240 lệnh, win 33%, PF 0.778, TB -0.64% | 1961 lệnh, PF 1.105, TB +0.27% | 0.947 |
| MACD signed — chỉ MUA (đang chạy live) | **OFF** | 1346 lệnh, win 30%, PF 0.723, TB -0.81% | 1657 lệnh, PF 1.39, TB +0.92% | 0.631 |

SHIP = gửi lệnh MUA có entry/SL/TP và vào sổ lệnh; WATCH = chỉ danh sách theo dõi; OFF = không gửi.

## Phá nền giá đi ngang

Cấu hình (`base_breakout-236fc358`, chọn bằng dự phòng: không cấu hình nào qua bước chọn train/validate):
```json
{"id": "base_breakout-236fc358", "setup": "base_breakout", "params": {"bbw_rank_max": 0.6, "drift_frac": 1.0, "dryup_max": 1.0, "height_atr_k": 1.8, "max_height": [[20, 0.18], [40, 0.22], [60, 0.27]], "rvol_min": 2.0}, "exit": {"mode": "B", "tp_r": 2.0, "time_stop": 40, "be_r": 1.0, "trail_atr": 3.0, "use_breakdown": true, "use_bear_div": false, "use_signal_exit": false}, "regime_filter": false, "trend": "full"}
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

- Bootstrap cận dưới 97,5% TB/lệnh: -1.57% · random p90: +1.90%
- Danh mục (≤5 vị thế, 1% rủi ro): 95 lệnh nhận, CAGR -1.85%, max DD -15.79%
- Tập trung: mã lớn nhất 1.424 tổng lãi, PF bỏ top 3: 0.762
- Theo năm (TB/lệnh): {'2024': 0.01859, '2025': 0.00044, '2026': -0.04059}

## Phân kỳ dương MACD/RSI

Cấu hình (`div_bull-8bc79576`, chọn bằng dự phòng: không cấu hình nào qua bước chọn train/validate):
```json
{"id": "div_bull-8bc79576", "setup": "div_bull", "params": {"require_sma200": false, "trigger": "immediate"}, "exit": {"mode": "B", "tp_r": 2.0, "time_stop": 40, "be_r": 1.0, "trail_atr": 3.0, "use_breakdown": true, "use_bear_div": true, "use_signal_exit": false}, "regime_filter": false, "trend": "full"}
```

| Ngưỡng | Đạt |
|---|---|
| trades>=60 | ✗ |
| accepted>=40 | ✗ |
| pf>=1.2 | ✓ |
| bootstrap_lb>0 | ✓ |
| beats_random_p90 | ✗ |
| pf_ex_top3>=1 | ✗ |
| symbol_share<=25% | ✗ |
| validate_pf>=1 | ✗ |
| oos_years_positive>=2 | ✓ |
| portfolio_dd<=20% | ✓ |
| pf_2x_costs>=1.05 | ✓ |

- Bootstrap cận dưới 97,5% TB/lệnh: +0.55% · random p90: +2.86%
- Danh mục (≤5 vị thế, 1% rủi ro): 33 lệnh nhận, CAGR +2.39%, max DD -5.41%
- Tập trung: mã lớn nhất 1.479 tổng lãi, PF bỏ top 3: 0.311
- Theo năm (TB/lệnh): {'2024': -0.01088, '2025': 0.06446, '2026': 0.01145}

## MACD+RSI ATR (đã hạ xuống theo dõi)

Cấu hình (`macd_rsi_atr-292a6b8e`, chọn bằng đối chứng — cấu hình live):
```json
{"id": "macd_rsi_atr-292a6b8e", "setup": "macd_rsi_atr", "params": {}, "exit": {"mode": "A", "tp_r": 1.6666666666666667, "time_stop": 60, "be_r": 1.0, "trail_atr": 3.0, "use_breakdown": false, "use_bear_div": false, "use_signal_exit": true}, "regime_filter": false, "trend": "none"}
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
- Danh mục (≤5 vị thế, 1% rủi ro): 411 lệnh nhận, CAGR -24.53%, max DD -55.34%
- Tập trung: mã lớn nhất None tổng lãi, PF bỏ top 3: 0.756
- Theo năm (TB/lệnh): {'2024': -0.00839, '2025': -0.00053, '2026': -0.0103}

## MACD signed — chỉ MUA (đang chạy live)

Cấu hình (`macd_signed-4198415f`, chọn bằng đối chứng — cấu hình live):
```json
{"id": "macd_signed-4198415f", "setup": "macd_signed", "params": {"allow_short": false}, "exit": {"mode": "A", "tp_r": 2.0, "time_stop": 30, "be_r": 1.0, "trail_atr": 3.0, "use_breakdown": false, "use_bear_div": false, "use_signal_exit": true}, "regime_filter": false, "trend": "none"}
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

- Bootstrap cận dưới 97,5% TB/lệnh: -1.40% · random p90: +0.29%
- Danh mục (≤5 vị thế, 1% rủi ro): 398 lệnh nhận, CAGR -16.91%, max DD -42.60%
- Tập trung: mã lớn nhất None tổng lãi, PF bỏ top 3: 0.685
- Theo năm (TB/lệnh): {'2024': -0.00912, '2025': -0.00041, '2026': -0.01991}

## Toàn bộ lưới (train / validate)

| Cấu hình | Train n | Train PF | Train TB | Validate n | Validate PF |
|---|---|---|---|---|---|
| `base_breakout-948e2575` | 70 | 0.77 | -0.77% | 21 | 0.774 |
| `base_breakout-8f617a7a` | 63 | 0.787 | -0.71% | 20 | 0.854 |
| `base_breakout-7a612a13` | 66 | 0.737 | -0.92% | 15 | 0.568 |
| `base_breakout-23e3ab9d` | 59 | 0.75 | -0.87% | 14 | 0.644 |
| `base_breakout-cd949db0` | 69 | 0.68 | -0.99% | 21 | 1.109 |
| `base_breakout-6437656b` | 62 | 0.765 | -0.71% | 20 | 1.227 |
| `base_breakout-99449294` | 65 | 0.648 | -1.13% | 15 | 0.526 |
| `base_breakout-99c04973` | 58 | 0.73 | -0.85% | 14 | 0.599 |
| `base_breakout-be3d82bb` | 48 | 0.621 | -1.38% | 15 | 0.573 |
| `base_breakout-95b09233` | 43 | 0.631 | -1.34% | 15 | 0.573 |
| `base_breakout-ff8a24d0` | 46 | 0.611 | -1.48% | 11 | 0.456 |
| `base_breakout-99606142` | 41 | 0.62 | -1.44% | 11 | 0.456 |
| `base_breakout-836bb294` | 48 | 0.592 | -1.41% | 15 | 0.156 |
| `base_breakout-869ce523` | 43 | 0.66 | -1.16% | 15 | 0.156 |
| `base_breakout-48103a36` | 46 | 0.551 | -1.62% | 11 | 0.063 |
| `base_breakout-5da80e48` | 41 | 0.614 | -1.37% | 11 | 0.063 |
| `base_breakout-c9e691fe` | 196 | 1.077 | +0.25% | 85 | 0.715 |
| `base_breakout-ddce4d1a` | 193 | 1.103 | +0.33% | 85 | 0.715 |
| `base_breakout-394c4319` | 186 | 1.072 | +0.24% | 67 | 0.668 |
| `base_breakout-ba5428c7` | 183 | 1.099 | +0.32% | 67 | 0.668 |
| `base_breakout-fec0f6c4` | 194 | 1.666 | +1.99% | 81 | 0.979 |
| `base_breakout-ef14da12` | 191 | 1.71 | +2.10% | 81 | 0.979 |
| `base_breakout-8d009044` | 184 | 1.655 | +2.02% | 65 | 0.724 |
| `base_breakout-1f6af855` | 181 | 1.7 | +2.14% | 65 | 0.724 |
| `base_breakout-daa61a47` | 121 | 1.164 | +0.50% | 56 | 0.924 |
| `base_breakout-a29ab227` | 119 | 1.194 | +0.58% | 56 | 0.924 |
| `base_breakout-c6987376` | 117 | 1.165 | +0.52% | 44 | 0.862 |
| `base_breakout-752493c0` | 115 | 1.195 | +0.60% | 44 | 0.862 |
| `base_breakout-c9943385` | 120 | 1.914 | +2.58% | 53 | 0.838 |
| `base_breakout-236fc358` | 118 | 1.969 | +2.70% | 53 | 0.838 |
| `base_breakout-98e5b6c6` | 116 | 1.858 | +2.50% | 43 | 0.62 |
| `base_breakout-4e3cba90` | 114 | 1.911 | +2.62% | 43 | 0.62 |
| `div_bull-9877c90e` | 80 | 0.936 | -0.19% | 26 | 0.214 |
| `div_bull-27d9e2f4` | 31 | 1.358 | +0.92% | 6 | 0.0 |
| `div_bull-c21306f7` | 80 | 1.179 | +0.59% | 26 | 0.071 |
| `div_bull-7d58fdc8` | 31 | 1.609 | +1.58% | 6 | 0.0 |
| `div_bull-15ba5694` | 199 | 0.856 | -0.40% | 113 | 0.748 |
| `div_bull-95aa2b95` | 34 | 1.36 | +0.86% | 7 | 0.0 |
| `div_bull-a687c3da` | 196 | 0.949 | -0.17% | 112 | 1.102 |
| `div_bull-8bc79576` | 34 | 1.745 | +1.82% | 7 | 0.0 |
| `div_bull-8b33d33e` | 23 | 0.833 | -0.46% | 11 | 0.359 |
| `div_bull-96633ae7` | 17 | 0.615 | -1.04% | 3 | 0.0 |
| `div_bull-117cbdc1` | 23 | 0.402 | -1.66% | 11 | 0.43 |
| `div_bull-3a75ab73` | 17 | 0.414 | -1.51% | 3 | 0.0 |
| `div_bull-e69436d7` | 47 | 0.719 | -0.79% | 32 | 0.541 |
| `div_bull-0548ca1b` | 17 | 0.615 | -1.04% | 4 | 0.0 |
| `div_bull-f02b8632` | 47 | 0.617 | -1.17% | 32 | 0.822 |
| `div_bull-ad99383c` | 17 | 0.414 | -1.51% | 4 | 0.0 |
| `macd_rsi_atr-292a6b8e` | 1961 | 1.105 | +0.27% | 1405 | 0.947 |
| `macd_signed-4198415f` | 1657 | 1.39 | +0.92% | 898 | 0.631 |
| `macd_rsi_atr-8960d120` | 1081 | 1.102 | +0.25% | 538 | 0.675 |
| `macd_signed-2c14ff32` | 1534 | 1.433 | +1.01% | 736 | 0.573 |

Không phải lời khuyên đầu tư.
