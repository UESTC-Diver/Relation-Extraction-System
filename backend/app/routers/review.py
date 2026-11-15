# -*- coding: utf-8 -*-
"""复核闭环 API：抽取 → 人工复核 → 定稿 → 分享。

路径挂在 /api/records/{id}/review 下，避开 knowledge.py 已有的
/api/review（那是低置信度关系的自动复核队列，两者语义不同）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import review_store

router = APIRouter(prefix="/api/records", tags=["复核"])


class DecisionItem(BaseModel):
    relation_key: str = Field(..., max_length=32)
    decision: str
    note: str = Field(default="", max_length=500)


class DecisionsRequest(BaseModel):
    decisions: list[DecisionItem] = Field(default_factory=list)
    reviewer: str = Field(default="", max_length=40)


class StatusRequest(BaseModel):
    status: str


class FinalizeRequest(BaseModel):
    title: str = Field(default="", max_length=120)


def _unwrap(result: dict | None, not_found: str = "记录不存在") -> dict:
    if result is None:
        raise HTTPException(status_code=404, detail=not_found)
    if result.get("error"):
        raise HTTPException(status_code=409, detail=result["error"])
    return result


@router.get("/{record_id}/review", summary="读取复核状态与逐条结论")
def get_review(record_id: int) -> dict:
    return _unwrap(review_store.get_state(record_id))


@router.put("/{record_id}/review/decisions", summary="批量保存逐条复核结论")
def put_decisions(record_id: int, payload: DecisionsRequest) -> dict:
    return _unwrap(
        review_store.save_decisions(
            record_id, [item.model_dump() for item in payload.decisions], payload.reviewer
        )
    )


@router.put("/{record_id}/review/status", summary="切换复核状态（草稿 / 复核中 / 已定稿）")
def put_status(record_id: int, payload: StatusRequest) -> dict:
    if payload.status not in review_store.STATUSES:
        raise HTTPException(status_code=400, detail="未知的复核状态")
    return _unwrap(review_store.set_status(record_id, payload.status))


@router.post("/{record_id}/review/finalize", summary="定稿并生成不可变快照")
def post_finalize(record_id: int, payload: FinalizeRequest) -> dict:
    return _unwrap(review_store.finalize(record_id, payload.title))


@router.get("/{record_id}/review/snapshots", summary="定稿快照列表")
def list_snapshots(record_id: int) -> dict:
    state = review_store.get_state(record_id)
    if not state:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"items": state["snapshots"], "total": len(state["snapshots"])}


@router.get("/{record_id}/review/snapshots/{snapshot_id}", summary="读取单份定稿快照")
def get_snapshot(record_id: int, snapshot_id: int) -> dict:
    return _unwrap(
        review_store.get_snapshot(record_id, snapshot_id), "定稿快照不存在"
    )
