# -*- coding: utf-8 -*-
"""自定义关系触发词接口。

只给内置 19 类关系追加领域说法（例如给「投资」补「战略注资」），
不改变关系目录、配色与句式模板；保存后下一次抽取立即生效，无需重启。
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..nlp.lexicon import RELATION_MAP, relation_catalog

router = APIRouter(prefix="/api/rules", tags=["规则"])

_TRIGGER_RE = re.compile(r"[\w\u4e00-\u9fff·]+", re.UNICODE)


class RuleCreate(BaseModel):
    relation_key: str = Field(..., description="内置关系类型的 key")
    trigger: str = Field(..., min_length=2, max_length=24, description="要追加的触发词")


@router.get("", summary="自定义触发词与内置关系目录")
def list_rules() -> dict:
    items = db.list_custom_rules()
    return {
        "items": items,
        "total": len(items),
        "relation_types": [
            {**r, "triggers": list(RELATION_MAP[r["key"]].triggers)} for r in relation_catalog()
        ],
    }


@router.post("", summary="给某类关系追加触发词")
def add_rule(payload: RuleCreate) -> dict:
    key = payload.relation_key.strip()
    trigger = payload.trigger.strip()
    rule = RELATION_MAP.get(key)
    if rule is None:
        raise HTTPException(status_code=400, detail=f"未知关系类型：{key}")
    if not _TRIGGER_RE.fullmatch(trigger):
        raise HTTPException(status_code=400, detail="触发词只能包含中英文、数字与间隔号")
    if trigger in rule.triggers:
        raise HTTPException(status_code=400, detail=f"「{trigger}」已是「{rule.label}」的内置触发词")
    return db.add_custom_rule(key, trigger)


@router.delete("/{rule_id}", summary="删除自定义触发词")
def delete_rule(rule_id: int) -> dict:
    if not db.delete_custom_rule(rule_id):
        raise HTTPException(status_code=404, detail="触发词不存在")
    return {"ok": True}


@router.delete("", summary="清空自定义触发词")
def clear_rules() -> dict:
    return {"ok": True, "removed": db.clear_custom_rules()}
