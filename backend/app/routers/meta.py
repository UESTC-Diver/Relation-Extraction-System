# -*- coding: utf-8 -*-
"""历史记录与元数据接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..nlp.lexicon import RELATION_RULES, entity_catalog, relation_catalog
from ..samples import SAMPLES

router = APIRouter(prefix="/api", tags=["数据"])


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
