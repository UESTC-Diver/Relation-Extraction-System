# -*- coding: utf-8 -*-
"""关系抽取：触发词锚定 + 句式模板 + 类型约束 + 轻量指代消解。

实现思路
--------
1. 把句子中的实体替换成占位符，得到"掩码句"，用于匹配 "A 成为 B 的子公司"
   这类语序与常规相反的高价值句式模板（SPECIAL_PATTERNS）。
2. 对剩余文本做触发词扫描：以触发词为锚点，向左 / 向右找最近的、符合类型
   约束的实体，得到 (头实体, 关系, 尾实体)。
3. 轻量指代消解（DocumentContext，跨句维护）：
   * "该工厂 / 该公司" —— 依据 "投资/建设了 XX 工厂" 的所属登记回指到主体；
   * "双方 / 两者" —— 取句内最近的两个机构；不足时回溯全文最近出现的两个机构；
   * "后者 / 前者" —— 取句内最近一组并列实体（"A与B"）中对应的一方；
   * "此前，……并与……" —— 并列分句继承上一分句的主语（主语链）；
   * "挤压 / 蚕食 …… 市场份额" 这类隐性竞争表达，主语取全文话题实体。
4. 处理被动句（"A 被 B 收购"）、并列结构（"A 与 B 签署协议"）、
   后置定语（"总部位于杭州的 A 公司"）等特殊语序。
5. 按 (头实体, 关系, 尾实体) 去重，保留置信度最高的一条；"供货协议" 这类
   名词短语中的 "供货" 不当作供应事件（签署关系已覆盖）。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace

from .entity import Entity, canonical_name
from .lexicon import (
    FLEXIBLE_TRIGGERS,
    RELATION_MAP,
    ROLE_WORDS,
    SPECIAL_PATTERNS,
    TRIGGER_INDEX,
    TRIGGERS_BY_LENGTH,
)
from .tokenizer import Sentence

_ROLE_SET = set(ROLE_WORDS)

_PLACEHOLDER = r"\ue000(\d+)\ue001"
_PLACEHOLDER_CHARS = re.compile(r"\ue000(\d+)\ue001")
_PASSIVE_MARKERS = ("被", "由")
_CONJ_MARKERS = ("和", "与", "及", "同", "、", "以及", "连同")
_CLAUSE_BREAKS = "，。；！？,.!?;；"
# 分句以这些词开头时，主语继承上一分句（主语链）
_CHAIN_STARTERS = ("并", "且", "也", "还", "同时", "另外", "此外")
# “双方”类代词可支撑的关系：签约 / 合作 / 竞争 / 供应 / 诉讼
_AGREEMENT_KEYS = {"sign", "cooperate", "compete", "supply", "sue"}
# “供货/供应”后紧跟这些词时是名词短语（供货协议），不是供应事件
_SUPPLY_NOUN_TAIL = re.compile(r"(?:协议|合同|备忘录)")
# "投资/建设了 XX 工厂" -> 登记工厂的归属主体，供 "该工厂" 回指
_OBJECT_RE = re.compile(
    r"(?:投资|建设|兴建|设立|打造|成立)(?:了|的)?"
    r"([\u4e00-\u9fa5]{0,6}?)(?:生产基地|研发中心|产业园|工厂|基地|园区)"
)
# 句内指代词
_DEMONSTRATIVE_RE = re.compile(
    r"[该此本]([\u4e00-\u9fa5]{0,2}?)"
    r"(?:生产基地|研发中心|产业园|工厂|基地|园区|公司|集团|品牌|项目|平台|中心)"
)
_BOTH_RE = re.compile(r"双方|两方|两者|二者")
_ORDER_RE = re.compile(r"后者|前者")


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

_COMPILED_FLEXIBLE = [
    (re.compile(pattern), display, tuple(RELATION_MAP[k] for k in keys))
    for pattern, display, keys in FLEXIBLE_TRIGGERS
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


@dataclass
class Pseudo(Entity):
    """指代词生成的"伪实体"，本身不进入输出，只参与触发词匹配。

    resolved    : 指代落地到的真实实体（双方为两个）
    counterpart : 后者/前者对应的另一方（如 "A与B……后者" 中 A 是 B 的 counterpart）
    """

    resolved: list[Entity] = field(default_factory=list)
    counterpart: Entity | None = None


class DocumentContext:
    """跨句文档上下文：话题实体、建造物归属登记，供指代消解回指。"""

    def __init__(self) -> None:
        self._org_counter: Counter[str] = Counter()
        self._recent: dict[str, Entity] = {}
        self.object_owner: dict[str, Entity] = {}

    def observe(self, ents: list[Entity]) -> None:
        """统计真实机构实体，维护全文话题。"""
        for e in ents:
            if e.type != "ORG" or isinstance(e, Pseudo):
                continue
            name = canonical_name(e.text, "ORG")
            self._org_counter[name] += 1
            self._recent[name] = e

    def observe_objects(self, sent: Sentence, ents: list[Entity]) -> None:
        """登记 "X 投资/建设了 …… 工厂/基地" 的归属，供 "该工厂" 回指。"""
        for m in _OBJECT_RE.finditer(sent.text):
            tail = m.group(0)
            noun = next(
                (w for w in ("生产基地", "研发中心", "产业园", "工厂", "基地", "园区") if tail.endswith(w)),
                None,
            )
            if noun is None:
                continue
            owner = None
            for e in ents:
                if e.type != "ORG" or e.end > m.start():
                    continue
                if m.start() - e.end <= 20 and (owner is None or e.start > owner.start):
                    owner = e
            if owner is not None:
                self.object_owner[noun] = owner

    def topic(self) -> Entity | None:
        """全文话题实体：出现次数最多的机构（并列时取最近出现者）。"""
        if not self._org_counter:
            return None
        top = max(self._org_counter.values())
        names = [n for n, c in self._org_counter.items() if c == top]
        recent = [self._recent[n] for n in names if n in self._recent]
        return max(recent, key=lambda e: e.start) if recent else None

    def recent_orgs(self, n: int = 2) -> list[Entity]:
        """全文最近出现的 n 个不同机构（按提及顺序）。"""
        ordered = sorted(self._recent.values(), key=lambda e: e.start)
        return ordered[-n:]


class RelationExtractor:
    """规则式中文关系抽取器。"""

    def extract(self, sentences: list[Sentence], entities: list[Entity]) -> list[Triple]:
        triples: list[Triple] = []
        by_sentence: dict[int, list[Entity]] = {}
        for e in entities:
            by_sentence.setdefault(e.sentence_index, []).append(e)

        doc = DocumentContext()
        for sent in sentences:
            abs_ents = sorted(by_sentence.get(sent.index, []), key=lambda x: x.start)
            ents = []
            for e in abs_ents:
                # 关系抽取在句子内部进行：把实体的绝对偏移换算成句内偏移
                start, end = e.start - sent.start, e.end - sent.start
                if start < 0 or end > len(sent.text):
                    continue
                ents.append(replace(e, start=start, end=end))
            pseudo = self._resolve_pronouns(sent, ents, doc)
            if not ents and not pseudo:
                doc.observe(abs_ents)
                doc.observe_objects(sent, ents)
                continue
            triples.extend(self._special_patterns(sent, ents))
            triples.extend(self._trigger_scan(sent, ents, pseudo, doc))
            # 文档上下文使用全文绝对偏移，保证跨句排序与回指正确
            doc.observe(abs_ents)
            doc.observe_objects(sent, ents)

        return self._dedupe(triples)

    # ------------------------------------------------------------------ #
    # 0. 指代消解：为指代词生成伪实体
    # ------------------------------------------------------------------ #
    def _resolve_pronouns(self, sent: Sentence, ents: list[Entity], doc: DocumentContext) -> list[Pseudo]:
        text = sent.text
        pseudo: list[Pseudo] = []

        def free(s: int, e: int) -> bool:
            return all(e <= x.start or s >= x.end for x in ents)

        # ---- 该工厂 / 该公司：查归属登记，公司/集团回指最近的机构 ----
        antecedents: list[Entity] = []
        for m in _DEMONSTRATIVE_RE.finditer(text):
            noun = next(
                (w for w in ("生产基地", "研发中心", "产业园", "工厂", "基地", "园区", "公司", "集团")
                 if text[m.start():m.end()].endswith(w)),
                None,
            )
            owner = doc.object_owner.get(noun or "")
            if owner is None and noun in ("公司", "集团"):
                recents = doc.recent_orgs(1)
                owner = recents[0] if recents else None
            if owner is None or not free(m.start(), m.end()):
                continue
            pseudo.append(Pseudo(
                start=m.start(), end=m.end(), text=m.group(0), type=owner.type,
                score=70, source="coref", sentence_index=sent.index, resolved=[owner],
            ))
            antecedents.append(owner)

        # ---- 后者 / 前者：句内最近一组并列实体 ----
        if _ORDER_RE.search(text) and len(ents) >= 2:
            pairs = [
                (e1, e2) for e1, e2 in zip(ents, ents[1:])
                if e2.start - e1.end <= 3
                and (not text[e1.end:e2.start] or any(mk in text[e1.end:e2.start] for mk in _CONJ_MARKERS))
                and e1.type == e2.type
            ]
            for m in _ORDER_RE.finditer(text):
                target_pair = [p for p in pairs if p[1].end <= m.start()]
                if not target_pair or not free(m.start(), m.end()):
                    continue
                first, second = target_pair[-1]
                target, other = (second, first) if m.group(0) == "后者" else (first, second)
                pseudo.append(Pseudo(
                    start=m.start(), end=m.end(), text=m.group(0), type=target.type,
                    score=70, source="coref", sentence_index=sent.index,
                    resolved=[target], counterpart=other,
                ))

        # ---- 双方 / 两者：句内两个机构 > 句内机构 + 该X 落地实体 > 全文最近两机构 ----
        for m in _BOTH_RE.finditer(text):
            parties = [e for e in ents if e.type == "ORG" and e.end <= m.start()]
            if len(parties) >= 2:
                chosen = parties[:2]
            elif len(parties) == 1 and antecedents:
                other = next((a for a in antecedents if a.text != parties[0].text), None)
                chosen = [parties[0], other] if other else []
            else:
                chosen = doc.recent_orgs(2)
            if len(chosen) != 2:
                continue
            a, b = chosen
            if canonical_name(a.text, a.type) == canonical_name(b.text, b.type):
                continue
            if not free(m.start(), m.end()):
                continue
            pseudo.append(Pseudo(
                start=m.start(), end=m.end(), text=m.group(0), type="ORG",
                score=70, source="coref", sentence_index=sent.index, resolved=[a, b],
            ))
        return pseudo

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
    def _trigger_scan(
        self, sent: Sentence, ents: list[Entity], pseudo: list[Pseudo], doc: DocumentContext
    ) -> list[Triple]:
        text = sent.text
        participants: list[Entity] = [*ents, *pseudo]
        occurrences: list[tuple[int, int, str, list]] = []
        for trig in TRIGGERS_BY_LENGTH:
            start = 0
            while True:
                idx = text.find(trig, start)
                if idx < 0:
                    break
                occurrences.append((idx, idx + len(trig), trig, TRIGGER_INDEX[trig]))
                start = idx + 1
        for regex, display, rules in _COMPILED_FLEXIBLE:
            for m in regex.finditer(text):
                occurrences.append((m.start(), m.end(), display, list(rules)))
        occurrences.sort(key=lambda x: (x[0], -(x[1] - x[0])))

        consumed: list[tuple[int, int]] = []
        out: list[Triple] = []
        spans = [(e.start, e.end) for e in participants]
        for ts, te, trig, rules in occurrences:
            # 触发词若落在实体内部（如"腾讯控股"里的"控股"），不当作关系触发词
            if any(s <= ts and te <= e for s, e in spans):
                continue
            if any(not (te <= s or ts >= e) for s, e in consumed):
                continue
            produced = None
            for rule in rules:
                produced = self._apply_rule(sent, participants, pseudo, rule, ts, te, trig, doc)
                if produced:
                    break
            if produced:
                out.extend(produced)
                consumed.append((ts, te))
        return out

    def _apply_rule(
        self, sent: Sentence, ents: list[Entity], pseudo: list[Pseudo], rule,
        ts: int, te: int, trig: str, doc: DocumentContext,
    ) -> list[Triple]:
        text = sent.text

        # ---- "供货协议 / 供应合同"：名词短语而非事件，签署关系已覆盖 ----
        if rule.key == "supply" and _SUPPLY_NOUN_TAIL.match(text, te):
            return []

        lefts = self._nearest(ents, ts, side="left", window=rule.window)
        rights = self._nearest(ents, te, side="right", window=rule.window)

        # ---- "A 为 B 供应 C"：B 是接收方，头实体取句内主语 A ----
        if rule.key == "supply" and lefts:
            l, ldist = lefts[0]
            beneficiary = self._materialize(l)
            if beneficiary is not None and l.start >= 1 and text[l.start - 1] in "为给向":
                subject = None
                for e in ents:
                    if e is l or e.start >= l.start - 1 or isinstance(e, Pseudo):
                        continue
                    if e.type == "ORG" and l.start - 1 - e.end <= rule.window:
                        subject = e if subject is None or e.start > subject.start else subject
                if subject is not None and rule.accepts(subject.type, beneficiary.type):
                    return [self._make(subject, beneficiary, rule, ldist + 4, sent, trig, "coref", -0.05)]

        # ---- "PERSON 出任 ORG 的 职位"：职务词前紧邻机构时，机构才是任职对象 ----
        if trig in _ROLE_SET and rule.key == "employ" and lefts and lefts[0][0].type == "ORG":
            org, odist = lefts[0]
            person = self._nearest_before(ents, org.start, window=16)
            if person and person.type == "PERSON" and person.start != org.start:
                return [self._make(person, org, rule, odist, sent, trig, "attributive", -0.03)]

        # ---- 分句以"并/且/也……"开头：主语继承上一分句（主语链）----
        if self._chain_clause_start(text, ts):
            chained = self._chained_subject(text, ents, rule, ts, te, sent, trig)
            if chained:
                return [chained]

        # ---- 常规：触发词两侧各有一个实体（先近后远）----
        pair = self._match_pair(lefts, rights, rule, ts, te, sent, trig)
        if pair:
            return pair
        wide_lefts = self._nearest(ents, ts, side="left", window=rule.window + 16)
        wide_rights = self._nearest(ents, te, side="right", window=rule.window + 16)
        pair = self._match_pair(wide_lefts, wide_rights, rule, ts, te, sent, trig)
        if pair:
            return pair

        # ---- "双方 / 两者"支撑的签约、合作、竞争、供应、诉讼 ----
        agreed = self._agreement_pair(text, ents, pseudo, rule, ts, sent, trig)
        if agreed:
            return agreed

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

        # ---- 隐性竞争："（话题）挤压/蚕食 A 和 B 的市场份额" ----
        if rule.key == "compete" and not lefts and "市场份额" in text[te:te + 15]:
            implicit = self._implicit_compete(text, rights, rule, sent, trig, doc)
            if implicit:
                return implicit

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

        # ---- "后者 / 前者" 作主语且句内无宾语：宾语取并列短语的另一方 ----
        if not rights and lefts:
            l, ldist = lefts[0]
            if isinstance(l, Pseudo) and l.counterpart is not None and len(l.resolved) == 1:
                head = l.resolved[0]
                if rule.key in ("supply", "cooperate", "sue") and rule.accepts(head.type, l.counterpart.type):
                    return [self._make(head, l.counterpart, rule, ldist + 4, sent, trig, "coref", -0.06)]
        return []

    # ------------------------------------------------------------------ #
    # 指代相关子分支
    # ------------------------------------------------------------------ #
    @staticmethod
    def _materialize(e: Entity) -> Entity | None:
        """把伪实体落地为真实实体；"双方"这类多指伪实体无法唯一落地。"""
        if not isinstance(e, Pseudo):
            return e
        return e.resolved[0] if len(e.resolved) == 1 else None

    @staticmethod
    def _chain_clause_start(text: str, ts: int) -> bool:
        """触发词所在分句是否以"并/且/也……"开头（主语链句式）。"""
        br = -1
        for ch in _CLAUSE_BREAKS:
            p = text.rfind(ch, 0, ts)
            if p > br:
                br = p
        if br < 0:
            return False
        seg = text[br + 1:ts]
        return len(seg) <= 10 and seg.startswith(_CHAIN_STARTERS)

    def _chained_subject(self, text: str, ents: list[Entity], rule, ts, te, sent, trig) -> Triple | None:
        """主语链："此前，A 已……，并与 B 签署……" -> 头实体取上一分句主语 A。"""
        br = -1
        for ch in _CLAUSE_BREAKS:
            p = text.rfind(ch, 0, ts)
            if p > br:
                br = p
        prev = -1
        for ch in _CLAUSE_BREAKS:
            p = text.rfind(ch, 0, br)
            if p > prev:
                prev = p
        subj = next(
            (e for e in ents if not isinstance(e, Pseudo) and e.start >= prev + 1 and e.end <= br),
            None,
        )
        if subj is None:
            return None
        obj, odist = None, 0
        for e in ents:
            if e is subj or isinstance(e, Pseudo):
                continue
            if e.start >= te:
                d = e.start - te
                if d <= rule.window and (obj is None or d < odist):
                    obj, odist = e, d
        if obj is None:
            for e in ents:
                if e is subj or isinstance(e, Pseudo):
                    continue
                if e.start >= br + 1 and e.end <= ts:
                    obj, odist = e, ts - e.end
                    break
        if obj is not None and rule.accepts(subj.type, obj.type):
            return self._make(subj, obj, rule, odist + 2, sent, trig, "chain", -0.03)
        return None

    def _agreement_pair(self, text: str, ents: list[Entity], pseudo: list[Pseudo], rule, ts, sent, trig) -> list[Triple]:
        """"双方已签订协议 / 双方将深化合作"：代词落地为两个参与方。"""
        if rule.key not in _AGREEMENT_KEYS:
            return []
        for p in pseudo:
            if len(p.resolved) != 2 or p.end > ts:
                continue
            # 代词与触发词之间不应夹其他实体，否则"双方"另有所指
            if any(p.end <= e.start and e.end <= ts for e in ents):
                continue
            a, b = p.resolved
            if a.text == b.text or not rule.accepts(a.type, b.type):
                continue
            return [self._make(a, b, rule, 6, sent, trig, "coref", -0.04)]
        return []

    def _implicit_compete(self, text: str, rights, rule, sent, trig, doc) -> list[Triple]:
        """"此举将进一步挤压比亚迪和蔚来汽车的市场份额"：头实体取全文话题。"""
        if not rights:
            return []
        topic = doc.topic()
        if topic is None:
            return []
        chain = [rights[0][0]]
        current = rights[0][0]
        for e, _d in rights[1:]:
            if e.start - current.end <= 3 and any(mk in text[current.end:e.start] for mk in _CONJ_MARKERS):
                chain.append(e)
                current = e
        out: list[Triple] = []
        for member in chain:
            if canonical_name(member.text, member.type) == canonical_name(topic.text, topic.type):
                continue
            if rule.accepts(topic.type, member.type):
                out.append(self._make(topic, member, rule, 8, sent, trig, "coref", -0.10))
        return out

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #
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
                lm, rm = self._materialize(l), self._materialize(r)
                if lm is None or rm is None or lm.start == rm.start:
                    continue
                if rule.accepts(lm.type, rm.type):
                    return [self._make(lm, rm, rule, ldist + rdist, sent, trig, "trigger")]
                if rule.accepts(rm.type, lm.type):
                    return [self._make(rm, lm, rule, ldist + rdist, sent, trig, "trigger")]
        return []

    def _make(
        self, head: Entity, tail: Entity, rule, distance: int, sent: Sentence,
        trigger: str, base: str, adjust: float = 0.0,
    ) -> Triple:
        base_conf = {"pattern": 0.96, "coref": 0.90}.get(base, 0.93)
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
            candidates = [
                e for e in ents
                if e.end <= current.start and current.start - e.end <= 8
            ]
            candidates.sort(key=lambda e: e.start, reverse=True)
            chosen = None
            for e in candidates:
                gap = text[e.end:current.start]
                if any(mk in gap for mk in _CONJ_MARKERS):
                    chosen = e
                    break
                if e.type == current.type:
                    # 同类型实体相邻却无并列词：并列链到此为止
                    break
                # 异类型相邻（如地名修饰机构名"德国默克集团"）：跳过继续向左找
            if chosen is None:
                return chain
            chain.insert(0, chosen)
            current = chosen
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
        # "双方已签订供货协议" 场景下供应事件由签署关系覆盖，去掉同向的 supply
        sign_pairs = {(t.head.text, t.tail.text) for t in result if t.key == "sign"}
        result = [
            t for t in result
            if not (t.key == "supply" and (t.head.text, t.tail.text) in sign_pairs)
        ]
        result.sort(key=lambda t: (-t.confidence, t.sentence_index))
        return result
