# -*- coding: utf-8 -*-
"""案卷接口：建档、归档材料、读视图、出报告。

案卷不复制材料：它只记「哪份记录属于这个案卷、以什么角色归档」。
真正的内容、抽取结果、人工校正仍只有一份，所以案卷随时增删材料都不会
产生第二份真相。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .. import dossier
from ..dossier_report import build_dossier_report
from ..samples import DOSSIER_SAMPLE
from . import extract as extract_router

router = APIRouter(prefix="/api", tags=["案卷"])


class DossierCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    subject: str = Field(default="", max_length=64, description="标的公司 / 主体名称")
    subject_type: str = Field(default="ORG", max_length=16)
    note: str = Field(default="", max_length=400)


class DossierUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    subject: str | None = Field(default=None, max_length=64)
    subject_type: str | None = Field(default=None, max_length=16)
    note: str | None = Field(default=None, max_length=400)


class MaterialsPayload(BaseModel):
    record_ids: list[int] = Field(default_factory=list, max_length=200)
    role: str = Field(default="其他材料", max_length=24)


@router.get("/dossiers", summary="案卷列表")
def list_dossiers() -> dict:
    items = dossier.list_dossiers()
    return {"items": items, "total": len(items), "roles": dossier.MATERIAL_ROLES}


@router.post("/dossiers", summary="新建案卷")
def create_dossier(payload: DossierCreate) -> dict:
    row = dossier.create_dossier(payload.name, payload.subject, payload.subject_type, payload.note)
    return row


@router.post("/dossiers/seed", summary="载入内置示例案卷（幂等）")
def seed_dossier() -> dict:
    """把示例案卷的 6 份材料逐篇抽取后归档。

    同名案卷已存在时直接返回已有的，不重复建档，避免连点几次出现一堆
    「示例案卷（2）」。
    """
    existing = next((d for d in dossier.list_dossiers() if d["name"] == DOSSIER_SAMPLE["name"]), None)
    if existing:
        view = dossier.build_view(existing["id"])
        if view:
            return view

    row = dossier.create_dossier(
        DOSSIER_SAMPLE["name"],
        DOSSIER_SAMPLE["subject"],
        DOSSIER_SAMPLE["subject_type"],
        DOSSIER_SAMPLE["note"],
    )
    by_role: dict[str, list[int]] = {}
    for material in DOSSIER_SAMPLE["materials"]:
        try:
            with extract_router._extract_slot():
                resp = extract_router._run(material["text"], material["title"], True, "dossier-seed", profile="general")
        except HTTPException as err:
            raise HTTPException(
                status_code=500, detail=f"示例材料抽取失败：{material['title']}（{err.detail}）"
            ) from err
        if resp.record_id:
            by_role.setdefault(material["role"], []).append(resp.record_id)

    for role, ids in by_role.items():
        dossier.add_materials(row["id"], ids, role)

    view = dossier.build_view(row["id"])
    if not view:
        raise HTTPException(status_code=500, detail="示例案卷创建失败")
    return view


@router.get("/dossiers/{dossier_id}", summary="案卷详情：材料、直接结论、推断、疑点")
def get_dossier(dossier_id: int) -> dict:
    view = dossier.build_view(dossier_id)
    if not view:
        raise HTTPException(status_code=404, detail="案卷不存在")
    return view


@router.put("/dossiers/{dossier_id}", summary="修改案卷基本信息")
def update_dossier(dossier_id: int, payload: DossierUpdate) -> dict:
    row = dossier.update_dossier(dossier_id, **payload.model_dump(exclude_none=True))
    if not row:
        raise HTTPException(status_code=404, detail="案卷不存在")
    return row


@router.delete("/dossiers/{dossier_id}", summary="删除案卷（材料与标注不受影响）")
def delete_dossier(dossier_id: int) -> dict:
    if not dossier.delete_dossier(dossier_id):
        raise HTTPException(status_code=404, detail="案卷不存在")
    return {"ok": True}


@router.post("/dossiers/{dossier_id}/records", summary="把材料归档进案卷")
def add_materials(dossier_id: int, payload: MaterialsPayload) -> dict:
    if not dossier.get_dossier_row(dossier_id):
        raise HTTPException(status_code=404, detail="案卷不存在")
    result = dossier.add_materials(dossier_id, payload.record_ids, payload.role)
    if not result["added"] and not result["updated"] and result["missing"]:
        raise HTTPException(status_code=404, detail="这些记录都不存在")
    return result


@router.delete("/dossiers/{dossier_id}/records/{record_id}", summary="把材料移出案卷")
def remove_material(dossier_id: int, record_id: int) -> dict:
    if not dossier.get_dossier_row(dossier_id):
        raise HTTPException(status_code=404, detail="案卷不存在")
    if not dossier.remove_material(dossier_id, record_id):
        raise HTTPException(status_code=404, detail="这份材料不在该案卷里")
    return {"ok": True}


@router.get(
    "/dossiers/{dossier_id}/report",
    summary="案卷报告（单文件 HTML，可直接打印或另存）",
    response_class=HTMLResponse,
)
def dossier_report(dossier_id: int) -> HTMLResponse:
    view = dossier.build_view(dossier_id)
    if not view:
        raise HTTPException(status_code=404, detail="案卷不存在")
    return HTMLResponse(build_dossier_report(view))
