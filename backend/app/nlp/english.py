# -*- coding: utf-8 -*-
"""英文关系抽取引擎：spaCy NER + 依存句法 → 与中文同 schema 的三元组。

设计取舍（这是「双引擎架构」的英文半边）
------------------------------------------
中文侧是自研词典 + 触发词规则（体现手写规则的工作量）；英文侧接 spaCy
成熟模型（体现工程选型判断：什么时候该用现成工具）。两者输出**完全相同**
的 dict schema，前端、报告、评测层都无需区分语言。

为什么用 spaCy 而不是照搬中文规则
----------------------------------
英文有词形变化（acquire/acquired/acquiring）、从句与灵活语序，纯触发词规则
覆盖率很低。spaCy 的 ``en_core_web_sm`` 自带分词、词性、NER 与依存句法，
一条龙解决，是英文版的「LTP」。

技术边界
--------
* 关系抽取仍**锚定动词**：用依存句法找 nsubj（主语）与 dobj/pobj/attr（宾语），
  再用英文触发词映射到中文的 19 类关系 key，复用同一套 label / color / 类型约束。
* 确定性：同一模型同一文本结果一致；模型本身不联网、不调用 API。
* 优雅降级：模型缺失/加载失败时 ``available()`` 返回 False，接口给出明确提示，
  绝不拖垮中文链路（中文引擎完全不 import 本模块的成功路径）。
"""

from __future__ import annotations

import time
from typing import Any

from .entity import canonical_name
from .lexicon import ENTITY_TYPE_ORDER, ENTITY_TYPES, RELATION_MAP
from .polarity import judge_en

# spaCy NER label -> 本项目实体类型
# GPE（国家/城市）与 LOC（山川）都归到 LOC；日期走 DATE/TIME -> TIME；
# 金额 MONEY 与产品 WORK_OF_ART / PRODUCT 分别映射。
_LABEL_MAP = {
    "PERSON": "PERSON",
    "PERSON_TYPE": "PERSON",
    "ORG": "ORG",
    "GPE": "LOC",
    "LOC": "LOC",
    "FAC": "LOC",
    "DATE": "TIME",
    "TIME": "TIME",
    "MONEY": "MONEY",
    "PRODUCT": "PRODUCT",
    "WORK_OF_ART": "PRODUCT",
    "LAW": "PRODUCT",
}

# 英文触发词（lemma / 原形）-> 中文关系 key。
# 一个 key 多个说法；映射后复用 RELATION_MAP 的 label / color / 类型约束，
# 保证英文三元组在前端的配色、图例、解释口径与中文完全一致。
_EN_TRIGGERS: dict[str, tuple[str, ...]] = {
    "acquire": (
        "acquire", "buy", "purchase", "merge", "take over", "takeover",
        "absorb", "swallow", "snap up", "acquisition", "buyout",
    ),
    "invest": (
        "invest", "fund", "back", "finance", "inject", "stake", "round",
        "investment", "lead the round", "participate",
    ),
    "control": ("control", "own", "hold", "dominate", "majority stake", "controlling"),
    "subsidiary": ("subsidiary", "unit", "arm", "offshoot", "daughter company"),
    "employ": (
        "work for", "work at", "employ", "join", "serve as", "become", "lead",
        "chief executive", "ceo", "appointed", "named", "hire",
    ),
    "appoint": ("appoint", "name", "nominate", "recruit", "hire", "select"),
    "headquarter": ("headquarter", "based", "base", "headquarters"),
    "locate": ("locate", "situate", "based", "headquarter", "found in", "set in"),
    "found": ("found", "establish", "create", "start", "co-found", "launch"),
    "founded_at": ("founded in", "established in", "founded", "established"),
    "graduate": ("graduate", "study at", "attend", "alumnus", "alumni"),
    "born": ("born in", "born", "native of"),
    "cooperate": ("partner", "cooperate", "collaborate", "team up", "ally", "joint venture"),
    "compete": ("compete", "rival", "compete with", "challenge", "vying"),
    "supply": ("supply", "supplier", "provide", "provide to", "manufacture for", "deliver"),
    "sign": ("sign", "sign a deal", "sign an agreement", "ink", "reach an agreement"),
    "sue": ("sue", "lawsuit", "sued", "file suit", "accuse", "charge", "litigation"),
    "launch": ("launch", "release", "unveil", "introduce", "roll out", "debut"),
    "belong": ("belong to", "belongs to", "part of", "affiliated with", "under"),
}

# 触发词组（多词）按词数倒序，匹配时优先长词，避免 "found" 抢在 "founded in" 前。
_TRIGGER_LOOKUP: list[tuple[str, str]] = sorted(
    ((phrase, key) for key, phrases in _EN_TRIGGERS.items() for phrase in phrases),
    key=lambda pair: -len(pair[0].split()),
)

# spaCy 依存关系：主语 / 宾语 / 介词宾语 / 表语
_SUBJ_DEPS = {"nsubj", "nsubjpass", "csubj"}
_OBJ_DEPS = {"dobj", "pobj", "attr", "obl", "obj"}

# en_core_web_sm 对知名公司常误判为地名（Alibaba→GPE、Epic Games→FAC）。
# 这些后缀基本可断定为组织，用来纠正模型的小模型偏差。
_ORG_SUFFIX = ("Inc", "Inc.", "Corp", "Corp.", "Corporation", "Ltd", "Ltd.",
               "LLC", "Co.", "Group", "Games", "Systems", "Technologies",
               "Labs", "Motors", "Bank", "Airlines", "University")
# 职位词：X is the CEO/Founder of Y -> employ/found
_ROLE_WORDS_EN = {"ceo", "cto", "cfo", "coo", "president", "chairman",
                  "founder", "co-founder", "director", "manager", "head"}
# 不需要交换头尾的关系（主语就是头，即便被动式）
_NO_SWAP_KEYS = {"headquarter", "locate", "founded_at", "employ", "found"}

_nlp: Any = None
_load_error: str = ""


def available() -> bool:
    """英文模型是否可用。不抛异常，供 health / 接口探测。"""
    global _nlp, _load_error
    if _nlp is not None:
        return True
    try:
        import en_core_web_sm  # noqa: F401
        return True
    except Exception as exc:  # 模型未装或加载失败
        _load_error = f"{type(exc).__name__}: {exc}"
        return False


def engine_error() -> str:
    """给接口用的错误说明（不含敏感路径细节）。"""
    return _load_error or "英文模型未安装"


def _get_nlp() -> Any:
    global _nlp, _load_error
    if _nlp is not None:
        return _nlp
    try:
        import en_core_web_sm
        _nlp = en_core_web_sm.load()
        _load_error = ""
        return _nlp
    except Exception as exc:
        _load_error = f"{type(exc).__name__}: {exc}"
        raise RuntimeError(
            "英文抽取引擎需要 en_core_web_sm 模型，当前不可用。"
            "请先运行：pip install en_core_web_sm"
        ) from exc


def _match_key(verb_text: str, verb_lemma: str) -> str | None:
    """把英文动词（原文或 lemma）映射到中文关系 key，长词组优先。"""
    lowered = verb_text.lower().strip()
    lemma = verb_lemma.lower().strip()
    blob = f"{lemma} {lowered}"
    for phrase, key in _TRIGGER_LOOKUP:
        # 单词用边界匹配，避免 found 命中 fundamental；词组用子串即可
        if " " in phrase:
            if phrase in blob:
                return key
        elif phrase == lemma or phrase == lowered:
            return key
    return None


def _entity_index(entities: list[dict]) -> dict[int, dict]:
    """按起始字符建索引，便于判断依存节点是否落在实体跨度内。"""
    return {int(e["start"]): e for e in entities}


def _find_entity(token: Any, ents: list[dict]) -> dict | None:
    """token 是否落在某个实体跨度内（含专家标注的多词实体）。"""
    for e in ents:
        if int(e["start"]) <= token.idx < int(e["end"]):
            return e
    return None


def _sentences_from_doc(doc: Any) -> list[dict]:
    """用 spaCy 的句子边界，返回带字符偏移的句子列表。"""
    out: list[dict] = []
    for i, sent in enumerate(doc.sents):
        text = sent.text
        if not text.strip():
            continue
        out.append({
            "index": len(out),
            "start": sent.start_char,
            "end": sent.end_char,
            "text": text,
        })
    return out


def _entities_from_doc(doc: Any) -> list[dict]:
    """spaCy NER -> 项目实体 dict（复用 canonical_name 与配色）。

    顺带纠正 en_core_web_sm 的小模型偏差：带公司后缀、或在句中处于
    动词 dobj/pobj 位置且被误标为地名的专名，改判为 ORG。
    """
    # 动词宾语位置的 token 起点 -> 该处实体应判 ORG。
    # 只对「机构类」动词纠正：acquire/found/invest 的宾语是公司；
    # be/become 的 of 宾语（CEO of X）也是公司。
    # 注意 headquarter 的 in 宾语是地名，绝不能列进来（Hangzhou 会被误判）。
    org_candidates: set[int] = set()
    for token in doc:
        lemma = token.lemma_.lower()
        if token.pos_ not in ("VERB", "AUX"):
            continue
        if lemma in {"acquire", "found", "invest", "buy", "purchase"}:
            for child in token.children:
                if child.dep_ in ("dobj", "attr"):
                    org_candidates.add(child.idx)
                elif child.dep_ == "prep":
                    for sub in child.children:
                        if sub.dep_ in ("pobj", "obj"):
                            org_candidates.add(sub.idx)
        elif lemma in ("be", "become"):
            # X is/became CEO of Y：of 的 pobj 是机构
            for child in token.children:
                if child.dep_ == "attr":
                    for sub in child.children:
                        if sub.text.lower() == "of":
                            for org_tok in sub.children:
                                if org_tok.dep_ in ("pobj", "obj"):
                                    org_candidates.add(org_tok.idx)

    out: list[dict] = []
    for ent in doc.ents:
        etype = _LABEL_MAP.get(ent.label_)
        if not etype:
            continue
        raw = ent.text.strip()
        # 纠正规则：公司后缀 或 处在动词宾语位 且原判为 LOC/PRODUCT
        looks_org = raw.endswith(_ORG_SUFFIX) or ent.start_char in org_candidates
        if etype in ("LOC", "PRODUCT") and looks_org:
            etype = "ORG"
        out.append({
            "id": "",
            "text": ent.text,
            "canonical": canonical_name(ent.text, etype),
            "type": etype,
            "type_label": ENTITY_TYPES[etype]["label"],
            "color": ENTITY_TYPES[etype]["color"],
            "start": ent.start_char,
            "end": ent.end_char,
            "sentence_index": -1,
            "source": "spacy_ner" + ("+corrected" if looks_org and etype == "ORG" else ""),
            "confidence": 0.95,
        })
    # 补召回：spaCy 小模型会漏掉被动句主语（Alibaba is headquartered...）。
    # 用依存句法兜底：处在主/宾位置、未被 NER 覆盖的专有名词，按上下文补建。
    for token in doc:
        if token.pos_ != "PROPN":
            continue
        if token.dep_ not in ("nsubj", "nsubjpass", "dobj", "pobj"):
            continue
        if any(e["start"] <= token.idx < e["end"] for e in out):
            continue
        # 注意：这里按「字符偏移」而非「名字」去重。跨句同名实体（如第二句的
        # Alibaba）必须各自保留，否则 headquartered 找不到它的主语；前端图谱
        # 会按 canonical_name 归并，不会显示成两个节点。
        # 简单公司名判断：纯字母专名（含空格分词后的连续 token）视为 ORG
        etype = "ORG" if token.text[:1].isupper() else "PERSON"
        out.append({
            "id": "", "text": token.text, "canonical": canonical_name(token.text, etype),
            "type": etype, "type_label": ENTITY_TYPES[etype]["label"],
            "color": ENTITY_TYPES[etype]["color"],
            "start": token.idx, "end": token.idx + len(token.text),
            "sentence_index": -1, "source": "dependency_fallback", "confidence": 0.75,
        })

    # 按 start 升序，分配 id 并挂句子号（稍后由调用方补 sentence_index）
    out.sort(key=lambda e: e["start"])
    for i, e in enumerate(out, start=1):
        e["id"] = f"e{i}"
    return out


def _relation_dict(
    head: dict, tail: dict, key: str, evidence: str, trigger: str,
    sentence_index: int, rule_base: str,
) -> dict:
    rule = RELATION_MAP[key]
    # 与中文同源：英文也有「否认 / 传闻 / 条件」三档，只是词表不同。
    verdict = judge_en(evidence)
    confidence = 0.93 * verdict["penalty"]
    return {
        "head": head["text"],
        "head_canonical": canonical_name(head["text"], head["type"]),
        "head_type": head["type"],
        "head_id": head["id"],
        "tail": tail["text"],
        "tail_canonical": canonical_name(tail["text"], tail["type"]),
        "tail_type": tail["type"],
        "tail_id": tail["id"],
        "relation": key,
        "relation_label": rule.label,
        "relation_color": rule.color,
        "confidence": round(max(0.15, confidence), 2),
        "evidence": evidence.strip(),
        "sentence_index": sentence_index,
        "trigger": trigger,
        "rule_base": rule_base,
        "score_parts": {
            "base": 0.93, "distance_penalty": 0, "adjust": 0,
            **({"polarity": round(verdict["penalty"], 2)} if verdict["penalty"] < 1 else {}),
        },
        "matched_template": "dependency_anchor",
        "assertion": verdict["assertion"],
        "assertion_label": verdict["assertion_label"],
        "assertion_cue": verdict["assertion_cue"],
        "assertion_clause": verdict["assertion_clause"],
        "language": "en",
    }


def _en_explanation(rel: dict) -> dict:
    """英文关系的可读解释：说明走的是 spaCy 依存句法锚定，不是中文分句规则。"""
    rule = RELATION_MAP.get(rel["relation"])
    type_constraint = (
        f"{' / '.join(ENTITY_TYPES[t]['label'] for t in rule.head_types)} → "
        f"{' / '.join(ENTITY_TYPES[t]['label'] for t in rule.tail_types)}"
        if rule else f"{rel.get('head_type')} → {rel.get('tail_type')}"
    )
    return {
        "strategy": "依存句法锚定",
        "strategy_key": "dependency",
        "strategy_how": "spaCy NER 识别实体，依存句法以动词为锚点找主语与宾语，再按英文触发词映射到关系类型",
        "matched": rel.get("trigger") or "—",
        "template": "dependency_anchor",
        "type_constraint": type_constraint,
        "rule_description": rule.description if rule else "",
        "confidence_parts": {
            "base": 0.93,
            "distance_penalty": None,
            "adjust": None,
            "final": 0.93,
            "clamp": [0.52, 0.98],
            "formula": "spaCy 依存句法锚定基准分 0.93（模型推理，非中文距离衰减规则）",
            "exact": True,
        },
        "evidence": rel.get("evidence", ""),
        "sentence_index": rel.get("sentence_index"),
        "sentence_no": (rel.get("sentence_index") or 0) + 1,
        "source": "model",
        "steps": [
            "spaCy 按英文标点分句并做词性标注",
            f"NER 识别头实体「{rel.get('head', '')}」与尾实体「{rel.get('tail', '')}」",
            f"依存句法锚定动词「{rel.get('trigger', '')}」，确定主谓宾方向",
            f"英文触发词映射到关系「{rel.get('relation_label', '')}」并通过类型约束 {type_constraint}",
        ],
    }


def analyze_en(text: str) -> dict:
    """对英文文本执行抽取，返回与中文 analyze() 完全一致的 dict schema。"""
    started = time.perf_counter()
    text = (text or "").strip()
    if not text:
        return _empty_result(text, 0.0)

    nlp = _get_nlp()
    doc = nlp(text)

    sentences = _sentences_from_doc(doc)
    entities = _entities_from_doc(doc)
    sent_count = len(sentences)

    # 挂句子号：用字符偏移定位实体属于哪一句
    for e in entities:
        for s in sentences:
            if s["start"] <= e["start"] < s["end"]:
                e["sentence_index"] = s["index"]
                break

    relations: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def add_relation(h: dict, t: dict, key: str, trigger: str, sent_idx: int, base: str):
        sig = (h["text"], key, t["text"])
        if sig in seen or h["id"] == t["id"]:
            return
        seen.add(sig)
        relations.append(_relation_dict(h, t, key, s_text, trigger, sent_idx, base))

    for sent_idx, s in enumerate(sentences):
        s_text = s["text"]
        sent = next((x for x in doc.sents if x.start_char == s["start"]), None)
        if sent is None:
            continue
        tokens = list(sent)

        # ---- 句式模板 1：X is/was the CEO/Founder of Y ----
        # 动词 be + 职位词(attr) + of + ORG。主语是人物，of 后是机构。
        for i, token in enumerate(tokens):
            if token.lemma_.lower() not in ("be", "become", "became"):
                continue
            subj = next((c for c in token.children if c.dep_ == "nsubj"), None)
            attr = next((c for c in token.children if c.dep_ == "attr"), None)
            if not subj or not attr or attr.text.lower().strip(".") not in _ROLE_WORDS_EN:
                continue
            person = _find_entity(subj, entities)
            if not person or person["type"] != "PERSON":
                continue
            # 找 of 后面的机构
            org = None
            for c in attr.children:
                if c.text.lower() == "of":
                    for sub in c.children:
                        if sub.dep_ in ("pobj", "obj"):
                            cand = _find_entity(sub, entities)
                            if cand and cand["type"] in ("ORG", "LOC"):
                                org = cand
            if org:
                key = "found" if attr.text.lower().startswith("found") else "employ"
                add_relation(person, org, key, f"{token.text} {attr.text} of", sent_idx, "pattern")

        # ---- 通用：动词锚定 + 主语/宾语 ----
        for token in tokens:
            if token.pos_ not in ("VERB", "AUX"):
                continue
            key = _match_key(token.text, token.lemma_)
            if not key:
                continue
            rule = RELATION_MAP[key]
            heads: list[dict] = []
            tails: list[dict] = []
            for child in token.children:
                if child.dep_ in _SUBJ_DEPS:
                    ent = _find_entity(child, entities)
                    if ent:
                        heads.append(ent)
                elif child.dep_ in _OBJ_DEPS:
                    ent = _find_entity(child, entities)
                    if ent:
                        tails.append(ent)
            # 介词短语里的宾语：A was acquired by B -> by 的 pobj 是 B
            for child in token.children:
                if child.dep_ in ("prep", "agent"):
                    for sub in child.children:
                        if sub.dep_ in ("pobj", "obj", "obl"):
                            ent = _find_entity(sub, entities)
                            if ent:
                                tails.append(ent)

            is_passive = any(c.dep_ == "auxpass" for c in token.children) or "pass" in {
                c.dep_ for c in token.children
            }
            for h in heads:
                for t in tails:
                    if h["id"] == t["id"]:
                        continue
                    if rule.accepts(h["type"], t["type"]):
                        add_relation(h, t, key, token.text, sent_idx, "dependency")
                    elif rule.accepts(t["type"], h["type"]):
                        # 类型反了：主动句里可能是倒置，或被动句需要交换。
                        # 但 headquarter/locate/employ/found 这类关系主语就是头，
                        # 即便被动（is headquartered in）也不交换，否则方向倒挂。
                        if is_passive and key not in _NO_SWAP_KEYS:
                            add_relation(t, h, key, token.text, sent_idx, "passive")
                        elif not is_passive:
                            add_relation(t, h, key, token.text, sent_idx, "dependency")

    for i, r in enumerate(relations, start=1):
        r["id"] = f"r{i}"
        r["explanation"] = _en_explanation(r)

    entity_type_counts = {k: 0 for k in ENTITY_TYPE_ORDER}
    for e in entities:
        entity_type_counts[e["type"]] = entity_type_counts.get(e["type"], 0) + 1
    relation_type_counts: dict[str, int] = {}
    for r in relations:
        relation_type_counts[r["relation"]] = relation_type_counts.get(r["relation"], 0) + 1

    elapsed = (time.perf_counter() - started) * 1000
    assertion_counts: dict[str, int] = {}
    for r in relations:
        key = r.get("assertion") or "fact"
        assertion_counts[key] = assertion_counts.get(key, 0) + 1
    fact_count = assertion_counts.get("fact", 0)
    return {
        "text": text,
        "language": "en",
        "engine": "spacy",
        "sentences": sentences,
        "entities": entities,
        "relations": relations,
        "entity_type_counts": entity_type_counts,
        "relation_type_counts": relation_type_counts,
        "stats": {
            "char_count": len(text),
            "sentence_count": sent_count,
            "entity_count": len(entities),
            "relation_count": len(relations),
            "unique_entity_count": len({e["text"] for e in entities}),
            "elapsed_ms": round(elapsed, 1),
            "fact_relation_count": fact_count,
            "non_fact_relation_count": len(relations) - fact_count,
            "assertion_counts": assertion_counts,
        },
    }


def _empty_result(text: str, elapsed: float) -> dict:
    return {
        "text": text,
        "language": "en",
        "engine": "spacy",
        "sentences": [],
        "entities": [],
        "relations": [],
        "entity_type_counts": {k: 0 for k in ENTITY_TYPE_ORDER},
        "relation_type_counts": {},
        "stats": {
            "char_count": len(text),
            "sentence_count": 0,
            "entity_count": 0,
            "relation_count": 0,
            "unique_entity_count": 0,
            "elapsed_ms": elapsed,
            "fact_relation_count": 0,
            "non_fact_relation_count": 0,
            "assertion_counts": {},
        },
    }
