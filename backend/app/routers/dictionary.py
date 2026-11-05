# -*- coding: utf-8 -*-
"""自定义实体词典接口。

词条在抽取时优先参与实体融合，用于补充内置词典未覆盖的领域实体
（例如医药、能源行业的公司名）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..nlp.lexicon import ENTITY_TYPES

router = APIRouter(prefix="/api/dictionary", tags=["词典"])


class TermCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=32)
    type: str = Field(default="ORG")


@router.get("", summary="自定义词典列表")
def list_terms() -> dict:
    items = db.list_custom_terms()
    return {"items": items, "total": len(items)}


@router.post("", summary="新增自定义词条")
def add_term(payload: TermCreate) -> dict:
    text = payload.text.strip()
    if len(text) < 2:
        raise HTTPException(status_code=400, detail="词条至少需要 2 个字符")
    if payload.type not in ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"未知实体类型：{payload.type}")
    return db.add_custom_term(text, payload.type)


@router.delete("/{term_id}", summary="删除自定义词条")
def delete_term(term_id: int) -> dict:
    if not db.delete_custom_term(term_id):
        raise HTTPException(status_code=404, detail="词条不存在")
    return {"ok": True}


@router.delete("", summary="清空自定义词典")
def clear_terms() -> dict:
    return {"ok": True, "removed": db.clear_custom_terms()}
