# -*- coding: utf-8 -*-
"""关系抽取：触发词锚定 + 句式模板 + 类型约束。

实现思路
--------
1. 把句子中的实体替换成占位符，得到"掩码句"，用于匹配 "A 成为 B 的子公司"
   这类语序与常规相反的高价值句式模板（SPECIAL_PATTERNS）。
2. 对剩余文本做触发词扫描：以触发词为锚点，向左 / 向右找最近的、符合类型
   约束的实体，得到 (头实体, 关系, 尾实体)。
3. 处理被动句（"A 被 B 收购"）、并列结构（"A 与 B 签署协议"）、
   后置定语（"总部位于杭州的 A 公司"）等特殊语序。
4. 按 (头实体, 关系, 尾实体) 去重，保留置信度最高的一条。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .entity import Entity, canonical_name
from .lexicon import (
    COREF_DEFINITE_WORDS,
    COREF_EARLIER_WORDS,
    COREF_EVENT_WORDS,
    COREF_GROUP_WORDS,
    COREF_LATER_WORDS,
    RELATION_MAP,
    ROLE_WORDS,
    SPECIAL_PATTERNS,
    TRIGGER_FILLERS,
    TRIGGER_INDEX,
    TRIGGERS_BY_LENGTH,
)
from .tokenizer import Sentence

_ROLE_SET = set(ROLE_WORDS)

_PLACEHOLDER = r"\ue000(\d+)\ue001"
_PLACEHOLDER_CHARS = re.compile(r"\ue000(\d+)\ue001")
_PASSIVE_MARKERS = ("被", "由")
_CONJ_MARKERS = ("和", "与", "及", "同", "、", "以及", "连同")

# --------------------------------------------------------------------------- #
# 指代消解与触发词容错资源
# --------------------------------------------------------------------------- #
_GROUP_SET = set(COREF_GROUP_WORDS)
_LATER_SET = set(COREF_LATER_WORDS)
_EARLIER_SET = set(COREF_EARLIER_WORDS)
_DEFINITE_SET = set(COREF_DEFINITE_WORDS)
_EVENT_SET = set(COREF_EVENT_WORDS)
_COREF_RE = re.compile(
    "|".join(
        map(
            re.escape,
            sorted(
                _GROUP_SET | _LATER_SET | _EARLIER_SET | _DEFINITE_SET | _EVENT_SET,
                key=len,
                reverse=True,
            ),
        )
    )
)
_SALIENT_TYPES = {"ORG", "PERSON"}
_CLAUSE_PUNCT = "，,；;。！？!?"
# 事件回指词 -> 优先跟随的关系类型
_EVENT_RELATION_PREF = {
    "此次收购": ("acquire",),
    "本次收购": ("acquire",),
    "此次交易": ("acquire", "invest"),
    "本次交易": ("acquire", "invest"),
    "这笔交易": ("acquire", "invest"),
    "该笔交易": ("acquire", "invest"),
    "该交易": ("acquire", "invest"),
    "这一交易": ("acquire", "invest"),
    "此次合作": ("cooperate", "sign"),
    "本次合作": ("cooperate", "sign"),
    "此次投资": ("invest",),
    "本次投资": ("invest",),
}

# 触发词内部允许插入的副词：按长度倒序，最长优先
_FILLERS_BY_LENGTH = sorted(set(TRIGGER_FILLERS), key=len, reverse=True)


def _is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿"


def _trigger_view(text: str) -> tuple[str, list[int]]:
    """剔除触发词内部插入的副词，返回 (规范化文本, 位置映射)。

    例如 "饿了么总部仍位于上海" -> "饿了么总部位于上海"，
    "总部仍位于" 在原文中仍是一个连续的触发片段。只剥离两侧都是
    汉字、且属于 TRIGGER_FILLERS 的副词，否定词不在此列。
    """
    out: list[str] = []
    mapping: list[int] = []
    i, n = 0, len(text)
    while i < n:
        removed = 0
        if 0 < i < n - 1 and _is_cjk(text[i - 1]):
            for filler in _FILLERS_BY_LENGTH:
                j = i + len(filler)
                if j < n and text.startswith(filler, i) and _is_cjk(text[j]):
                    removed = len(filler)
                    break
        if removed:
            i += removed
            continue
        out.append(text[i])
        mapping.append(i)
        i += 1
    return "".join(out), mapping


def _ordered_distinct(entities: list[Entity]) -> list[Entity]:
    """按首次出现顺序去重（同一实体只保留第一次提及）。"""
    seen: set[tuple[str, str]] = set()
    out: list[Entity] = []
    for e in entities:
        key = (canonical_name(e.text, e.type), e.type)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _latest(candidates: list[Entity], etype: str | None = None) -> Entity | None:
    for e in reversed(candidates):
        if etype is None or e.type == etype:
            return e
    return None


def _render(span: str, order: list[Entity]) -> str:
    """把掩码片段还原成可读文本（占位符替换回实体名）。"""

    def repl(m: re.Match[str]) -> str:
        idx = int(m.group(1))
        return order[idx].text if 0 <= idx < len(order) else ""

    return _PLACEHOLDER_CHARS.sub(repl, span).strip()


def _compile_special(template: str) -> re.Pattern[str]:
    pattern = template.replace("{0}", _PLACEHOLDER).replace("{1}", _PLACEHOLDER).replace("{2}", _PLACEHOLDER)
    return re.compile(pattern)


_COMPILED_SPECIAL = [
    (_compile_special(tpl), key, head_pos, tail_pos)
    for tpl, key, head_pos, tail_pos in SPECIAL_PATTERNS
]


@dataclass
class Triple:
    head: Entity
    tail: Entity
    key: str
    confidence: float
    sentence_index: int
    evidence: str
    trigger: str
    rule_base: str = "trigger"

    def as_dict(self) -> dict:
        rule = RELATION_MAP[self.key]
        return {
            "head": self.head.text,
            "head_canonical": canonical_name(self.head.text, self.head.type),
            "head_type": self.head.type,
            "head_id": self.head.id,
            "tail": self.tail.text,
            "tail_canonical": canonical_name(self.tail.text, self.tail.type),
            "tail_type": self.tail.type,
            "tail_id": self.tail.id,
            "relation": self.key,
            "relation_label": rule.label,
            "relation_color": rule.color,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence.strip(),
            "sentence_index": self.sentence_index,
            "trigger": self.trigger,
            "rule_base": self.rule_base,
        }


class RelationExtractor:
    """规则式中文关系抽取器。"""

    def extract(self, sentences: list[Sentence], entities: list[Entity]) -> list[Triple]:
        triples: list[Triple] = []
        by_sentence: dict[int, list[Entity]] = {}
        for e in entities:
            by_sentence.setdefault(e.sentence_index, []).append(e)

        # 语篇状态：历史实体、上一句主语、最近事件的主事者，供指代消解使用
        history: list[Entity] = []
        last_subject: Entity | None = None
        last_agents: dict[str, Entity] = {}

        for sent in sentences:
            ents = []
            for e in sorted(by_sentence.get(sent.index, []), key=lambda x: x.start):
                # 关系抽取在句子内部进行：把实体的绝对偏移换算成句内偏移
                start, end = e.start - sent.start, e.end - sent.start
                if start < 0 or end > len(sent.text):
                    continue
                ents.append(replace(e, start=start, end=end))

            refs = self._resolve_references(sent, ents, history, last_subject, last_agents)
            all_ents = sorted(ents + refs, key=lambda e: (e.start, -(e.end - e.start)))
            has_group = any(
                e.ref_kind == "group" and len(e.ref_members) >= 2 for e in all_ents
            )
            if len(all_ents) >= 2 or has_group:
                produced = self._special_patterns(sent, all_ents)
                produced.extend(self._trigger_scan(sent, all_ents))
                triples.extend(produced)
                for t in produced:
                    if t.key in ("acquire", "invest", "cooperate", "sign"):
                        last_agents[t.key] = t.head

            history.extend(ents)
            if len(history) > 120:
                history = history[-120:]
            subject = next((e for e in ents if e.type == "ORG"), None)
            if subject is None:
                subject = next((e for e in ents if e.type == "PERSON"), None)
            if subject is not None:
                last_subject = subject

        return self._dedupe(triples)

    # ------------------------------------------------------------------ #
    # 0. 指代消解
    # ------------------------------------------------------------------ #
    def _resolve_references(
        self,
        sent: Sentence,
        ents: list[Entity],
        history: list[Entity],
        last_subject: Entity | None,
        last_agents: dict[str, Entity],
    ) -> list[Entity]:
        """把 "双方 / 后者 / 该公司 / 此举" 等回指映射成伪实体。

        伪实体使用回指所在位置作为 span、被指代实体的文本与类型，
        因此在三元组输出中显示真实名称，而证据句仍定位到当前句子。
        """
        if not sent.text:
            return []
        resolved: list[Entity] = []
        for m in _COREF_RE.finditer(sent.text):
            word = m.group(0)
            if any(not (m.end() <= e.start or m.start() >= e.end) for e in ents + resolved):
                continue
            current = [
                e for e in ents + resolved
                if e.start < m.start() and e.ref_kind != "group"
            ]
            pair = self._recent_pair(current, history)
            ref: Entity | None = None
            if word in _GROUP_SET:
                if pair[0] is not None and pair[1] is not None:
                    a, b = pair
                    ref = Entity(
                        start=m.start(), end=m.end(), text=a.text, type=a.type,
                        score=a.score, source="coref", sentence_index=sent.index,
                        id=a.id, ref_kind="group", ref_members=(a, b), ref_other=b,
                    )
            elif word in _LATER_SET or word in _EARLIER_SET:
                if pair[0] is not None and pair[1] is not None:
                    a, b = pair
                    target, other = (b, a) if word in _LATER_SET else (a, b)
                    ref = Entity(
                        start=m.start(), end=m.end(), text=target.text, type=target.type,
                        score=target.score, source="coref", sentence_index=sent.index,
                        id=target.id, ref_kind="pair", ref_members=(a, b), ref_other=other,
                    )
            elif word in _DEFINITE_SET:
                target = self._definite_referent(word, current, history, last_subject)
                if target is not None:
                    ref = Entity(
                        start=m.start(), end=m.end(), text=target.text, type=target.type,
                        score=target.score, source="coref", sentence_index=sent.index,
                        id=target.id, ref_kind="single",
                    )
            elif word in _EVENT_SET:
                target = self._event_referent(word, current, history, last_subject, last_agents)
                if target is not None:
                    ref = Entity(
                        start=m.start(), end=m.end(), text=target.text, type=target.type,
                        score=target.score, source="coref", sentence_index=sent.index,
                        id=target.id, ref_kind="event",
                    )
            if ref is not None:
                resolved.append(ref)
        return resolved

    def _recent_pair(
        self, current: list[Entity], history: list[Entity]
    ) -> tuple[Entity | None, Entity | None]:
        """取最近的两个显著实体（人物 / 机构），按首次提及顺序排列。"""
        cur = _ordered_distinct([e for e in current if e.type in _SALIENT_TYPES])
        if len(cur) >= 2:
            return cur[-2], cur[-1]
        hist = _ordered_distinct([e for e in history if e.type in _SALIENT_TYPES])
        combined = list(hist)
        seen = {(canonical_name(e.text, e.type), e.type) for e in combined}
        for e in cur:
            key = (canonical_name(e.text, e.type), e.type)
            if key not in seen:
                seen.add(key)
                combined.append(e)
        if len(combined) >= 2:
            return combined[-2], combined[-1]
        if len(combined) == 1:
            return None, combined[0]
        return None, None

    def _definite_referent(
        self, word: str, current: list[Entity], history: list[Entity],
        last_subject: Entity | None,
    ) -> Entity | None:
        """该公司 / 该工厂：优先回指语篇主事主体，必要时退回最近的机构。"""
        if last_subject is not None and last_subject.type == "ORG":
            return last_subject
        target = _latest(current, "ORG") or _latest(history, "ORG")
        if target is not None:
            return target
        if word == "该平台":
            target = _latest(current, "PRODUCT") or _latest(history, "PRODUCT")
        return target or last_subject

    def _event_referent(
        self, word: str, current: list[Entity], history: list[Entity],
        last_subject: Entity | None, last_agents: dict[str, Entity],
    ) -> Entity | None:
        """此举 / 本次收购：优先跟随最近一次相应事件的主事者。"""
        for key in _EVENT_RELATION_PREF.get(word, ()):
            if key in last_agents:
                return last_agents[key]
        return (
            last_subject
            or _latest(current, "ORG")
            or _latest(history, "ORG")
            or _latest(current)
            or _latest(history)
        )

    # ------------------------------------------------------------------ #
    # 1. 句式模板
    # ------------------------------------------------------------------ #
    def _special_patterns(self, sent: Sentence, ents: list[Entity]) -> list[Triple]:
        masked, order = self._mask(sent.text, ents)
        out: list[Triple] = []
        for regex, key, head_pos, tail_pos in _COMPILED_SPECIAL:
            rule = RELATION_MAP[key]
            for m in regex.finditer(masked):
                raw = [g for g in m.groups() if g is not None]
                if len(raw) <= max(head_pos, tail_pos):
                    continue
                try:
                    head = order[int(raw[head_pos])]
                    tail = order[int(raw[tail_pos])]
                except (IndexError, ValueError):
                    continue
                if head.id == tail.id or not rule.accepts(head.type, tail.type):
                    continue
                out.append(
                    Triple(
                        head=head, tail=tail, key=key,
                        confidence=0.94, sentence_index=sent.index,
                        evidence=sent.text,
                        trigger=_render(m.group(0), order)[:16],
                        rule_base="pattern",
                    )
                )
        return out

    def _mask(self, text: str, ents: list[Entity]) -> tuple[str, list[Entity]]:
        chunks: list[str] = []
        order: list[Entity] = []
        last = 0
        for e in ents:
            if e.start < last:
                continue
            chunks.append(text[last:e.start])
            chunks.append(f"\ue000{len(order)}\ue001")
            order.append(e)
            last = e.end
        chunks.append(text[last:])
        return "".join(chunks), order

    # ------------------------------------------------------------------ #
    # 2. 触发词扫描
    # ------------------------------------------------------------------ #
    def _trigger_scan(self, sent: Sentence, ents: list[Entity]) -> list[Triple]:
        text = sent.text
        # 先去掉触发词内部插入的副词（"总部仍位于" -> "总部位于"），
        # 再在规范化文本上扫描，位置映射回原文。
        norm, mapping = _trigger_view(text)
        occurrences: list[tuple[int, int, str, int, int]] = []
        for trig in TRIGGERS_BY_LENGTH:
            start = 0
            while True:
                idx = norm.find(trig, start)
                if idx < 0:
                    break
                ns, ne = idx, idx + len(trig)
                occurrences.append((mapping[ns], mapping[ne - 1] + 1, trig, ns, ne))
                start = idx + 1
        occurrences.sort(key=lambda x: (x[0], -(x[1] - x[0])))

        consumed: list[tuple[int, int]] = []
        out: list[Triple] = []
        spans = [(e.start, e.end) for e in ents]
        for ts, te, trig, ns, ne in occurrences:
            # 触发词若落在实体内部（如"腾讯控股"里的"控股"），不当作关系触发词
            if any(s <= ts and te <= e for s, e in spans):
                continue
            if any(not (te <= s or ts >= e) for s, e in consumed):
                continue
            rules = TRIGGER_INDEX.get(trig, [])
            # "签署供货协议" 里的 "供货" 不是供应关系；"采购合同" 同理
            if any(rule.key == "supply" for rule in rules) and norm[ne:ne + 2] in ("协议", "合同"):
                continue
            display = text[ts:te]
            produced = None
            for rule in rules:
                produced = self._apply_rule(sent, ents, rule, ts, te, trig, display)
                if produced:
                    break
            if produced:
                out.extend(produced)
                consumed.append((ts, te))
        return out

    def _apply_rule(
        self, sent: Sentence, ents: list[Entity], rule, ts: int, te: int,
        trig: str, display: str,
    ) -> list[Triple]:
        text = sent.text
        lefts = self._nearest(ents, ts, side="left", window=rule.window)
        rights = self._nearest(ents, te, side="right", window=rule.window)

        # ---- "双方" 类群体指代：直接在两方之间建立关系 ----
        group_left = next(
            (
                item for item in lefts
                if item[0].ref_kind == "group"
                and len(item[0].ref_members) >= 2
                and self._same_clause(text, item[0].end, ts)
            ),
            None,
        )
        if group_left is not None:
            partners = [r for r, _ in rights if self._same_clause(text, te, r.start)]
            return self._emit_group(sent, group_left[0], partners, rule, display, group_left[1])

        group_right = next(
            (
                item for item in rights
                if item[0].ref_kind == "group"
                and len(item[0].ref_members) >= 2
                and self._same_clause(text, te, item[0].start)
            ),
            None,
        )
        if group_right is not None:
            partners = [l for l, _ in lefts if self._same_clause(text, l.end, ts)]
            return self._emit_group(sent, group_right[0], partners, rule, display, group_right[1])

        # ---- "PERSON 出任 ORG 的 职位"：职务词前紧邻机构时，机构才是任职对象 ----
        if trig in _ROLE_SET and rule.key == "employ" and lefts and lefts[0][0].type == "ORG":
            org, odist = lefts[0]
            person = self._nearest_before(ents, org.start, window=16)
            if person and person.type == "PERSON" and person.start != org.start:
                return [self._make(person, org, rule, odist, sent, display, "attributive", -0.03)]

        # ---- "后者...供应..."：后者是供应方，另一方是接收方 ----
        if rule.key == "supply":
            for left, ldist in lefts:
                if left.ref_kind != "pair" or not self._same_clause(text, left.end, ts):
                    continue
                # "后者将向 X 供应..."：X 是显式接收方；
                # "后者将供应..."：另一方是隐含接收方。
                recipient = next(
                    (
                        e for e, _ in lefts
                        if e is not left and e.start >= left.end and e.type == "ORG"
                    ),
                    left.ref_other,
                )
                if recipient is not None and rule.accepts(left.type, recipient.type):
                    return [
                        self._make(left, recipient, rule, ldist, sent, display, "coref", -0.03)
                    ]

        # ---- "宁德时代将为该工厂供应..."：供应方是"为"之前的机构 ----
        if rule.key == "supply" and lefts and lefts[0][0].ref_kind == "single":
            ref, _ = lefts[0]
            for supplier, sdist in lefts[1:]:
                if supplier.type != "ORG" or not self._same_clause(text, supplier.end, ts):
                    continue
                if "为" not in text[supplier.end:ref.start]:
                    continue
                for r, rdist in rights:
                    if rule.accepts(supplier.type, r.type):
                        return [
                            self._make(
                                supplier, r, rule, sdist + rdist, sent, display, "trigger"
                            )
                        ]
                if rule.accepts(supplier.type, ref.type):
                    return [
                        self._make(supplier, ref, rule, sdist, sent, display, "trigger")
                    ]
                break

        # ---- "A 与 B 签署..."：用分句主语作头实体，避免并列宾语抢主语 ----
        comitative = self._comitative_subject(sent, ents, ts, rule, display)
        if comitative is not None:
            return [comitative]

        # ---- 常规：触发词两侧各有一个实体（先近后远）----
        pair = self._match_pair(lefts, rights, rule, sent, display)
        if pair:
            return pair
        wide_lefts = self._nearest(ents, ts, side="left", window=rule.window + 16)
        wide_rights = self._nearest(ents, te, side="right", window=rule.window + 16)
        pair = self._match_pair(wide_lefts, wide_rights, rule, sent, display)
        if pair:
            return pair

        # ---- 触发词前是"被 / 由"：被动句 ----
        if lefts:
            l, ldist = lefts[0]
            prefix = text[max(0, l.start - 2):l.start]
            if any(mk in prefix for mk in _PASSIVE_MARKERS):
                patient = self._nearest_before(ents, l.start - 2, window=rule.window)
                if patient and patient.start != l.start:
                    if rule.accepts(l.type, patient.type):
                        return [self._make(l, patient, rule, ldist, sent, display, "passive", -0.06)]
                    if rule.accepts(patient.type, l.type):
                        return [self._make(patient, l, rule, ldist, sent, display, "passive", -0.06)]

        # ---- 触发词前是 "A 和 B" 并列结构（"华为与比亚迪签署协议"）----
        if lefts:
            chain = self._conjunction_chain(text, ents, lefts[0][0])
            if len(chain) >= 2 and rule.accepts(chain[0].type, chain[-1].type):
                return [
                    self._make(chain[0], chain[-1], rule, 6, sent, display, "conjunction", -0.05)
                ]

        # ---- 触发词在后置定语前："总部位于杭州的 A 公司" ----
        if rights and not lefts and rule.forward_pair:
            for r, rdist in rights:
                if r.type not in rule.tail_types:
                    continue
                for head, hdist in self._nearest(ents, r.start, side="right", window=rule.window + 6):
                    if rule.accepts(head.type, r.type):
                        return [self._make(head, r, rule, hdist + rdist, sent, display, "postmodifier", -0.04)]

        # ---- "的 + 职位"："阿里巴巴的创始人马云" ----
        if lefts:
            l, ldist = lefts[0]
            if l.type in ("ORG", "LOC"):
                person = self._nearest_before(ents, l.start, window=14)
                if person and person.type == "PERSON" and rule.accepts(person.type, l.type):
                    return [self._make(person, l, rule, ldist, sent, display, "attributive", -0.05)]
        return []

    def _match_pair(
        self,
        lefts: list[tuple[Entity, int]],
        rights: list[tuple[Entity, int]],
        rule,
        sent: Sentence,
        display: str,
    ) -> list[Triple]:
        for l, ldist in lefts:
            for r, rdist in rights:
                if l.start == r.start and l.text == r.text:
                    continue
                if rule.accepts(l.type, r.type):
                    out = [self._make(l, r, rule, ldist + rdist, sent, display, "trigger")]
                    out.extend(
                        self._conjoined_tails(
                            sent.text, l, r, rights, rule, sent, display, ldist + rdist
                        )
                    )
                    return out
                if rule.accepts(r.type, l.type):
                    return [self._make(r, l, rule, ldist + rdist, sent, display, "trigger")]
        return []

    def _conjoined_tails(
        self, text: str, head: Entity, first_tail: Entity,
        rights: list[tuple[Entity, int]], rule, sent: Sentence,
        display: str, base_distance: int,
    ) -> list[Triple]:
        """同一分句内 "A 和 B" 的并列宾语：为每个尾实体各生成一条三元组。"""
        out: list[Triple] = []
        prev = first_tail
        for r, rdist in rights:
            if r.start <= prev.end:
                continue
            gap = text[prev.end:r.start]
            if not re.fullmatch(r"(?:以及|连同|和|与|及|、|\s){1,8}", gap):
                break
            if r.text != head.text and rule.accepts(head.type, r.type):
                out.append(
                    self._make(
                        head, r, rule, base_distance + rdist, sent, display,
                        "conjunction", -0.03,
                    )
                )
            prev = r
        return out

    def _emit_group(
        self, sent: Sentence, group: Entity, partners: list[Entity],
        rule, display: str, distance: int,
    ) -> list[Triple]:
        """把 "双方" 展开成实体对：优先与对侧实体配对，否则两方内部配对。"""
        members = [m for m in group.ref_members[:2] if m is not None]
        if len(members) < 2:
            return []
        a, b = members[0], members[1]
        out: list[Triple] = []
        for member in (a, b):
            for partner in partners:
                if (
                    member.text == partner.text
                    and member.type == partner.type
                    and member.id == partner.id
                ):
                    continue
                if rule.accepts(member.type, partner.type):
                    out.append(
                        self._make(member, partner, rule, distance, sent, display, "coref", -0.04)
                    )
                    break
                if rule.accepts(partner.type, member.type):
                    out.append(
                        self._make(partner, member, rule, distance, sent, display, "coref", -0.04)
                    )
                    break
        if out:
            return out
        if rule.accepts(a.type, b.type):
            return [self._make(a, b, rule, 0, sent, display, "coref", -0.02)]
        if rule.symmetric and rule.accepts(b.type, a.type):
            return [self._make(b, a, rule, 0, sent, display, "coref", -0.02)]
        return []

    def _comitative_subject(
        self, sent: Sentence, ents: list[Entity], ts: int, rule, display: str,
    ) -> Triple | None:
        """处理 "A 与 B 签署..."：头实体是分句主语 A，而不是紧邻的 B。

        "并与搜狐签署" 这类分句没有显式主语时，主语继承自前一分句。
        """
        text = sent.text
        lefts = self._nearest(ents, ts, side="left", window=rule.window)
        if not lefts:
            return None
        obj, dist = lefts[0]
        if obj.ref_kind:
            return None
        boundary = max(
            (text.rfind(ch, 0, obj.start) for ch in _CLAUSE_PUNCT), default=-1
        ) + 1
        prefix = text[boundary:obj.start]
        if not re.search(r"(?:与|和|同|及)$", prefix):
            return None
        rights = self._nearest(ents, ts, side="right", window=rule.window)
        same_clause_rights = [r for r, _ in rights if self._same_clause(text, ts, r.start)]
        # 若触发词后面还有更自然的宾语（"A 与 B 收购 C"），交给常规匹配
        if any(rule.accepts(obj.type, r.type) for r in same_clause_rights):
            return None
        subject = self._clause_subject(text, ents, boundary, obj.start, obj)
        if (
            subject is not None
            and subject.start != obj.start
            and rule.accepts(subject.type, obj.type)
        ):
            return self._make(subject, obj, rule, dist, sent, display, "trigger")
        return None

    def _clause_subject(
        self, text: str, ents: list[Entity], clause_start: int,
        clause_end: int, exclude: Entity,
    ) -> Entity | None:
        """取分句内的首个机构 / 人物；没有则从前一分句继承主语。"""
        def pick(candidates: list[Entity], prefer_last: bool = False) -> Entity | None:
            ordered = sorted(candidates, key=lambda e: e.start)
            if prefer_last:
                ordered = list(reversed(ordered))
            return (
                next((e for e in ordered if e.type == "ORG"), None)
                or next((e for e in ordered if e.type == "PERSON"), None)
            )

        candidates = [
            e for e in ents
            if clause_start <= e.start and e.end <= clause_end
            and e is not exclude and e.ref_kind != "group"
        ]
        # 同一分句内："此举将加剧饿了么与美团点评的竞争" 的主语是离"与"最近的饿了么，
        # 而不是句首的事件回指 "此举"。
        subject = pick(candidates, prefer_last=True)
        if subject is not None:
            return subject

        end = clause_start
        for _ in range(2):
            if end <= 0:
                break
            begin = max(
                (text.rfind(ch, 0, end - 1) for ch in _CLAUSE_PUNCT), default=-1
            ) + 1
            prev = [
                e for e in ents
                if begin <= e.start and e.end <= end and e.ref_kind != "group"
            ]
            subject = pick(prev)
            if subject is not None:
                return subject
            end = begin
        return None

    def _same_clause(self, text: str, a: int, b: int) -> bool:
        lo, hi = (a, b) if a <= b else (b, a)
        return not any(ch in text[lo:hi] for ch in _CLAUSE_PUNCT)

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #
    def _make(
        self, head: Entity, tail: Entity, rule, distance: int, sent: Sentence,
        trigger: str, base: str, adjust: float = 0.0,
    ) -> Triple:
        confidence = 0.93 - min(0.32, 0.013 * max(0, distance)) + adjust
        base_conf = 0.96 if base == "pattern" else 0.93
        confidence = max(0.52, min(0.98, base_conf - min(0.32, 0.013 * max(0, distance)) + adjust))
        return Triple(
            head=head, tail=tail, key=rule.key,
            confidence=confidence, sentence_index=sent.index,
            evidence=sent.text, trigger=trigger, rule_base=base,
        )

    def _nearest(
        self, ents: list[Entity], pos: int, side: str, window: int
    ) -> list[tuple[Entity, int]]:
        found: list[tuple[Entity, int]] = []
        for e in ents:
            if side == "left":
                if e.end <= pos:
                    dist = pos - e.end
                else:
                    continue
            else:
                if e.start >= pos:
                    dist = e.start - pos
                else:
                    continue
            if dist <= window:
                found.append((e, dist))
        found.sort(key=lambda x: x[1])
        return found[:3]

    def _nearest_before(self, ents: list[Entity], pos: int, window: int) -> Entity | None:
        best: tuple[Entity, int] | None = None
        for e in ents:
            if e.end <= pos:
                dist = pos - e.end
                if dist <= window and (best is None or dist < best[1]):
                    best = (e, dist)
        return best[0] if best else None

    def _conjunction_chain(self, text: str, ents: list[Entity], start: Entity) -> list[Entity]:
        chain = [start]
        current = start
        for _ in range(4):
            prev = None
            for e in ents:
                if e.end <= current.start and (prev is None or e.start > prev.start):
                    if current.start - e.end <= 8:
                        prev = e
            if prev is None:
                return chain
            gap = text[prev.end:current.start]
            if not any(mk in gap for mk in _CONJ_MARKERS):
                return chain
            chain.insert(0, prev)
            current = prev
        return chain

    def _dedupe(self, triples: list[Triple]) -> list[Triple]:
        best: dict[tuple[str, str, str], Triple] = {}
        for t in triples:
            if t.head.text == t.tail.text:
                continue
            key = (t.head.text, t.key, t.tail.text)
            if key not in best or t.confidence > best[key].confidence:
                best[key] = t
        result = list(best.values())
        # 同一对实体的 "总部位于" 比泛化的 "位于" 更具体，去掉后者
        hq_pairs = {(t.head.text, t.tail.text) for t in result if t.key == "headquarter"}
        result = [
            t for t in result
            if not (t.key == "locate" and (t.head.text, t.tail.text) in hq_pairs)
        ]
        result.sort(key=lambda t: (-t.confidence, t.sentence_index))
        return result
