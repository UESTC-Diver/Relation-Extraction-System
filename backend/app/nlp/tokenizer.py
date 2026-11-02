# -*- coding: utf-8 -*-
"""中文分句与分词基础能力。

* ``split_sentences`` —— 按中文标点切分句子，保留偏移量，供前端高亮定位
* ``tokenize`` —— 基于 jieba 的词性标注，叠加领域自定义词典
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import jieba
import jieba.posseg as pseg

from .lexicon import (
    LOC_GAZETTEER,
    ORG_GAZETTEER,
    PERSON_GAZETTEER,
    PRODUCT_GAZETTEER,
)

_DICT_LOADED = False

# 句子结束符（保留在句子内部）
_SENT_END = "。！？!?；;\n"
# 过短的句子片段（如引号残留）合并到上一句
_MIN_SENT_LEN = 6


@dataclass
class Sentence:
    index: int
    start: int
    end: int
    text: str


@dataclass
class Token:
    text: str
    flag: str
    start: int
    end: int


def _load_dict() -> None:
    global _DICT_LOADED
    if _DICT_LOADED:
        return
    jieba.initialize()
    # 把领域词条写入 jieba，保证分词边界与词典一致
    for word in ORG_GAZETTEER:
        jieba.add_word(word, freq=20000, tag="nt")
    for word in PERSON_GAZETTEER:
        jieba.add_word(word, freq=20000, tag="nr")
    for word in LOC_GAZETTEER:
        jieba.add_word(word, freq=20000, tag="ns")
    for word in PRODUCT_GAZETTEER:
        jieba.add_word(word, freq=12000, tag="nz")
    _DICT_LOADED = True


def warmup() -> None:
    """预加载词典，避免首个请求超时。"""
    _load_dict()


def split_sentences(text: str) -> list[Sentence]:
    """按标点切句，返回带原文偏移的句子列表。"""
    sentences: list[Sentence] = []
    buf_start = 0
    buf: list[str] = []
    for i, ch in enumerate(text):
        buf.append(ch)
        if ch in _SENT_END:
            piece = "".join(buf)
            if piece.strip():
                sentences.append(Sentence(len(sentences), buf_start, i + 1, piece))
            buf = []
            buf_start = i + 1
    tail = "".join(buf)
    if tail.strip():
        sentences.append(Sentence(len(sentences), buf_start, len(text), tail))

    # 合并过短片段，避免 "。" 前只有标点导致的碎片
    merged: list[Sentence] = []
    for s in sentences:
        if merged and len(s.text.strip(" \t\r\n")) < _MIN_SENT_LEN:
            prev = merged[-1]
            merged[-1] = Sentence(prev.index, prev.start, s.end, text[prev.start:s.end])
        else:
            merged.append(s)
    for i, s in enumerate(merged):
        merged[i] = Sentence(i, s.start, s.end, text[s.start:s.end])
    return merged


def tokenize(text: str) -> list[Token]:
    """jieba 词性标注，返回带偏移的词序列。"""
    _load_dict()
    tokens: list[Token] = []
    cursor = 0
    for word, flag in pseg.cut(text):
        start = text.find(word, cursor)
        if start < 0:  # 理论上不会发生
            start = cursor
        end = start + len(word)
        tokens.append(Token(word, flag, start, end))
        cursor = end
    return tokens


def normalize_space(text: str) -> str:
    return re.sub(r"[ \t\u3000]+", " ", text).strip()
