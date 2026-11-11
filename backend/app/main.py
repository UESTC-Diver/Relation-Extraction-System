# -*- coding: utf-8 -*-
"""FastAPI 应用入口。

启动（两种方式均可）：
    cd backend && python main.py                     # 一键启动（推荐）
    cd backend && python -m uvicorn app.main:app --reload --port 8000
文档：http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .nlp.tokenizer import warmup
from .routers import dictionary, extract, meta

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    warmup()  # 预热 jieba 词典，避免首个请求卡顿
    yield


app = FastAPI(
    title="中文关系抽取系统 API",
    description=(
        "基于词典与词法规则的中文实体识别 + 关系抽取服务。\n\n"
        "识别实体：人物 / 组织机构 / 地理位置 / 时间 / 金额 / 产品技术\n"
        "抽取关系：19 类，输出 <头实体, 关系, 尾实体> 三元组\n"
        "支持人工校正、证据联动与自定义实体词典"
    ),
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(extract.router)
app.include_router(meta.router)
app.include_router(dictionary.router)


@app.get("/", include_in_schema=False)
def root():
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {
            "service": "中文关系抽取系统",
            "docs": "/docs",
            "hint": "前端未构建：在 frontend 目录执行 npm install && npm run build，或 npm run dev",
        }
    )


if FRONTEND_DIST.exists():
    DIST_ROOT = FRONTEND_DIST.resolve()
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # full_path 来自 URL，可能带 .. 或 %2f 编码的穿越片段。先把路径解析成
        # 绝对路径，再确认它仍在 dist 目录内；否则一律回落到 SPA 入口，
        # 避免把 backend 源码、README 或 SQLite 数据库当静态文件发出去。
        target = (FRONTEND_DIST / full_path).resolve()
        if target.is_file() and target.is_relative_to(DIST_ROOT):
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
