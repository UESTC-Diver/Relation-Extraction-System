# -*- coding: utf-8 -*-
"""关系抽取评测脚本。

在 eval/gold.json 的人工标注集上运行完整流水线，输出整体与分类型的
Precision / Recall / F1，以及漏抽、误抽明细。

    cd backend && python eval/run_eval.py
    cd backend && python eval/run_eval.py --json

匹配规则
--------
头尾实体先做机构名归一（"腾讯控股" 与 "腾讯" 视为同一实体），关系 key
必须完全一致，因此评测的是"关系判断"能力，不因后缀写法差异扣分。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.nlp.entity import canonical_name  # noqa: E402
from app.nlp.lexicon import RELATION_MAP  # noqa: E402
from app.nlp.pipeline import analyze  # noqa: E402

GOLD_PATH = Path(__file__).resolve().parent / "gold.json"


def normalize(name: str) -> str:
    """统一按机构规则归一，保证金标与预测走同一条路径。"""
    return canonical_name(name or "", "ORG")


def same_entity(a: str, b: str) -> bool:
    """实体等价判断：完全相同，或一方是另一方的前缀。

    系统识别出的实体粒度常与人工标注不同（"华为" vs "华为技术有限公司"），
    这类差异属于实体识别范畴，不应计入关系抽取的错误。要求较短一方
    至少 2 个字，避免 "中" 这类单字造成误配。
    """
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 2 and long_.startswith(short)


def align(gold: set, pred: set) -> tuple[set, set, set, set]:
    """按关系 key + 实体等价做一对一匹配，返回 (命中金标, 命中预测, 漏抽, 误抽)。"""
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


def disp_width(text: str) -> int:
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - disp_width(text))


def run() -> dict:
    data = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]

    total_tp = total_fp = total_fn = 0
    per_case = []
    per_rel = defaultdict(lambda: {"gold": 0, "pred": 0, "tp": 0})
    misses: list[dict] = []
    spurious: list[dict] = []

    for case in cases:
        gold = {(normalize(h), rel, normalize(t)) for h, rel, t in case["relations"]}
        result = analyze(case["text"])
        pred = {
            (normalize(r["head"]), r["relation"], normalize(r["tail"]))
            for r in result["relations"]
        }

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

        for h, rel, t in sorted(fn):
            misses.append({"case": case["id"], "head": h, "relation": rel,
                           "relation_label": label_of(rel), "tail": t})
        for h, rel, t in sorted(fp):
            spurious.append({"case": case["id"], "head": h, "relation": rel,
                             "relation_label": label_of(rel), "tail": t})

        per_case.append({
            "id": case["id"],
            "title": case["title"],
            "gold": len(gold),
            "pred": len(pred),
            "tp": len(tp),
            "fp": len(fp),
            "fn": len(fn),
        })

    def prf(tp: int, pred: int, gold: int) -> tuple[float, float, float]:
        p = tp / pred if pred else 0.0
        r = tp / gold if gold else 0.0
        f = 2 * p * r / (p + r) if (p + r) else 0.0
        return p, r, f

    precision, recall, f1 = prf(total_tp, total_tp + total_fp, total_tp + total_fn)

    rel_rows = []
    macro = []
    for rel, stat in per_rel.items():
        p, r, f = prf(stat["tp"], stat["pred"], stat["gold"])
        rel_rows.append({
            "relation": rel,
            "label": label_of(rel),
            "gold": stat["gold"],
            "pred": stat["pred"],
            "tp": stat["tp"],
            "precision": round(p, 3),
            "recall": round(r, 3),
            "f1": round(f, 3),
        })
        if stat["gold"] > 0:
            macro.append(f)
    rel_rows.sort(key=lambda row: (-row["gold"], row["relation"]))
    macro_f1 = sum(macro) / len(macro) if macro else 0.0

    return {
        "cases": len(cases),
        "gold_total": total_tp + total_fn,
        "pred_total": total_tp + total_fp,
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "macro_f1": round(macro_f1, 3),
        "per_case": per_case,
        "per_relation": rel_rows,
        "misses": misses,
        "spurious": spurious,
    }


def print_report(report: dict, show_errors: int) -> None:
    print()
    print("关系抽取评测 · 金标准集")
    print("=" * 78)
    print(
        pad("用例", 26) + pad("金标", 6) + pad("预测", 6) + pad("命中", 6)
        + pad("误抽", 6) + "漏抽"
    )
    print("-" * 78)
    for row in report["per_case"]:
        print(
            pad(f"{row['id']} {row['title']}", 26)
            + pad(str(row["gold"]), 6)
            + pad(str(row["pred"]), 6)
            + pad(str(row["tp"]), 6)
            + pad(str(row["fp"]), 6)
            + str(row["fn"])
        )
    print("-" * 78)
    print(
        pad("合计", 26)
        + pad(str(report["gold_total"]), 6)
        + pad(str(report["pred_total"]), 6)
        + pad(str(report["tp"]), 6)
        + pad(str(report["fp"]), 6)
        + str(report["fn"])
    )

    print()
    print("整体指标")
    print(f"  Precision  {report['precision']:.3f}")
    print(f"  Recall     {report['recall']:.3f}")
    print(f"  F1         {report['f1']:.3f}    （Macro-F1 {report['macro_f1']:.3f}）")

    print()
    print("分关系类型")
    print("-" * 78)
    print(pad("关系", 10) + pad("金标", 6) + pad("预测", 6) + pad("命中", 6) + pad("P", 8) + pad("R", 8) + "F1")
    print("-" * 78)
    for row in report["per_relation"]:
        print(
            pad(f"{row['label']}({row['relation']})", 18)
            + pad(str(row["gold"]), 6)
            + pad(str(row["pred"]), 6)
            + pad(str(row["tp"]), 6)
            + pad(f"{row['precision']:.2f}", 8)
            + pad(f"{row['recall']:.2f}", 8)
            + f"{row['f1']:.2f}"
        )

    def show(title: str, items: list[dict]) -> None:
        print()
        print(f"{title}（共 {len(items)} 条）")
        print("-" * 78)
        for item in items[:show_errors]:
            print(
                f"  {item['case']}  {item['head']} —[{item['relation_label']}]→ {item['tail']}"
            )
        if len(items) > show_errors:
            print(f"  … 另有 {len(items) - show_errors} 条未显示")

    show("漏抽（金标有、系统未抽出）", report["misses"])
    show("误抽（系统抽出、金标无）", report["spurious"])
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="在人工金标准集上评测关系抽取效果")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而不是表格")
    parser.add_argument("--show-errors", type=int, default=10, help="每类错误最多展示几条")
    args = parser.parse_args()

    report = run()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report, args.show_errors)


if __name__ == "__main__":
    main()
