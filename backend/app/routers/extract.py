# -*- coding: utf-8 -*-
"""抽取接口：文本抽取、单文件 / 批量文件抽取、批量文本抽取。"""

from __future__ import annotations

import io
import os
import threading
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import db
from ..nlp.lexicon import RELATION_RULES
from ..nlp.pipeline import analyze
from ..nlp import profiles as domain_profiles

router = APIRouter(prefix="/api", tags=["抽取"])

MAX_CHARS = 20000
MAX_FILE_BYTES = 2 * 1024 * 1024
CHUNK_SIZE = 64 * 1024
MAX_BATCH_ITEMS = 20
MAX_PDF_PAGES = 60
MAX_DOCX_UNCOMPRESSED = 8 * 1024 * 1024
try:
    PARSE_TIMEOUT = max(1.0, float(os.environ.get("APP_PARSE_TIMEOUT", "10")))
except ValueError:
    PARSE_TIMEOUT = 10.0
# 解析库的调用单独放一个线程池，才能对超时做硬截断
_parse_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="parse")

# 候选编码。gbk 是 gb18030 的子集，结果等价，不再单列。
ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5", "utf-16")

# jieba 是纯 Python、受 GIL 约束，同时跑太多长文本只会互相拖慢。
# 超出并发额度直接回 429，而不是让请求在线程池里无限排队。
MAX_CONCURRENT_EXTRACT = max(1, int(os.environ.get("APP_MAX_CONCURRENT_EXTRACT", "4")))
_extract_slots = threading.BoundedSemaphore(MAX_CONCURRENT_EXTRACT)


@contextmanager
def _extract_slot():
    if not _extract_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="抽取任务过多，请稍后重试")
    try:
        yield
    finally:
        _extract_slots.release()


class ExtractRequest(BaseModel):
    text: str = Field(..., description="待抽取的新闻文本（中文或英文）")
    title: str | None = Field(default=None, description="自定义标题，留空则自动截取")
    save: bool = Field(default=True, description="是否写入历史记录")
    profile: str = Field(default="general", description="领域包：general / finance / legal")
    language: str = Field(default="auto", description="语言：auto（按 CJK 占比自动选，默认）/ zh（自研规则引擎）/ en（spaCy 引擎）")


class ExtractResponse(BaseModel):
    record_id: int | None = None
    result: dict


class BatchItem(BaseModel):
    text: str = Field(..., description="单篇文本")
    title: str = Field(default="", description="单篇标题")


class BatchRequest(BaseModel):
    items: list[BatchItem] = Field(default_factory=list, max_length=MAX_BATCH_ITEMS)
    save: bool = Field(default=True, description="是否把每篇写入历史")
    profile: str = Field(default="general", description="领域包：general / finance / legal")


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
    """采样打分选编码，再用选中的编码解全文。

    不能取「第一个不报错的」：gb18030 几乎能解任意字节，排它后面的 big5
    永远轮不到，繁体文件会被静默解成乱码。也不能对 2 MB 全文逐个候选逐字符
    打分——纯 Python 循环会放大到千万级迭代。前 16 KB 的汉字、标点与控制符
    分布已经足够区分 UTF-8 / GB18030 / BIG5 / UTF-16。
    """
    sample = raw[: 16 * 1024]
    if len(sample) % 2:  # UTF-16 需偶数字节；也避免采样末尾截断多字节字符
        sample = sample[:-1]

    best_enc, best_score = "", float("-inf")
    for enc in ENCODINGS:
        try:
            head = sample.decode(enc, errors="ignore")
        except (UnicodeError, LookupError):
            continue
        score = _score(head)
        if score > best_score:
            best_enc, best_score = enc, score
    if best_score == float("-inf"):
        raise HTTPException(status_code=400, detail=f"无法识别 {filename} 的编码，请另存为 UTF-8 后重试")

    try:
        text = raw.decode(best_enc)
    except UnicodeError:
        # 采样段正常、文件尾部有坏字节时，不让整次上传直接失败
        text = raw.decode(best_enc, errors="replace")
    return text.lstrip("\ufeff")


def _read_pdf(raw: bytes, name: str) -> str:
    """PyMuPDF 本地解析，不联网、不调用任何外部服务。"""
    if not raw.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail=f"{name} 不是有效的 PDF 文件")
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz  # 旧版包名的兼容别名
        except ImportError:
            raise HTTPException(
                status_code=400, detail="未安装 PyMuPDF，无法解析 PDF（可执行 pip install pymupdf）"
            )
    try:
        with fitz.open(stream=raw, filetype="pdf") as doc:
            if len(doc) > MAX_PDF_PAGES:
                raise HTTPException(
                    status_code=413,
                    detail=f"PDF 页数过多（{len(doc)} 页），请控制在 {MAX_PDF_PAGES} 页以内",
                )
            text = "\n".join(page.get_text() for page in doc)
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"PDF 解析失败：{err}")
    if not text.strip():
        raise HTTPException(status_code=400, detail=f"{name} 没有可提取的文字层（扫描件需先做 OCR）")
    return text[: MAX_CHARS * 2]


def _read_docx(raw: bytes, name: str) -> str:
    """python-docx 本地解析：段落 + 表格单元格。"""
    if not raw.startswith(b"PK"):
        raise HTTPException(status_code=400, detail=f"{name} 不是有效的 DOCX 文件")
    try:
        from docx import Document
    except ImportError:
        raise HTTPException(status_code=400, detail="未安装 python-docx，无法解析 DOCX（可执行 pip install python-docx）")
    try:
        # 解压炸弹防护：先核对 zip 入口与累计解压体积，再交给解析库
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if "word/document.xml" not in archive.namelist():
                raise HTTPException(status_code=400, detail=f"{name} 缺少 DOCX 正文结构")
            total = sum(info.file_size for info in archive.infolist())
            if total > MAX_DOCX_UNCOMPRESSED:
                raise HTTPException(status_code=413, detail="DOCX 解压后体积过大，请精简文档后重试")
        document = Document(io.BytesIO(raw))
        blocks = [p.text for p in document.paragraphs if p.text.strip()]
        for table in document.tables:
            for row in table.rows:
                line = "\t".join(cell.text.strip() for cell in row.cells)
                if line.strip():
                    blocks.append(line)
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"DOCX 解析失败：{err}")
    if not blocks:
        raise HTTPException(status_code=400, detail=f"{name} 没有可提取的文字内容")
    return "\n".join(blocks)[: MAX_CHARS * 2]


ALLOWED_SUFFIXES = (".txt", ".md", ".text", ".pdf", ".docx")


def _parse_with_timeout(raw: bytes, name: str) -> str:
    """解析库放进独立线程池并设硬超时；超时回 400，不把请求挂住。"""
    target = _read_pdf if name.lower().endswith(".pdf") else _read_docx
    future = _parse_pool.submit(target, raw, name)
    try:
        return future.result(timeout=PARSE_TIMEOUT)
    except FutureTimeoutError as err:
        raise HTTPException(status_code=400, detail="文档解析超时，请换用更小的文件") from err


async def _read_upload(file: UploadFile) -> tuple[str, str]:
    """校验扩展名与文件头并按块读取，返回 (文本, 去掉扩展名的标题)。

    纯文本走候选编码打分；PDF / DOCX 用本地解析库取文字层，全程离线。
    """
    name = file.filename or "upload.txt"
    if not name.lower().endswith(ALLOWED_SUFFIXES):
        raise HTTPException(
            status_code=415,
            detail="仅支持 .txt / .md / .text / .pdf / .docx 文件",
        )
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
    lowered = name.lower()
    # 扩展名 + magic bytes 双检：改后缀的二进制文件不能混进解析库
    if lowered.endswith(".pdf") and not raw.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail=f"{name} 不是有效的 PDF 文件")
    if lowered.endswith(".docx") and not raw.startswith(b"PK"):
        raise HTTPException(status_code=400, detail=f"{name} 不是有效的 DOCX 文件")
    if lowered.endswith((".pdf", ".docx")):
        text = await run_in_threadpool(_parse_with_timeout, raw, name)
    else:
        text = await run_in_threadpool(_decode, raw, name)
    return text, name.rsplit(".", 1)[0]


def _check_profile(profile: str) -> str:
    key = (profile or "general").strip()
    if key not in domain_profiles.valid_keys():
        raise HTTPException(status_code=400, detail=f"未知领域包：{key}")
    return key


def _run(
    text: str,
    title: str | None,
    save: bool,
    source: str,
    custom_terms: list[dict] | None = None,
    custom_triggers: dict[str, list[str]] | None = None,
    profile: str = "general",
    language: str = "auto",
) -> ExtractResponse:
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本内容为空")
    if len(text) > MAX_CHARS:
        raise HTTPException(status_code=413, detail=f"文本过长（{len(text)} 字），请控制在 {MAX_CHARS} 字以内")
    lang = (language or "auto").strip().lower()
    if lang not in ("auto", "zh", "en"):
        raise HTTPException(status_code=400, detail=f"未知语言：{language}（仅支持 auto / zh / en）")
    key = _check_profile(profile)
    terms, triggers = domain_profiles.merge(
        custom_terms if custom_terms is not None else db.list_custom_terms(),
        custom_triggers if custom_triggers is not None else db.custom_triggers_by_relation(),
        key,
    )
    try:
        result = analyze(text, custom_terms=terms, custom_triggers=triggers, language=lang)
    except RuntimeError as exc:
        # 英文模型缺失时不 500，给出可操作的提示
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    result["source"] = source
    result["profile"] = key
    result["profile_label"] = domain_profiles.get(key)["label"]
    # 实际引擎由 pipeline 按语言判别写入，不覆盖成请求里的 "auto"
    result["language"] = result.get("language", "zh")
    record_id = (
        db.save_record(result, source=source, title=title or "", profile=key) if save else None
    )
    if record_id:
        result["record_id"] = record_id
    return ExtractResponse(record_id=record_id, result=result)


def _aggregate_in_memory(results: list[dict]) -> dict:
    """save=false 时没有历史记录可查，直接在内存里做同样的跨文档聚合。"""
    entities: Counter = Counter()
    relations: Counter = Counter()
    pairs: Counter = Counter()
    documents = []
    for i, res in enumerate(results):
        documents.append({
            "id": None,
            "title": res.get("title") or f"第 {i + 1} 篇",
            "relation_count": res["stats"]["relation_count"],
        })
        for rel in res["relations"]:
            h = rel.get("head_canonical") or rel["head"]
            t = rel.get("tail_canonical") or rel["tail"]
            entities[(h, rel["head_type"])] += 1
            entities[(t, rel["tail_type"])] += 1
            relations[(rel["relation"], rel["relation_label"])] += 1
            pairs[(h, rel["relation_label"], t)] += 1
    return {
        "records": len(results),
        "entities": sum(res["stats"]["entity_count"] for res in results),
        "relations": sum(res["stats"]["relation_count"] for res in results),
        "top_entities": [
            {"name": k[0], "type": k[1], "cnt": v} for k, v in entities.most_common(10)
        ],
        "top_relations": [
            {"relation": k[0], "relation_label": k[1], "cnt": v} for k, v in relations.most_common(8)
        ],
        "top_pairs": [
            {"head": k[0], "relation_label": k[1], "tail": k[2], "cnt": v}
            for k, v in pairs.most_common(8)
        ],
        "documents": documents,
    }


def _run_batch(
    items: list[tuple[str, str]], save: bool, source: str, profile: str = "general"
) -> dict:
    """逐篇抽取并汇总；单篇失败不打断整批。"""
    if not items:
        raise HTTPException(status_code=400, detail="批量内容为空")
    if len(items) > MAX_BATCH_ITEMS:
        raise HTTPException(status_code=413, detail=f"单批最多 {MAX_BATCH_ITEMS} 篇")
    key = _check_profile(profile)
    custom_terms = db.list_custom_terms()
    custom_triggers = db.custom_triggers_by_relation()

    summaries: list[dict] = []
    record_ids: list[int] = []
    full_results: list[dict] = []
    for index, (text, title) in enumerate(items):
        label = title or (text.strip()[:20] + "…")
        try:
            with _extract_slot():
                res = _run(text, title, save, source, custom_terms, custom_triggers, key)
        except HTTPException as err:
            summaries.append({
                "index": index, "title": label, "record_id": None,
                "entity_count": 0, "relation_count": 0, "elapsed_ms": 0,
                "error": str(err.detail),
            })
            continue
        stats = res.result["stats"]
        summaries.append({
            "index": index,
            "title": label,
            "record_id": res.record_id,
            "entity_count": stats["entity_count"],
            "relation_count": stats["relation_count"],
            "elapsed_ms": stats["elapsed_ms"],
            "error": None,
        })
        if res.record_id:
            record_ids.append(res.record_id)
        full_results.append({"title": label, **res.result})

    ok = [s for s in summaries if s["error"] is None]
    aggregate = (
        db.aggregate_records(record_ids)
        if save and record_ids
        else _aggregate_in_memory(full_results)
    )
    return {
        "total": len(items),
        "succeeded": len(ok),
        "failed": len(items) - len(ok),
        "items": summaries,
        "aggregate": aggregate,
    }


@router.post("/extract", response_model=ExtractResponse, summary="粘贴文本抽取")
def extract_text(payload: ExtractRequest) -> ExtractResponse:
    with _extract_slot():
        return _run(
            payload.text, payload.title, payload.save, "text",
            profile=payload.profile, language=payload.language,
        )


@router.post("/extract/file", response_model=ExtractResponse, summary="上传文本文件抽取")
async def extract_file(
    file: UploadFile = File(..., description=".txt / .md / .text / .pdf / .docx，纯本地解析"),
    save: bool = True,
    profile: str = "general",
    language: str = "auto",
) -> ExtractResponse:
    text, title = await _read_upload(file)
    if not _extract_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="抽取任务过多，请稍后重试")
    try:
        return await run_in_threadpool(
            _run, text, title, save, "file", None, None, profile, language
        )
    finally:
        _extract_slots.release()


@router.post("/extract/batch", summary="批量抽取多段文本")
def extract_batch(payload: BatchRequest) -> dict:
    return _run_batch(
        [(item.text, item.title) for item in payload.items],
        payload.save, "text", payload.profile,
    )


@router.post("/extract/batch/files", summary="批量上传多个文本文件")
async def extract_batch_files(
    files: list[UploadFile] = File(..., description="多个 .txt / .md / .pdf / .docx 文件"),
    save: bool = True,
    profile: str = "general",
) -> dict:
    if len(files) > MAX_BATCH_ITEMS:
        raise HTTPException(status_code=413, detail=f"单批最多 {MAX_BATCH_ITEMS} 个文件")
    items: list[tuple[str, str]] = []
    for file in files:
        text, title = await _read_upload(file)
        items.append((text, title))
    return await run_in_threadpool(_run_batch, items, save, "file", profile)


@router.get("/health", summary="健康检查")
def health() -> dict:
    # 延迟取版本号：版本只在 main 里定义一处，避免两处硬编码各改一半。
    from ..main import VERSION
    from ..verify import capability
    from ..nlp import english

    en_available = english.available()
    return {
        "status": "ok",
        "engine": "dual-engine" if en_available else "rule-based-cn-nlp",
        "engines": {
            "zh": {"type": "rule-based", "available": True},
            "en": {"type": "spacy", "available": en_available},
        },
        "version": VERSION,
        "relation_types": len(RELATION_RULES),
        "profiles": domain_profiles.valid_keys(),
        "custom_terms": len(db.list_custom_terms()),
        "custom_rules": len(db.list_custom_rules()),
        "records": db.overview()["records"],
        "db_size_bytes": db.db_size_bytes(),
        "max_concurrent_extract": MAX_CONCURRENT_EXTRACT,
        "full_text_search": db.fts_enabled(),
        "verify_external": capability()["enabled"],
    }
