# -*- coding: utf-8 -*-
"""2.5.0：语言自动识别（auto）+ 手动覆盖 + 版本/品牌改名。"""

from __future__ import annotations

import re

import pytest

from app import main
from app.nlp import language, pipeline


# --------------------------------------------------------------------------- #
# 语言判别：确定性规则，不依赖模型
# --------------------------------------------------------------------------- #

def test_detect_chinese_by_cjk_ratio():
    r = language.detect_language("腾讯收购了搜狗公司，双方将展开合作。")
    assert r["language"] == "zh"
    assert r["method"] == "auto"
    assert r["cjk_chars"] > r["latin_chars"]
    assert r["cjk_ratio"] >= r["threshold"]


def test_detect_english_when_no_cjk():
    r = language.detect_language("Apple acquired Sogou Inc. in 2021.")
    assert r["language"] == "en"
    assert r["cjk_chars"] == 0
    assert r["latin_chars"] > 0


def test_chinese_with_latin_abbrev_still_chinese():
    """中文新闻里夹 CEO / Inc. 这类拉丁缩写不应误判成英文。"""
    r = language.detect_language("苹果公司 CEO 宣布收购 Inc. 子公司，交易金额 5 亿美元。")
    assert r["language"] == "zh"


def test_empty_text_falls_back_to_chinese():
    r = language.detect_language("   ")
    assert r["language"] == "zh"
    assert r["method"] == "default"


def test_digits_only_falls_back_to_chinese():
    r = language.detect_language("2024 18% 2.25")
    assert r["language"] == "zh"
    assert r["method"] == "default"


def test_resolve_manual_overrides_auto():
    lang, info = language.resolve_language("en", "腾讯收购搜狗")
    assert lang == "en"
    assert info is None
    lang, info = language.resolve_language("zh", "Apple acquired Sogou")
    assert lang == "zh"
    assert info is None


def test_resolve_auto_returns_detection():
    lang, info = language.resolve_language("auto", "Apple acquired Sogou")
    assert lang == "en"
    assert info and info["method"] == "auto"
    lang, info = language.resolve_language(None, "腾讯收购搜狗")
    assert lang == "zh"
    assert info is not None


def test_detection_is_deterministic():
    text = "Alibaba invested in Epic Games."
    assert language.detect_language(text) == language.detect_language(text)


# --------------------------------------------------------------------------- #
# pipeline：auto 分流 + 判别信息写进结果
# --------------------------------------------------------------------------- #

def test_pipeline_auto_chinese():
    r = pipeline.analyze("腾讯控股有限公司收购了搜狗公司。", language="auto")
    assert r["language"] == "zh"
    assert r["language_detection"]["language"] == "zh"


def test_pipeline_auto_english():
    if not _spacy_ready():
        pytest.skip("en_core_web_sm 未安装")
    r = pipeline.analyze("Apple acquired Sogou Inc. in 2021.", language="auto")
    assert r["language"] == "en"
    assert r["language_detection"]["language"] == "en"
    assert any(x["relation"] == "acquire" for x in r["relations"])


def test_pipeline_manual_override_has_no_detection():
    r = pipeline.analyze("腾讯收购搜狗公司。", language="zh")
    assert r["language"] == "zh"
    assert r["language_detection"] is None


def test_pipeline_default_keeps_chinese():
    """内部调用不传 language 仍走中文，保证甄别/评测/规则链路零回归。"""
    r = pipeline.analyze("腾讯收购搜狗公司。")
    assert r["language"] == "zh"


def _spacy_ready() -> bool:
    from app.nlp import english
    return english.available()


# --------------------------------------------------------------------------- #
# API：auto / 手动覆盖 / 版本与品牌
# --------------------------------------------------------------------------- #

def test_api_auto_chinese(client):
    resp = client.post("/api/extract", json={
        "text": "腾讯控股有限公司收购了搜狗公司。", "save": False, "language": "auto",
    })
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["language"] == "zh"
    assert result["language_detection"]["method"] == "auto"


def test_api_default_is_auto(client):
    resp = client.post("/api/extract", json={
        "text": "腾讯收购搜狗公司。", "save": False,
    })
    assert resp.status_code == 200
    assert resp.json()["result"]["language_detection"]["method"] == "auto"


def test_api_manual_en(client):
    if not _spacy_ready():
        pytest.skip("en_core_web_sm 未安装")
    resp = client.post("/api/extract", json={
        "text": "Apple acquired Sogou Inc. in 2021.", "save": False, "language": "en",
    })
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["language"] == "en"
    assert result["language_detection"] is None


def test_api_rejects_unknown_language(client):
    resp = client.post("/api/extract", json={
        "text": "腾讯收购搜狗公司。", "save": False, "language": "fr",
    })
    assert resp.status_code == 400
    assert "auto / zh / en" in resp.json()["detail"]


def test_version_and_brand(client):
    # 版本号动态读单一来源，避免每发一版都要改测试断言（2.6.0 起）。
    assert re.match(r"^\d+\.\d+\.\d+$", main.VERSION)
    assert "文本关系抽取与信息甄别系统" in main.app.title
    health = client.get("/api/health").json()
    assert health["version"] == main.VERSION
