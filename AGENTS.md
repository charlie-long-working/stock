# stock — hướng dẫn cho agent

Đọc skill trước khi quét cây thư mục: `.cursor/skills/vn-stock/SKILL.md`
(Claude Code: `.claude/skills/vn-stock`, Codex: `.agents/skills/vn-stock` — đều là symlink).

Tổng quan cho người: `README.md`. Workspace: `../AGENTS.md`.

Quy tắc ngắn:
- Python `.venv/bin/python`, `PYTHONPATH="$PWD:$PWD/../Trading-bot"`.
- Test Telegram luôn `--dry-run`.
- Repo **public** — không commit `.env` hay dữ liệu cá nhân.
- Bot hourly chạy bằng launchd trên Mac, không phải GitHub Actions.
