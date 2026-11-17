# -*- coding: utf-8 -*-
"""把一条三元组还原成「为什么抽出来」的可读解释。

纯函数，不参与抽取判定：输入是 relation.py 输出的字典（或历史记录从
SQLite 读回的同一形状），输出一个 explanation 对象。评测只比较
head / relation / tail，因此这里增加任何字段都不会改变 P/R/F1。

为什么不把解释直接写死在前端：同一条关系既可能来自实时抽取，也可能来自
历史记录、项目包导入或只读报告；把解释的生成放在唯一一处，四处口径才一致。
"""

from __future__ import annotations

from typing import Any

from .lexicon import ENTITY_TYPES, RELATION_MAP

# rule_base -> (可读名称, 判定说明)
STRATEGIES: dict[str, tuple[str, str]] = {
    "pattern": ("句式模板", "命中固定句式模板，按模板槽位直接确定头尾实体，不依赖触发词左右扫描"),
    "trigger": ("触发词锚定", "以触发词为锚点，向左 / 向右寻找符合类型约束且距离最近的实体"),
    "passive": ("被动句", "识别「被 / 由」结构后交换头尾实体，再按类型约束校验"),
    "conjunction": ("并列结构", "识别「A 与 B」并列链，取链首与链尾作为关系双方"),
    "postmodifier": ("后置定语", "触发词在前、实体在后，走正向配对分支"),
    "attributive": ("职位线索", "职务词与紧邻机构 / 人物组合，确定真正的任职对象"),
    "coref": ("指代消解", "「双方 / 该公司 / 后者」等回指词落地到前文真实实体"),
    "chain": ("主语链", "分句以「并 / 且 / 也」开头，主语继承上一分句"),
    "manual": ("人工校正", "由人工录入或改写，不经过规则引擎"),
}

_BASE_CONF = {"pattern": 0.96, "coref": 0.90}


def _type_label(key: str) -> str:
    return ENTITY_TYPES.get(key, {}).get("label", key or "未标注")


def _confidence(rel: dict[str, Any]) -> dict[str, Any]:
    """给出置信度构成。有新抽取带的 score_parts 就精确展开，否则定性说明。"""
    parts = rel.get("score_parts") or {}
    final = round(float(rel.get("confidence") or 0), 2)
    if parts:
        base = round(float(parts.get("base", 0)), 2)
        penalty = round(float(parts.get("distance_penalty", 0)), 2)
        adjust = round(float(parts.get("adjust", 0)), 2)
        expr = f"{base:.2f}"
        if penalty:
            expr += f" − {abs(penalty):.2f}（实体距离）"
        if adjust:
            expr += f" {adjust:+.2f}（句式修正）"
        expr += f" = {final:.2f}（限定在 0.52–0.98）"
        return {
            "base": base,
            "distance_penalty": penalty,
            "adjust": adjust,
            "final": final,
            "clamp": [0.52, 0.98],
            "formula": expr,
            "exact": True,
        }
    strategy = str(rel.get("rule_base") or "trigger")
    base = 0.94 if strategy == "pattern" else _BASE_CONF.get(strategy, 0.93)
    return {
        "base": round(base, 2),
        "distance_penalty": None,
        "adjust": None,
        "final": final,
        "clamp": [0.52, 0.98],
        "formula": (
            f"{strategy} 基准分约 {base:.2f}，按实体距离衰减与句式修正后为 {final:.2f}；"
            "历史快照未保存逐步分值"
        ),
        "exact": False,
    }


def explain(rel: dict[str, Any]) -> dict[str, Any]:
    """从一条关系生成解释对象；缺字段时全部降级，不抛异常。"""
    strategy_key = str(rel.get("rule_base") or "trigger")
    label, how = STRATEGIES.get(strategy_key, ("规则匹配", "由规则引擎给出"))
    relation_key = str(rel.get("relation") or "")
    rule = RELATION_MAP.get(relation_key)
    head_type = str(rel.get("head_type") or "")
    tail_type = str(rel.get("tail_type") or "")

    if rule is not None:
        type_constraint = (
            f"{' / '.join(_type_label(t) for t in rule.head_types)} → "
            f"{' / '.join(_type_label(t) for t in rule.tail_types)}"
        )
        rule_description = rule.description
    else:
        type_constraint = f"{_type_label(head_type)} → {_type_label(tail_type)}"
        rule_description = ""

    matched = str(rel.get("trigger") or "").strip()
    template = str(rel.get("matched_template") or "").strip()
    confidence = _confidence(rel)
    sentence_index = rel.get("sentence_index")
    try:
        sentence_no = int(sentence_index) + 1
    except (TypeError, ValueError):
        sentence_no = None

    return {
        "strategy": label,
        "strategy_key": strategy_key,
        "strategy_how": how,
        "matched": matched or "—",
        "template": template or None,
        "type_constraint": type_constraint,
        "rule_description": rule_description,
        "confidence_parts": confidence,
        "evidence": str(rel.get("evidence") or ""),
        "sentence_index": sentence_index,
        "sentence_no": sentence_no,
        "source": "manual" if strategy_key == "manual" else "rule",
        "steps": [
            "按中文标点分句并记录字符偏移",
            f"识别头实体「{rel.get('head', '')}」（{_type_label(head_type)}）与尾实体「{rel.get('tail', '')}」（{_type_label(tail_type)}）",
            f"{label}：{how}",
            f"类型约束 {type_constraint} 通过，去重后保留置信度最高的一条",
        ],
    }


def attach(result: dict[str, Any]) -> dict[str, Any]:
    """给结果里的每条关系补 explanation，并返回同一个 result（原地）。"""
    for rel in result.get("relations") or []:
        if isinstance(rel, dict):
            rel["explanation"] = explain(rel)
    return result
