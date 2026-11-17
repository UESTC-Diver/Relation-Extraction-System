# -*- coding: utf-8 -*-
"""关键抽取机制的点状回归。

总体 F1 由 eval/gold.json 负责；这里固定几条最容易在重构中被悄悄改坏的
具体句式，避免“总指标没掉、但某个机制已经失效”。
"""

from __future__ import annotations

from app.nlp.pipeline import analyze


def _triples(text: str) -> set[tuple[str, str, str]]:
    return {
        (r["head"], r["relation"], r["tail"])
        for r in analyze(text)["relations"]
    }


def test_subject_chain_inherits_previous_clause_subject():
    triples = _triples("腾讯控股已投资搜狗多年，并与搜狐签署了相关协议。")
    assert ("腾讯控股", "sign", "搜狐") in triples
    assert ("搜狗", "sign", "搜狐") not in triples


def test_both_parties_resolve_across_sentences():
    triples = _triples(
        "特斯拉宣布在上海投资建设第二座超级工厂。"
        "宁德时代将为该工厂供应磷酸铁锂电池，双方已签订长期供货协议。"
    )
    assert ("宁德时代", "sign", "特斯拉") in triples


def test_latter_party_supply_direction():
    triples = _triples("华为与京东方签署供货协议，后者将为新机供应OLED屏幕。")
    assert ("华为", "sign", "京东方") in triples
    assert ("京东方", "supply", "华为") in triples
