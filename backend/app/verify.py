# -*- coding: utf-8 -*-
"""信息甄别：把一段网传消息拆成可核查的断言，逐条给出可信度分层与证据。

为什么要自己写判断逻辑，而不是丢给大模型
------------------------------------------
这一段是这个项目「体现人思考过」的核心，所以每一条判断都必须满足三条硬约束：

1. **确定性、可复现**：同一段文字，任何时候跑出来的结论都一样。不用 LLM，
   因为 LLM 换个温度、升个版本就可能翻脸，也没法写进测试断言。
2. **每个结论指回原句**：可信度不是凭空打的分数，它由一组「命中了哪条规则」
   和「哪句话支撑/削弱了它」推导出来，前端可以一路点回原文。
3. **说清楚不知道什么**：甄别的目标不是盖一个「真/假」的章，而是把「哪几句
   有据可查、哪几句存疑、哪几句根本无从核实」摆出来，让使用的人自己判断。
   凡是外部检索没覆盖到的，一律标注「未外部核实」，绝不默认当成「属实」。

架构：三段式，每段都可单独替换
------------------------------
- **本地观察**（纯函数，零网络）：句式可疑信号 + 关系抽取结果 + 证据质量。
  这是基线和主体，断网也完整可用。
- **外部核验**（可配置 provider）：默认 ``null`` provider，不发任何请求；
  配置了 key 才走 Serper / Tavily。只送「实体名 + 关系短句」，绝不上传全文。
- **AI 表达层**（默认关闭）：可选把结论改写成一段人话摘要，由供应商 SDK 完成，
  且强制网关能看到「AI 生成」标识。它不参与任何打分，关掉不影响结论。

三条安全底线
------------
- 全文不出网：外部检索 query 由白名单字段拼成，长度上限，且剔除长句。
- 结论不落库：甄别是一次性只读分析，不写 records / relations，不污染抽取库与评测集。
- URL 只回显不代理：外部证据的链接原样返回给前端新窗口打开，服务端不代理抓取。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any

from . import db
from .nlp.pipeline import analyze

# --------------------------------------------------------------------------- #
# 常量与配置
# --------------------------------------------------------------------------- #

VERDICT_GROUNDED = "grounded"   # 有据可查：原文给出可核查的具体信息，且有证据句
VERDICT_QUESTION = "question"   # 存疑待核：说法模糊 / 只有单方说法 / 缺关键要素
VERDICT_UNCHECKABLE = "uncheckable"  # 无从核实：情绪化、口号式、无可核查事实内核
VERDICT_ORDER = {VERDICT_GROUNDED: 0, VERDICT_QUESTION: 1, VERDICT_UNCHECKABLE: 2}

VERDICT_LABELS = {
    VERDICT_GROUNDED: "有据可查",
    VERDICT_QUESTION: "存疑待核",
    VERDICT_UNCHECKABLE: "无从核实",
}

MAX_CHARS = 8000
MAX_EXTERNAL_QUERIES = 6
EXTERNAL_TIMEOUT = float(os.environ.get("VERIFY_EXTERNAL_TIMEOUT", "6"))

# 句式可疑信号。每一条都是「文本里出现这类写法，就值得提醒读者」的确定性规则。
# level: high 会单独抬高整段的风险，medium 只作用于命中的那一句。
SIGNAL_RULES: list[dict[str, Any]] = [
    {
        "key": "absolute",
        "label": "绝对化表述",
        "level": "high",
        "pattern": r"(一定|必然|百分之百|绝对|肯定|铁定|万无一失|100%|百分百)",
        "hint": "用了不留余地的措辞，现实中的事实判断很少这么绝对。",
    },
    {
        "key": "sensation",
        "label": "煽动性措辞",
        "level": "high",
        "pattern": r"(震惊|紧急|刚刚|突发|劲爆|重磅|不看后悔|转疯了|紧急通知|扩散)",
        "hint": "煽动情绪、催促转发的措辞，常见于追求传播而非传递信息的文本。",
    },
    {
        "key": "vague_source",
        "label": "模糊信源",
        "level": "medium",
        "pattern": r"(据悉|据了解|知情人士|内部消息|有消息称|据传|网传|网友爆料|有人说|据说)",
        "hint": "没有点名具体来源，读者无法回溯核实这句话出自哪里。",
    },
    {
        "key": "vague_time",
        "label": "时间模糊",
        "level": "medium",
        "pattern": r"(近日|日前|最近|近期|前不久|这段时间|这两天)",
        "hint": "只有模糊时间，没有确切日期，事后很难对证。",
    },
    {
        "key": "clickbait",
        "label": "诱导点击",
        "level": "medium",
        "pattern": r"(点击|扫码|速看|马上删|赶紧看|立即查看|点进来看|转发)",
        "hint": "把注意力引向点击或转发，而不是信息本身。",
    },
    {
        "key": "superlative_claim",
        "label": "夸大断言",
        "level": "medium",
        "pattern": r"(史上最|前所未有|震惊全国|全网沸腾|彻底崩盘|全面崩塌|一夜暴富|血本无归)",
        "hint": "强度极高的定性，通常需要强证据支撑，单独出现时应当打个问号。",
    },
]

# 外部证据来源分级。域名后缀命中即定级，逐级降权；都不命中算 unknown。
_OFFICIAL_HINTS = (".gov.cn", ".court.gov.cn", ".people.com.cn", ".xinhuanet.com", ".news.cn")
_MAJOR_HINTS = ("sina.", "sohu.", "163.com", "qq.com", "thepaper.cn", "caixin.com", "yicai.com", "cctv.")
_COMMUNITY_HINTS = ("zhihu.", "weibo.", "bbs.", "tieba.", "douyin.", "xiaohongshu.", "bilibili.")
_SOURCE_LABELS = {
    "official": "官方 / 权威机构",
    "major": "主流媒体",
    "community": "社区 / 自媒体",
    "unknown": "未识别来源",
    "none": "未外部核实",
}

# 削弱信号：外部摘要里出现这些词，说明这条说法可能被否认或辟谣。
_REFUTE_WORDS = ("辟谣", "不实", "谣言", "澄清", "否认", "回应称", "并非", "系误传", "假的")

# 外部检索 query 的停用片段：这些词对定位一条断言没帮助，还会把 query 撑成句子。
_QUERY_STOP = re.compile(r"(近日|日前|据悉|据了解|网传|网友|消息|称|表示|宣布|官方|近日)")


# --------------------------------------------------------------------------- #
# 能力探测：provider 抽象
# --------------------------------------------------------------------------- #


class SearchProvider:
    """外部检索的最小接口：给定短句，返回证据列表。"""

    name = "none"
    label = "未启用"

    def search(self, query: str) -> list[dict[str, Any]]:  # pragma: no cover - 接口定义
        return []

    def available(self) -> bool:
        return False


class NullProvider(SearchProvider):
    """默认 provider：不发任何请求，明确告知用户当前是离线模式。"""

    name = "none"
    label = "离线模式"

    def __init__(self, reason: str = "") -> None:
        self.reason = reason

    def search(self, query: str) -> list[dict[str, Any]]:
        return []


class SerperProvider(SearchProvider):
    """Serper 搜索 API（需 SERPER_API_KEY）。仅发送短句，不发送全文。"""

    name = "serper"
    label = "Serper 联网核验"
    endpoint = "https://google.serper.dev/search"

    def __init__(self, key: str) -> None:
        self.key = key

    def available(self) -> bool:
        return bool(self.key)

    def search(self, query: str) -> list[dict[str, Any]]:
        payload = json.dumps({"q": query, "num": 5}).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"X-API-KEY": self.key, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=EXTERNAL_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = []
        for item in data.get("organic", [])[:5]:
            title = str(item.get("title") or "").strip()
            link = str(item.get("link") or "").strip()
            snippet = str(item.get("snippet") or item.get("description") or "").strip()
            # URL 必须来自响应且是 http(s)，杜绝 javascript: 之类的注入
            if not (title and link.startswith(("http://", "https://"))):
                continue
            out.append({"title": title[:160], "url": link[:500], "snippet": snippet[:300]})
        return out


class TavilyProvider(SearchProvider):
    """Tavily 搜索 API（需 TAVILY_API_KEY）。仅发送短句，不发送全文。"""

    name = "tavily"
    label = "Tavily 联网核验"
    endpoint = "https://api.tavily.com/search"

    def __init__(self, key: str) -> None:
        self.key = key

    def available(self) -> bool:
        return bool(self.key)

    def search(self, query: str) -> list[dict[str, Any]]:
        payload = json.dumps(
            {"api_key": self.key, "query": query, "max_results": 5, "search_depth": "basic"}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=EXTERNAL_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = []
        for item in data.get("results", [])[:5]:
            title = str(item.get("title") or "").strip()
            link = str(item.get("url") or "").strip()
            snippet = str(item.get("content") or "").strip()
            if not (title and link.startswith(("http://", "https://"))):
                continue
            out.append({"title": title[:160], "url": link[:500], "snippet": snippet[:300]})
        return out


def build_provider() -> SearchProvider:
    """按环境变量选择 provider；任何异常都降级成 NullProvider，绝不让联网挂掉分析。"""
    choice = os.environ.get("VERIFY_PROVIDER", "auto").strip().lower()
    serper_key = os.environ.get("SERPER_API_KEY", "").strip()
    tavily_key = os.environ.get("TAVILY_API_KEY", "").strip()

    if choice == "off":
        return NullProvider("已通过配置关闭联网核验")
    if choice == "serper":
        return SerperProvider(serper_key) if serper_key else NullProvider("已选择 Serper，但未配置 SERPER_API_KEY")
    if choice == "tavily":
        return TavilyProvider(tavily_key) if tavily_key else NullProvider("已选择 Tavily，但未配置 TAVILY_API_KEY")
    # auto：谁配了 key 用谁，优先 Serper
    if serper_key:
        return SerperProvider(serper_key)
    if tavily_key:
        return TavilyProvider(tavily_key)
    return NullProvider("未配置搜索服务密钥，当前为离线模式")


def capability() -> dict[str, Any]:
    """给前端展示的「联网能力」状态，不泄露任何 key 内容。"""
    provider = build_provider()
    return {
        "enabled": provider.available(),
        "provider": provider.name,
        "provider_label": provider.label,
        "reason": getattr(provider, "reason", ""),
        "options": ["off", "auto", "serper", "tavily"],
        "privacy_note": "联网时只发送实体名与关系短语（不超过 60 字），不会上传原文全文。",
    }


# --------------------------------------------------------------------------- #
# 第一段：本地观察（纯函数，零网络）
# --------------------------------------------------------------------------- #


def _compile_signals() -> list[tuple[dict[str, Any], re.Pattern[str]]]:
    return [(rule, re.compile(rule["pattern"])) for rule in SIGNAL_RULES]


_SIGNALS = _compile_signals()


def _hash_text(text: str) -> str:
    """内容指纹：前端可用它缓存同一段文字的甄别结果。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _skill_check(text: str) -> list[dict[str, Any]]:
    """句式可疑信号。按出现顺序去重，指回命中的原词。"""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule, pattern in _SIGNALS:
        for m in pattern.finditer(text):
            if rule["key"] in seen:
                break
            seen.add(rule["key"])
            found.append(
                {
                    "key": rule["key"],
                    "label": rule["label"],
                    "level": rule["level"],
                    "matched": m.group(0),
                    "position": m.start(),
                    "hint": rule["hint"],
                }
            )
            break
    found.sort(key=lambda x: x["position"])
    return found


def _query_for(rel: dict[str, Any]) -> str:
    """从一条关系拼出最小检索短句：谁 + 什么关系 + 谁，长度硬上限 60。"""
    head = str(rel.get("head_canonical") or rel.get("head") or "").strip()
    tail = str(rel.get("tail_canonical") or rel.get("tail") or "").strip()
    label = str(rel.get("relation_label") or "").strip()
    parts = [p for p in (head, label, tail) if p and not _QUERY_STOP.fullmatch(p)]
    query = " ".join(dict.fromkeys(parts))  # 去重保序
    return query[:60]


def _build_claims(result: dict[str, Any]) -> list[dict[str, Any]]:
    """把抽取出的三元组转成「可核查断言」。每条带证据句、置信度与检索短句。"""
    sentences = {
        int(s.get("index", 0)): {
            "text": str(s.get("text") or ""),
            "start": int(s.get("start") or 0),
            "end": int(s.get("end") or 0),
        }
        for s in result.get("sentences", [])
    }
    claims: list[dict[str, Any]] = []
    for r in result.get("relations", []):
        evidence = str(r.get("evidence") or "").strip()
        idx = int(r.get("sentence_index") or 0)
        sent = sentences.get(idx, {"text": evidence, "start": 0, "end": 0})
        query = _query_for(r)
        claims.append(
            {
                "head": r.get("head") or "",
                "head_canonical": r.get("head_canonical") or r.get("head") or "",
                "head_type": r.get("head_type") or "",
                "relation": r.get("relation") or "",
                "relation_label": r.get("relation_label") or "",
                "tail": r.get("tail") or "",
                "tail_canonical": r.get("tail_canonical") or r.get("tail") or "",
                "tail_type": r.get("tail_type") or "",
                "confidence": round(float(r.get("confidence") or 0), 2),
                "evidence": evidence,
                "evidence_sentence": sent["text"],
                "sentence_index": idx,
                "sentence_start": sent["start"],
                "sentence_end": sent["end"],
                "query": query,
            }
        )
    claims.sort(key=lambda c: (-c["confidence"], c["sentence_index"]))
    return claims


# --------------------------------------------------------------------------- #
# 第二段：外部核验（可配置，默认关闭）
# --------------------------------------------------------------------------- #


def _source_tier(url: str) -> str:
    low = url.lower()
    if any(h in low for h in _OFFICIAL_HINTS):
        return "official"
    if any(h in low for h in _MAJOR_HINTS):
        return "major"
    if any(h in low for h in _COMMUNITY_HINTS):
        return "community"
    return "unknown"


def _external_for_claim(
    claim: dict[str, Any],
    provider: SearchProvider,
    seen_queries: set[str],
) -> dict[str, Any]:
    """对一条断言做外部核验。失败 / 无 query 时给出明确状态，不伪造证据。"""
    query = claim.get("query", "").strip()
    if not provider.available() or len(query) < 4:
        return {"status": "skipped", "evidence": [], "domains": [], "refuted": False}

    # 相同短句只查一次，避免把同一个实体反复送去外部
    qkey = query.lower()
    if qkey in seen_queries:
        return {"status": "duplicate", "evidence": [], "domains": [], "refuted": False}
    if len(seen_queries) >= MAX_EXTERNAL_QUERIES:
        return {"status": "quota", "evidence": [], "domains": [], "refuted": False}
    seen_queries.add(qkey)

    try:
        raw = provider.search(query)
    except Exception:
        # 联网失败一律降级，不把异常暴露成整个功能不可用
        return {"status": "error", "evidence": [], "domains": [], "refuted": False}

    evidence = []
    refuted = False
    for item in raw[:5]:
        url = item.get("url", "")
        blob = f"{item.get('title', '')} {item.get('snippet', '')}"
        is_refute = any(w in blob for w in _REFUTE_WORDS)
        if is_refute:
            refuted = True
        evidence.append(
            {
                "title": item.get("title", ""),
                "url": url,
                "snippet": item.get("snippet", ""),
                "source_tier": _source_tier(url),
                "source_label": _SOURCE_LABELS[_source_tier(url)],
                "refuting": is_refute,
            }
        )
    domains = list(dict.fromkeys(urllib.parse.urlparse(e["url"]).netloc for e in evidence))
    return {
        "status": "checked",
        "query": query,
        "evidence": evidence,
        "domains": domains,
        "refuted": refuted,
    }


# --------------------------------------------------------------------------- #
# 第三段：分层裁决（确定性，可解释）
# --------------------------------------------------------------------------- #


def _grade_claim(
    claim: dict[str, Any],
    signals: list[dict[str, Any]],
    external: dict[str, Any],
) -> dict[str, Any]:
    """给一条断言定级，并把理由摊开。核心判断全部可指回原句或证据。"""
    reasons: list[str] = []
    # 基线分 1：存在一条被抽取器识别出的具体关系本身，就是可核查的事实内核。
    # 这样离线模式下「具体 + 高置信 + 无可疑措辞」也能达到有据可查，而不是
    # 必须联网才给高分 —— 离线可复现是这套判断的底线。
    score = 1

    # 1. 证据句质量：有具体原句支撑是「有据可查」的必要条件
    evidence = claim.get("evidence", "")
    if len(evidence) >= 8:
        score += 1
        reasons.append(f"原文有具体证据句（第 {claim['sentence_index'] + 1} 句）")
    else:
        reasons.append("没有具体证据句支撑")

    # 2. 抽取置信度
    if claim["confidence"] >= 0.85:
        score += 1
        reasons.append(f"抽取置信度较高（{claim['confidence']}）")
    elif claim["confidence"] > 0:
        reasons.append(f"抽取置信度一般（{claim['confidence']}）")

    # 3. 句式可疑信号：只归因落在同一句字符区间内的信号，不拿别句的措辞误伤
    start, end = claim.get("sentence_start", 0), claim.get("sentence_end", 0)
    near = [
        s for s in signals
        if s["key"] in ("vague_source", "vague_time", "absolute", "sensation")
        and (start == 0 or start <= s["position"] <= end)
    ]
    if near:
        score -= 1
        reasons.append("本句出现可疑措辞：" + "、".join(s["label"] for s in near[:3]))

    # 4. 外部核验：只在真正拿到证据时改变结论
    ext_status = external.get("status")
    if ext_status == "checked":
        tiers = [e["source_tier"] for e in external.get("evidence", []) if not e["refuting"]]
        if external.get("refuted"):
            score -= 2
            reasons.append("外部检索到疑似辟谣 / 否认的信息")
        elif "official" in tiers:
            score += 2
            reasons.append("外部检索到官方 / 权威来源的印证")
        elif len(set(external.get("domains", []))) >= 2:
            score += 1
            reasons.append(f"外部有 {len(set(external['domains']))} 个不同来源提及")
        else:
            reasons.append("外部检索未找到明确印证")
    elif ext_status in ("skipped", "quota", "duplicate", "error"):
        reasons.append("未做外部核实（不代表属实）")

    # 5. 定级（阈值刻意保守：宁可报存疑，不轻易报有据可查）
    if score >= 3:
        verdict = VERDICT_GROUNDED
    elif score >= 1:
        verdict = VERDICT_QUESTION
    else:
        verdict = VERDICT_UNCHECKABLE

    return {
        **claim,
        "verdict": verdict,
        "verdict_label": VERDICT_LABELS[verdict],
        "score": score,
        "reasons": reasons,
        "external": external,
    }


def _overall(claims: list[dict[str, Any]], signals: list[dict[str, Any]], text_len: int) -> dict[str, Any]:
    """给出整段文字的概览结论。注意：这是「值不值得信」，不是真伪判定。"""
    if not claims:
        tier = VERDICT_UNCHECKABLE
        summary = "这段文字没有抽出可核查的具体关系，多为陈述或情绪表达，无法做事实层面的核实。"
    else:
        counts = {v: sum(1 for c in claims if c["verdict"] == v) for v in VERDICT_ORDER}
        grounded_share = counts[VERDICT_GROUNDED] / len(claims)
        high_signals = [s for s in signals if s["level"] == "high"]
        if grounded_share >= 0.5 and not high_signals:
            tier = VERDICT_GROUNDED
            summary = f"{len(claims)} 条可核查断言中，多数有原文证据支撑，未发现明显的煽动性措辞。"
        elif counts[VERDICT_QUESTION] >= counts[VERDICT_UNCHECKABLE]:
            tier = VERDICT_QUESTION
            summary = f"{len(claims)} 条断言里，{counts[VERDICT_QUESTION]} 条缺少关键要素或只有单方说法，建议逐条核实。"
        else:
            tier = VERDICT_UNCHECKABLE
            summary = f"{len(claims)} 条断言中多数缺乏可核查的事实内核，建议先确认信息来源再采信。"

    high = [s["label"] for s in signals if s["level"] == "high"]
    if high:
        summary += " 另检测到明显的可疑措辞：" + "、".join(dict.fromkeys(high)) + "。"

    return {
        "verdict": tier,
        "verdict_label": VERDICT_LABELS[tier],
        "summary": summary,
        "text_length": text_len,
        "claim_count": len(claims),
    }


# --------------------------------------------------------------------------- #
# 对外主入口
# --------------------------------------------------------------------------- #


def verify_text(text: str, use_external: bool = True) -> dict[str, Any]:
    """对一段文字做完整甄别。同步纯计算（联网时是短超时请求），不写任何库。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("文本内容为空")
    if len(text) > MAX_CHARS:
        raise ValueError(f"文本过长（{len(text)} 字），请控制在 {MAX_CHARS} 字以内")

    # 复用现有抽取能力：用户的自定义词典与触发词同样生效，保持一致
    try:
        terms = db.list_custom_terms()
        triggers = db.custom_triggers_by_relation()
    except Exception:
        terms, triggers = [], {}
    result = analyze(text, custom_terms=terms, custom_triggers=triggers)

    signals = _skill_check(text)
    claims = _build_claims(result)

    provider: SearchProvider = build_provider() if use_external else NullProvider("本次未请求联网核验")
    seen: set[str] = set()
    external_reports = [_external_for_claim(c, provider, seen) for c in claims]
    graded = [_grade_claim(c, signals, ext) for c, ext in zip(claims, external_reports)]
    graded.sort(key=lambda c: (VERDICT_ORDER[c["verdict"]], -c["confidence"]))

    overall = _overall(graded, signals, len(text))
    return {
        "fingerprint": _hash_text(text),
        "text": text,
        "overall": overall,
        "signals": signals,
        "claims": graded,
        "external": {
            "enabled": provider.available(),
            "provider": provider.name,
            "provider_label": provider.label,
            "reason": getattr(provider, "reason", ""),
            "queries_used": len(seen),
        },
        "disclaimer": (
            "本结果由确定性规则生成，用于提示信息中值得核实的地方，不等于事实真伪判定。"
            "外部检索结果仅供参考，请优先采信官方与权威来源。"
        ),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def seed_examples() -> list[dict[str, str]]:
    """内置的演示样例：贴近日常、一眼能看出不同类型的问题，用于引导用户。"""
    return [
        {
            "id": "rumor",
            "title": "群聊爆料式消息",
            "text": (
                "紧急通知！据悉某知名科技公司近日将大规模裁员，内部人士透露补偿方案已经确定，"
                "有的部门一个不留，百分之百属实。看到的朋友赶紧转发，马上就要删了！"
            ),
            "hint": "大量模糊信源 + 煽动措辞 + 绝对化表述，几乎没有可核查的具体关系。",
        },
        {
            "id": "grounded",
            "title": "有据可查的新闻",
            "text": (
                "据新华社报道，腾讯今日宣布收购搜狗公司。搜狗公司此前由王小川创立，"
                "总部位于北京。"
            ),
            "hint": "点名来源、给出具体主体与地点，能抽出带证据句的关系。",
        },
        {
            "id": "mixed",
            "title": "半真半假的转述",
            "text": (
                "网传腾讯将收购搜狗公司，金额高达上百亿。据了解双方已签署合作协议，"
                "但具体什么时候签的没说。有消息称这是史上最大手笔，绝对准确无误。"
            ),
            "hint": "既有可抽取的断言，又混着模糊时间、夸大和绝对化措辞。",
        },
    ]


__all__ = [
    "verify_text",
    "capability",
    "seed_examples",
    "VERDICT_GROUNDED",
    "VERDICT_QUESTION",
    "VERDICT_UNCHECKABLE",
    "VERDICT_LABELS",
]
