# -*- coding: utf-8 -*-
"""领域包：给固定 19 类关系叠加领域词典与领域说法。

设计边界
--------
* 领域包**不改** RELATION_RULES / SPECIAL_PATTERNS / 词典本体，只以「额外
  custom_terms + 额外 custom_triggers」的形式在调用 analyze() 前合并。
* `general` 的两个附加集合都是空的，因此默认路径与 1.4.0 逐字节等价：
  67 条测试、F1 0.980、金标准集都不受影响。
* 领域说法只能给**已存在的**关系 key 追加触发词，不能凭空新增关系类型，
  保持 schema 与配色稳定。
"""

from __future__ import annotations

from typing import Any

# key -> {label, description, terms, triggers}
DOMAIN_PROFILES: dict[str, dict[str, Any]] = {
    "general": {
        "label": "通用新闻",
        "description": "系统默认配置，覆盖企业收购、投资、任职、地点与合作等常见新闻表述。",
        "terms": [],
        "triggers": {},
    },
    "finance": {
        "label": "财经市场",
        "description": "追加一级市场与二级市场常见说法：举牌、战投、吃下、对赌、独家保荐等。",
        "terms": [
            {"text": "科创板", "type": "PRODUCT"},
            {"text": "创业板", "type": "PRODUCT"},
            {"text": "北交所", "type": "ORG"},
            {"text": "上交所", "type": "ORG"},
            {"text": "深交所", "type": "ORG"},
            {"text": "高瓴资本", "type": "ORG"},
            {"text": "中金公司", "type": "ORG"},
            {"text": "可转债", "type": "PRODUCT"},
        ],
        "triggers": {
            "acquire": ["吃下", "拿下控股权", "协议受让"],
            "invest": ["战投", "举牌", "加仓", "战略入股"],
            "control": ["实际控制人", "表决权委托"],
            "sign": ["对赌", "签署框架协议"],
            "cooperate": ["联合承销", "共同设立"],
            "supply": ["独家保荐", "独家承销"],
            "launch": ["挂牌", "过会", "递表"],
        },
    },
    "legal": {
        "label": "法律文书",
        "description": "追加裁判与争议解决表述：立案、仲裁、判决、执行、管辖权异议等。",
        "terms": [
            {"text": "人民法院", "type": "ORG"},
            {"text": "仲裁委员会", "type": "ORG"},
            {"text": "检察机关", "type": "ORG"},
            {"text": "判决书", "type": "PRODUCT"},
        ],
        "triggers": {
            "sue": ["立案", "仲裁", "提起公诉", "管辖权异议", "申请执行"],
            "sign": ["达成和解", "签署调解协议"],
            "control": ["代持", "股权质押"],
            "belong": ["归口管理", "受辖于"],
        },
    },
}

DEFAULT_PROFILE = "general"


def catalog() -> list[dict[str, Any]]:
    """给前端与 /api/profiles 用的目录，不含具体词条明细。"""
    return [
        {
            "key": key,
            "label": item["label"],
            "description": item["description"],
            "term_count": len(item["terms"]),
            "trigger_count": sum(len(v) for v in item["triggers"].values()),
            "relations": sorted(item["triggers"].keys()),
        }
        for key, item in DOMAIN_PROFILES.items()
    ]


def get(key: str | None) -> dict[str, Any]:
    """未知 key 回落到 general，避免前端传脏数据导致 500。"""
    return DOMAIN_PROFILES.get((key or "").strip() or DEFAULT_PROFILE, DOMAIN_PROFILES[DEFAULT_PROFILE])


def valid_keys() -> list[str]:
    return list(DOMAIN_PROFILES.keys())


def merge(
    custom_terms: list[dict] | None,
    custom_triggers: dict[str, list[str]] | None,
    profile_key: str | None = None,
) -> tuple[list[dict], dict[str, list[str]]]:
    """把领域包叠加到用户自定义配置上，返回新的列表与字典（不修改入参）。

    顺序：领域包在前、用户配置在后；重复词条按 text 去重（用户优先），
    重复触发词按 (relation_key, trigger) 去重，避免索引里出现同义重复。
    """
    profile = get(profile_key)
    terms: list[dict] = [dict(t) for t in profile["terms"]]
    seen_terms = {str(t.get("text", "")).strip() for t in terms}
    for term in custom_terms or []:
        if not isinstance(term, dict):
            continue
        name = str(term.get("text", "")).strip()
        if not name or name in seen_terms:
            continue
        seen_terms.add(name)
        terms.append(dict(term))

    triggers: dict[str, list[str]] = {
        key: list(values) for key, values in profile["triggers"].items()
    }
    for key, values in (custom_triggers or {}).items():
        bucket = triggers.setdefault(key, [])
        for value in values or []:
            word = str(value).strip()
            if word and word not in bucket:
                bucket.append(word)
    return terms, triggers
