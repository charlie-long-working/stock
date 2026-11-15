"""Bot API tối giản (urllib): gửi có chia tin/retry/biên nhận, getUpdates. Không log token."""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from brief import db
from brief.config import DB_PATH, TelegramSecret, redact

LIMIT = 3900  # < 4096, chừa chỗ cho thẻ HTML


class TelegramError(Exception):
    def __init__(self, code: int, description: str, retry_after: Optional[int] = None):
        super().__init__(f"{code}: {description}")
        self.code, self.description, self.retry_after = code, description, retry_after


@dataclass
class Api:
    secret: TelegramSecret

    def call(self, method: str, http_timeout: float = 20, **params: Any) -> Any:
        url = f"https://api.telegram.org/bot{self.secret.token}/{method}"
        data = json.dumps(params).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=http_timeout) as r:
                payload = json.load(r)
        except urllib.error.HTTPError as ex:
            try:
                payload = json.load(ex)
            except Exception:
                raise TelegramError(ex.code, "HTTP error") from None
        except Exception as ex:
            raise TelegramError(0, redact(f"{type(ex).__name__}: {ex}", self.secret)[:200]) from None
        if not payload.get("ok"):
            ra = (payload.get("parameters") or {}).get("retry_after")
            raise TelegramError(payload.get("error_code", 0), str(payload.get("description", ""))[:200], ra)
        return payload["result"]


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    """Chia theo đoạn (dòng trống), rồi theo dòng; không cắt giữa thẻ HTML của một dòng."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cur = ""
    for block in text.split("\n\n"):
        piece = block if not cur else "\n\n" + block
        if len(cur) + len(piece) <= limit:
            cur += piece
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        if len(block) <= limit:
            cur = block
            continue
        for line in block.split("\n"):
            add = line if not cur else "\n" + line
            if len(cur) + len(add) <= limit:
                cur += add
            else:
                if cur:
                    chunks.append(cur)
                cur = line[:limit]  # dòng đơn quá dài: cắt cứng (hiếm)
    if cur:
        chunks.append(cur)
    return chunks


def html_to_plain(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s))


def send_text(api: Api, chat_id: int, text: str, brief_id: Optional[int] = None,
              path: Path = DB_PATH, max_attempts: int = 3) -> list[dict[str, Any]]:
    """Gửi từng phần. Phần nào đã có message_id (theo brief_id) thì không gửi lại.
    Trả danh sách kết quả {chunk, ok, message_id, error}. 'ok' chỉ khi API trả message_id."""
    chunks = split_message(text)
    results = []
    for idx, chunk in enumerate(chunks):
        sha = hashlib.sha256(chunk.encode()).hexdigest()
        if brief_id is not None:
            with db.connect(path) as con:
                row = con.execute("SELECT status, tg_message_id FROM deliveries WHERE brief_id=? AND chunk_idx=?",
                                  (brief_id, idx)).fetchone()
            if row and row["status"] == "sent":
                results.append({"chunk": idx, "ok": True, "message_id": row["tg_message_id"], "skipped": True})
                continue
        msg_id, err, plain_used = None, None, False
        body, mode = chunk, "HTML"
        for attempt in range(max_attempts):
            try:
                params: dict[str, Any] = {"chat_id": chat_id, "text": body, "disable_web_page_preview": True}
                if mode:
                    params["parse_mode"] = mode
                res = api.call("sendMessage", **params)
                msg_id, err = res.get("message_id"), None
                break
            except TelegramError as ex:
                err = str(ex)
                if ex.code == 429 and ex.retry_after:
                    time.sleep(min(int(ex.retry_after), 60))
                elif ex.code == 400 and "parse" in ex.description.lower() and mode:
                    body, mode, plain_used = html_to_plain(chunk), None, True  # gửi lại dạng thường
                elif ex.code in (0, 500, 502, 503, 504):
                    time.sleep(2 * (attempt + 1))
                else:
                    break
        status = "sent" if msg_id else "failed"
        if brief_id is not None:
            with db.connect(path) as con:
                con.execute(
                    "INSERT INTO deliveries(brief_id, chunk_idx, text_sha256, status, tg_message_id, sent_at, error)"
                    " VALUES(?,?,?,?,?,?,?) ON CONFLICT(brief_id, chunk_idx) DO UPDATE SET status=excluded.status,"
                    " tg_message_id=excluded.tg_message_id, sent_at=excluded.sent_at, error=excluded.error",
                    (brief_id, idx, sha, status, msg_id, db.iso(db.now_utc()), err),
                )
        results.append({"chunk": idx, "ok": bool(msg_id), "message_id": msg_id, "error": err, "plain": plain_used})
        if not msg_id:
            break  # dừng ở phần lỗi; chạy lại sẽ chỉ gửi phần còn thiếu
    if brief_id is not None:
        all_ok = len(results) == len(chunks) and all(r["ok"] for r in results)
        any_ok = any(r["ok"] for r in results)
        with db.connect(path) as con:
            con.execute("UPDATE briefs SET status=? WHERE id=?",
                        ("sent" if all_ok else "partial" if any_ok else "failed", brief_id))
    return results
