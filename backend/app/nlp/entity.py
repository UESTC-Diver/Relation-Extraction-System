# -*- coding: utf-8 -*-
"""实体识别：词典 + 词法规则 + 词性标注的多路融合。

识别流程
--------
1. 词典匹配：人名 / 机构 / 地名 / 产品词表，最长优先
2. 词法规则：以 jieba 的分词边界为单位，识别 "XX公司""XX市" 这类
   带后缀的机构名与地名，并向前扩展专名部分（避免把动词吞进实体）
3. 上下文规则：识别 "CEO 张三""张三表示" 这类人名结构
4. 词性兜底：jieba 的 nr / ns / nt 标签
5. 融合消歧：最长优先 + 置信度优先的贪心去重，保证实体互不交叉
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .lexicon import (
    COMPOUND_SURNAMES,
    LOC_GAZETTEER,
    ORG_GAZETTEER,
    PERSON_GAZETTEER,
    PERSON_SURNAMES,
    PRODUCT_GAZETTEER,
    ROLE_WORDS,
)
from .tokenizer import Sentence, Token, tokenize

_TYPE_SCORE = {
    "gazetteer": 100,
    "suffix": 76,
    "context": 72,
    "pos": 55,
}

STOPWORDS = {
    "公司", "集团", "企业", "机构", "部门", "政府", "市场", "行业", "领域",
    "技术", "产品", "服务", "业务", "项目", "计划", "报告", "消息", "新闻",
    "记者", "用户", "客户", "员工", "股东", "投资者", "消费者", "分析人士",
    "分析师", "专家", "人士", "方面", "问题", "情况", "数据", "平台", "系统",
    "战略", "合作", "协议", "会议", "发布会", "研究院", "委员会", "大学",
    "银行", "中心", "基地", "园区", "机场", "车站", "今日", "昨日", "近日",
    "地区", "城区", "社区", "小区", "市区", "郊区", "景区", "辖区", "灾区",
    "园区", "新区", "片区", "山区", "产区", "矿区", "厂区", "城区",
}

# 泛称机构：出现在 "XX的子公司" 等结构里，不是具体实体
GENERIC_ORG = {
    "全资子公司", "控股子公司", "子公司", "母公司", "分公司", "合资公司",
    "全资子公司", "上市公司", "国有企业", "国有控股", "民营企业", "外资企业",
    "互联网公司", "初创公司", "科技公司", "该子公司", "该集团", "该公司",
    "合作伙伴", "供应商", "竞争对手", "董事局", "董事会", "管理层", "高管层",
    # 指代词组合：交给关系抽取层的指代消解处理，不作为实体
    "该工厂", "该基地", "该园区", "该品牌", "该项目", "该平台", "该中心",
    "本工厂", "本公司", "本集团", "此工厂", "此公司",
    "生物医药企业", "高科技企业", "创新型企业", "初创企业",
}

EN_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "with", "by",
    "ceo", "cto", "cfo", "coo", "ai", "it", "app", "id", "ip", "ok", "vs",
    "us", "uk", "eu", "gdp", "cpi", "ipo", "http", "https", "www", "com",
    "and", "the",
}

# 机构 / 地点后缀（按长度倒序判断，保证 "股份有限公司" 优先于 "公司"）
ORG_SUFFIX_WORDS = [
    "股份有限公司", "有限责任公司", "有限公司", "集团公司", "集团", "控股",
    "公司", "银行", "证券", "保险", "基金", "信托", "大学", "学院", "研究院",
    "研究所", "科学院", "医院", "管理局", "监督局", "委员会", "协会", "学会",
    "联合会", "基金会", "事务所", "实验室", "电视台", "广播电台", "日报",
    "晚报", "商报", "时报", "通讯社", "出版社", "交易所",
]

LOC_SUFFIX_WORDS = ["特别行政区", "自治区", "自治州", "省", "市", "县", "镇", "州", "区"]

# 允许向前扩展的词性：名词类 + 动名词（"建设银行""投资集团"）
_NAME_FLAGS = {"n", "nr", "ns", "nt", "nz", "nrt", "nrfg", "j", "vn", "an", "eng"}

_SURNAME_ALT = "|".join(
    sorted(PERSON_SURNAMES | set(COMPOUND_SURNAMES), key=len, reverse=True)
)
_ROLE_ALT = "|".join(sorted(ROLE_WORDS, key=len, reverse=True))

# 人名之后的常见边界（人名必须紧接这些词或标点）
_PERSON_STOP = (
    "表示|称|指出|认为|透露|介绍|强调|坦言|宣布|回应|说|撰文|发文|同时|也|还|"
    "将|已|曾|即|现|于|在|对|向|与|和|及|的|是|担任|出任|就任|加盟|毕业|出生|"
    "先生|女士|总裁|董事长|总经理|教授|博士|记者|创始人"
)
_PERSON_TAIL = rf"(?=[，。、；：！？\s,.;:!?]|$|{_PERSON_STOP})"
# 人名之前必须出现的左边界：句首 / 标点 / 职衔，避免把普通词当人名
_PERSON_SAY = "表示|称|指出|认为|透露|介绍|强调|坦言|宣布|回应|说|撰文|发文|回忆|预测|预计|接受"
_PERSON_HEAD = rf"(?:^|[，。；：、！？\s“”\"']|{_ROLE_ALT})"

PERSON_CTX_RE = re.compile(
    rf"{_PERSON_HEAD}((?:{_SURNAME_ALT})[\u4e00-\u9fa5]{{1,2}}?)(?={_PERSON_SAY})"
)
PERSON_ROLE_RE = re.compile(
    rf"(?:{_ROLE_ALT})(?:兼[\u4e00-\u9fa5]{{2,6}})?((?:{_SURNAME_ALT})[\u4e00-\u9fa5]{{1,2}}?){_PERSON_TAIL}"
)
PERSON_AFTER_BY = re.compile(
    rf"(?:由|被|与|和|同)((?:{_SURNAME_ALT})[\u4e00-\u9fa5]{{1,2}}?){_PERSON_TAIL}"
)

TIME_RE = re.compile(
    r"\d{4}年(?:\d{1,2}月(?:\d{1,2}日)?)?"
    r"|\d{1,2}月\d{1,2}日"
    r"|\d{4}-\d{2}-\d{2}"
    r"|(?:今年|去年|明年|前年|近日|日前|昨日|今日|本周|上周|本月|上月|年底|年初)"
)
MONEY_RE = re.compile(
    r"\d+(?:\.\d+)?(?:亿美元|万美元|亿欧元|亿元|万元|亿|万|美元|元|欧元)"
    r"(?!名|人|台|辆|家|个|吨|平|次|户|条|件)"
)
EN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[\-\.][A-Za-z0-9]+)*")

_ALL_WORDS = sorted(
    set(ORG_GAZETTEER) | set(LOC_GAZETTEER) | set(PERSON_GAZETTEER) | set(PRODUCT_GAZETTEER),
    key=len,
    reverse=True,
)
_DICT_RE = re.compile("|".join(_ALL_WORDS))
_ORG_SET = set(ORG_GAZETTEER)
_LOC_SET = set(LOC_GAZETTEER)
_PERSON_SET = set(PERSON_GAZETTEER)
_PRODUCT_SET = set(PRODUCT_GAZETTEER)


@dataclass
class Entity:
    start: int
    end: int
    text: str
    type: str
    score: float
    source: str
    sentence_index: int = -1
    id: str = ""
    # 指代消解元信息：ref_kind 取 "group" / "pair" / "single" / "event"，
    # ref_members 记录 "双方/后者" 指向的实体对，ref_other 记录另一方。
    # 普通实体这三个字段保持默认值，不影响现有逻辑。
    ref_kind: str = ""
    ref_members: tuple["Entity", ...] = ()
    ref_other: "Entity | None" = None

    def as_dict(self) -> dict:
        from .lexicon import ENTITY_TYPES

        return {
            "id": self.id,
            "text": self.text,
            "canonical": canonical_name(self.text, self.type),
            "type": self.type,
            "type_label": ENTITY_TYPES[self.type]["label"],
            "color": ENTITY_TYPES[self.type]["color"],
            "start": self.start,
            "end": self.end,
            "sentence_index": self.sentence_index,
            "source": self.source,
            "confidence": round(min(0.99, self.score / 100), 2),
        }


_CANONICAL_SUFFIXES = (
    "股份有限公司", "有限责任公司", "有限公司", "集团公司", "集团", "控股", "公司",
)


def canonical_name(text: str, etype: str) -> str:
    """机构名归一化：反复剥离 "有限公司 / 集团 / 控股" 等后缀。

    采用循环剥离而非只剥一层，是为了让 "腾讯控股有限公司" 与 "腾讯公司"
    落到同一个规范名 "腾讯" 上，避免同一实体在统计与图谱中分裂成多个节点。
    每次剥离后至少保留 2 个字，防止把 "公司" 之类的泛称剥成空串。
    """
    if etype != "ORG":
        return text
    result = text
    while True:
        for suffix in _CANONICAL_SUFFIXES:
            if result.endswith(suffix) and len(result) - len(suffix) >= 2:
                result = result[: -len(suffix)]
                break
        else:
            return result


def _dict_type(word: str) -> str:
    if word in _ORG_SET:
        return "ORG"
    if word in _PERSON_SET:
        return "PERSON"
    if word in _LOC_SET:
        return "LOC"
    if word in _PRODUCT_SET:
        return "PRODUCT"
    return "ORG"


class EntityRecognizer:
    """中文实体识别器（无外部模型依赖，纯词典 + 规则）。"""

    def recognize(self, text: str, sentences: list[Sentence]) -> list[Entity]:
        tokens = tokenize(text)
        candidates: list[Entity] = []
        candidates.extend(self._dict_entities(text))
        candidates.extend(self._suffix_entities(tokens))
        candidates.extend(self._context_entities(text))
        candidates.extend(self._pattern_entities(text))
        candidates.extend(self._pos_entities(tokens))

        accepted = self._resolve_overlaps(candidates)
        accepted.sort(key=lambda e: e.start)
        self._assign_sentence(accepted, sentences)
        return accepted

    # ------------------------------------------------------------------ #
    # 各路子识别
    # ------------------------------------------------------------------ #
    def _dict_entities(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        for m in _DICT_RE.finditer(text):
            word = m.group(0)
            if word in STOPWORDS or len(word) < 2:
                continue
            out.append(
                Entity(m.start(), m.end(), word, _dict_type(word),
                       _TYPE_SCORE["gazetteer"], "gazetteer")
            )
        return out

    def _suffix_entities(self, tokens: list[Token]) -> list[Entity]:
        out: list[Entity] = []
        for i, tok in enumerate(tokens):
            built = self._build_named(tokens, i, ORG_SUFFIX_WORDS, max_len=16, forbid_loc_prefix=True)
            if built:
                start, end, text = built
                if (
                    len(text) >= 4
                    and text not in STOPWORDS
                    and text not in GENERIC_ORG
                    and not self._is_person(text)
                ):
                    out.append(Entity(start, end, text, "ORG",
                                      _TYPE_SCORE["suffix"], "suffix"))
                continue
            built = self._build_named(tokens, i, LOC_SUFFIX_WORDS, max_len=10)
            if built:
                start, end, text = built
                if len(text) >= 3 and text not in STOPWORDS and not self._is_person(text):
                    out.append(Entity(start, end, text, "LOC",
                                      _TYPE_SCORE["suffix"] - 6, "suffix"))
        return out

    def _build_named(
        self, tokens: list[Token], i: int, suffixes: list[str], max_len: int,
        forbid_loc_prefix: bool = False,
    ) -> tuple[int, int, str] | None:
        tok = tokens[i]
        word = tok.text
        if len(word) < 2 or not word.endswith(tuple(suffixes)):
            return None
        if word in STOPWORDS or tok.flag in ("v", "p", "c", "d", "u", "r", "y", "m", "q"):
            return None
        start, text = tok.start, word
        j = i - 1
        while j >= 0 and len(text) < max_len:
            prev = tokens[j]
            if prev.flag not in _NAME_FLAGS:
                break
            if forbid_loc_prefix and prev.text in _LOC_SET:
                # 机构名不从地名上扩展（"德国" + "默克集团" ≠ "德国默克集团"）
                break
            if tokens[j + 1].start != prev.end:
                break
            merged = prev.text + text
            if len(merged) > max_len or prev.text in STOPWORDS:
                break
            text, start = merged, prev.start
            j -= 1
        return start, tok.end, text

    def _context_entities(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        for regex, score in (
            (PERSON_ROLE_RE, _TYPE_SCORE["context"]),
            (PERSON_CTX_RE, _TYPE_SCORE["context"] - 2),
            (PERSON_AFTER_BY, _TYPE_SCORE["context"] - 4),
        ):
            for m in regex.finditer(text):
                piece = m.group(1)
                if self._is_person(piece):
                    out.append(Entity(m.start(1), m.end(1), piece, "PERSON", score, "context"))
        return out

    def _pattern_entities(self, text: str) -> list[Entity]:
        out: list[Entity] = []
        for m in TIME_RE.finditer(text):
            out.append(Entity(m.start(), m.end(), m.group(0), "TIME",
                              _TYPE_SCORE["suffix"] - 8, "regex"))
        for m in MONEY_RE.finditer(text):
            out.append(Entity(m.start(), m.end(), m.group(0), "MONEY",
                              _TYPE_SCORE["suffix"] - 8, "regex"))
        for m in EN_TOKEN_RE.finditer(text):
            piece = m.group(0)
            low = piece.lower()
            if len(piece) < 2 or low in EN_STOPWORDS:
                continue
            if piece.isupper() and len(piece) <= 4:
                continue
            if not (any(c.isupper() for c in piece) or any(c.isdigit() for c in piece)):
                continue
            etype = "ORG" if piece.endswith(("Inc", "Corp", "Group", "Ltd")) else "PRODUCT"
            out.append(Entity(m.start(), m.end(), piece, etype,
                              _TYPE_SCORE["suffix"] - 10, "regex"))
        return out

    def _pos_entities(self, tokens: list[Token]) -> list[Entity]:
        out: list[Entity] = []
        for t in tokens:
            piece = t.text.strip()
            if len(piece) < 2 or piece in STOPWORDS:
                continue
            if t.flag in ("nr", "nrfg", "nrt"):
                if self._is_person(piece):
                    out.append(Entity(t.start, t.end, piece, "PERSON",
                                      _TYPE_SCORE["pos"], "pos"))
            elif t.flag == "ns":
                if piece in _LOC_SET or piece.endswith(tuple(LOC_SUFFIX_WORDS)):
                    out.append(Entity(t.start, t.end, piece, "LOC",
                                      _TYPE_SCORE["pos"] - 4, "pos"))
            elif t.flag == "nt":
                if 2 <= len(piece) <= 16 and piece not in GENERIC_ORG and not piece.endswith("企业"):
                    out.append(Entity(t.start, t.end, piece, "ORG",
                                      _TYPE_SCORE["pos"] - 2, "pos"))
            elif t.flag == "nz" and piece in _PRODUCT_SET:
                out.append(Entity(t.start, t.end, piece, "PRODUCT",
                                  _TYPE_SCORE["pos"], "pos"))
        return out

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #
    def _is_person(self, piece: str) -> bool:
        if not (2 <= len(piece) <= 4):
            return False
        if piece in STOPWORDS or piece in _ORG_SET or piece in _LOC_SET:
            return False
        if any(ch in "省市县区镇州国集团部委局行院校" for ch in piece):
            return False
        if piece[:2] in COMPOUND_SURNAMES:
            return True
        if piece[0] not in PERSON_SURNAMES:
            return False
        if any(ch in "的了和与及是在于对为该公司企业集团" for ch in piece[1:]):
            return False
        return True

    def _resolve_overlaps(self, candidates: list[Entity]) -> list[Entity]:
        """最长优先 + 分数优先的重叠消解。"""
        best: dict[tuple[int, int], Entity] = {}
        for c in candidates:
            key = (c.start, c.end)
            if key not in best or c.score > best[key].score:
                best[key] = c
        ordered = sorted(best.values(), key=lambda e: (-(e.end - e.start), -e.score, e.start))
        selected: list[Entity] = []
        for cand in ordered:
            if any(not (cand.end <= s.start or cand.start >= s.end) for s in selected):
                continue
            selected.append(cand)
        return selected

    def _assign_sentence(self, entities: list[Entity], sentences: list[Sentence]) -> None:
        for e in entities:
            for s in sentences:
                if s.start <= e.start < s.end:
                    e.sentence_index = s.index
                    break
