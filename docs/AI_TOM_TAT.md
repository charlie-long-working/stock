# Tóm tắt bản tin bằng Claude (16/11/2026)

## Trạng thái

- Code đã xong và đã bật (`[ai] enabled = true`).
- **Chưa chạy được vì Claude Code CLI trên máy chưa đăng nhập.** Trong lúc đó bản tin vẫn gửi bằng template như trước, không báo lỗi.
- Bot đã tìm thấy CLI. Đây là bản Claude Code đi kèm app Claude Desktop, nằm tại `~/Library/Application Support/Claude/claude-code/<phiên bản>/…/claude`. Khi app cập nhật, bot tự lấy bản mới nhất.

## Bật AI (làm một lần, khoảng 2 phút)

1. Mở Terminal và tạo token dài hạn. Cách này dùng gói Pro/Max của bạn, mở trình duyệt để bạn tự đăng nhập:

   ```bash
   "$(ls -d ~/Library/Application\ Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude | tail -1)" setup-token
   ```

2. Dán token vào `daily-brief/.env` trên một dòng riêng. File này không được commit.

   ```
   CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
   ```

3. Khởi động lại bot rồi kiểm tra:

   ```bash
   cd ~/Documents/Cursor/daily-brief && scripts/botctl.sh restart
   ../stock/.venv/bin/python -m brief status      # dòng "AI: 🤖 bật – … token từ .env"
   ../stock/.venv/bin/python -m brief brief       # chỉ in, không gửi; đầu bản tin ghi "🤖 Chế độ: AI tổng hợp"
   ```

Nếu dùng API key thay cho gói: đặt `ANTHROPIC_API_KEY=…` vào `.env`. Khi đó bot tự thêm `--bare` để gọi gọn nhất.

## Mỗi ngày chạy thế nào (tự động trong process bot)

| Giờ VN | Việc |
| --- | --- |
| 08:15 | Thu RSS (gồm 6 feed CafeF + 5 feed VnExpress) → lọc trùng → chọn ≤ 12 tin → lấy đoạn mở đầu bài CafeF/VnExpress → **1 lời gọi Claude** → kiểm tra → gửi Telegram |
| 08:25 | Dựng trang tĩnh. Tab Tin có card "🤖 Tóm tắt AI" (bản gần nhất trong 30 giờ) → đẩy lên https://charlie-long-working.github.io/stock/ |
| 16:30 / 16:45 | Lặp lại cho bản chiều (thêm chứng khoán) |

## Tiết kiệm token

- **Một lời gọi cho cả bản tin**, không gọi theo từng bài. Gói bằng chứng khoảng 9–11 nghìn ký tự (khoảng 3–4 nghìn token vào), bản tóm tắt khoảng 1,5–2,5 nghìn token ra. Hai bản mỗi ngày tổng cộng khoảng 10–13 nghìn token.
- **Bỏ phần "Claude Code" khỏi lời gọi:**
  - `--system-prompt` thay prompt hệ thống mặc định (vốn rất dài) bằng 10 luật biên tập trong `brief/prompts/brief_vi.md`;
  - `--tools ""` tắt mọi tool;
  - `--strict-mcp-config`, `--disable-slash-commands`, `--setting-sources ""` không nạp MCP, skill hay settings;
  - `--no-session-persistence` không lưu phiên;
  - chạy trong thư mục trống `var/ai-cwd`, nên không nạp CLAUDE.md/AGENTS.md của repo.
- `--effort low`: tóm tắt không cần suy luận dài. Model mặc định `sonnet`; muốn rẻ hơn nữa thì đổi `[ai] model = "haiku"`.
- **Đoạn mở đầu bài (sapo + 2–4 đoạn đầu, tối đa 900 ký tự)** chỉ tải cho tin *đã chọn*, chỉ từ `vnexpress.net` và `cafef.vn`. Mỗi URL chỉ tải một lần: lưu vào bảng `articles`, bài bị chặn hoặc lỗi cũng được nhớ. Xoá sau 30 ngày.
- **Bản AI sai vài mục thì bỏ đúng các mục đó (`salvage`)**, không gọi lại AI. Chỉ quay về template khi còn dưới 60% số mục hoặc dưới 3 mục.
- Mỗi lần gọi ghi token, thời gian và chi phí quy đổi vào `runs/<ngày>/bot-*/ai_usage.json`, kv `ai_last_usage` và `/status`.

## An toàn nội dung (giữ nguyên từ trước)

- `validate()`: mọi gạch đầu dòng phải có tham chiếu `[N…]`/`[M…]` tồn tại, và mọi con số (từ 2 chữ số) phải có trong gói bằng chứng.
- Chỉ giữ thẻ `<b>`/`<i>`; link do code gắn theo tham chiếu, AI không tự viết link.
- Không khuyến nghị mua/bán. Nhận định của AI bắt đầu bằng 🤖.

## File

| File | Vai trò |
| --- | --- |
| `brief/article.py` | Trích sapo và các đoạn đầu (VnExpress `p.description` / `fck_detail`; CafeF `data-role=sapo` / `detail-content`), cache SQLite |
| `brief/ai.py` | `find_cli`, `auth_env`, `ai_status` (cache 10 phút), `cli_args`, `run_cli` (JSON + usage), `salvage`, `validate` |
| `brief/service.py` `run_brief` | Template → đoạn mở đầu → evidence → Claude → validate/salvage → lưu bản AI |
| `brief/site_data.py` `latest_ai_brief` | Bản AI gần nhất do bot tạo (`runs/*/bot-*`) cho tab Tin trên trang |
| `config/settings.toml` `[ai]` | `enabled, model, effort, timeout_s, fetch_articles, article_hosts, article_chars` |
| `tests/test_ai_brief.py` | 11 test (CLI giả, không mạng, không token thật) |
