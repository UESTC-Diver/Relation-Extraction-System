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
    RELATION_MAP,
    ROLE_WORDS,
    SPECIAL_PATTERNS,
    SYMMETRIC_RELATIONS,
    TRIGGER_INDEX,
    TRIGGERS_BY_LENGTH,
)
from .tokenizer import Sentence

_ROLE_SET = set(ROLE_WORDS)

_PLACEHOLDER = r"\ue000(\d+)\ue001"
_PLACEHOLDER_CHARS = re.compile(r"\ue000(\d+)\ue001")
_PASSIVE_MARKERS = ("被", "由")
_CONJ_MARKERS = ("和", "与", "及", "同", "、", "以及", "连同")


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

        for sent in sentences:
            ents = []
            for e in sorted(by_sentence.get(sent.index, []), key=lambda x: x.start):
                # 关系抽取在句子内部进行：把实体的绝对偏移换算成句内偏移
                start, end = e.start - sent.start, e.end - sent.start
                if start < 0 or end > len(sent.text):
                    continue
                ents.append(replace(e, start=start, end=end))
            if len(ents) < 2:
                continue
            triples.extend(self._special_patterns(sent, ents))
            triples.extend(self._trigger_scan(sent, ents))

        return self._dedupe(triples)

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
        occurrences: list[tuple[int, int, str]] = []
        for trig in TRIGGERS_BY_LENGTH:
            start = 0
            while True:
                idx = text.find(trig, start)
                if idx < 0:
                    break
                occurrences.append((idx, idx + len(trig), trig))
                start = idx + 1
        occurrences.sort(key=lambda x: (x[0], -(x[1] - x[0])))

        consumed: list[tuple[int, int]] = []
        out: list[Triple] = []
        spans = [(e.start, e.end) for e in ents]
        for ts, te, trig in occurrences:
            # 触发词若落在实体内部（如"腾讯控股"里的"控股"），不当作关系触发词
            if any(s <= ts and te <= e for s, e in spans):
                continue
            if any(not (te <= s or ts >= e) for s, e in consumed):
                continue
            rules = TRIGGER_INDEX.get(trig, [])
            produced = None
            for rule in rules:
                produced = self._apply_rule(sent, ents, rule, ts, te, trig)
                if produced:
                    break
            if produced:
                out.extend(produced)
                consumed.append((ts, te))
        return out

    def _apply_rule(
        self, sent: Sentence, ents: list[Entity], rule, ts: int, te: int, trig: str
    ) -> list[Triple]:
        text = sent.text
        lefts = self._nearest(ents, ts, side="left", window=rule.window)
        rights = self._nearest(ents, te, side="right", window=rule.window)

        # ---- "PERSON 出任 ORG 的 职位"：职务词前紧邻机构时，机构才是任职对象 ----
        if trig in _ROLE_SET and rule.key == "employ" and lefts and lefts[0][0].type == "ORG":
            org, odist = lefts[0]
            person = self._nearest_before(ents, org.start, window=16)
            if person and person.type == "PERSON" and person.start != org.start:
                return [self._make(person, org, rule, odist, sent, trig, "attributive", -0.03)]

        # ---- 常规：触发词两侧各有一个实体（先近后远）----
        pair = self._match_pair(lefts, rights, rule, ts, te, sent, trig)
        if pair:
            return pair
        wide_lefts = self._nearest(ents, ts, side="left", window=rule.window + 16)
        wide_rights = self._nearest(ents, te, side="right", window=rule.window + 16)
        pair = self._match_pair(wide_lefts, wide_rights, rule, ts, te, sent, trig)
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
                        return [self._make(l, patient, rule, ldist, sent, trig, "passive", -0.06)]
                    if rule.accepts(patient.type, l.type):
                        return [self._make(patient, l, rule, ldist, sent, trig, "passive", -0.06)]

        # ---- 触发词前是 "A 和 B" 并列结构（"华为与比亚迪签署协议"）----
        if lefts:
            chain = self._conjunction_chain(text, ents, lefts[0][0])
            if len(chain) >= 2 and rule.accepts(chain[0].type, chain[-1].type):
                return [
                    self._make(chain[0], chain[-1], rule, 6, sent, trig, "conjunction", -0.05)
                ]

        # ---- 触发词在后置定语前："总部位于杭州的 A 公司" ----
        if rights and not lefts and rule.forward_pair:
            for r, rdist in rights:
                if r.type not in rule.tail_types:
                    continue
                for head, hdist in self._nearest(ents, r.start, side="right", window=rule.window + 6):
                    if rule.accepts(head.type, r.type):
                        return [self._make(head, r, rule, hdist + rdist, sent, trig, "postmodifier", -0.04)]

        # ---- "的 + 职位"："阿里巴巴的创始人马云" ----
        if lefts:
            l, ldist = lefts[0]
            if l.type in ("ORG", "LOC"):
                person = self._nearest_before(ents, l.start, window=14)
                if person and person.type == "PERSON" and rule.accepts(person.type, l.type):
                    return [self._make(person, l, rule, ldist, sent, trig, "attributive", -0.05)]
        return []

    def _match_pair(
        self,
        lefts: list[tuple[Entity, int]],
        rights: list[tuple[Entity, int]],
        rule,
        ts: int,
        te: int,
        sent: Sentence,
        trig: str,
    ) -> list[Triple]:
        for l, ldist in lefts:
            for r, rdist in rights:
                if l.start == r.start:
                    continue
                if rule.accepts(l.type, r.type):
                    return [self._make(l, r, rule, ldist + rdist, sent, trig, "trigger")]
                if rule.accepts(r.type, l.type):
                    return [self._make(r, l, rule, ldist + rdist, sent, trig, "trigger")]
        return []

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
