# -*- coding: utf-8 -*-
"""P/R/F1 评测核心：命令行脚本与界面化评测台共用同一份实现。

匹配规则：头尾实体先做机构名归一，关系 key 必须完全一致，
因此评测的是「关系判断」能力，不因后缀写法差异扣分。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Callable

from .entity import canonical_name
from .lexicon import RELATION_MAP
from .pipeline import analyze

GOLD_PATH = Path(__file__).resolve().parent.parent.parent / "eval" / "gold.json"


def load_gold(path: Path | None = None) -> list[dict]:
    data = json.loads((path or GOLD_PATH).read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    if not isinstance(cases, list) or not cases:
        raise ValueError("金标准集为空或格式不正确")
    return cases


def normalize(name: str) -> str:
    return canonical_name(name or "", "ORG")


def same_entity(a: str, b: str) -> bool:
    """短的一方至少 2 字，避免「中」这类单字造成误配。"""
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 2 and long_.startswith(short)


def align(gold: set, pred: set) -> tuple[set, set, set, set]:
    hit_gold: set = set()
    hit_pred: set = set()
    for g in sorted(gold):
        for p in sorted(pred):
            if p in hit_pred:
                continue
            if g[1] == p[1] and same_entity(g[0], p[0]) and same_entity(g[2], p[2]):
                hit_gold.add(g)
                hit_pred.add(p)
                break
    return hit_gold, hit_pred, gold - hit_gold, pred - hit_pred


def label_of(key: str) -> str:
    rule = RELATION_MAP.get(key)
    return rule.label if rule else key


def _triple(row: dict) -> tuple[str, str, str]:
    return (
        normalize(str(row.get("head", ""))),
        str(row.get("relation", "")),
        normalize(str(row.get("tail", ""))),
    )


def evaluate(
    cases: list[dict],
    analyzer: Callable[[str], dict] | None = None,
    pred_scope: dict[str, set] | None = None,
) -> dict:
    """对一组金标准用例跑流水线，返回整体 / 分类型指标与漏抽误抽明细。

    pred_scope 用来算「已标注范围内」的口径：给出每个用例里人类已经判过的
    三元组集合，只有落在集合里的预测才计入 FP。标注没做完时，严格口径会把
    「没判过的」一律当误抽，P 会被系统性低估；两种口径一起给，才不至于
    用单一数字骗自己。
    """
    run_analyze = analyzer or analyze
    total_tp = total_fp = total_fn = 0
    per_case: list[dict] = []
    per_rel: dict[str, dict] = defaultdict(lambda: {"gold": 0, "pred": 0, "tp": 0})
    misses: list[dict] = []
    spurious: list[dict] = []
    skipped = 0

    for index, case in enumerate(cases):
        case_id = case.get("id") or f"case-{index + 1}"
        text = str(case.get("text") or "")
        gold = {
            _triple({"head": h, "relation": rel, "tail": t})
            for h, rel, t in (case.get("relations") or [])
        }
        predicted = run_analyze(text)["relations"] if text.strip() else []
        pred = {_triple(r) for r in predicted}
        if pred_scope is not None:
            scope = pred_scope.get(case_id)
            if scope is not None:
                kept = {p for p in pred if p in scope}
                skipped += len(pred) - len(kept)
                pred = kept

        tp, _, fn, fp = align(gold, pred)
        total_tp += len(tp)
        total_fp += len(fp)
        total_fn += len(fn)

        for _, rel, _ in gold:
            per_rel[rel]["gold"] += 1
        for _, rel, _ in pred:
            per_rel[rel]["pred"] += 1
        for _, rel, _ in tp:
            per_rel[rel]["tp"] += 1

        evidence = {
            _triple(r): r.get("evidence", "") for r in predicted
        }
        for h, rel, t in sorted(fn):
            misses.append({
                "case": case_id, "head": h, "relation": rel,
                "relation_label": label_of(rel), "tail": t,
                "text": text[:200],
            })
        for h, rel, t in sorted(fp):
            spurious.append({
                "case": case_id, "head": h, "relation": rel,
                "relation_label": label_of(rel), "tail": t,
                "evidence": evidence.get((h, rel, t), ""),
            })

        per_case.append({
            "id": case_id, "title": case.get("title", ""),
            "gold": len(gold), "pred": len(pred), "tp": len(tp),
            "fp": len(fp), "fn": len(fn),
        })

    def prf(tp: int, pred: int, gold: int) -> tuple[float, float, float]:
        p = tp / pred if pred else 0.0
        r = tp / gold if gold else 0.0
        f = 2 * p * r / (p + r) if (p + r) else 0.0
        return p, r, f

    precision, recall, f1 = prf(total_tp, total_tp + total_fp, total_tp + total_fn)
    rel_rows, macro = [], []
    for rel, stat in per_rel.items():
        p, r, f = prf(stat["tp"], stat["pred"], stat["gold"])
        rel_rows.append({
            "relation": rel, "label": label_of(rel),
            "gold": stat["gold"], "pred": stat["pred"], "tp": stat["tp"],
            "precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3),
        })
        if stat["gold"] > 0:
            macro.append(f)
    rel_rows.sort(key=lambda row: (-row["gold"], row["relation"]))

    return {
        "cases": len(cases),
        "scoped": pred_scope is not None,
        "skipped_unjudged": skipped,
        "gold_total": total_tp + total_fn,
        "pred_total": total_tp + total_fp,
        "tp": total_tp, "fp": total_fp, "fn": total_fn,
        "precision": round(precision, 3), "recall": round(recall, 3),
        "f1": round(f1, 3),
        "macro_f1": round(sum(macro) / len(macro), 3) if macro else 0.0,
        "per_case": per_case, "per_relation": rel_rows,
        "misses": misses, "spurious": spurious,
    }
