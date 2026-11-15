"""Cấu hình + secret. Secret chỉ nằm trong bộ nhớ tiến trình, không bao giờ in/log."""

from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent
VAR = ROOT / "var"
DB_PATH = Path(os.environ.get("BRIEF_DB", str(VAR / "brief.db")))
LOG_DIR = VAR / "logs"
RUNS = ROOT / "runs"
TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Tái sử dụng loader của các repo anh em (cùng pattern sys.path đang dùng ở đó).
for _p in (WORKSPACE / "stock", WORKSPACE / "precious-metals"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))

_ENV_RE = re.compile(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def load_settings() -> dict[str, Any]:
    with (ROOT / "config" / "settings.toml").open("rb") as f:
        return tomllib.load(f)


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = _ENV_RE.match(line)
        if m and not line.lstrip().startswith("#"):
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


@dataclass(frozen=True)
class TelegramSecret:
    token: str
    chat_id: int
    token_source: str  # tên file (không phải giá trị)

    def __repr__(self) -> str:  # tránh lộ token khi debug
        return f"TelegramSecret(token=***, chat_id=***, source={self.token_source})"


SECRET_ERROR = ""  # lý do gần nhất telegram_secret() trả None (không chứa giá trị secret)


def telegram_secret(settings: Optional[dict[str, Any]] = None) -> Optional[TelegramSecret]:
    settings = settings or load_settings()
    merged: dict[str, tuple[str, str]] = {}
    for k in ("BRIEF_TELEGRAM_BOT_TOKEN", "BRIEF_TELEGRAM_CHAT_ID", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if os.environ.get(k):
            merged[k] = (os.environ[k], "env")
    for rel in settings["telegram"]["env_files"]:
        p = (ROOT / rel).resolve()
        for k, v in _read_env_file(p).items():
            if v and k not in merged:
                merged[k] = (v, p.parent.name + "/.env")
    tok = merged.get("BRIEF_TELEGRAM_BOT_TOKEN") or merged.get("TELEGRAM_BOT_TOKEN")
    chat = merged.get("BRIEF_TELEGRAM_CHAT_ID") or merged.get("TELEGRAM_CHAT_ID")
    global SECRET_ERROR
    if not tok or not chat:
        SECRET_ERROR = "Thiếu " + " và ".join(n for n, v in (("token bot", tok), ("chat ID", chat)) if not v)
        return None
    try:
        chat_id = int(chat[0])
    except ValueError:
        name = "BRIEF_TELEGRAM_CHAT_ID" if merged.get("BRIEF_TELEGRAM_CHAT_ID") else "TELEGRAM_CHAT_ID"
        SECRET_ERROR = f"{name} trong {chat[1]} không phải số (chat ID là dãy số, không phải username)"
        return None
    SECRET_ERROR = ""
    return TelegramSecret(token=tok[0], chat_id=chat_id, token_source=tok[1])


def redact(text: str, secret: Optional[TelegramSecret]) -> str:
    if secret and secret.token:
        text = text.replace(secret.token, "***")
    return re.sub(r"bot\d+:[A-Za-z0-9_-]{20,}", "bot***", text)
