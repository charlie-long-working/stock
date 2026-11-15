# Kiểm chứng nguồn (Mốc 0.5)

- Thời điểm chạy: **2026-11-15 17:20:58** (Asia/Ho_Chi_Minh)
- Máy: Mac local, Python 3.13.2, thư viện chuẩn `urllib`
- User-Agent: `daily-brief/0.1 (personal news reader; python-urllib)` (không giả lập trình duyệt)
- Mỗi URL: 1 GET, timeout 10 s, tối đa 1 lần retry cho lỗi mạng/5xx, giới hạn 2 MB.
- Không lưu nội dung bài. Chỉ ghi thống kê. Kết quả là ảnh chụp một thời điểm, không phải SLA.

Trạng thái: `ok` · `stale` (bài mới nhất > 48 h) · `empty` · `blocked` (401/403/429/451) · `not_found` · `not_feed` (trả HTML) · `error`.

## Nguồn tin (RSS)

| Nguồn | Loại | Tier | Trạng thái | HTTP | Số item | Có tóm tắt | Độ dài TB | Toàn văn | Bài mới nhất | Tuổi (h) | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| VnExpress – Thời sự | press | core | `ok` | 200 | 60 | 60/60 | 153 | không | 2026-11-15 13:48 | 3.5 |  |
| VnExpress – Kinh doanh | press | core | `ok` | 200 | 60 | 60/60 | 141 | không | 2026-11-15 13:30 | 3.8 |  |
| VnExpress – Thế giới | press | core | `ok` | 200 | 60 | 60/60 | 137 | không | 2026-11-15 16:12 | 1.1 |  |
| Báo Điện tử Chính phủ | official | core | `ok` | 200 | 50 | 50/50 | 250 | không | 2026-11-15 15:57 | 1.4 | ngày không có múi giờ (giả định giờ VN) |
| VnEconomy – Tin mới | press | core | `ok` | 200 | 50 | 50/50 | 244 | không | 2026-11-15 14:10 | 3.2 |  |
| VnEconomy – Chứng khoán | press | core | `ok` | 200 | 50 | 50/50 | 195 | không | 2026-11-15 10:29 | 6.9 |  |
| VnEconomy – Tài chính | press | core | `ok` | 200 | 50 | 50/50 | 245 | không | 2026-11-14 20:07 | 21.2 |  |
| CafeF – Thị trường chứng khoán | press | core | `ok` | 200 | 50 | 50/50 | 162 | không | 2026-11-15 15:18 | 2.0 |  |
| CafeF – Tài chính ngân hàng | press | core | `ok` | 200 | 50 | 50/50 | 241 | không | 2026-11-15 16:53 | 0.5 |  |
| CafeF – Doanh nghiệp | press | extended | `ok` | 200 | 50 | 50/50 | 198 | không | 2026-11-15 15:59 | 1.4 |  |
| Tin nhanh chứng khoán – Chứng khoán | press | core | `ok` | 200 | 50 | 50/50 | 406 | không | 2026-11-15 17:00 | 0.3 |  |
| VnEconomy – Kinh tế thế giới | press | core | `ok` | 200 | 50 | 50/50 | 191 | không | 2026-11-14 14:47 | 26.6 |  |
| Vietstock – Cổ phiếu | press | core | `blocked` | 403 | 0 | 0/0 | 0 | không | — | — | HTTP 403 (trang HTML – có thể là bot-challenge; không vượt) |
| Vietstock – Vĩ mô | press | core | `blocked` | 403 | 0 | 0/0 | 0 | không | — | — | HTTP 403 (trang HTML – có thể là bot-challenge; không vượt) |
| Vietstock – Vàng và kim loại quý | press | core | `blocked` | 403 | 0 | 0/0 | 0 | không | — | — | HTTP 403 (trang HTML – có thể là bot-challenge; không vượt) |
| Vietstock – Nhận định thị trường | press | core | `blocked` | 403 | 0 | 0/0 | 0 | không | — | — | HTTP 403 (trang HTML – có thể là bot-challenge; không vượt) |
| Vietstock (qua Google News RSS) | aggregator | core | `ok` | 200 | 35 | 32/35 | 68 | không | 2026-11-15 16:32 | 0.8 | description chỉ là link + tên báo → coi như chỉ có tiêu đề |
| Reuters (qua Google News RSS) | aggregator | core | `ok` | 200 | 100 | 100/100 | 73 | không | 2026-11-15 17:07 | 0.2 | description chỉ là link + tên báo → coi như chỉ có tiêu đề |
| AP News (qua Google News RSS) | aggregator | core | `ok` | 200 | 100 | 81/100 | 73 | không | 2026-11-15 17:15 | 0.1 | description chỉ là link + tên báo → coi như chỉ có tiêu đề |
| Tuổi Trẻ – Thời sự | press | extended | `ok` | 200 | 50 | 50/50 | 162 | không | 2026-11-15 15:58 | 1.4 | ngày không có múi giờ (giả định giờ VN) |
| Tuổi Trẻ – Kinh doanh | press | extended | `ok` | 200 | 50 | 50/50 | 175 | không | 2026-11-15 14:01 | 3.3 | ngày không có múi giờ (giả định giờ VN) |
| BBC – World | press | extended | `ok` | 200 | 21 | 21/21 | 112 | không | 2026-11-15 16:57 | 0.4 |  |
| BBC – Business | press | extended | `ok` | 200 | 57 | 57/57 | 101 | không | 2026-11-15 07:01 | 10.3 |  |
| BBC Tiếng Việt | press | extended | `ok` | 200 | 26 | 26/26 | 159 | không | 2026-11-15 15:16 | 2.1 |  |
| Financial Times – Home (tiêu đề) | press | extended | `ok` | 200 | 9 | 9/9 | 98 | không | 2026-11-15 12:00 | 5.3 |  |
| Bloomberg – Markets (feed không tài liệu hoá) | press | extended | `ok` | 200 | 17 | 17/17 | 375 | không | 2026-11-15 15:00 | 2.3 |  |

## Dữ liệu thị trường

### Vietcombank – Tỷ giá (XML công khai)
- Trạng thái: `ok` · HTTP 200 · 0.66s · 
- `DateTime` trong XML: 11/15/2026 5:13:31 PM · số ngoại tệ: 20
- USD: Mua 25,500.00 / Chuyển khoản 25,530.00 / Bán 25,910.00 (VND, giá niêm yết của VCB)

### SJC – Giá vàng (XML, endpoint đang dùng ở precious-metals)
- Trạng thái: `not_found` · HTTP 404 · 0.41s · HTTP 404
- Số dòng có buy/sell: 0 · updated: — · unit: —
- Loại vàng xuất hiện: —
- Có dòng vàng nhẫn: không thấy

