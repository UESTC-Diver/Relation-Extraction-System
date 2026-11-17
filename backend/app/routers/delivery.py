# -*- coding: utf-8 -*-
"""交付与集成：离线报告、只读分享页、项目包、后台批量任务。"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .. import db, review_store, security, store
from ..report import build_report_html
from . import extract

router = APIRouter(tags=["交付"])

# 后台批量最多 100 篇，任务本身在独立线程池里跑，不占用 FastAPI 的请求线程。
MAX_TASK_ITEMS = 100
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="batch")

# 只读分享页：内容可能含用户原文，不允许共享缓存、不允许被搜索引擎收录。
_READONLY_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class ReportRequest(BaseModel):
    record_id: int | None = None
    title: str = ""
    result: dict | None = None


class ShareRequest(BaseModel):
    record_id: int
    ttl_seconds: int = Field(default=7 * 24 * 3600, ge=60, le=90 * 24 * 3600)


class ProjectImportRequest(BaseModel):
    payload: dict
    mode: str = Field(default="merge", pattern="^(merge|replace)$")


class TaskItem(BaseModel):
    text: str
    title: str = ""


class TaskBatchRequest(BaseModel):
    items: list[TaskItem] = Field(default_factory=list)
    save: bool = True
    profile: str = "general"


def _safe_filename(value: str) -> str:
    clean = re.sub(r'[\\/:*?"<>|\r\n]+', "-", value or "未命名文本").strip(" -. ")
    return (clean or "未命名文本")[:60]


def _result_from_record(record_id: int) -> dict | None:
    rec = db.get_record(record_id)
    if not rec:
        return None
    return {
        "title": rec["title"],
        "text": rec["text"],
        "profile": rec.get("profile") or "general",
        "profile_label": rec.get("profile_label") or "",
        "entities": rec["entities"],
        "relations": rec["relations"],
        "stats": {
            "char_count": rec["char_count"],
            "sentence_count": rec["sentence_count"],
            "entity_count": rec["entity_count"],
            "relation_count": rec["relation_count"],
            "elapsed_ms": rec["elapsed_ms"],
        },
        "record_id": record_id,
    }


@router.post("/api/report", summary="生成单文件离线 HTML 报告")
def make_report(payload: ReportRequest) -> dict:
    data = _result_from_record(payload.record_id) if payload.record_id else payload.result
    if not data:
        raise HTTPException(status_code=404, detail="记录不存在或未提供结果")
    if payload.title:
        data = {**data, "title": payload.title}
    html = build_report_html(
        data,
        readonly_link=False,
        review=review_store.report_review(payload.record_id),
    )
    return {
        "filename": f"{_safe_filename(data.get('title', ''))}-分析报告.html",
        "html": html,
        "bytes": len(html.encode("utf-8")),
    }


@router.post("/api/report/share", summary="生成带签名与有效期的只读报告链接")
def make_share_link(payload: ShareRequest, request: Request) -> dict:
    if not db.get_record(payload.record_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    base = str(request.base_url).rstrip("/")
    return {
        "url": security.sign_report(payload.record_id, payload.ttl_seconds, base),
        "signed": True,
        "enforced": security.signing_enabled(),
        "ttl_seconds": payload.ttl_seconds,
    }


@router.get("/report/{record_id}", include_in_schema=False, response_class=HTMLResponse)
def shared_report(
    record_id: int,
    expires: str = Query(default=""),
    token: str = Query(default=""),
) -> HTMLResponse:
    """独立只读报告页：不加载工作台 JS，也不暴露编辑与历史入口。

    生产配置 APP_REPORT_SECRET 后，裸 id 无法访问，必须带有效签名与过期时间；
    本机未配置时保持开箱即用（旧链接与回归测试不受影响）。
    """
    if security.signing_enabled() and not security.verify_report(record_id, expires, token):
        return HTMLResponse(
            "<!DOCTYPE html><html lang='zh-CN'><meta charset='utf-8'>"
            "<body style='font-family:system-ui;padding:48px;background:#f6f3ea;color:#1e1c18'>"
            "<h1 style='font-weight:500'>链接无效或已过期</h1>"
            "<p>请回到工作台重新生成分享链接。</p>"
            "<a style='color:#a8322a' href='/'>返回首页</a></body></html>",
            status_code=403,
            headers=_READONLY_HEADERS,
        )
    data = _result_from_record(record_id)
    if not data:
        return HTMLResponse(
            "<!DOCTYPE html><html lang='zh-CN'><meta charset='utf-8'>"
            "<body style='font-family:system-ui;padding:48px;background:#f6f3ea;color:#1e1c18'>"
            "<h1 style='font-weight:500'>报告不存在</h1><p>这条记录可能已被删除。</p>"
            "<a style='color:#a8322a' href='/'>返回首页</a></body></html>",
            status_code=404,
            headers=_READONLY_HEADERS,
        )
    return HTMLResponse(
        build_report_html(
            data, readonly_link=True, review=review_store.report_review(record_id)
        ),
        headers=_READONLY_HEADERS,
    )


@router.get("/api/project/export", summary="导出完整项目包（文本 / 校正 / 词典 / 规则 / 金标准）")
def project_export() -> dict:
    return store.export_project()


@router.post("/api/project/import", summary="导入项目包（merge 追加 / replace 覆盖）")
def project_import(payload: ProjectImportRequest) -> dict:
    try:
        return store.import_project(payload.payload, mode=payload.mode)
    except (ValueError, TypeError) as err:
        raise HTTPException(status_code=400, detail=f"项目包格式不正确：{err}")


# --------------------------------------------------------------------------- #
# 后台批量任务
# --------------------------------------------------------------------------- #

def _execute_batch_task(
    task_id: str, items: list[TaskItem], save: bool, profile: str = "general"
) -> None:
    summaries: list[dict] = []
    record_ids: list[int] = []
    full_results: list[dict] = []
    try:
        for index, item in enumerate(items):
            label = item.title or (item.text.strip()[:20] + "…")
            try:
                with extract._extract_slot():
                    res = extract._run(item.text, item.title, save, "text", profile=profile)
            except HTTPException as err:
                summaries.append({
                    "index": index, "title": label, "record_id": None,
                    "entity_count": 0, "relation_count": 0,
                    "elapsed_ms": 0, "error": str(err.detail),
                })
            else:
                st = res.result["stats"]
                summaries.append({
                    "index": index, "title": label, "record_id": res.record_id,
                    "entity_count": st["entity_count"],
                    "relation_count": st["relation_count"],
                    "elapsed_ms": st["elapsed_ms"], "error": None,
                })
                if res.record_id:
                    record_ids.append(res.record_id)
                full_results.append({"title": label, **res.result})
            store.update_task(task_id, done=index + 1)

        ok = [s for s in summaries if not s["error"]]
        aggregate = (
            db.aggregate_records(record_ids)
            if save and record_ids
            else extract._aggregate_in_memory(full_results)
        )
        store.update_task(
            task_id, status="done",
            result_json={
                "total": len(items), "succeeded": len(ok),
                "failed": len(items) - len(ok),
                "items": summaries, "aggregate": aggregate,
            },
        )
    except Exception as err:  # 任务线程里的异常必须落到状态里，否则前端会一直轮询
        store.update_task(task_id, status="failed", error=str(err)[:300])


@router.post("/api/tasks/batch", summary="提交后台批量抽取任务，立即返回任务 id")
def submit_batch(payload: TaskBatchRequest) -> dict:
    if not payload.items:
        raise HTTPException(status_code=400, detail="批量内容为空")
    if len(payload.items) > MAX_TASK_ITEMS:
        raise HTTPException(status_code=413, detail=f"后台任务最多 {MAX_TASK_ITEMS} 篇")
    task_id = store.create_task("batch", len(payload.items))
    _pool.submit(_execute_batch_task, task_id, payload.items, payload.save, payload.profile)
    return {"task_id": task_id, "total": len(payload.items), "status": "running"}


@router.get("/api/tasks", summary="后台任务列表")
def tasks(limit: int = Query(default=20, ge=1, le=50)) -> dict:
    items = store.list_tasks(limit)
    return {"items": items, "total": len(items)}


@router.get("/api/tasks/{task_id}", summary="查询后台任务进度与结果")
def task_status(task_id: str) -> dict:
    data = store.get_task(task_id)
    if not data:
        raise HTTPException(status_code=404, detail="任务不存在")
    return data
