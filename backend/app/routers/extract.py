# -*- coding: utf-8 -*-
"""抽取接口：文本抽取 + .txt 文件上传抽取。"""

from __future__ import annotations

import re

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import db
from ..nlp.pipeline import analyze

router = APIRouter(prefix="/api", tags=["抽取"])

MAX_CHARS = 20000
MAX_FILE_BYTES = 2 * 1024 * 1024
CHUNK_SIZE = 64 * 1024

# 候选编码。gbk 是 gb18030 的子集，结果等价，不再单列。
ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5", "utf-16")


class ExtractRequest(BaseModel):
    text: str = Field(..., description="待抽取的中文新闻文本")
    title: str | None = Field(default=None, description="自定义标题，留空则自动截取")
    save: bool = Field(default=True, description="是否写入历史记录")


class ExtractResponse(BaseModel):
    record_id: int | None = None
    result: dict


# 解码打分的正则：命中乱码特征扣分，命中常见中文/标点加分。
_KANA_ETC = re.compile(r"[\u3040-\u30ff\uac00-\ud7af\u0370-\u04ff]")  # 假名/谚文/希腊西里尔
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]")  # 控制符与替换符
_RARE = re.compile(r"[\u3400-\u4dbf\ue000-\uf8ff\uf900-\ufaff]")  # 扩展 A / 私用区 / 兼容区
_CJK = re.compile(r"[\u4e00-\u9fff]")
_CJK_PUNCT = re.compile(r"[\u3000-\u303f\uff00-\uffef]")
_ASCII_OK = re.compile(r"[\x20-\x7e\n\r\t]")
_SCORE_SAMPLE = 4000  # 只取前 N 字打分，2 MB 文件也不用整体扫描


def _score(text: str) -> float:
    """给一个解码结果打分，越像正常中文越高。

    gb18030 几乎能解开任意字节序列（错误编码也会"成功"），所以不能只看
    是否抛异常 —— 用字符分布判断哪个候选最可能是原文。
    """
    sample = text[:_SCORE_SAMPLE]
    n = len(sample)
    if not n:
        return float("-inf")
    good = (
        len(_CJK.findall(sample))
        + len(_CJK_PUNCT.findall(sample)) * 0.8
        + len(_ASCII_OK.findall(sample)) * 0.5
    )
    bad = (
        len(_KANA_ETC.findall(sample)) * 6
        + len(_CTRL.findall(sample)) * 10
        + len(_RARE.findall(sample)) * 1.5
    )
    return (good - bad) / n


def _decode(raw: bytes, filename: str) -> str:
    best: tuple[float, str] | None = None
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        if not text.strip():
            continue
        score = _score(text)
        if best is None or score > best[0]:
            best = (score, text)
    if best is None:
        raise HTTPException(status_code=400, detail=f"无法识别 {filename} 的编码，请另存为 UTF-8 后重试")
    return best[1]



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

    # 分块读取，超限立刻中断 —— 不要等整个文件进内存再判断
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="文件过大，请控制在 2 MB 以内")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
        raise HTTPException(status_code=400, detail="文件内容为空")
    text = _decode(raw, name)
    return _run(text, name.rsplit(".", 1)[0], save, "file")


@router.get("/health", summary="健康检查")
def health() -> dict:
    return {"status": "ok", "engine": "rule-based-cn-nlp"}
