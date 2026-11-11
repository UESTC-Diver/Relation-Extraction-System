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


_PUNCT = set("，。、；：！？（）《》〈〉「」『』“”‘’…—·～￥％")
# 假名 / 谚文 / 希腊西里尔 / 私用区 / C1 控制符：正常中文新闻里几乎不会出现
_BAD_RANGES = ((0x3040, 0x30FF), (0xAC00, 0xD7AF), (0x0370, 0x052F),
               (0xE000, 0xF8FF), (0x0080, 0x009F))
_COMMON = set(
    "的一是在不了有人我他这中大来上国个到说们为子和地出道也时年得就那要下以生会自着去过家学"
    "对可她里后小么心多天而能好都然没日于起还发成事只作当看文无开手十用主行方又见新老"
    "公司收购投资宣布表示亿元万月双方后将已并与及其实该产品技术市场总部位于创立任职签署"
    "合作竞争供应发布诉讼隶属控股子公司腾讯阿里华为比亚迪特斯拉搜狗搜狐北京上海王小川"
    "臺灣萬與業經營資訊經濟國際企業董事長總部位於收購投資宣佈雙方後將已併與"
)


def _score(text: str) -> float:
    """给一次解码结果打分：像中文新闻的得高分，像乱码的得低分。"""
    if not text.strip():
        return float("-inf")
    common = cjk = punct = plain = bad = 0
    for ch in text:
        o = ord(ch)
        if ch == "\ufffd" or (o < 0x20 and ch not in "\t\n\r"):
            bad += 1
        elif any(a <= o <= b for a, b in _BAD_RANGES):
            bad += 1
        elif 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            cjk += 1
            if ch in _COMMON:
                common += 1
        elif 0xF900 <= o <= 0xFAFF:  # 兼容表意文字，乱码常见
            bad += 1
        elif ch in _PUNCT:
            punct += 1
        elif o < 0x80 or 0x3000 <= o <= 0x303F:
            plain += 1
        else:
            bad += 1
    return (common * 4 + cjk + punct * 3 + plain * 0.2 - bad * 6) / max(len(text), 1)


def _decode(raw: bytes, filename: str) -> str:
    """把所有候选编码都试一遍，挑最像中文新闻的那个。

    不能取「第一个不报错的」：gb18030 几乎能解任意字节，排它后面的 big5
    永远轮不到，繁体文件会被静默解成乱码。
    """
    best_text, best_score = "", float("-inf")
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
        except (UnicodeError, LookupError):
            continue
        score = _score(text)
        if score > best_score:
            best_text, best_score = text, score
    if best_score == float("-inf"):
        raise HTTPException(status_code=400, detail=f"无法识别 {filename} 的编码，请另存为 UTF-8 后重试")
    return best_text.lstrip("\ufeff")


def _run(text: str, title: str | None, save: bool, source: str) -> ExtractResponse:
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本内容为空")
    if len(text) > MAX_CHARS:
        raise HTTPException(status_code=413, detail=f"文本过长（{len(text)} 字），请控制在 {MAX_CHARS} 字以内")
    result = analyze(text, custom_terms=db.list_custom_terms())
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
