# -*- coding: utf-8 -*-
"""信息甄别接口：一次性只读分析，不写入任何库。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import verify

router = APIRouter(prefix="/api/verify", tags=["信息甄别"])


class VerifyRequest(BaseModel):
    text: str = Field(..., description="待甄别的网传消息文本")
    use_external: bool = Field(default=False, description="是否允许调用外部检索 provider（零 key 免费通道或已配置的付费 provider）")


@router.post("", summary="甄别一段文字")
def verify_endpoint(payload: VerifyRequest) -> dict:
    try:
        return verify.verify_text(payload.text, use_external=payload.use_external)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as err:  # 兜底：联网异常已在引擎内降级，这里是最后一道
        raise HTTPException(status_code=500, detail=f"甄别失败：{err}") from err


@router.get("/capability", summary="查询联网核验能力")
def capability_endpoint() -> dict:
    return verify.capability()


@router.get("/examples", summary="获取演示样例")
def examples_endpoint() -> list[dict[str, str]]:
    return verify.seed_examples()
