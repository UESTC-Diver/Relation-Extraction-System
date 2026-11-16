# -*- coding: utf-8 -*-
"""规则体检：从历史抽取结果里找出「哪些规则在干活、哪些从没命中过」。

不新建统计表，只做一次 relations 全表扫描 + 两张留痕表的聚合；
纯本地、纯读取，不联网也不调用模型。输出既给界面展示，也直接给出
可执行的主动建议，把质量闭环从「人看报表」推到「系统提建议」。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from . import db
from .nlp.explanation import STRATEGIES
from .nlp.lexicon import RELATION_MAP
from .nlp.profiles import catalog

# 低于这个置信度的关系值得先进复核队列
LOW_CONF = 0.75


def _label(key: str) -> str:
    rule = RELATION_MAP.get(key)
    return rule.label if rule else key


def build() -> dict[str, Any]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT relation, relation_label, rule_base, trigger, confidence, evidence
               FROM relations"""
        ).fetchall()
        deletions = conn.execute(
            "SELECT relation, relation_label FROM relation_deletions"
        ).fetchall()
        reviews = conn.execute(
            "SELECT decision FROM review_decisions"
        ).fetchall()
        custom_rules = conn.execute(
            "SELECT relation_key, trigger FROM custom_rules"
        ).fetchall()

    total = len(rows)
    trigger_hits: Counter[str] = Counter()
    strategy_hits: Counter[str] = Counter()
    relation_hits: Counter[str] = Counter()
    low_conf = 0
    manual = 0
    for r in rows:
        key = r["relation"] or ""
        relation_hits[key] += 1
        strategy_hits[r["rule_base"] or "trigger"] += 1
        trig = (r["trigger"] or "").strip()
        if trig:
            trigger_hits[trig] += 1
        if float(r["confidence"] or 0) < LOW_CONF:
            low_conf += 1
        if r["rule_base"] == "manual":
            manual += 1

    # 命中判据：trigger 精确相等，或证据句里含该触发词（句式模板命中的
    # trigger 是渲染后的片段，不是原始词，只看 trigger 会误报「从未命中」）。
    evidence_text = "\n".join(r["evidence"] or "" for r in rows)
    hit_words = set(trigger_hits) | {
        word for word in _all_trigger_words() if word in evidence_text
    }
    unused: list[dict[str, Any]] = []
    for key, rule in RELATION_MAP.items():
        for word in rule.triggers:
            if word not in hit_words:
                unused.append({
                    "trigger": word,
                    "relation": key,
                    "relation_label": rule.label,
                    "source": "builtin",
                })
    for r in custom_rules:
        word = (r["trigger"] or "").strip()
        if word and word not in hit_words:
            unused.append({
                "trigger": word,
                "relation": r["relation_key"] or "",
                "relation_label": _label(r["relation_key"] or ""),
                "source": "custom",
            })

    deleted: Counter[str] = Counter()
    deleted_labels: dict[str, str] = {}
    for r in deletions:
        key = r["relation"] or ""
        deleted[key] += 1
        deleted_labels[key] = r["relation_label"] or _label(key)

    review_counts: Counter[str] = Counter(r["decision"] or "" for r in reviews)

    hot_triggers = [
        {"trigger": word, "count": count}
        for word, count in trigger_hits.most_common(20)
    ]
    hot_strategies = [
        {
            "rule_base": key,
            "label": STRATEGIES.get(key, (key, ""))[0],
            "count": count,
        }
        for key, count in strategy_hits.most_common()
    ]
    hot_relations = [
        {"relation": key, "relation_label": _label(key), "count": count}
        for key, count in relation_hits.most_common()
    ]
    deleted_rows = [
        {
            "relation": key,
            "relation_label": deleted_labels.get(key, _label(key)),
            "count": count,
        }
        for key, count in deleted.most_common()
    ]

    summary = {
        "relations": total,
        "low_confidence": low_conf,
        "low_confidence_ratio": round(low_conf / total, 3) if total else 0.0,
        "manual": manual,
        "unused_triggers": len(unused),
        "deleted_relations": len(deletions),
        "rejected": review_counts.get("rejected", 0),
        "questioned": review_counts.get("questioned", 0),
        "approved": review_counts.get("approved", 0),
    }
    return {
        "summary": summary,
        "hot_triggers": hot_triggers,
        "hot_strategies": hot_strategies,
        "hot_relations": hot_relations,
        "unused_triggers": unused[:80] if total else [],
        "deleted_by_relation": deleted_rows,
        "confidence_threshold": LOW_CONF,
        "profiles": catalog(),
        "suggestions": _suggestions(summary, unused, deleted_rows, hot_strategies),
    }


def _all_trigger_words() -> set[str]:
    return {word for rule in RELATION_MAP.values() for word in rule.triggers}


def _suggestions(
    summary: dict[str, Any],
    unused: list[dict[str, Any]],
    deleted: list[dict[str, Any]],
    strategies: list[dict[str, Any]],
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []

    # 空库时所有触发词都「从未命中」，据此给建议等于误导；只提示先积累数据。
    if summary["relations"] == 0:
        return [{
            "kind": "baseline",
            "title": "暂无明显改进信号",
            "detail": "还没有历史抽取结果，命中热区与触发词覆盖都无从谈起。"
                      "先在工作台抽几篇不同领域的文本，体检结论才有参考价值。",
            "action": "进入工作台",
        }]

    if deleted:
        top = deleted[0]
        out.append({
            "kind": "deleted",
            "title": f"「{top['relation_label']}」被人工删掉 {top['count']} 次",
            "detail": "这一类关系的自动抽取最常被否掉。先在规则实验室用同类文本做 A/B 试跑，"
                      "确认是触发词过宽还是句式模板误配，再决定收紧或改写。",
            "action": "打开规则实验室",
        })

    if summary["low_confidence"] and summary["low_confidence_ratio"] >= 0.15:
        pct = round(summary["low_confidence_ratio"] * 100)
        out.append({
            "kind": "confidence",
            "title": f"{pct}% 的关系置信度低于 {LOW_CONF}",
            "detail": f"共 {summary['low_confidence']} 条。建议先走复核队列逐条核对，"
                      "把确认无误的高频说法沉淀成触发词，而不是直接降低阈值。",
            "action": "查看复核队列",
        })

    by_relation: Counter[str] = Counter(u["relation"] for u in unused)
    if by_relation:
        key, count = by_relation.most_common(1)[0]
        out.append({
            "kind": "unused",
            "title": f"「{_label(key)}」有 {count} 个触发词从未命中",
            "detail": "这类词可能是领域外说法，也可能缺一份能覆盖它的样例文本。"
                      "试跑一次再决定是否保留；删掉无效词能减少误抽与索引噪音。",
            "action": "打开规则实验室",
        })

    if summary["manual"]:
        out.append({
            "kind": "manual",
            "title": f"已有 {summary['manual']} 条人工补录关系",
            "detail": "把反复人工补录的说法整理成候选触发词，用 A/B 试跑确认没有误抽后"
                      "再写入配置，并顺手存一份版本快照以便回滚。",
            "action": "打开规则实验室",
        })

    if strategies and strategies[0]["rule_base"] == "trigger" and summary["relations"] >= 5:
        out.append({
            "kind": "coverage",
            "title": "命中主要来自触发词扫描",
            "detail": "句式模板能处理反常语序与被动句。若文本里大量关系是靠远距离触发词配对，"
                      "可考虑为高频句式补一条模板，提高置信度与可解释性。",
            "action": "查看解释详情",
        })

    if not out:
        out.append({
            "kind": "baseline",
            "title": "暂无明显改进信号",
            "detail": "历史结果还太少，或各规则命中分布均衡。多抽几篇不同领域的文本，"
                      "体检结论会更有参考价值。",
            "action": "进入工作台",
        })
    return out
