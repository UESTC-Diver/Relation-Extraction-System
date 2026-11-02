# -*- coding: utf-8 -*-
"""抽取接口：文本抽取 + .txt 文件上传抽取。"""

from __future__ import annotations

import io

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import db
from ..nlp.pipeline import analyze

router = APIRouter(prefix="/api", tags=["抽取"])

MAX_CHARS = 20000
MAX_FILE_BYTES = 2 * 1024 * 1024
ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "utf-16", "big5")


class ExtractRequest(BaseModel):
    text: str = Field(..., description="待抽取的中文新闻文本")
    title: str | None = Field(default=None, description="自定义标题，留空则自动截取")
    save: bool = Field(default=True, description="是否写入历史记录")


class ExtractResponse(BaseModel):
    record_id: int | None = None
    result: dict


def _decode(raw: bytes, filename: str) -> str:
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        if text.strip():
            return text
    raise HTTPException(status_code=400, detail=f"无法识别 {filename} 的编码，请另存为 UTF-8 后重试")


def _run(text: str, title: str | None, save: bool, source: str) -> ExtractResponse:
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本内容为空")
    if len(text) > MAX_CHARS:
        raise HTTPException(status_code=413, detail=f"文本过长（{len(text)} 字），请控制在 {MAX_CHARS} 字以内")
    result = analyze(text)
    result["source"] = source
    record_id = db.save_record(result, source=source, title=title or "") if save else None
    if record_id:
        result["record_id"] = record_id
    return ExtractResponse(record_id=record_id, result=result)


@router.post("/extract", response_model=ExtractResponse, summary="粘贴文本抽取")
def extract_text(payload: ExtractRequest) -> ExtractResponse:
    return _run(payload.text, payload.title, payload.save, "text")


@router.post("/extract/file", response_model=ExtractResponse, summary="上传 .txt 文件抽取")
async def extract_file(
    file: UploadFile = File(..., description="UTF-8 / GBK 编码的 .txt 文件"),
    save: bool = True,
) -> ExtractResponse:
    name = file.filename or "upload.txt"
    if not name.lower().endswith((".txt", ".md", ".text")):
        raise HTTPException(status_code=415, detail="仅支持 .txt / .md 文本文件")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="文件过大，请控制在 2 MB 以内")
    text = _decode(raw, name)
    return _run(text, name.rsplit(".", 1)[0], save, "file")


@router.get("/health", summary="健康检查")
def health() -> dict:
    return {"status": "ok", "engine": "rule-based-cn-nlp"}
