# -*- coding: utf-8 -*-
"""语言自动判别：确定性规则，按 CJK 字符占比决定走哪套抽取引擎。

设计取舍：
- 不引入 langdetect / fasttext 等概率模型。这里只需要区分「中文新闻」和
  「英文新闻」两种输入，字符占比足够，且完全可复现、零依赖、可解释。
- 阈值 0.15：中文文本里夹几个英文缩写（CEO、AI、Inc.）很常见，用低阈值
  避免把中文新闻误判成英文；纯英文文本 CJK 为 0，不会被误判。
- 空文本 / 无可判定字符时回退中文（项目默认语言）。
"""

from __future__ import annotations

CJK_THRESHOLD = 0.15


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x3400 <= cp <= 0x4DBF      # CJK 扩展 A
        or 0x4E00 <= cp <= 0x9FFF   # CJK 基本区
        or 0xF900 <= cp <= 0xFAFF   # CJK 兼容表意文字
        or 0x20000 <= cp <= 0x2FFFF  # CJK 扩展 B-F
    )


def _is_latin_letter(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def detect_language(text: str) -> dict:
    """返回语言判别结果。

    {
      "language": "zh" | "en",       # 实际选用的引擎
      "method": "auto" | "default",  # auto=按占比判定；default=空文本回退
      "cjk_chars": int,
      "latin_chars": int,
      "cjk_ratio": float,            # CJK / (CJK + 拉丁字母)，保留 4 位
      "threshold": float,
    }
    """
    text = text or ""
    cjk = sum(1 for ch in text if _is_cjk(ch))
    latin = sum(1 for ch in text if _is_latin_letter(ch))
    total = cjk + latin
    if total == 0:
        return {
            "language": "zh",
            "method": "default",
            "cjk_chars": 0,
            "latin_chars": 0,
            "cjk_ratio": 0.0,
            "threshold": CJK_THRESHOLD,
        }
    ratio = cjk / total
    return {
        "language": "zh" if ratio >= CJK_THRESHOLD else "en",
        "method": "auto",
        "cjk_chars": cjk,
        "latin_chars": latin,
        "cjk_ratio": round(ratio, 4),
        "threshold": CJK_THRESHOLD,
    }


def resolve_language(language: str | None, text: str) -> tuple[str, dict | None]:
    """把请求里的 language 解析成实际引擎代码。

    返回 (lang, detection_info)：
    - language 为 zh / en（或 english）时直接返回，detection_info=None（手动指定）；
    - language 为 auto / 空时调用判别，detection_info 带回可解释的占比细节。
    """
    lang = (language or "auto").strip().lower()
    if lang in ("zh", "zh-cn", "chinese"):
        return "zh", None
    if lang in ("en", "english"):
        return "en", None
    detection = detect_language(text)
    return detection["language"], detection
