# -*- coding: utf-8 -*-
"""FastAPI 应用入口。

启动（两种方式均可）：
    cd backend && python main.py                     # 一键启动（推荐）
    cd backend && python -m uvicorn app.main:app --reload --port 8000
文档：http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import db, security, store
from .nlp.tokenizer import warmup
from .routers import (
    annotation,
    delivery,
    dossier as dossier_router,
    mining,
    dictionary,
    extract,
    knowledge,
    meta,
    quality,
    review,
    rules,
    verify as verify_router,
)

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
VERSION = "2.5.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    store.fail_stale_tasks()  # 重启后内存中的后台 worker 已不存在
    warmup()  # 预热 jieba 词典，避免首个请求卡顿
    yield


app = FastAPI(
    title="文本关系抽取与信息甄别系统 API",
    description=(
        "基于词典与词法规则的中文实体识别 + 关系抽取服务。\n\n"
        "识别实体：人物 / 组织机构 / 地理位置 / 时间 / 金额 / 产品技术\n"
        "抽取关系：19 类，输出 <头实体, 关系, 尾实体> 三元组\n"
        "支持人工校正、证据联动、自定义词典与触发词、批量抽取、跨文档知识库、"
        "界面化评测、复核定稿与离线报告"
    ),
    version=VERSION,
    lifespan=lifespan,
)

# 默认只放行本机开发源；对外部署在 .env / 环境变量里写自己的域名。
# 前后端同源由本服务一起托管，同源请求不受 CORS 限制。
app.add_middleware(
    CORSMiddleware,
    allow_origins=security.allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Token"],
)
# 主 JS/CSS 与较大的抽取结果走 gzip；小于 1KB 的响应不压缩，避免得不偿失。
app.add_middleware(GZipMiddleware, minimum_size=1024)

_access_log = logging.getLogger("app.access")
_access_log.setLevel(logging.INFO)
if not _access_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _access_log.addHandler(_handler)
    _access_log.propagate = False


@app.middleware("http")
async def api_token_guard(request: Request, call_next):
    """可选写保护：设置 APP_API_TOKEN 后，非只读的 /api 请求须带 X-API-Token。

    默认不启用，本机单用户开箱即用；对外部署时配合收敛 CORS 一起打开。
    """
    token = os.environ.get("APP_API_TOKEN", "").strip()
    if not token or request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    if request.headers.get("X-API-Token") != token:
        return JSONResponse({"detail": "缺少或无效的 API Token"}, status_code=401)
    return await call_next(request)


@app.middleware("http")
async def safety_guard(request: Request, call_next):
    """外层防护：请求体上限、per-IP 限流、结构化访问日志与 request id。

    只约束 /api 与 /report：静态资源体积可控且带内容 hash，不该被限流误伤。
    """
    path = request.url.path
    guarded = path.startswith("/api/") or path.startswith("/report/")
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    started = time.monotonic()

    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > security.max_body_bytes():
        return JSONResponse(
            {"detail": "请求体过大"}, status_code=413, headers={"X-Request-ID": request_id}
        )

    if guarded:
        client = request.client.host if request.client else "unknown"
        if not security.limiter.allow(client):
            return JSONResponse(
                {"detail": "请求过于频繁，请稍后重试"},
                status_code=429,
                headers={"X-Request-ID": request_id, "Retry-After": "60"},
            )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    if guarded or path in ("/", "/app", "/demo"):
        _access_log.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "method": request.method,
                    "path": path,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                },
                ensure_ascii=False,
            )
        )
    return response


app.include_router(extract.router)
app.include_router(meta.router)
app.include_router(dictionary.router)
app.include_router(rules.router)
app.include_router(knowledge.router)
app.include_router(quality.router)
app.include_router(review.router)
app.include_router(annotation.router)
app.include_router(dossier_router.router)
app.include_router(mining.router)
app.include_router(verify_router.router)
# delivery 里含 /report/{id} 独立只读页，必须注册在 SPA catch-all 之前
app.include_router(delivery.router)


@app.get("/", include_in_schema=False)
def root():
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse(
        {
            "service": "文本关系抽取与信息甄别系统",
            "docs": "/docs",
            "hint": "前端未构建：在 frontend 目录执行 npm install && npm run build，或 npm run dev",
        }
    )


if FRONTEND_DIST.exists():
    DIST_ROOT = FRONTEND_DIST.resolve()

    @app.get("/assets/{asset_path:path}", include_in_schema=False)
    def assets(asset_path: str):
        # Vite 产物文件名带内容 hash，重新构建即换名，可以放心长缓存。
        # 不用 StaticFiles.mount 是为了能显式写 Cache-Control。
        target = (FRONTEND_DIST / "assets" / asset_path).resolve()
        if not (target.is_file() and target.is_relative_to(DIST_ROOT)):
            raise HTTPException(status_code=404)
        return FileResponse(
            target, headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # full_path 来自 URL，可能带 .. 或 %2f 编码的穿越片段。先把路径解析成
        # 绝对路径，再确认它仍在 dist 目录内；否则一律回落到 SPA 入口，
        # 避免把 backend 源码、README 或 SQLite 数据库当静态文件发出去。
        target = (FRONTEND_DIST / full_path).resolve()
        if target.is_file() and target.is_relative_to(DIST_ROOT):
            # 媒体与字体不带内容 hash，给一天缓存；HTML 入口每次回源，
            # 保证重新构建后访问者立刻拿到新的资源引用。
            long_lived = full_path.startswith(("media/", "fonts/")) or full_path == "favicon.svg"
            cache = "public, max-age=86400" if long_lived else "no-cache"
            return FileResponse(target, headers={"Cache-Control": cache})
        return FileResponse(
            FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"}
        )
