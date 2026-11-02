# -*- coding: utf-8 -*-
"""开发期自检脚本：对内置示例跑一遍流水线，把结果写入 JSON 便于人工核对。

用法（在 backend 目录下）：
    python devtools/check.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.nlp.pipeline import analyze  # noqa: E402
from app.samples import SAMPLES  # noqa: E402


def main() -> None:
    out = []
    for sample in SAMPLES:
        result = analyze(sample["content"])
        out.append(
            {
                "sample": sample["id"],
                "stats": result["stats"],
                "entities": [
                    (e["text"], e["type"], e["source"] if "source" in e else "")
                    for e in result["entities"]
                ],
                "relations": [
                    (r["head"], r["relation_label"], r["tail"], r["confidence"], r["trigger"])
                    for r in result["relations"]
                ],
            }
        )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check_output.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"written: {path}")


if __name__ == "__main__":
    main()
