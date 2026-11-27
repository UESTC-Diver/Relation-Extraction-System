# -*- coding: utf-8 -*-
"""断言极性判定：区分「事实陈述 / 否定 / 传闻 / 条件」。

抽取引擎只关心「谁和谁有什么关系」，不区分这句话是在陈述事实、否认事实、
转述传闻还是提出假设。结果是「腾讯否认收购搜狗」和「腾讯收购搜狗」抽出同一条
三元组、置信度几乎一样（0.89 vs 0.94）—— 对做尽调、做信息核实的人来说，
这两种说法的价值完全相反。

这里用确定性规则补上这一层，按「小句」而不是整句判断：中文新闻里一条
「双方签署合作协议。有媒体报道称将收购对方」的句子，前半句是事实、后半句是
传闻，按整句判断会把真事一起压掉。

判定优先级：否定 > 条件 > 传闻 > 事实。命中的词与所在小句一并返回，
前端可以直接告诉用户「为什么这条被标成传闻」。

词表与信息甄别模块共用：verify.py 的「模糊信源」可疑措辞就是这里的传闻框架，
两处必须同源，否则同一个「网传」在甄别页是可疑、在抽取页却是确定事实。
"""

from __future__ import annotations

import re

# 判定档位：被标为非 fact 的关系不进默认视图，也不计入事实抽取的评测口径。
ASSERTION_LABELS = {
    "fact": "事实陈述",
    "negated": "否认 / 否定",
    "rumored": "传闻 / 转述",
    "conditional": "假设 / 条件",
}

# 否定与否证。未(?!来) 是为了避开「未来三年」这类时间词。
NEGATION_RE = re.compile(
    r"(否认|予以否认|并未|从未|不曾|尚未|并无|并非|没有|未(?!来)|不存在|拒绝|"
    r"辟谣|澄清|不属实|不实|系误传|系谣言|纯属|为假)"
)

# 条件与假设。
CONDITION_RE = re.compile(r"(如果|假如|倘若|一旦|要是|若(?!干)|假设|前提是|除非|万一)")

# 传闻框架：模糊信源 + 明确转述 + 未经证实。与 verify.py 的模糊信源同源。
RUMOR_RE = re.compile(
    r"(据悉|据了解|知情人士|内部人士|内部消息|消息人士|有消息称|消息称|据传|网传|"
    r"传闻|传言|网友爆料|爆料称|有人说|据说|据媒体|媒体报道称|报道称|据报道|"
    r"尚未证实|未经证实|无法证实|有待证实)"
)

# 后置否证：命题后另起一句「该说法已被辟谣」，也算否定。
BACK_REF_RE = re.compile(r"(该说法|这一说法|此说法|该消息|此消息|上述说法|上述消息)")
REFUTE_IN_BACK_CLAUSE_RE = re.compile(r"(辟谣|否认|不实|不属实|不存在|系谣言|纯属|为假)")

# 官方发布动词：出现这些词说明是权威方主动公布，不应因句中有其他传闻词而降级。
ANNOUNCE_RE = re.compile(r"(宣布|公告|披露|通报|发布公告)")

_CLAUSE_SPLIT_RE = re.compile(r"[，。；：！？,;:!?\n]")

# 否定词允许出现在触发词前后多少字内。窗口太大会把邻句的否定吸过来。
NEG_WINDOW = 12
# 前一小句里的传闻框架只有紧跟「称 / 透露 / 报道」时才对后文生效。
FORWARD_FRAME_RE = re.compile(r"(称|透露|报道|表示)$")


def clauses(text: str) -> list[tuple[int, int, str]]:
    """按中文标点切小句，返回 [(起, 止, 文本)]，偏移相对整句。"""
    out: list[tuple[int, int, str]] = []
    start = 0
    for m in _CLAUSE_SPLIT_RE.finditer(text or ""):
        if m.start() > start:
            out.append((start, m.start(), text[start:m.start()]))
        start = m.end()
    if start < len(text or ""):
        out.append((start, len(text), text[start:]))
    return out


def _locate_trigger(text: str, trigger: str, anchor: int) -> int:
    """在句中找到离头实体最近的触发词位置，找不到返回 -1。"""
    trig = (trigger or "").strip()
    if not trig:
        return -1
    best, best_dist = -1, 10**9
    pos = text.find(trig)
    while pos >= 0:
        dist = abs(pos - anchor)
        if dist < best_dist:
            best, best_dist = pos, dist
        pos = text.find(trig, pos + 1)
    return best


def judge(text: str, trigger: str, head_start: int = 0, head_end: int = 0) -> dict:
    """判定一条关系所在小句的断言极性。

    返回 {assertion, assertion_label, assertion_cue, assertion_clause, penalty}。
    penalty 是乘在置信度上的系数：否定最狠，传闻次之，条件再次之。
    """
    text = text or ""
    parts = clauses(text)
    if not parts:
        return _result("fact", "", "")

    anchor = head_end if head_end > head_start else head_start
    trig_pos = _locate_trigger(text, trigger, anchor)

    # 触发词找不到（模板改写过触发词）时，退化成整句判断：宁可标得保守一点，
    # 也不要因为定位失败把明确的否定当成事实。
    idx = -1
    current = (0, len(text), text)
    if trig_pos >= 0:
        for i, c in enumerate(parts):
            if c[0] <= trig_pos < c[1]:
                idx, current = i, c
                break
    c_start, c_end, c_text = current
    trig_rel = (trig_pos - c_start) if trig_pos >= 0 else 0

    # 1) 否定：小句内、触发词前 WIN 字内的否定词；或触发词后紧接「不实 / 不存在」。
    for m in NEGATION_RE.finditer(c_text):
        before = m.end() <= trig_rel and trig_rel - m.end() <= NEG_WINDOW
        after = m.start() >= trig_rel + len(trigger or "") - 1 and m.start() - trig_rel <= NEG_WINDOW
        if before or after:
            return _result("negated", m.group(0), c_text)

    # 2) 后置否证：「该说法已被辟谣」这类紧邻的后一小句。
    if 0 <= idx < len(parts) - 1 and BACK_REF_RE.search(parts[idx + 1][2]):
        back = parts[idx + 1]
        m = REFUTE_IN_BACK_CLAUSE_RE.search(back[2])
        if m:
            return _result("negated", m.group(0), f"{c_text}，{back[2]}")

    # 3) 条件：小句内或紧邻的前一小句出现条件连词。
    m = CONDITION_RE.search(c_text)
    if not m and idx > 0:
        m = CONDITION_RE.search(parts[idx - 1][2])
        if m:
            return _result("conditional", m.group(0), c_text)
    if m:
        return _result("conditional", m.group(0), c_text)

    # 4) 传闻：小句内的传闻框架；或前一小句以「称 / 透露 / 报道」收尾的转述框架。
    m = RUMOR_RE.search(c_text)
    if m:
        return _result("rumored", m.group(0), c_text)
    if idx > 0:
        prev = parts[idx - 1][2]
        if RUMOR_RE.search(prev) and FORWARD_FRAME_RE.search(prev.strip()):
            mm = RUMOR_RE.search(prev)
            assert mm is not None
            return _result("rumored", mm.group(0), c_text)

    return _result("fact", "", c_text)


def _result(assertion: str, cue: str, clause: str) -> dict:
    penalty = {"fact": 1.0, "rumored": 0.62, "conditional": 0.58, "negated": 0.40}
    return {
        "assertion": assertion,
        "assertion_label": ASSERTION_LABELS[assertion],
        "assertion_cue": cue,
        "assertion_clause": clause.strip()[:60],
        "penalty": penalty[assertion],
    }


# ---------- 英文引擎的等价判定 ----------
# 英文走 spaCy 依存句法，句内结构不同，单独一套词表；语义分档保持一致。

_EN_NEGATION_RE = re.compile(
    r"\b(not|never|no longer|denied|denies|deny|refuted|refutes|rejected|rejects|"
    r"dismissed|dismisses|did not|does not|do not|has not|have not|was not|were not|unfounded|false)\b",
    re.IGNORECASE,
)
_EN_CONDITION_RE = re.compile(r"\b(if|unless|provided that|assuming|suppose|were to)\b", re.IGNORECASE)
_EN_RUMOR_RE = re.compile(
    r"\b(reportedly|allegedly|rumou?red|rumou?rs?|is said to|are said to|sources said|"
    r"people familiar|unconfirmed|unverified|speculation|reportedly plans?)\b",
    re.IGNORECASE,
)


def judge_en(text: str, relation_text: str = "") -> dict:
    """英文版：spaCy 侧没有触发词偏移，按整句判断即可（英文句多为单主句）。"""
    text = text or ""
    m = _EN_NEGATION_RE.search(text)
    if m:
        return _result("negated", m.group(0), text)
    m = _EN_CONDITION_RE.search(text)
    if m:
        return _result("conditional", m.group(0), text)
    m = _EN_RUMOR_RE.search(text)
    if m:
        return _result("rumored", m.group(0), text)
    return _result("fact", "", text)
