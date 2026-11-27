# -*- coding: utf-8 -*-
"""抽取流水线：分句 -> 实体识别 -> 关系抽取 -> 结构化输出。"""

from __future__ import annotations

import threading
import time

from .entity import Entity, EntityRecognizer
from .explanation import attach as attach_explanations
from .language import resolve_language
from .lexicon import ENTITY_TYPE_ORDER, ENTITY_TYPES, apply_custom_triggers
from .relation import RelationExtractor
from .tokenizer import split_sentences, warmup

_recognizer: EntityRecognizer | None = None
_extractor: RelationExtractor | None = None

# apply_custom_triggers 原地改写全局触发词索引。领域包让不同请求可能带不同
# 配置，两次 analyze 若不串行，A 的索引会被 B 覆盖，抽出错误结果。
# 同一配置下 apply 是签名相同的 O(1) 空操作，锁的开销可忽略；
# quality.py 的 A/B 试跑也复用这把锁，确保 before / after 之间不被插入。
analysis_lock = threading.RLock()


def _engines() -> tuple[EntityRecognizer, RelationExtractor]:
    global _recognizer, _extractor
    if _recognizer is None:
        warmup()
        _recognizer = EntityRecognizer()
        _extractor = RelationExtractor()
    assert _extractor is not None
    return _recognizer, _extractor


def analyze(
    text: str,
    custom_terms: list[dict] | None = None,
    custom_triggers: dict[str, list[str]] | None = None,
    language: str = "zh",
) -> dict:
    """对文本执行实体识别与关系抽取，返回可直接序列化的结果。

    custom_terms    —— 用户自定义词典，[{"text": ..., "type": ...}]
    custom_triggers —— 用户自定义关系触发词，{关系 key: [触发词...]}
    language        —— "zh"（默认，内部调用保持中文链路）/ "auto"（按 CJK
                       占比自动选）/ "en"（spaCy 双引擎）

    注意：默认值保留 "zh"，让信息甄别、评测、规则实验室等内部调用维持
    原来的确定性中文链路；面向用户的抽取接口默认传 "auto" 做自动识别。
    双引擎：中文走自研词典 + 触发词规则（零模型依赖），英文走 spaCy 的
    NER + 依存句法。两者输出同一套 schema。english 模块在函数内懒加载，
    因此未装 spaCy 的环境里中文链路完全不受影响。
    自动识别为确定性规则，判别细节写进结果的 language_detection 字段。
    """
    lang, detection = resolve_language(language, text)
    if lang == "en":
        from .english import analyze_en
        result = analyze_en(text)
        result["language_detection"] = detection
        return result

    started = time.perf_counter()
    text = (text or "").strip()
    if not text:
        result = _empty_result(text, 0.0)
        result["language"] = "zh"
        result["language_detection"] = detection
        return result

    # 自定义触发词按签名增量同步，同一套配置下是常数级空操作。
    # 索引是全局的，配置→抽取必须在同一把锁内完成，否则领域包并发会串味。
    with analysis_lock:
        apply_custom_triggers(custom_triggers)
        recognizer, extractor = _engines()
        sentences = split_sentences(text)
        entities = recognizer.recognize(text, sentences, custom_terms=custom_terms)
        for i, e in enumerate(entities, start=1):
            e.id = f"e{i}"
        triples = extractor.extract(sentences, entities)
    relations = []
    for i, t in enumerate(triples, start=1):
        item = t.as_dict()
        item["id"] = f"r{i}"
        relations.append(item)

    entity_type_counts = {k: 0 for k in ENTITY_TYPE_ORDER}
    for e in entities:
        entity_type_counts[e.type] = entity_type_counts.get(e.type, 0) + 1

    relation_type_counts: dict[str, int] = {}
    for r in relations:
        relation_type_counts[r["relation"]] = relation_type_counts.get(r["relation"], 0) + 1

    elapsed = (time.perf_counter() - started) * 1000
    return attach_explanations({
        "text": text,
        "language": "zh",
        "language_detection": detection,
        "sentences": [
            {"index": s.index, "start": s.start, "end": s.end, "text": s.text}
            for s in sentences
        ],
        "entities": [e.as_dict() for e in entities],
        "relations": relations,
        "entity_type_counts": entity_type_counts,
        "relation_type_counts": relation_type_counts,
        "stats": {
            "char_count": len(text),
            "sentence_count": len(sentences),
            "entity_count": len(entities),
            "relation_count": len(relations),
            "unique_entity_count": len({e.text for e in entities}),
            "elapsed_ms": round(elapsed, 1),
        },
    })


def highlight_spans(entities: list[Entity]) -> list[dict]:
    """把实体转成前端的标注片段（按 start 升序，不含重叠）。"""
    spans = sorted(entities, key=lambda e: e.start)
    return [
        {
            "start": e.start,
            "end": e.end,
            "text": e.text,
            "type": e.type,
            "type_label": ENTITY_TYPES[e.type]["label"],
            "id": e.id,
        }
        for e in spans
    ]


def _empty_result(text: str, elapsed: float) -> dict:
    return {
        "text": text,
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
        },
    }
