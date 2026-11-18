---
name: daily-brief
description: >-
  Personal Vietnamese news/market brief bot in daily-brief/ (Telegram bot
  @nam_daily_brief_bot via launchd local.daily-brief.bot, RSS sources.toml,
  SQLite dedupe, scheduled 08:15 / 16:30 briefs, /brief /stock /gold /status,
  optional Claude CLI writing with validator, static dashboard site/index.html with news,
  BTC/ETH, VN stocks by sector, top 100, gold/silver). Use when the user mentions bản tin
  sáng/chiều, daily brief, nguồn tin RSS, sources.toml, bot tin tức, /brief, trang tĩnh,
  bảng tin thị trường, dashboard site, or
  edits daily-brief — not for the Vietstock news digest of the stock repo
  (vn-stock), trading signals (vn-stock, precious-metals, trading-bot).
---

# daily-brief (bot bản tin cá nhân)

Folder: `Documents/Cursor/daily-brief` (git init, **chưa có commit**, chưa có remote).
Bot riêng `@nam_daily_brief_bot` — khác bot cảnh báo giao dịch. **Không bao giờ** đưa tín hiệu mua/bán.

## Agent rules

1. Python: `../stock/.venv/bin/python` (không có venv riêng). `PYTHONPATH=.` từ `daily-brief/`.
2. Lệnh CLI mặc định chỉ in; chỉ thêm `--send` khi user bảo gửi.
3. Bot đang chạy dưới launchd → đổi code/config xong: `scripts/botctl.sh restart`. Không chạy `python -m brief bot` song song (409).
4. Không vượt chặn bot của nguồn tin (UA trung thực trong `brief/http.py`). Nguồn 403 → tắt `enabled = false` và thay bằng Google News `site:` như `gnews_vietstock`.
5. Không đổi tên import từ anh em: `vn_stock.data_loaders.vn_ohlcv`, `precious.universe`.
6. Chạy test sau khi sửa: `../stock/.venv/bin/python -m unittest discover -s tests -t .` (~50 test, gồm `tests/test_ai_brief.py`).

## Cách hoạt động

- `brief/bot.py`: long-poll Telegram, chỉ trả lời `chat_id` cấu hình, bỏ lệnh cũ > 15 phút. Lệnh: `/start /help /brief [full] /stock [refresh] /gold [refresh] /status`.
- `brief/schedule.py` (trong process bot): 08:15 tin + vàng; 16:30 tin + chứng khoán (nếu có phiên) + vàng. Trễ > 20 phút ghi "gửi bù"; thử lại 3 lần cách 10 phút.
- `brief/news.py`: RSS → SQLite `var/brief.db`, dedupe URL + trùng tiêu đề ≥ 0.5, chia mục theo nguồn/từ khoá. `compose.py`: tin từ lần gửi trước, bỏ URL đã gửi 48h.
- `brief/market.py`: giá cổ phiếu (vn_stock + vnstock price board), vàng (GC=F, Vietcombank XML, VND=X), cache 10 phút.
- `brief/ai.py`: `[ai] enabled = true` (16/11). `find_cli` tìm `claude` trên PATH → ~/.local/bin → bản đi kèm Claude Desktop (`~/Library/Application Support/Claude/claude-code/<ver>/…/claude`). Đăng nhập bằng `CLAUDE_CODE_OAUTH_TOKEN` (hoặc `ANTHROPIC_API_KEY`) trong `.env`; chưa có → template, không lỗi. Gọi gọn: `--system-prompt` (= `prompts/brief_vi.md`), `--tools ""`, không MCP/skill/settings, cwd `var/ai-cwd`, `--effort low`, JSON → usage ở `runs/*/bot-*/ai_usage.json` + kv `ai_last_usage`. `validate()` + `salvage()` (bỏ dòng lỗi, không gọi lại). Hướng dẫn: `docs/AI_TOM_TAT.md`.
- `brief/article.py`: sapo + đoạn đầu bài CafeF/VnExpress cho tin đã chọn (≤ 900 ký tự), cache bảng `articles` (mỗi URL tải 1 lần).

## Map

| Path | Role |
|------|------|
| `brief/cli.py` | `python -m brief <cmd>` |
| `brief/{bot,schedule,service,news,compose,market,ai,db,telegram_api,config,http,check_sources}.py` | Xem mục trên |
| `brief/prompts/brief_vi.md` | Prompt AI (10 luật) |
| `config/sources.toml` | Nguồn tin `[[source]]`: `id, name, kind, tier, format, url, enabled` |
| `config/settings.toml` | telegram, brief, schedule, watchlist, market, ai |
| `docs/source_check.md` | Kết quả `check-sources --write` |
| `scripts/botctl.sh` | `install|uninstall|start|stop|restart|status|logs [n]` |
| `var/brief.db`, `var/logs/bot.log` | DB (giữ 30 ngày), log xoay vòng — log thật ở đây, không phải `~/Library/Logs/daily-brief/bot.out` |
| `runs/<ngày>/` | Evidence + bản AI mỗi lần chạy |

## Commands

```bash
cd /Users/namnguyen/Documents/Cursor/daily-brief
PY=../stock/.venv/bin/python
$PY -m brief brief [--full] [--send]
$PY -m brief stock|gold [--refresh] [--send]
$PY -m brief status
$PY -m brief check-sources --write [--tier core|extended]
$PY -m brief evidence [--full]
$PY -m brief send-ai runs/<ngày>/manual-*/ --dry-run
scripts/botctl.sh status ; scripts/botctl.sh logs 50 ; scripts/botctl.sh restart
# Máy khác (VPS/mini PC) có gọi được mọi nguồn của các bot không – chỉ stdlib, chép 1 file là chạy:
$PY scripts/check_vps.py --no-ip --save var/source_check_mac.json   # mốc Mac
python3 check_vps.py --baseline source_check_mac.json               # trên VPS
```

## Thêm một nguồn tin

1. Thêm `[[source]]` vào `config/sources.toml`.
2. Map `id` → mục trong `SECTION_BY_SOURCE` (`brief/news.py`), nếu không mặc định `vn_economy`.
3. (Tuỳ) tên ngắn trong `compose.SOURCE_NAMES`; xem `publisher()` nếu cùng nhà xuất bản.
4. `check-sources --write` → `scripts/botctl.sh restart`.

## Trang tĩnh `site/index.html`

- `brief/site_data.py` gom dữ liệu: `news_section` (cụm tin 24h), `crypto_section` (subprocess `Trading-bot/.venv/bin/python scripts/crypto_snapshot.py` → nến ngày + `scan_oi_live` 1h/4h + USDT.D; bỏ nến UTC chưa đóng; chỉ báo/SMC/khuyến nghị ngắn hạn bằng `vn_stock.intel`), `vn_section` (đọc `stock/vn_stock/data/intel/latest.json` + kho giá điều chỉnh `load_adjusted`), `metals_section` (yfinance GC=F/SI=F 3 năm + `market.gold_market`).
- `brief/site.py`: `build()` (giữ phần lỗi từ `site/data.json` lần trước), `rerender()`, `render()` – JSON nhúng thoát `< > &` thành `\u003c…`.
- `brief/site_template.html`: 5 tab, Chart.js 4.4.1 + lightweight-charts 4.1.3 (CDN), sáng/tối, con lăn không zoom biểu đồ (kéo để xem lịch sử). Giá cổ phiếu trên biểu đồ = nghìn VND → đường vùng giá chia 1000.
- Lịch: `schedule.site_tick` trong thread lịch của bot, mốc `[site] rebuild_at` (08:25, 16:45), kv `site:<ngày>:<mốc>`.
- **GitHub Pages** (từ 15/11): https://charlie-long-working.github.io/stock/ — repo `stock` **public**, trang ai cũng xem được. Dựng xong → `schedule.site_publish` → `brief/publish.py` đẩy commit mồ côi (force push, nhánh luôn 1 commit) lên `gh-pages` qua repo riêng `var/pages-repo` (không đụng cây làm việc `../stock`). Push kích hoạt workflow `.github/workflows/pages.yml` trên nhánh đó (bản gốc `brief/pages_workflow.yml` — sửa ở đây, lần đẩy sau tự chép). Trang không đổi (sha256, kv `site_last_publish`) thì bỏ qua. Pages source = GitHub Actions; environment `github-pages` đã thêm branch policy `gh-pages` (mặc định chỉ `main`). Tắt: `[site] publish = false`. Thủ công: `$PY -m brief publish [--force|--dry-run]`, `$PY -m brief site --publish`. Push dùng khoá SSH `github-charlie` không passphrase (chạy được dưới launchd). Xem run: `gh run list -R charlie-long-working/stock --branch gh-pages`.
- Xem trong khung trình duyệt của Claude: `file://` bị chặn → preview `daily-brief-site` trong `../.claude/launch.json` (http.server :8768 bằng `stock/.venv` python – `/usr/bin/python3` không có quyền Documents).
- Trading-bot: lần dựng đầu đã làm mới cache USDT.D (`Trading-bot/data/macro/usdt_d_daily.csv`, trước đó dừng 22/08).

## Trạng thái & gotchas (15/11/2026)

- Bot `@nam_daily_brief_bot` chạy dưới launchd từ 15/11; bản sáng gửi bù 12:03 cùng ngày (message 16–17) xác nhận lịch chạy thật. Bot cảnh báo cũ `@bedboiz_bot` chỉ còn nhận cảnh báo GitHub Actions, **không** poll.
- `BRIEF_TELEGRAM_CHAT_ID` phải là **số** (user ID), không phải username. Để trống → lấy `TELEGRAM_CHAT_ID` (chat riêng). Lỗi đọc secret ghi rõ biến nào sai (`config.SECRET_ERROR`), không in giá trị.
- Token bot từng bị dán vào chat 15/11 → nên `/revoke` trong BotFather nếu chưa làm, rồi dán token mới vào `.env` và `botctl.sh restart`. `can_join_groups` còn bật (nên `/setjoingroups` → Disable).
- launchd + `~/Documents`: Python Homebrew cần quyền Files & Folders → Documents (đã cho phép 15/11). Bot không chạy, `~/Library/Logs/daily-brief/bot.out` trống → kiểm tra quyền này. Plist không đặt WorkingDirectory/log trong Documents (launchd trả EX_CONFIG 78).
- Thoát mã 2/3/4 (secret sai, webhook, 409) dưới launchd được đổi thành 0 để không lặp khởi động.
- Lịch: trạng thái mỗi slot ở kv `sched:<ngày>:<slot>`; `/status` có mục "Lịch tự gửi hôm nay". Máy ngủ đúng giờ → gửi bù khi thức nếu chưa quá 15:00 (sáng) / 23:00 (chiều).
- Nguồn: 19/23 RSS chạy; 4 RSS Vietstock 403 → `gnews_vietstock`. Chưa có giá SJC/vàng nhẫn tự động (sjc.com.vn Cloudflare 403, XML cũ 404). Chưa nối bot Telegram bên thứ ba (cần phiên client do user tự đăng nhập).
- AI (16/11): code xong, CLI tìm thấy nhưng **chưa đăng nhập** → user cần `claude setup-token` rồi dán `CLAUDE_CODE_OAUTH_TOKEN` vào `.env` (docs/AI_TOM_TAT.md). Bản AI soạn tay 14/11 (`runs/2026-11-14/manual-172106/`) không hiện trên trang (site chỉ lấy `runs/*/bot-*`).
- Báo cáo triển khai: `docs/BAO_CAO_2026-11-15.md`.

Env: `BRIEF_TELEGRAM_BOT_TOKEN`, `BRIEF_TELEGRAM_CHAT_ID` (ưu tiên hơn `TELEGRAM_*`), đọc từ env → `.env` → `../Trading-bot/.env` → `../stock/.env` → `../precious-metals/.env`. `BRIEF_DB`, `BRIEF_SUPERVISED` (launchd đặt).

## Nguồn bổ sung 15/11/2026

`cafef_chungkhoan`, `cafef_taichinh`, `cafef_doanhnghiep` (extended), `tnck_chungkhoan` — RSS công khai, đã `check-sources --write` (HTTP 200, 50 item) và map trong `SECTION_BY_SOURCE`.

## Nguồn bổ sung 16/11/2026

`vnexpress_noibat`, `vnexpress_batdongsan`, `cafef_vimo`, `cafef_batdongsan`, `cafef_quocte` (core). Tổng: 6 feed CafeF + 5 feed VnExpress. `cafef.vn/thi-truong.rss` (tin cũ) và `trang-chu.rss` (404) không dùng.
