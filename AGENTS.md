# daily-brief — hướng dẫn cho agent

Đọc skill trước: `.cursor/skills/daily-brief/SKILL.md`
(Claude Code: `.claude/skills/daily-brief`, Codex: `.agents/skills/daily-brief` — symlink).

Tổng quan cho người: `README.md`. Workspace: `../AGENTS.md`.

- Python: `../stock/.venv/bin/python`.
- Bot chạy launchd `local.daily-brief.bot` → sửa xong `scripts/botctl.sh restart`.
- CLI chỉ gửi Telegram khi có `--send`.
- Không vượt chặn bot của nguồn tin.
