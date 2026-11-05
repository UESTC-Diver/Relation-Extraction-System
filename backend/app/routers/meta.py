# -*- coding: utf-8 -*-
"""历史记录与元数据接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import db
from ..nlp.entity import canonical_name
from ..nlp.lexicon import (
    ENTITY_TYPES,
    RELATION_MAP,
    RELATION_RULES,
    entity_catalog,
    relation_catalog,
)
from ..samples import SAMPLES

router = APIRouter(prefix="/api", tags=["数据"])


class SnapshotRequest(BaseModel):
    title: str = ""
    source: str = "text"
    result: dict


class RelationsReplaceRequest(BaseModel):
    relations: list[dict] = Field(default_factory=list)


def _normalize_relations(
    raw: list[dict], default_base: str = "trigger"
) -> list[dict]:
    """校验并补全前端提交的三元组，计算归一化名与关系标签。"""
    out: list[dict] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"第 {i + 1} 条三元组格式错误")
        head = str(item.get("head") or "").strip()
        tail = str(item.get("tail") or "").strip()
        key = str(item.get("relation") or "").strip()
        head_type = str(item.get("head_type") or "").strip()
        tail_type = str(item.get("tail_type") or "").strip()
        if not head or not tail:
            raise HTTPException(status_code=400, detail=f"第 {i + 1} 条三元组的头/尾实体不能为空")
        if key not in RELATION_MAP:
            raise HTTPException(status_code=400, detail=f"第 {i + 1} 条：未知关系类型 {key}")
        if head_type not in ENTITY_TYPES or tail_type not in ENTITY_TYPES:
            raise HTTPException(status_code=400, detail=f"第 {i + 1} 条：未知实体类型")
        try:
            confidence = float(item.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        try:
            sentence_index = max(0, int(item.get("sentence_index", 0)))
        except (TypeError, ValueError):
            sentence_index = 0
        out.append(
            {
                "head": head[:64],
                "head_canonical": canonical_name(head[:64], head_type),
                "head_type": head_type,
                "relation": key,
                "relation_label": RELATION_MAP[key].label,
                "tail": tail[:64],
                "tail_canonical": canonical_name(tail[:64], tail_type),
                "tail_type": tail_type,
                "confidence": max(0.0, min(1.0, confidence)),
                "evidence": str(item.get("evidence") or "")[:2000],
                "trigger": str(item.get("trigger") or "")[:64],
                "sentence_index": sentence_index,
                "rule_base": str(item.get("rule_base") or default_base)[:20],
            }
        )
    return out


@router.get("/records", summary="历史记录列表")
def records(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    keyword: str = Query(default=""),
) -> dict:
    return db.list_records(limit=limit, offset=offset, keyword=keyword.strip())


@router.get("/records/{record_id}", summary="单条历史记录详情")
def record_detail(record_id: int) -> dict:
    data = db.get_record(record_id)
    if not data:
        raise HTTPException(status_code=404, detail="记录不存在")
    return data


@router.post("/records", summary="保存当前结果快照（含人工校正）")
def record_save(payload: SnapshotRequest) -> dict:
    result = dict(payload.result or {})
    text = str(result.get("text") or "")
    if not text.strip():
        raise HTTPException(status_code=400, detail="文本内容为空")
    if len(text) > 20000:
        raise HTTPException(status_code=413, detail="文本过长，请控制在 20000 字以内")
    result["relations"] = _normalize_relations(result.get("relations") or [])
    stats = dict(result.get("stats") or {})
    stats["relation_count"] = len(result["relations"])
    result["stats"] = stats
    record_id = db.save_record(
        result,
        source=payload.source or "text",
        title=payload.title or "",
    )
    return {"record_id": record_id}


@router.put("/records/{record_id}/relations", summary="保存人工校正的三元组")
def record_relations_replace(record_id: int, payload: RelationsReplaceRequest) -> dict:
    if not db.get_record(record_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    relations = _normalize_relations(payload.relations, default_base="manual")
    db.replace_relations(record_id, relations)
    return db.get_record(record_id)


@router.delete("/records/{record_id}", summary="删除单条记录")
def record_delete(record_id: int) -> dict:
    if not db.delete_record(record_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"ok": True}


@router.delete("/records", summary="清空历史记录")
def records_clear() -> dict:
    return {"ok": True, "removed": db.clear_records()}


@router.get("/stats", summary="统计概览")
def stats() -> dict:
    return db.overview()


@router.get("/samples", summary="内置示例文本")
def samples() -> list[dict]:
    return SAMPLES


@router.get("/schema", summary="实体类型与关系类型目录")
def schema() -> dict:
    return {
        "entity_types": entity_catalog(),
        "relation_types": relation_catalog(),
        "relation_count": len(RELATION_RULES),
    }
