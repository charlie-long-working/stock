"""HTTP GET tối giản: timeout, giới hạn kích thước, retry hữu hạn.

Chỉ dùng thư viện chuẩn. Không giả lập trình duyệt, không vượt bot-detection:
User-Agent tự nhận là client cá nhân; nguồn chặn (403/429/challenge) được ghi nhận
là "blocked" và bỏ qua.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

USER_AGENT = "daily-brief/0.1 (personal news reader; python-urllib)"
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
RETRYABLE_STATUS = {500, 502, 503, 504}


@dataclass
class FetchResult:
    url: str
    status: Optional[int] = None
    content_type: str = ""
    body: bytes = b""
    truncated: bool = False
    elapsed_s: float = 0.0
    attempts: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status == 200


def fetch(
    url: str,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    retries: int = 1,
    backoff_s: float = 2.0,
) -> FetchResult:
    """GET `url`. Retry tối đa `retries` lần cho lỗi mạng hoặc 5xx; không retry 4xx."""
    res = FetchResult(url=url)
    start = time.monotonic()
    for attempt in range(retries + 1):
        res.attempts = attempt + 1
        res.error = None
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.5",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res.status = resp.status
                res.content_type = resp.headers.get("Content-Type", "") or ""
                data = resp.read(max_bytes + 1)
                res.truncated = len(data) > max_bytes
                res.body = data[:max_bytes]
            break
        except urllib.error.HTTPError as e:
            res.status = e.code
            res.content_type = (e.headers.get("Content-Type", "") if e.headers else "") or ""
            try:
                res.body = e.read(64 * 1024)
            except Exception:
                res.body = b""
            res.error = f"HTTP {e.code}"
            if e.code not in RETRYABLE_STATUS:
                break
        except Exception as e:  # URLError, timeout, ssl, ...
            res.error = f"{type(e).__name__}: {e}"[:200]
        if attempt < retries:
            time.sleep(backoff_s * (attempt + 1))
    res.elapsed_s = round(time.monotonic() - start, 2)
    return res
