# -*- coding: utf-8 -*-
"""抽取流水线：分句 -> 实体识别 -> 关系抽取 -> 结构化输出。"""

from __future__ import annotations

import time

from .entity import Entity, EntityRecognizer
from .lexicon import ENTITY_TYPE_ORDER, ENTITY_TYPES, RELATION_MAP
from .relation import RelationExtractor
from .tokenizer import split_sentences, warmup

_recognizer: EntityRecognizer | None = None
_extractor: RelationExtractor | None = None


def _engines() -> tuple[EntityRecognizer, RelationExtractor]:
    global _recognizer, _extractor
    if _recognizer is None:
        warmup()
        _recognizer = EntityRecognizer()
        _extractor = RelationExtractor()
    assert _extractor is not None
    return _recognizer, _extractor


def analyze(text: str) -> dict:
    """对一段中文文本执行实体识别与关系抽取，返回可直接序列化的结果。"""
    started = time.perf_counter()
    text = (text or "").strip()
    if not text:
        return _empty_result(text, 0.0)

    recognizer, extractor = _engines()
    sentences = split_sentences(text)
    entities = recognizer.recognize(text, sentences)
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
    return {
        "text": text,
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
    }


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
