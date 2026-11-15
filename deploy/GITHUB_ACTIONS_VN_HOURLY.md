> **LƯU TRỮ (15/11/2026):** Workflow này đã tắt — vnstock không còn trên PyPI nên GitHub Actions không cài được. Bot hourly hiện chạy bằng launchd trên Mac: xem `README_hourly_vn.md`. Nội dung dưới đây chỉ để tham khảo, nhiều chỗ đã cũ.

# Chạy VN hourly trên GitHub Actions

## Cách khuyến nghị: repo `stock` trên GitHub

`stock/` hiện **chưa** là git repo. Cần đẩy lên GitHub rồi bật Actions.

### 1. Tạo repo & push

```bash
cd /Users/namnguyen/Documents/Cursor/stock
git init
git add .
# Đừng commit .env (đã có trong .gitignore nếu có; nếu chưa thì thêm)
echo ".env" >> .gitignore
echo ".venv/" >> .gitignore
echo "vn_stock/data/ohlcv/" >> .gitignore   # optional — cache Actions sẽ giữ
git add .gitignore
git commit -m "chore: stock package + VN hourly Actions"
# Tạo repo trống trên GitHub (private), rồi:
git branch -M main
git remote add origin git@github.com:charlie-long-working/stock.git   # sửa user/repo
git push -u origin main
```

### 2. Secrets (repo **stock**)

Settings → Secrets and variables → Actions:

| Secret | Giá trị |
|--------|---------|
| `TELEGRAM_BOT_TOKEN` | token bot |
| `TELEGRAM_CHAT_ID` | chat id |
| `TB_CHECKOUT_TOKEN` | GitHub PAT (scope `repo`) để clone **Trading-bot** nếu private |

Optional Variables:

| Variable | Mặc định |
|----------|----------|
| `TB_REPO` | `charlie-long-working/trading-bot` |

### 3. Workflow có sẵn

File: `.github/workflows/vn-hourly-telegram.yml`

- **Cron:** `5 1-7 * * 1-5` UTC = **T2–T6 8:05–14:05 ICT**
- Checkout `stock` + `Trading-bot`
- Chạy `python -m vn_stock.scripts.run_hourly_vn_session`
- Cache OHLCV + dedupe; upload artifact snapshot

### 4. Chạy thử tay

GitHub → Actions → **VN Hourly Telegram** → Run workflow  
- `force=true` (ngoài giờ vẫn chạy)  
- `dry_run=true` lần đầu để xem log không spam Telegram

---

## Cách 2: trigger từ repo **Trading-bot**

File đã thêm: `Trading-bot/.github/workflows/vn-hourly-telegram.yml`

Secrets trên **trading-bot**:

| Secret | |
|--------|--|
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | như trên |
| `STOCK_CHECKOUT_TOKEN` | PAT đọc repo stock |

Variable optional: `STOCK_REPO` = `charlie-long-working/stock`

Cần **push workflow này** lên `trading-bot` và repo `stock` đã tồn tại trên GitHub.

---

## Lịch UTC ↔ ICT

| ICT | UTC |
|-----|-----|
| 08:05 | 01:05 |
| 09:05 | 02:05 |
| … | … |
| 14:05 | 07:05 |

Cron: `5 1-7 * * 1-5`

---

## Lưu ý

- Sau mỗi run, Actions **commit + push** `vn_stock/data/ohlcv/` (+ snapshot/dedupe) vào chính repo → lần sau chỉ fetch incremental (CSV trên Git = “DB file”).
- Tắt khi Run workflow: `commit_data=false`.
- Repo sẽ lớn dần; public repo thì ai cũng xem được CSV.
- `vnstock` rate-limit: tăng `--delay` hoặc giảm `--symbols`.
- Không commit `.env` — chỉ dùng Secrets.
- Artifact `hourly-vn-snapshot` giữ 14 ngày để tải JSON về xem.
