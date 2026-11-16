# -*- coding: utf-8 -*-
"""2.3.0 信息甄别：分层裁决、可疑信号、联网降级、只读与隐私约束。"""

from __future__ import annotations

import pytest

from app import verify


# --------------------------------------------------------------------------- #
# 分层裁决
# --------------------------------------------------------------------------- #


def test_three_tiers_are_distinguished():
    """三个内置样例必须落到三个不同的层级——这是「判断力」的核心证据。"""
    examples = {e["id"]: e["text"] for e in verify.seed_examples()}
    rumor = verify.verify_text(examples["rumor"])
    grounded = verify.verify_text(examples["grounded"])
    mixed = verify.verify_text(examples["mixed"])

    assert rumor["overall"]["verdict"] == verify.VERDICT_UNCHECKABLE
    assert grounded["overall"]["verdict"] == verify.VERDICT_GROUNDED
    assert mixed["overall"]["verdict"] == verify.VERDICT_QUESTION


def test_grounded_claim_has_evidence_and_sentence():
    r = verify.verify_text("据新华社报道，腾讯今日宣布收购搜狗公司。")
    grounded = [c for c in r["claims"] if c["verdict"] == verify.VERDICT_GROUNDED]
    assert grounded
    claim = grounded[0]
    assert claim["head"] and claim["tail"]
    assert len(claim["evidence"]) >= 8
    assert claim["sentence_index"] >= 0
    assert claim["evidence_sentence"]


def test_every_claim_has_explainable_reasons():
    r = verify.verify_text("腾讯收购搜狗公司，闻名世界。")
    for c in r["claims"]:
        assert c["reasons"], "每条断言都必须给出可解释的分级理由"
        assert c["verdict"] in verify.VERDICT_LABELS
        assert isinstance(c["score"], int)


def test_same_text_is_deterministic():
    """确定性是本功能的底线：同文本两次结果必须逐字一致（去掉时间戳）。"""
    text = "腾讯收购搜狗公司，近日有消息称绝对属实。"
    a = verify.verify_text(text)
    b = verify.verify_text(text)
    for key in ("overall", "signals", "claims", "external", "disclaimer"):
        assert a[key] == b[key]
    assert a["fingerprint"] == b["fingerprint"]


# --------------------------------------------------------------------------- #
# 可疑信号
# --------------------------------------------------------------------------- #


def test_signals_detected_with_position_and_matched_text():
    text = "紧急通知！据悉近日有内部消息，绝对准确无误，看到赶紧转发。"
    r = verify.verify_text(text)
    keys = {s["key"] for s in r["signals"]}
    assert {"sensation", "vague_source", "vague_time", "absolute", "clickbait"} <= keys
    for s in r["signals"]:
        assert s["matched"] in text
        assert text[s["position"]:].startswith(s["matched"])
        assert s["hint"]


def test_no_signal_on_clean_news():
    r = verify.verify_text("腾讯收购搜狗公司。")
    assert r["signals"] == []


# --------------------------------------------------------------------------- #
# 联网降级与隐私约束
# --------------------------------------------------------------------------- #


def test_no_key_uses_free_provider_and_offline_opt_in(monkeypatch):
    """无 key 时 capability 报告零 key 免费通道可用；但默认不联网，勾选才联网。"""
    monkeypatch.delenv("VERIFY_PROVIDER", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    caps = verify.capability()
    assert caps["enabled"] is True
    assert caps["provider"] == "free"
    assert "免费" in caps["provider_label"]

    # 默认离线：即使免费通道可用，不显式请求就不发任何网络调用
    class Boom(verify.SearchProvider):
        name = "free"
        def available(self):
            return True  # 假装可用，验证「available 为真」也不该被默认调用
        def search(self, query):
            raise AssertionError("默认离线：未请求联网时绝不能发起检索")

    monkeypatch.setattr(verify, "build_provider", lambda: Boom())
    r = verify.verify_text("腾讯收购搜狗公司。")
    assert all(c["external"]["status"] == "skipped" for c in r["claims"])


def test_query_is_short_and_does_not_contain_full_text():
    """外部检索 query 只能由实体名 + 关系短语拼成，长度受限且不含原文。"""
    long_tail = "这是一段绝不可能被当成实体名的超长描述文字" * 5
    result = {
        "sentences": [],
        "relations": [{
            "head": "腾讯", "head_canonical": "腾讯", "head_type": "ORG",
            "relation": "acquire", "relation_label": "收购",
            "tail": long_tail, "tail_canonical": long_tail, "tail_type": "ORG",
            "confidence": 0.9, "evidence": "腾讯收购。" * 4, "sentence_index": 0,
        }],
    }
    claims = verify._build_claims(result)
    q = claims[0]["query"]
    assert len(q) <= 60
    assert long_tail not in q


def test_external_evidence_is_classified_and_refute_detected(monkeypatch):
    """配了 key 时：来源分级、辟谣识别、域名去重都要正确；失败要降级不抛错。"""

    class FakeProvider(verify.SearchProvider):
        name = "serper"
        label = "测试"
        def available(self):
            return True
        def search(self, query):
            return [
                {"title": "官方辟谣：相关传闻不实", "url": "https://www.gov.cn/x/x.html", "snippet": "经核实属谣言"},
                {"title": "媒体报道", "url": "https://www.sina.com.cn/a", "snippet": "双方达成收购协议"},
            ]

    monkeypatch.setattr(verify, "build_provider", lambda: FakeProvider())
    r = verify.verify_text("腾讯收购搜狗公司。", use_external=True)
    checked = [c for c in r["claims"] if c["external"]["status"] == "checked"]
    assert checked
    ext = checked[0]["external"]
    assert ext["refuted"] is True
    tiers = {e["source_tier"] for e in ext["evidence"]}
    assert "official" in tiers and "major" in tiers
    assert any(e["refuting"] for e in ext["evidence"])


def test_provider_error_degrades_to_error_status(monkeypatch):
    class FailingProvider(verify.SearchProvider):
        name = "serper"
        def available(self):
            return True
        def search(self, query):
            raise RuntimeError("network down")

    monkeypatch.setattr(verify, "build_provider", lambda: FailingProvider())
    r = verify.verify_text("腾讯收购搜狗公司。", use_external=True)
    assert all(c["external"]["status"] == "error" for c in r["claims"])


def test_provider_selection_off_free_and_explicit(monkeypatch):
    monkeypatch.setenv("VERIFY_PROVIDER", "off")
    assert verify.build_provider().name == "none"
    monkeypatch.setenv("VERIFY_PROVIDER", "free")
    assert verify.build_provider().name == "free"
    monkeypatch.setenv("VERIFY_PROVIDER", "auto")
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert verify.build_provider().name == "free"  # auto 无 key → 零 key 免费通道
    monkeypatch.setenv("VERIFY_PROVIDER", "serper")
    assert verify.build_provider().name == "none"  # 选了但没 key → 降级
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    assert verify.build_provider().name == "serper"


def test_tavily_uses_bearer_auth_header(monkeypatch):
    """回归防护：Tavily 必须走 Authorization Bearer，旧版塞 body 的 api_key 会 401。"""
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return b'{"results": []}'

    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.headers)
        captured["body"] = req.data.decode("utf-8")
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(verify.urllib.request, "urlopen", fake_urlopen)
    provider = verify.TavilyProvider("tvly-test-key")
    provider.search("腾讯 收购 搜狗")

    headers = {k.lower(): v for k, v in captured["headers"].items()}
    assert "authorization" in headers
    assert headers["authorization"] == "Bearer tvly-test-key"
    assert "api_key" not in captured["body"]  # 不能再出现在 body 里
    assert "topic" in captured["body"] and '"news"' in captured["body"]


def test_free_provider_is_zero_key_and_degrades_silently(monkeypatch):
    """零 key 免费 provider 永远 available；两个来源都挂时返回空而非抛错。"""
    def boom(*args, **kwargs):
        raise RuntimeError("no network")

    monkeypatch.setattr(verify.urllib.request, "urlopen", boom)
    p = verify.FreeProvider()
    assert p.available() is True
    assert p.search("腾讯 收购 搜狗") == []


# --------------------------------------------------------------------------- #
# 只读 + 边界 + 输入校验
# --------------------------------------------------------------------------- #


def test_verify_does_not_write_database(client):
    """甄别是一次性只读分析：跑完前后历史记录数不能变。"""
    before = client.get("/api/records").json()["total"]
    client.post("/api/verify", json={"text": "腾讯收购搜狗公司。", "use_external": False})
    after = client.get("/api/records").json()["total"]
    assert before == after


def test_disclaimer_present_and_no_true_false_stamp():
    r = verify.verify_text("腾讯收购搜狗公司。")
    assert "不等于事实真伪判定" in r["disclaimer"]
    assert r["overall"]["verdict"] in verify.VERDICT_LABELS


@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_text_rejected(bad):
    with pytest.raises(ValueError):
        verify.verify_text(bad)


def test_too_long_text_rejected():
    with pytest.raises(ValueError):
        verify.verify_text("腾讯" * (verify.MAX_CHARS + 10))


# --------------------------------------------------------------------------- #
# 接口
# --------------------------------------------------------------------------- #


def test_verify_api_returns_report(client):
    res = client.post("/api/verify", json={"text": "腾讯收购搜狗公司。", "use_external": False})
    assert res.status_code == 200
    data = res.json()
    assert "overall" in data and "claims" in data and "signals" in data
    assert data["overall"]["verdict"] in verify.VERDICT_LABELS


def test_verify_api_bad_request(client):
    res = client.post("/api/verify", json={"text": "  "})
    assert res.status_code == 400


def test_capability_and_examples_api(client):
    caps = client.get("/api/verify/capability").json()
    assert caps["enabled"] is True  # 零 key 免费通道默认可用
    assert caps["provider"] == "free"
    assert "privacy_note" in caps
    exs = client.get("/api/verify/examples").json()
    assert len(exs) >= 3
    assert {e["id"] for e in exs} >= {"rumor", "grounded", "mixed"}


def test_health_exposes_verify_flag(client):
    h = client.get("/api/health").json()
    assert h["version"] == "2.3.0"
    assert "verify_external" in h
