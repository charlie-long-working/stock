# Phân tích cơ bản — cổ phiếu ngành Bất động sản

*Dữ liệu: BCTC đã tải trong `fundamentals/` (kỳ mới nhất theo quý 4/năm gần nhất). Chỉ số từ bảng cân đối + ratios vnstock.*

## Cách đọc nhanh

| Khái niệm | Ý nghĩa |
|-----------|---------|
| **Hàng tồn / Tổng tài sản (%)** | Tỷ trọng hàng tồn kho (dự án/BĐS dở dang…) trên tổng tài sản — BĐS thường cao; quá cao + nợ lớn + P/B thấp có thể là **rủi ro thanh khoản**. |
| **P/B** | Giá / BVPS; **< 1** = thị trường định giá thấp hơn sổ sách (có thể rẻ hoặc thị trường lo ngại). |
| **Điểm tiềm lực (0–100)** | Heuristic nội bộ: thanh khoản ngắn hạn (Current ratio), ROE, mức **Debt/Equity** (BĐS thường nợ cao nên chỉ mang tính **so sánh tương đối** trong nhóm). |

---

## Mã thỏa đồng thời: tiềm lực tốt + hàng tồn cao (so trung vị nhóm) + P/B thấp

Theo bộ lọc tự động (P/B ≤ ~1.08, tồn kho/TA ≥ trung vị nhóm ~29%, điểm tiềm lực ≥ 35 & Current ratio ≥ 1):

| Mã      | Nhận xét ngắn                                                                                                                                                                                                                |
| ---------| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **IJC** | **P/B ~0,79**, tồn kho/TA ~**36%**, **D/E thấp** (~0,28), **Current ratio rất cao** — trong nhóm BĐS đang xét, đây là mã **cân bằng nhất** giữa định giá thấp, tồn kho đáng kể và chỉ số nợ/thanh khoản tương đối lành mạnh. |

*Không có mã thứ hai thỏa cùng lúc cả ba điều kiện chặt; nhiều mã P/B thấp nhưng nợ cao hoặc điểm tiềm lực thấp hơn.*

---

## Nhóm P/B thấp + hàng tồn lớn (đáng chú ý — cần đọc thêm rủi ro)

| Mã | P/B (gần đúng) | Tồn kho / TA | Ghi chú |
|----|-----------------|-------------|---------|
| **NVL** | ~0,66 | **~62%** | P/B rất thấp, tồn kho chi phối bảng cân đối; **D/E ~3,2** — đòn bẩy tài chính cao, cần theo dõi nợ, dòng tiền, triển khai dự án. |
| **CKG** | ~0,74 | **~68%** | Tồn kho/TA cao nhất nhóm; P/B thấp; điểm tiềm lực trung bình — rủi ro tập trung vào **thanh khoản hàng tồn**. |
| **DXG** | ~1,10 | **~41%** | P/B tương đối thấp trong nhóm “bluechip” BĐS, tồn kho/TA cao hơn trung vị. |
| **SCR** | ~0,48 | ~27% | P/B thấp; tồn kho/TA vừa phải; điểm tiềm lực vừa — kiểm tra kỹ chất lượng tài sản và nợ. |

---

## Tiềm lực tài chính tương đối tốt (điểm heuristic cao trong nhóm)

Ưu tiên xem **Current ratio**, **D/E**, **ROE** kết hợp (không chỉ P/B):

1. **IJC** — điểm cao nhất; D/E thấp; CR rất tốt.  
2. **DLG** — ROE cao trong dữ liệu snapshot; **Current ratio < 1** → thanh khoản ngắn hạn cần lưu ý.  
3. **L14, CEO, NLG, TCH, DIG** — cân bằng tương đối giữa các chỉ số (từng mã cần đọc chi tiết BCTC).  
4. **VRE** — tồn kho/TA rất thấp (mô hình khác — bán lẻ/cho thuê), không so sánh “hàng tồn nhiều” kiểu chủ đầu tư dự án.

---

## P/B rất thấp — cảnh báo

| Mã | P/B | Ghi chú |
|----|-----|---------|
| **HQC** | ~0,28 | Cực thấp — thường phản ánh **rủi ro** hoặc thanh khoản CP; không tự suy là “rẻ tốt” nếu chưa phân tích sâu. |

---

## File dữ liệu chi tiết

- `bd_san_fundamental_screen.csv` — bảng đầy đủ từng mã  
- `bd_san_fundamental_screen.json` — cùng nội dung dạng JSON  

*Bạn nên đối chiếu thêm: báo cáo lưu chuyển tiền tệ, nợ đến hạn, cơ cấu hàng tởn (dự án nào), và kịch bản thị trường BĐS — phân tích này chỉ hỗ trợ sàng lọc định lượng ban đầu.*
