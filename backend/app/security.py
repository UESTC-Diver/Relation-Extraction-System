# -*- coding: utf-8 -*-
"""上线最小安全集：来源白名单、请求体上限、per-IP 限流、报告分享签名。

设计原则：本地开发零配置可用（同源访问不受 CORS 限制），生产通过
环境变量收紧。分享签名只在显式配置 APP_REPORT_SECRET 后强制启用，
避免本机开箱即用与既有回归测试被破坏。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlencode

# 默认只放行本机开发源；生产用 APP_ALLOWED_ORIGINS 改成自己的域名。
# 前后端同源部署时浏览器不发 Origin 头，CORS 规则根本不参与。
DEFAULT_DEV_ORIGINS = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)

_LOCAL_SECRET_FILE = Path(__file__).resolve().parent.parent / "data" / ".report-secret"
_secret_cache: bytes | None = None


def allowed_origins() -> list[str]:
    raw = os.environ.get("APP_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return list(DEFAULT_DEV_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


def max_body_bytes() -> int:
    try:
        return max(1024, int(os.environ.get("APP_MAX_BODY_BYTES", str(4 * 1024 * 1024))))
    except ValueError:
        return 4 * 1024 * 1024


def rate_limit_per_min() -> int:
    try:
        return max(1, int(os.environ.get("APP_RATE_LIMIT_PER_MIN", "120")))
    except ValueError:
        return 120


class SlidingWindowLimiter:
    """单进程内存滑动窗口。

    当前部署形态是单机单进程，没必要为此引入 Redis；多 worker 部署时
    每个进程各自计数，等价于上限乘以进程数，README 里如实写明。
    """

    def __init__(self, window: float = 60.0) -> None:
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        # 每次读配置：测试可用环境变量放宽额度，不用为了改配置重启进程
        limit = rate_limit_per_min()
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            # 长期运行后清理冷 key，避免字典无界增长
            if len(self._hits) > 4096:
                stale = [k for k, v in self._hits.items() if not v or v[-1] < cutoff]
                for k in stale:
                    self._hits.pop(k, None)
            return True


limiter = SlidingWindowLimiter()


def report_secret() -> bytes:
    """优先读环境变量；未配置时用 data 目录里的持久随机密钥。

    持久化是为了让「已发出的分享链接」在服务重启后依然有效；该文件
    由 .gitignore 排除，不会进版本库。生产应显式设置 APP_REPORT_SECRET，
    这样换机器、清数据都不会导致链接失效。
    """
    global _secret_cache
    configured = os.environ.get("APP_REPORT_SECRET", "").strip()
    if configured:
        return configured.encode("utf-8")
    if _secret_cache:
        return _secret_cache
    _LOCAL_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _LOCAL_SECRET_FILE.exists():
        _secret_cache = _LOCAL_SECRET_FILE.read_bytes().strip()
    else:
        _secret_cache = os.urandom(32).hex().encode("ascii")
        _LOCAL_SECRET_FILE.write_bytes(_secret_cache)
    return _secret_cache or b"fallback-local-secret"


def signing_enabled() -> bool:
    """只有显式配置密钥时才强制签名，本机默认仍是裸 id 可访问。"""
    return bool(os.environ.get("APP_REPORT_SECRET", "").strip())


def _signature(record_id: int, expires_at: int) -> str:
    message = f"{record_id}:{expires_at}".encode("ascii")
    return hmac.new(report_secret(), message, hashlib.sha256).hexdigest()[:24]


def sign_report(record_id: int, ttl_seconds: int = 7 * 24 * 3600, base: str = "") -> str:
    expires_at = int(time.time()) + max(60, int(ttl_seconds))
    query = urlencode({"expires": expires_at, "token": _signature(record_id, expires_at)})
    return f"{base.rstrip('/')}/report/{record_id}?{query}"


def verify_report(record_id: int, expires: str, token: str) -> bool:
    try:
        expires_at = int(expires)
    except (TypeError, ValueError):
        return False
    if expires_at < int(time.time()):
        return False
    return hmac.compare_digest(_signature(record_id, expires_at), token or "")
