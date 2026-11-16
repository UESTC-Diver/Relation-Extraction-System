# -*- coding: utf-8 -*-
"""金标准标注接口：建集、挂材料、逐条判定、补录漏抽、看覆盖度。

和复核接口分开，避免「能不能交付」与「规则准不准」两种结论互相污染。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import annotation_store as store
from ..nlp.lexicon import RELATION_MAP

router = APIRouter(prefix="/api/annotation", tags=["标注"])


class SetCreate(BaseModel):
    name: str = Field(default="", max_length=80, description="标注集名称，例如「某某收购案 20 篇」")
    note: str = Field(default="", max_length=300, description="这个集的口径说明")
    record_ids: list[int] = Field(default_factory=list, description="初始挂进来的记录 id")


class SetRecords(BaseModel):
    record_ids: list[int] = Field(default_factory=list)


class AnnotationItem(BaseModel):
    relation_key: str = Field(default="", description="系统抽出项的指纹；补录项留空，由后端生成")
    verdict: str = Field(default="", description="positive 该抽 / negative 不该抽 / 留空撤回判定")
    head: str = Field(default="", max_length=80)
    relation: str = Field(default="", max_length=40, description="必须是 19 类关系之一")
    tail: str = Field(default="", max_length=80)
    sentence_index: int = Field(default=-1, description="证据句序号，补录时可留空")
    evidence: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=300)
    source: str = Field(default="human", description="human 人判 / inferred 从复核结论预填")


class AnnotationSave(BaseModel):
    items: list[AnnotationItem] = Field(default_factory=list)


@router.get("/sets", summary="标注集列表")
def list_sets() -> dict:
    items = store.list_sets()
    return {"items": items, "total": len(items)}


@router.post("/sets", summary="新建标注集")
def create_set(payload: SetCreate) -> dict:
    data = store.create_set(payload.name, payload.note, payload.record_ids)
    if not data:
        raise HTTPException(status_code=400, detail="标注集创建失败")
    return data


@router.get("/sets/{set_id}", summary="标注集详情（含材料清单）")
def get_set(set_id: int) -> dict:
    data = store.get_set(set_id)
    if not data:
        raise HTTPException(status_code=404, detail="标注集不存在")
    return data


@router.delete("/sets/{set_id}", summary="删除标注集（不影响材料与标注本身）")
def delete_set(set_id: int) -> dict:
    if not store.delete_set(set_id):
        raise HTTPException(status_code=404, detail="标注集不存在")
    return {"deleted": set_id}


@router.post("/sets/{set_id}/records", summary="往标注集里追加材料")
def add_records(set_id: int, payload: SetRecords) -> dict:
    data = store.add_records(set_id, payload.record_ids)
    if not data:
        raise HTTPException(status_code=404, detail="标注集不存在")
    return data


@router.delete("/sets/{set_id}/records", summary="从标注集里移除材料")
def remove_records(set_id: int, payload: SetRecords) -> dict:
    data = store.remove_records(set_id, payload.record_ids)
    if not data:
        raise HTTPException(status_code=404, detail="标注集不存在")
    return data


@router.get("/sets/{set_id}/coverage", summary="标注覆盖度：已判 / 未判比例与正负例分布")
def coverage(set_id: int) -> dict:
    data = store.coverage(set_id)
    if not data:
        raise HTTPException(status_code=404, detail="标注集不存在")
    return data


@router.get("/records/{record_id}", summary="单篇标注：系统三元组、已有判定、补录项与可预填建议")
def get_record(record_id: int) -> dict:
    data = store.get_record_annotation(record_id)
    if not data:
        raise HTTPException(status_code=404, detail="记录不存在")
    return data


@router.put("/records/{record_id}", summary="保存单篇标注（逐条判定与补录漏抽）")
def save_record(record_id: int, payload: AnnotationSave) -> dict:
    if len(payload.items) > 500:
        raise HTTPException(status_code=413, detail="单篇最多 500 条标注")
    bad = sorted(
        {
            item.relation
            for item in payload.items
            if item.relation and item.relation not in RELATION_MAP
        }
    )
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"关系类型不在 19 类内：{'、'.join(bad[:5])}",
        )
    data = store.save_record_annotation(record_id, [i.model_dump() for i in payload.items])
    if not data:
        raise HTTPException(status_code=404, detail="记录不存在")
    return data


@router.delete("/records/{record_id}", summary="清空单篇标注，回到未判状态")
def clear_record(record_id: int) -> dict:
    store.clear_record_annotation(record_id)
    return {"cleared": record_id}
