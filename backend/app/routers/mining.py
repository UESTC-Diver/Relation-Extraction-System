# -*- coding: utf-8 -*-
"""规则反推接口：把标注集里的补录变成候选触发词。

只有一个读接口。候选要生效必须走已有的 A/B 试跑与规则写入，不在这里另开
一条能改配置的路径——反推的结果在被人确认之前，不该有能力影响线上抽取。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import annotation_store, rule_mining
from ..nlp.pipeline import analysis_lock

router = APIRouter(prefix="/api/mining", tags=["mining"])


@router.get("/triggers", summary="从标注集的补录反推候选触发词")
def mine_triggers(
    set_id: int | None = Query(default=None, description="只看某个标注集；留空看全部"),
    verify: bool = Query(default=True, description="是否用真实抽取自证候选"),
    include_weak: bool = Query(
        default=False, description="是否返回只有单条证据的弱候选"
    ),
) -> dict:
    if set_id is not None and annotation_store.get_set(set_id) is None:
        raise HTTPException(status_code=404, detail="标注集不存在")
    # 自证要把候选临时挂进全局触发词索引再跑抽取，整个过程串行化，
    # 免得与并发抽取互相看见对方的临时配置。
    with analysis_lock:
        return rule_mining.mine(
            set_id=set_id, verify=verify, include_weak=include_weak
        )
