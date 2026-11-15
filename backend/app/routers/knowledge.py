# -*- coding: utf-8 -*-
"""知识库接口：把「单篇文本的一次抽取」变成可跨文档检索的资产。

全局实体与关系网络都直接查 relations 的归一化字段，不另建实体表，
因此人工校正、删除记录、导入项目包之后不需要额外同步。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import store

router = APIRouter(prefix="/api", tags=["知识库"])


class TagsPayload(BaseModel):
    tags: list[str] = Field(default_factory=list)


@router.get("/entities", summary="跨文档实体检索")
def entities(
    q: str = Query(default="", description="实体名子串"),
    type: str = Query(default="", description="实体类型 key"),
    limit: int = Query(default=40, ge=1, le=200),
) -> dict:
    return store.global_entities(q=q.strip(), entity_type=type.strip(), limit=limit)


@router.get("/entities/profile", summary="全局实体画像：别名、来源、全部关系")
def entity_profile(name: str = Query(..., min_length=1, max_length=64)) -> dict:
    return store.entity_profile(name.strip())


@router.get("/graph/global", summary="跨文档关系网络")
def graph_global(
    relation: str = Query(default="", description="只保留某类关系"),
    limit: int = Query(default=120, ge=1, le=400),
) -> dict:
    return store.global_graph(relation=relation.strip(), limit=limit)


@router.get("/tags", summary="全部记录标签及使用次数")
def tags() -> dict:
    items = store.list_tags()
    return {"items": items, "total": len(items)}


@router.put("/records/{record_id}/tags", summary="设置单条记录的标签")
def set_tags(record_id: int, payload: TagsPayload) -> dict:
    result = store.set_record_tags(record_id, payload.tags)
    if result is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"ok": True, "tags": result}


@router.get("/conflicts", summary="跨文档关系冲突（同一实体对被判成不同关系）")
def conflicts(limit: int = Query(default=30, ge=1, le=100)) -> dict:
    return store.conflicts(limit=limit)


@router.get("/review", summary="低置信度复核队列")
def review(
    threshold: float = Query(default=0.8, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    return store.review_queue(threshold=threshold, limit=limit)
