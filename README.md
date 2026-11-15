# daily-brief

Trợ lý thông tin cá nhân tiếng Việt, chạy local trên Mac và trả lời qua bot Telegram.

- Python (code xác định) lo thu thập RSS, lấy giá, lọc trùng, soạn bản tin theo mẫu và gửi.
- AI chỉ được dùng khi bật, và mọi bản AI đều phải qua kiểm tra tự động trước khi gửi.

## Dùng thế nào

Bot: **@nam_daily_brief_bot** (https://t.me/nam_daily_brief_bot). Bot riêng cho bản tin, tách khỏi bot cảnh báo `@bedboiz_bot`.
- Token lấy từ `BRIEF_TELEGRAM_BOT_TOKEN` trong `daily-brief/.env`.
- Nếu để trống `BRIEF_TELEGRAM_CHAT_ID`, bot dùng `TELEGRAM_CHAT_ID` của bot cảnh báo. Đó là chat riêng của bạn, có ID bằng Telegram user ID.
- Bot chỉ trả lời chat cá nhân này; chat khác bị bỏ qua.
- Chat ID phải là dãy số, không phải username.

| Lệnh | Kết quả |
|---|---|
| `/start`, `/help` | Hướng dẫn |
| `/brief` | Tin mới kể từ bản tin trước đã gửi. Tối đa 12 mục, chia 5 nhóm, mỗi mục có nguồn, giờ, link. Không lặp tin đã gửi trong 48 giờ; không đủ tin liên quan thì nói rõ, không lấp đầy |
| `/brief full` | Tin 24 giờ qua, không loại tin đã gửi |
| `/stock` | VN-Index, VN30, HNX-Index phiên gần nhất, cộng 27 mã watchlist: tăng/giảm, GTGD, khối ngoại. Nguồn vnstock (VCI). `/stock refresh` bỏ bộ nhớ đệm 10 phút |
| `/gold` | Vàng COMEX GC=F, tỷ giá Vietcombank và Yahoo, giá quy đổi VND/lượng, tham chiếu giá vàng trong nước từ báo chí |
| `/status` | Trạng thái từng nguồn, lần cập nhật, lỗi gần nhất, chế độ AI |

Ký hiệu trong tin nhắn:

| Ký hiệu | Nghĩa |
|---|---|
| 📋 | Template, không AI |
| 🤖 | AI tổng hợp, hoặc câu nhận định của AI |
| ⚠️ | Dữ liệu cũ hoặc nguồn lỗi |
| 🔗 / `*` | Chỉ có tiêu đề (qua Google News) |

## Lịch tự gửi

| Bản | Giờ (VN) | Nội dung | Lỡ mốc thì |
|---|---|---|---|
| Sáng | 08:15 | Tin tức + vàng/tỷ giá | Gửi bù khi máy thức, có ghi "gửi bù lúc HH:MM". Quá 15:00 thì bỏ |
| Chiều | 16:30 | Tin tức + chứng khoán (chỉ khi hôm nay có phiên) + vàng/tỷ giá | Gửi bù, quá 23:00 thì bỏ |

- Bản bị bỏ không làm mất tin: bản tin luôn lấy tin kể từ bản đã gửi trước đó.
- Lỗi mạng hoặc nguồn: thử lại sau 10 phút, tối đa 3 lần. Phần đã gửi xong không gửi lại.
- `/status` có mục "Lịch tự gửi hôm nay".
- Đổi giờ hoặc tắt lịch trong `[schedule]` của `config/settings.toml`, rồi `scripts/botctl.sh restart`.
- Lịch chạy bên trong tiến trình bot. **Máy ngủ thì không gửi.** Để gửi đúng giờ, máy cần thức lúc 08:15 và 16:30: cắm sạc, và bật trong System Settings → Battery/Energy "Prevent automatic sleeping when the display is off". Việc này bạn tự chỉnh.

## Trang tĩnh "Bảng tin thị trường"

`site/index.html` – một file HTML, dữ liệu nhúng sẵn, 5 tab:

| Tab | Nội dung | Nguồn |
|---|---|---|
| Tin tức hằng ngày | Cụm tin 24 giờ đã lọc trùng, lọc theo nhóm; biểu đồ theo nhóm/nguồn | RSS của bot |
| BTC / ETH | Giá, % thay đổi, khuyến nghị ngắn hạn (kỹ thuật/SMC/khối lượng), tín hiệu OI live I/K khung 1h/4h (OI z, funding z, USDT.D), SMC, nến + vùng mua/vô hiệu/mục tiêu, so sánh BTC–ETH, ETH/BTC, USDT.D, bảng chỉ số | Trading-bot (`scripts/crypto_snapshot.py` chạy bằng venv Trading-bot) |
| Chứng khoán theo ngành | VN-Index/VN30/HNX, chế độ thị trường, độ rộng, khối ngoại; lợi suất & điểm theo ngành; bảng xếp hạng ngành; cổ phiếu trong ngành, P/B–ROE, hiệu suất | Stock Intelligence (`stock/vn_stock/intel`) |
| Top 100 cổ phiếu | Bảng lọc/sắp xếp (vốn hoá, giá, P/E, P/B, ROE, tăng trưởng, RSI, mây, 5 điểm thành phần, upside, khối ngoại, khuyến nghị 3 khung); bản đồ định giá–kỹ thuật; phân bố khuyến nghị; so sánh ≤ 5 mã; chi tiết từng mã (nến + vùng giá, BCTC, giá trị nội tại, lý do/rủi ro); kết quả backtest | như trên |
| Vàng & bạc | GC=F, SI=F, tỷ lệ vàng/bạc, USD Vietcombank, quy đổi VND/lượng, nến, so sánh, RSI, khuyến nghị ngắn hạn | Yahoo, Vietcombank |

```bash
../stock/.venv/bin/python -m brief site                       # dựng toàn bộ (~50 giây)
../stock/.venv/bin/python -m brief site --parts news,crypto   # chỉ làm mới một phần (phần còn lại giữ bản trước)
../stock/.venv/bin/python -m brief site --render-only         # chỉ dựng lại HTML sau khi sửa giao diện
open site/index.html                                          # mở bằng trình duyệt mặc định
```

- Bot tự dựng lại lúc **08:25** và **16:45** (`[site]` trong `settings.toml`); máy ngủ lỡ mốc → dựng khi thức (trước mốc kế tiếp).
- Biểu đồ dùng Chart.js 4.4.1 và lightweight-charts 4.1.3 từ CDN → cần internet khi xem. Trang ~2,5 MB.
- Một phần lỗi khi dựng → giữ dữ liệu phần đó từ lần trước, ghi lỗi ở chân trang.
- Khuyến nghị crypto/kim loại chỉ có khung ngắn hạn theo kỹ thuật (không có dữ liệu cơ bản); khuyến nghị cổ phiếu lấy từ Stock Intelligence. Backtest chưa cho thấy lợi thế – trang ghi rõ.
- `site/` nằm trong `.gitignore`.

## Chạy / dừng

Bot chạy bằng **launchd**, qua một LaunchAgent của riêng user này, không cần sudo: `~/Library/LaunchAgents/local.daily-brief.bot.plist`.
- Tự chạy khi đăng nhập hoặc bật máy.
- Tự khởi động lại nếu bị crash hoặc mất mạng lúc khởi động (sau khoảng 60 giây).
- Thiếu token / chat ID (exit 2), có webhook (3) hoặc 409 xung đột (4) thì dừng hẳn, không lặp lại.
- **Sai token** (401 từ `getMe`) thì process thoát lỗi và launchd khởi động lại mỗi 60 giây — xem `var/logs/bot.log`.

```bash
scripts/botctl.sh status
scripts/botctl.sh logs 50    # var/logs/bot.log (chỉ ghi tên lệnh và message_id, không ghi nội dung/secret)
scripts/botctl.sh restart    # cần chạy sau khi sửa code hoặc config
scripts/botctl.sh stop       # dừng; tự chạy lại ở lần đăng nhập sau, hoặc khi gõ start
scripts/botctl.sh start
scripts/botctl.sh uninstall  # gỡ launchd: bot dừng, không tự chạy khi bật máy
scripts/botctl.sh install    # cài lại launchd
```

- Chưa `install` thì `start` chạy tiến trình nền thường, không tự chạy lại sau reboot.
- Log stdout của launchd nằm ở `~/Library/Logs/daily-brief/bot.out`.
- **Quyền Documents của macOS:** tiến trình do launchd chạy cần quyền đọc `~/Documents`. Ngày 15/11, lần chạy đầu bị macOS giữ lại chờ quyền, sau đó đã được cho phép.
  - Nếu sau này bot không chạy và `bot.out` trống, vào System Settings → Privacy & Security → Files and Folders, kiểm tra mục **Python** đã bật **Documents Folder** chưa.
  - Quyền này cấp cho cả bản Python Homebrew. Mọi script chạy nền bằng Python đó đều đọc được Documents.

Python dùng chung `../stock/.venv`, đã có vnstock 3.5.0, yfinance và pandas. PyPI hiện không còn bản vnstock nào cài được nên không tạo venv riêng. Có thể đổi bằng `BRIEF_PYTHON=/đường/dẫn/python`, rồi chạy `install` lại.

Bot **chỉ chạy khi máy Mac thức**:
- Máy ngủ hoặc tắt thì bot dừng nhận lệnh. Đăng xuất thì launchd dừng bot, đăng nhập lại thì bot tự chạy.
- Lệnh gửi trong lúc bot không chạy, cũ hơn 15 phút, sẽ bị bỏ qua.

## CLI (không cần bot)

Mặc định các lệnh chỉ in ra màn hình. Thêm `--send` mới gửi tới chat cá nhân.

```bash
PY=../stock/.venv/bin/python
$PY -m brief brief [--full] [--send]
$PY -m brief bot                                           # chạy bot foreground (launchd dùng lệnh này)
$PY -m brief stock|gold [--refresh] [--send]
$PY -m brief status [--send]
$PY -m brief check-sources --write [--tier core|extended]  # kiểm chứng nguồn -> docs/source_check.md
$PY -m brief evidence --full                                # gói bằng chứng cho AI -> runs/<ngày>/manual-*/
$PY -m brief send-ai runs/<ngày>/manual-*/ [--producer TEXT] [--dry-run]  # kiểm tra + gửi ai_brief.txt
$PY -m unittest discover -s tests -t .                      # 32 test, dữ liệu, giờ và API giả
```

## AI: phần nào có, phần nào chưa

- **Bot tự động hiện chạy chế độ 📋 Template.** Tiến trình bot **không** dùng hạn mức của phiên Claude Desktop. Máy cũng chưa cài Claude Code CLI (`claude` không có trên PATH).
- **Bản 🤖 AI ngày 14/11 17:20** do Claude trong phiên Desktop soạn từ `runs/2026-11-14/manual-172106/evidence.md`.
  - Bản này qua `validate()`: mọi mục có `[N#]`/`[M#]` tồn tại, mọi con số có trong gói bằng chứng.
  - Đã gửi bằng `send-ai`, Telegram trả message_id 116 và 117.
- **Muốn bot tự tổng hợp bằng AI** (cơ chế chính thức, tính vào gói Claude của bạn):
  1. Tự cài Claude Code CLI theo hướng dẫn chính thức của Anthropic.
  2. Chạy `claude` một lần trong Terminal và tự đăng nhập. Không gửi mã hay token vào chat.
  3. Trong `config/settings.toml`, đặt `[ai] enabled = true`, rồi `scripts/botctl.sh restart`.
  - Khi đó `/brief` gọi `claude -p` với gói bằng chứng. Bản AI không qua kiểm tra thì bot tự quay về template và ghi rõ lý do.
  - Cách gọi CLI này **chưa được chạy thử** trên máy này, vì máy chưa có CLI.
  - Tài khoản Claude đang dùng chung thì nội dung gói bằng chứng sẽ đi qua tài khoản đó.

## Nguồn dữ liệu và giới hạn

- **RSS chạy được:**
  - VnExpress, VnEconomy, Báo Chính phủ, Tuổi Trẻ, BBC, FT và Bloomberg: chỉ có tiêu đề và tóm tắt.
  - Reuters, AP và Vietstock: qua Google News, chỉ có tiêu đề.
- **RSS Vietstock trả 403:** đã tắt (`enabled = false`). Không vượt chặn.
- **Chứng khoán:** gọi vnstock trực tiếp mỗi lần, không dùng snapshot local của repo `stock` (cũ từ 23/08).
  - Trạng thái phiên được suy từ dữ liệu, không đoán lịch nghỉ lễ.
  - Watchlist là danh sách `watchlist_27` có sẵn trong repo `stock`, **chưa được xác nhận** là watchlist chính thức.
- **Vàng – tỷ giá:**
  - GC=F là hợp đồng tương lai, có thể trễ 10–15 phút.
  - Giá quy đổi = GC=F × VCB bán ra × 37,5/31,1035. Đây **không phải** giá bán lẻ.
  - **Chưa có giá SJC/vàng nhẫn niêm yết tự động:** sjc.com.vn chặn bằng Cloudflare (403), XML cũ trả 404. Bot chỉ đưa tin báo chí làm tham chiếu và ghi rõ "chưa xác minh".
- **Telegram bot bên thứ ba:** **chưa kết nối.** Cần phiên Telegram client đăng nhập trên máy (bạn tự nhập OTP) và danh sách chat nguồn.
- **Dữ liệu runtime:**
  - `var/brief.db` (SQLite: items, fetch_log, briefs, deliveries) và `runs/` đều nằm trong `.gitignore`.
  - Tin cũ hơn 30 ngày tự xoá khi bot khởi động.

## Kiểm tra nguồn trước khi chuyển sang VPS

`scripts/check_vps.py` gọi thử một lần mỗi nguồn mà các bot đang dùng, để biết máy đó có bị chặn không. Các nguồn gồm: Telegram, VCI/KBS/VNDirect (chứng khoán), Yahoo/Vietcombank/SJC/OKX (vàng, tỷ giá), Binance/Bybit/Gate/CMC/DefiLlama (crypto), RSS, PyPI/GitHub.

- Chỉ dùng thư viện chuẩn Python 3.8+, không cần token hay `.env`, và không gửi tin.
- Telegram được thử bằng token giả `bot0`: nhận HTTP 404 nghĩa là máy tới được API.
- Nguồn có dấu `*` là bắt buộc. Mã thoát 1 nghĩa là có nguồn bắt buộc bị lỗi.

```bash
# Trên Mac (đã có mốc: var/source_check_mac.json, ngày 15/11/2026: 37/38 OK, chỉ SJC lỗi)
../stock/.venv/bin/python scripts/check_vps.py --no-ip --save var/source_check_mac.json
# Chép script và file mốc lên VPS rồi chạy (VPS chỉ cần python3)
scp scripts/check_vps.py var/source_check_mac.json user@VPS:~
ssh user@VPS 'python3 check_vps.py --baseline source_check_mac.json --save vps.json'
```

Cột cuối có ghi chú "← máy mốc chạy được, máy này KHÔNG" là chỗ VPS bị chặn mà Mac thì không. Cách đọc kết quả lỗi:

| Kết quả | Ý nghĩa |
| --- | --- |
| `BLOCKED` (403/451) | Nguồn chặn IP hoặc khu vực |
| `DNS`/`RESET`/`TIMEOUT` | Bị chặn ở tầng mạng. Telegram trên VPS đặt ở Việt Nam hay gặp kiểu này |
| `LIMIT` (429) | Bị giới hạn tần suất. Yahoo hay làm vậy với IP của trung tâm dữ liệu |

Mỗi nguồn chỉ được gọi một lần, nên hãy chạy vài lần ở các giờ khác nhau trước khi trả tiền thuê dài hạn.

## Còn thiếu / bước tiếp

1. Nguồn giá SJC/vàng nhẫn hợp lệ.
2. Telegram client cho bot bên thứ ba.
3. AI tự động trong bot: cài và đăng nhập Claude Code CLI.
4. ~~Tự gửi theo lịch 08:15/16:30 và tự khởi động bằng launchd~~: đã có (ngày 15/11). Còn thiếu: watchdog báo lỗi độc lập với bot, và lịch nghỉ lễ HOSE.
5. ~~Bot riêng cho bản tin~~: đã có `@nam_daily_brief_bot` (ngày 15/11).

Kế hoạch tổng thể: `~/.claude/plans/pasted-content-id-e9d8-b-n-l-fluttering-crane.md`. Kiểm chứng nguồn: `docs/source_check.md`.
