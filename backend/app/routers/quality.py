# -*- coding: utf-8 -*-
"""质量闭环接口：界面化评测、规则实验室 A/B 试跑、配置版本与实体级校正。"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import db, insights, store
from ..nlp.entity import canonical_name
from ..nlp.evaluation import evaluate, load_gold
from ..nlp.lexicon import ENTITY_TYPES, RELATION_MAP, apply_custom_triggers
from ..nlp.pipeline import analysis_lock, analyze
from ..nlp import profiles

router = APIRouter(prefix="/api", tags=["质量"])

# apply_custom_triggers 原地改写全局索引，试跑必须让「基线 → 候选」两次
# 抽取连续完成，不能与其他试跑交错，也不能被正常抽取插入。
_trial_lock = threading.Lock()


class EvalRequest(BaseModel):
    cases: list[dict] | None = Field(default=None, description="自定义金标准；留空用内置 eval/gold.json")
    save: bool = Field(default=True, description="是否留一条回归历史")


class TriggerCandidate(BaseModel):
    relation_key: str
    trigger: str = Field(min_length=1, max_length=24)


class TrialRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000)
    triggers: list[TriggerCandidate] = Field(default_factory=list)
    profile: str = Field(default="general", description="试跑所用领域包，默认与线上一致")


class VersionCreate(BaseModel):
    name: str = Field(default="", max_length=60)


class EntityReplaceRequest(BaseModel):
    entities: list[dict] = Field(default_factory=list)
    corrections: list[dict] = Field(default_factory=list)


def _rel_key(r: dict) -> tuple[str, str, str]:
    return (
        r.get("head_canonical") or r.get("head") or "",
        r.get("relation") or "",
        r.get("tail_canonical") or r.get("tail") or "",
    )


# --------------------------------------------------------------------------- #
# 评测台
# --------------------------------------------------------------------------- #

@router.get("/eval/gold", summary="内置金标准集（只读）")
def eval_gold() -> dict:
    try:
        cases = load_gold()
    except (OSError, ValueError) as err:
        raise HTTPException(status_code=500, detail=f"金标准集不可读：{err}")
    return {
        "cases": [
            {
                "id": c.get("id"), "title": c.get("title", ""),
                "text": c.get("text", ""),
                "relations": [
                    {"head": h, "relation": rel, "tail": t}
                    for h, rel, t in (c.get("relations") or [])
                ],
            }
            for c in cases
        ],
        "total": len(cases),
    }


@router.post("/eval", summary="跑一次 P/R/F1 评测并保存回归历史")
def run_eval(payload: EvalRequest) -> dict:
    try:
        cases = payload.cases if payload.cases is not None else load_gold()
    except (OSError, ValueError) as err:
        raise HTTPException(status_code=500, detail=f"金标准集不可读：{err}")
    if not cases:
        raise HTTPException(status_code=400, detail="评测用例为空")
    if len(cases) > 100:
        raise HTTPException(status_code=413, detail="单次评测最多 100 条用例")

    report = evaluate(cases)
    run_id = store.save_eval_run(report) if payload.save else None
    return {"run_id": run_id, "report": report}


@router.get("/eval/runs", summary="评测历史（回归曲线）")
def eval_runs(limit: int = Query(default=30, ge=1, le=100)) -> dict:
    items = store.list_eval_runs(limit)
    return {"items": items, "total": len(items)}


@router.get("/eval/runs/{run_id}", summary="单次评测完整报告")
def eval_run_detail(run_id: int) -> dict:
    data = store.get_eval_run(run_id)
    if not data:
        raise HTTPException(status_code=404, detail="评测记录不存在")
    return data


# --------------------------------------------------------------------------- #
# 规则实验室
# --------------------------------------------------------------------------- #

@router.post("/rules/trial", summary="候选触发词 A/B 试跑，返回新增与消失的关系")
def rules_trial(payload: TrialRequest) -> dict:
    profile_key = (payload.profile or "general").strip()
    if profile_key not in profiles.valid_keys():
        raise HTTPException(status_code=400, detail=f"未知领域包：{profile_key}")
    real_terms = db.list_custom_terms()
    real_triggers = db.custom_triggers_by_relation()
    # 领域包既参与基线也参与候选，才能单独看出「新增触发词」带来的差异
    base_terms, base_triggers = profiles.merge(real_terms, real_triggers, profile_key)
    candidate: dict[str, list[str]] = {k: list(v) for k, v in base_triggers.items()}
    added_triggers = []
    for item in payload.triggers:
        key = item.relation_key.strip()
        trigger = item.trigger.strip()
        if key not in RELATION_MAP:
            raise HTTPException(status_code=400, detail=f"未知关系类型：{key}")
        if not trigger:
            raise HTTPException(status_code=400, detail="触发词不能为空")
        bucket = candidate.setdefault(key, [])
        if trigger not in bucket:
            bucket.append(trigger)
            added_triggers.append({"relation_key": key, "trigger": trigger})

    with _trial_lock, analysis_lock:
        try:
            before = analyze(
                payload.text.strip(), custom_terms=base_terms, custom_triggers=base_triggers
            )
            after = analyze(
                payload.text.strip(), custom_terms=base_terms, custom_triggers=candidate
            )
        finally:
            # 试跑不落库：把全局索引恢复成当前真实配置
            apply_custom_triggers(real_triggers)

    before_map = {_rel_key(r): r for r in before["relations"]}
    after_map = {_rel_key(r): r for r in after["relations"]}
    added = [after_map[k] for k in after_map.keys() - before_map.keys()]
    removed = [before_map[k] for k in before_map.keys() - after_map.keys()]
    unchanged = [after_map[k] for k in after_map.keys() & before_map.keys()]
    return {
        "text": payload.text.strip(),
        "profile": profile_key,
        "triggers": added_triggers,
        "before": before["relations"],
        "after": after["relations"],
        "before_count": len(before["relations"]),
        "after_count": len(after["relations"]),
        "added": added, "removed": removed, "unchanged": unchanged,
        "elapsed_ms": round(before["stats"]["elapsed_ms"] + after["stats"]["elapsed_ms"], 1),
    }


@router.get("/insights", summary="规则体检：命中热区、从未命中的触发词与主动建议")
def rule_insights() -> dict:
    return insights.build()


@router.get("/profiles", summary="领域包目录与词条 / 触发词规模")
def domain_profiles() -> dict:
    items = profiles.catalog()
    return {"items": items, "total": len(items), "default": profiles.DEFAULT_PROFILE}


@router.get("/rules/versions", summary="规则配置版本列表")
def rule_versions() -> dict:
    items = store.list_rule_versions()
    return {"items": items, "total": len(items)}


@router.post("/rules/versions", summary="把当前触发词与词典保存为版本快照")
def save_version(payload: VersionCreate) -> dict:
    return {"id": store.save_rule_version(payload.name.strip())}


@router.post("/rules/versions/{version_id}/restore", summary="回滚到某个配置版本")
def restore_version(version_id: int) -> dict:
    data = store.restore_rule_version(version_id)
    if not data:
        raise HTTPException(status_code=404, detail="配置版本不存在")
    # 立即让抽取索引与新配置一致，不必等下一次请求才发现变化
    apply_custom_triggers(db.custom_triggers_by_relation())
    return {"ok": True, **data}


# --------------------------------------------------------------------------- #
# 实体级校正
# --------------------------------------------------------------------------- #

@router.put("/records/{record_id}/entities", summary="校正实体边界、类型与归一写法")
def replace_entities(record_id: int, payload: EntityReplaceRequest) -> dict:
    record = db.get_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    if record.get("review_status") == "final":
        raise HTTPException(status_code=409, detail="记录已定稿，请先在复核台解锁后再修改")
    clean: list[dict[str, Any]] = []
    for i, raw in enumerate(payload.entities):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"第 {i + 1} 个实体格式错误")
        text = str(raw.get("text") or "").strip()[:64]
        typ = str(raw.get("type") or "").strip()[:20]
        if not text:
            raise HTTPException(status_code=400, detail=f"第 {i + 1} 个实体名称为空")
        if typ not in ENTITY_TYPES:
            raise HTTPException(status_code=400, detail=f"第 {i + 1} 个实体类型未知：{typ}")
        canonical = str(raw.get("canonical") or canonical_name(text, typ)).strip()[:64]
        clean.append({**raw, "text": text, "type": typ, "canonical": canonical})

    corrections = [
        {
            "original": str(c.get("original", ""))[:64],
            "corrected": str(c.get("corrected", ""))[:64],
            "type": str(c.get("type", ""))[:20],
        }
        for c in payload.corrections
        if isinstance(c, dict)
    ]
    store.replace_entities(record_id, clean, corrections)
    return db.get_record(record_id)
