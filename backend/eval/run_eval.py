# -*- coding: utf-8 -*-
"""关系抽取评测命令行入口。

    cd backend && python eval/run_eval.py
    cd backend && python eval/run_eval.py --json

指标算法统一在 app/nlp/evaluation.py 实现，界面化评测台调用同一份
evaluate()，避免命令行与界面出现两套会各自漂移的 P/R/F1。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.nlp.evaluation import evaluate, load_gold  # noqa: E402


def disp_width(text: str) -> int:
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - disp_width(text))


def run() -> dict:
    return evaluate(load_gold())


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
            pad(f"{row['id']} {row['title']}", 26) + pad(str(row["gold"]), 6)
            + pad(str(row["pred"]), 6) + pad(str(row["tp"]), 6)
            + pad(str(row["fp"]), 6) + str(row["fn"])
        )
    print("-" * 78)
    print(
        pad("合计", 26) + pad(str(report["gold_total"]), 6)
        + pad(str(report["pred_total"]), 6) + pad(str(report["tp"]), 6)
        + pad(str(report["fp"]), 6) + str(report["fn"])
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
            + pad(str(row["gold"]), 6) + pad(str(row["pred"]), 6)
            + pad(str(row["tp"]), 6) + pad(f"{row['precision']:.2f}", 8)
            + pad(f"{row['recall']:.2f}", 8) + f"{row['f1']:.2f}"
        )

    def show(title: str, items: list[dict]) -> None:
        print()
        print(f"{title}（共 {len(items)} 条）")
        print("-" * 78)
        for item in items[:show_errors]:
            print(f"  {item['case']}  {item['head']} —[{item['relation_label']}]→ {item['tail']}")
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
