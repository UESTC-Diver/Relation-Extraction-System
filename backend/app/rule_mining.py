# -*- coding: utf-8 -*-
"""从标注集反推候选触发词。

人在标注台补录一条关系，等于留下一句「这句话里确实有 control 关系」的证据。
把补录原句里两个实体夹住的那段文字取出来，按关系类型聚合，反复出现的片段
就是最可能的触发词——不是猜，是从人已经确认过的判断里反推。

反向信号同样有价值：人判「不该抽」的自动项，说明产出它的那个触发词过宽。

全程只读：候选必须经 A/B 试跑确认没有误抽，再由人写入 custom_rules。
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from . import db
from .nlp.entity import canonical_name
from .nlp.lexicon import RELATION_MAP
from .nlp.pipeline import analysis_lock, analyze, apply_custom_triggers

MIN_LEN, MAX_LEN = 2, 6
MIN_COUNT = 2  # 至少两条独立补录都夹着同一片段，才当候选
# 只出现一次的片段无法区分「触发词」与「这句话的特定措辞」，只保留它恰好
# 是整段片段本身的情况；滑窗切出来的碎片一律不进，否则一条补录能生十几个候选。
MAX_FRAGMENT = 16  # 单个片段过长，说明夹的不是触发词而是半句话
SIDE_WINDOW = 14  # 实体外侧近邻窗口：触发词不一定夹在两个实体中间
MAX_CANDIDATES = 30
VERIFY_LIMIT = 12  # 自证要做真实抽取，一次请求里只验前几名
MAX_VERIFY_SENTENCES = 3

_HAN = re.compile(r"^[\u4e00-\u9fa5]+$")
# 纯虚词片段一定不是触发词；但夹在实词里的（"由…实际控制"）必须保留，
# 所以只在片段**全部**由这类字组成时才丢弃。
_FUNC = set("的了在由为和与及被是有将对把向从而且但或这那其之也就都还再又很更最着过所")


def _ngrams(text: str) -> list[str]:
    """片段里的所有 2-6 字滑窗。不用分词：触发词常跨词边界。"""
    out: list[str] = []
    for size in range(MIN_LEN, MAX_LEN + 1):
        for i in range(len(text) - size + 1):
            out.append(text[i : i + size])
    return out


def _spans(text: str, name: str) -> list[tuple[int, int]]:
    if not name:
        return []
    out: list[tuple[int, int]] = []
    start = 0
    while True:
        idx = text.find(name, start)
        if idx < 0:
            return out
        out.append((idx, idx + len(name)))
        start = idx + 1


def _pick_pair(text: str, head: str, tail: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """挑出距离最近、互不重叠的一对实体位置。

    一句话里同名实体可能出现多次，取最近的那对，夹住的片段才最可能是触发词。
    """
    best: tuple[int, tuple[int, int], tuple[int, int]] | None = None
    for h in _spans(text, head):
        for t in _spans(text, tail):
            if not (h[1] <= t[0] or t[1] <= h[0]):
                continue  # 重叠
            gap = t[0] - h[1] if h[1] <= t[0] else h[0] - t[1]
            if best is None or gap < best[0]:
                best = (gap, h, t)
    if best is None:
        return None
    return best[1], best[2]


_PUNCT = re.compile(r"[，。；！？、,.;!?：:（）()「」“”\"\n]")


def _cut(segment: str) -> str:
    """触发词不会跨标点，切到第一个标点为止。"""
    match = _PUNCT.search(segment)
    return segment[: match.start()] if match else segment


def _fragments(text: str, h: tuple[int, int], t: tuple[int, int]) -> list[str]:
    """取可能藏着触发词的三段：两实体之间、以及靠后那个实体的外侧近邻。

    只看中间会漏掉一半句式：「A 由 B 实际控制」里触发词在 B 之后，
    「A 是 B 的子公司」里在 B 之后。反过来把整句都收进来又全是噪音，
    所以外侧只取紧邻的一小段，并切到标点为止。
    """
    parts: list[str] = []
    if h[1] <= t[0]:
        parts.append(_cut(text[h[1] : t[0]]))
        parts.append(_cut(text[t[1] : t[1] + SIDE_WINDOW]))
    elif t[1] <= h[0]:
        parts.append(_cut(text[t[1] : h[0]]))
        parts.append(_cut(text[h[1] : h[1] + SIDE_WINDOW]))
    return [p.strip() for p in parts if p.strip()]


def _sentence_for(row: dict[str, Any]) -> str:
    """优先用标注时记下的原句；没有就按句序从记录正文里取。"""
    evidence = (row.get("evidence") or "").strip()
    if evidence:
        return evidence
    text = (row.get("text") or "").strip()
    index = int(row.get("sentence_index") or -1)
    if not text:
        return ""
    if index < 0:
        return text[:400]
    from .nlp.tokenizer import split_sentences

    sentences = split_sentences(text)
    if 0 <= index < len(sentences):
        return sentences[index].text
    return ""


def _known_triggers() -> tuple[set[tuple[str, str]], dict[str, list[str]]]:
    """(关系, 词) 已注册的集合，以及每个词被哪些关系占用。"""
    pairs: set[tuple[str, str]] = set()
    owners: dict[str, list[str]] = defaultdict(list)
    for key, rule in RELATION_MAP.items():
        for word in rule.triggers:
            pairs.add((key, word))
            owners[word].append(key)
    for key, words in db.custom_triggers_by_relation().items():
        for word in words:
            pairs.add((key, word))
            owners[word].append(key)
    return pairs, {k: sorted(set(v)) for k, v in owners.items()}


def _collect_manual(set_id: int | None) -> tuple[list[dict[str, Any]], int]:
    """取人工补录且判为「该抽」的项，连同它所在记录的正文。"""
    sql = """SELECT a.record_id, a.head, a.relation, a.tail, a.evidence,
                    a.sentence_index, r.title, r.text
             FROM annotations a JOIN records r ON r.id = a.record_id
             WHERE a.origin = 'manual' AND a.verdict = 'positive'"""
    args: tuple[Any, ...] = ()
    if set_id is not None:
        sql += """ AND a.record_id IN (
                       SELECT record_id FROM annotation_set_records WHERE set_id = ?
                   )"""
        args = (set_id,)
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    return rows, len(rows)


def _collect_rejected(set_id: int | None) -> list[dict[str, Any]]:
    """人判「不该抽」的自动项，用来反推哪个触发词过宽。"""
    sql = """SELECT a.record_id, a.relation FROM annotations a
             WHERE a.verdict = 'negative' AND a.origin = 'auto'"""
    args: tuple[Any, ...] = ()
    if set_id is not None:
        sql += """ AND a.record_id IN (
                       SELECT record_id FROM annotation_set_records WHERE set_id = ?
                   )"""
        args = (set_id,)
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _rejected_triggers(set_id: int | None) -> list[dict[str, Any]]:
    """被否掉的自动项，回到 relations 表里查是哪个触发词产出的。"""
    rows = _collect_rejected(set_id)
    if not rows:
        return []
    record_ids = sorted({int(r["record_id"]) for r in rows})
    placeholders = ",".join("?" * len(record_ids))
    with db.connect() as conn:
        rels = [
            dict(r)
            for r in conn.execute(
                f"""SELECT record_id, relation, trigger, head, tail, evidence
                    FROM relations WHERE record_id IN ({placeholders})""",
                tuple(record_ids),
            ).fetchall()
        ]
    index: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for rel in rels:
        index[(int(rel["record_id"]), rel["relation"])].append(rel)

    pairs, _ = _known_triggers()
    words_by_relation: dict[str, list[str]] = defaultdict(list)
    for key, word in pairs:
        words_by_relation[key].append(word)

    bucket: dict[str, dict[str, Any]] = {}
    for row in rows:
        relation = row["relation"]
        for rel in index.get((int(row["record_id"]), relation), []):
            evidence = rel.get("evidence") or ""
            # relations.trigger 可能是句式模板渲染后的整句片段，直接当词用会把
            # 一整句写成「触发词」。回到原句里找这一类关系真正命中的那个词。
            hits = [w for w in words_by_relation.get(relation, []) if w in evidence]
            if hits:
                trigger = max(hits, key=len)
            else:
                stored = (rel.get("trigger") or "").strip()
                trigger = stored if 0 < len(stored) <= 12 else ""
            if not trigger:
                continue
            item = bucket.setdefault(
                trigger,
                {
                    "trigger": trigger,
                    "relation": relation,
                    "relation_label": _label(relation),
                    "rejected": 0,
                    "examples": [],
                },
            )
            item["rejected"] += 1
            if len(item["examples"]) < 3:
                item["examples"].append(
                    {
                        "head": rel.get("head") or "",
                        "tail": rel.get("tail") or "",
                        "sentence": (rel.get("evidence") or "")[:120],
                    }
                )
    return sorted(bucket.values(), key=lambda x: -x["rejected"])


def _label(key: str) -> str:
    rule = RELATION_MAP.get(key)
    return rule.label if rule else key


def _mine_candidates(
    samples: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pairs, owners = _known_triggers()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}

    for sample in samples:
        relation = sample["relation"]
        seen: set[str] = set()
        grams = [g for frag in sample["fragments"] for g in _ngrams(frag)]
        for gram in grams:
            if not _HAN.match(gram):
                continue
            if all(ch in _FUNC for ch in gram):
                continue
            if (relation, gram) in pairs:
                continue  # 已经是这个关系的触发词，提了也没用
            if gram in seen:
                continue  # 同一句里的重复滑窗只算一次
            seen.add(gram)
            entry = grouped.setdefault(
                (relation, gram),
                {
                    "trigger": gram,
                    "relation": relation,
                    "count": 0,
                    "samples": [],
                    "records": set(),
                    "full": False,
                },
            )
            entry["count"] += 1
            if gram in sample["fragments"]:
                entry["full"] = True
            entry["records"].add(sample["record_id"])
            if len(entry["samples"]) < 4:
                entry["samples"].append(sample)

    # 子串收敛：高频短片段先占位，包含它但出现次数明显更少的长片段视为
    # 「那个短词的一种上下文」而不是独立说法。「入主」出现 3 次时，
    # 「今日宣布入主」只出现 1 次，前者能覆盖后者的句子，后者就不必单独提。
    # 反过来「全资收购」出现 5 次、其中「收购」8 次，两者都给——具体说法
    # 有自己的价值，砍掉会让人以为系统只会认宽泛词。
    entries = list(grouped.values())
    entries.sort(key=lambda e: (-e["count"], -len(e["trigger"])))
    kept: list[dict[str, Any]] = []
    for entry in entries:
        blob = entry["trigger"]
        redundant = False
        for other in kept:
            if other["relation"] != entry["relation"]:
                continue
            if other["trigger"] == blob:
                redundant = True
                break
            if other["trigger"] in blob and entry["count"] <= other["count"] * 0.6:
                redundant = True
                break
        if not redundant:
            kept.append(entry)

    out: list[dict[str, Any]] = []
    for entry in kept:
        count = entry["count"]
        if count < MIN_COUNT and not entry["full"]:
            continue
        coverage = len(entry["records"])
        length = len(entry["trigger"])
        # 三条以上补录、跨两篇材料、长度 3-5，是最像触发词的形态
        score = min(count, 4) * 0.9 + min(coverage, 2) * 0.7 + (0.5 if 3 <= length <= 5 else 0.2)
        out.append(
            {
                "trigger": entry["trigger"],
                "relation": entry["relation"],
                "relation_label": _label(entry["relation"]),
                "count": count,
                "records": coverage,
                "score": round(min(1.0, score / 5.6), 3),
                "weak": count < MIN_COUNT,
                "conflicts": [k for k in owners.get(entry["trigger"], []) if k != entry["relation"]],
                "verified": None,
                "already_hit": False,
                "examples": [
                    {
                        "head": s["head"],
                        "tail": s["tail"],
                        "sentence": s["sentence"][:160],
                        "record_id": s["record_id"],
                        "title": s["title"],
                    }
                    for s in entry["samples"][:3]
                ],
                "_samples": entry["samples"],
            }
        )
    out.sort(key=lambda c: (c["weak"], -c["score"], -c["count"], -len(c["trigger"])))
    return out[:MAX_CANDIDATES]


def _triple_key(head: str, relation: str, tail: str) -> tuple[str, str, str]:
    return (
        canonical_name(head, "ORG"),
        relation,
        canonical_name(tail, "ORG"),
    )


def _verify(candidate: dict[str, Any], real_triggers: dict[str, list[str]]) -> None:
    """把候选真的加进配置跑一遍，看它能不能抽出人补录的那条关系。

    这是整个功能里最要紧的一步：统计只能说「这些片段长得像」，只有真抽出
    来才算证据。抽不出来就标 False，界面会把它排到后面并注明没自证成功。
    """
    samples = candidate["_samples"][:MAX_VERIFY_SENTENCES]
    text = "\n".join(s["sentence"] for s in samples if s["sentence"]).strip()
    if not text:
        candidate["verified"] = False
        return

    relation = candidate["relation"]
    base = {k: list(v) for k, v in real_triggers.items()}
    after_cfg = {k: list(v) for k, v in base.items()}
    bucket = after_cfg.setdefault(relation, [])
    if candidate["trigger"] not in bucket:
        bucket.append(candidate["trigger"])

    targets = {_triple_key(s["head"], relation, s["tail"]) for s in samples}
    try:
        with analysis_lock:
            before = analyze(text, custom_triggers=base)
            after = analyze(text, custom_triggers=after_cfg)
    except Exception:  # noqa: BLE001 - 单条候选验证失败不该拖垮整个挖掘
        candidate["verified"] = False
        return
    finally:
        with analysis_lock:
            apply_custom_triggers(real_triggers)

    before_keys = {_triple_key(r["head"], r["relation"], r["tail"]) for r in before["relations"]}
    after_keys = {_triple_key(r["head"], r["relation"], r["tail"]) for r in after["relations"]}
    if targets & before_keys:
        # 现在的配置本来就抽得到，说明这条补录不是「漏抽」，加了也没增量
        candidate["already_hit"] = True
        candidate["verified"] = False
        return
    candidate["verified"] = bool(targets & after_keys)


def mine(
    set_id: int | None = None, verify: bool = True, include_weak: bool = False
) -> dict[str, Any]:
    rows, total_manual = _collect_manual(set_id)

    samples: list[dict[str, Any]] = []
    unlocatable = 0
    for row in rows:
        sentence = _sentence_for(row)
        pair = _pick_pair(sentence, row["head"], row["tail"])
        if pair is None:
            unlocatable += 1
            continue
        fragments = [f for f in _fragments(sentence, pair[0], pair[1]) if len(f) <= MAX_FRAGMENT]
        if not fragments:
            unlocatable += 1
            continue
        samples.append(
            {
                "relation": row["relation"],
                "head": row["head"],
                "tail": row["tail"],
                "fragments": fragments,
                "sentence": sentence,
                "record_id": int(row["record_id"]),
                "title": row["title"] or "",
            }
        )

    candidates = _mine_candidates(samples)
    weak_count = sum(1 for c in candidates if c["weak"])
    if not include_weak:
        # 只有一条证据的片段分不清「触发词」和「这句话的措辞」，默认不摆出来。
        # 留着这个开关是为了排查「为什么我补了却没候选」，而不是给日常用。
        candidates = [c for c in candidates if not c["weak"]]

    verified_count = 0
    if verify and candidates:
        real_triggers = db.custom_triggers_by_relation()
        # 只验证有成对证据的候选：单条补录验证不出「通用性」，白花时间。
        strong = [c for c in candidates if not c["weak"]][:VERIFY_LIMIT]
        for candidate in strong:
            _verify(candidate, real_triggers)
            if candidate["verified"]:
                verified_count += 1
        # 自证成功的排前面：这是唯一能证明「加了这个词真能多抽一条」的依据
        candidates.sort(
            key=lambda c: (
                c["verified"] is not True,
                c["already_hit"],
                -c["score"],
            )
        )

    for candidate in candidates:
        candidate.pop("_samples", None)

    overbroad = _rejected_triggers(set_id)
    relations = {c["relation"] for c in candidates}

    return {
        "summary": {
            "manual_total": total_manual,
            "usable_samples": len(samples),
            "unlocatable": unlocatable,
            "candidates": len(candidates),
            "weak_hidden": 0 if include_weak else weak_count,
            "verified": verified_count,
            "verified_limit": min(VERIFY_LIMIT, len(candidates)),
            "relations": len(relations),
            "overbroad": len(overbroad),
            "set_id": set_id,
        },
        "candidates": candidates,
        "overbroad": overbroad[:12],
        "advice": _advice(total_manual, samples, candidates, verified_count, overbroad),
    }


def _advice(
    total_manual: int,
    samples: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    verified: int,
    overbroad: list[dict[str, Any]],
) -> list[dict[str, str]]:
    if total_manual == 0:
        return [
            {
                "kind": "baseline",
                "title": "还没有可用的补录",
                "detail": "这里只读「人工补录 + 判为该抽」的项。打开标注台，在系统漏抽的地方"
                "补一条关系并标为正面，回来就能看到候选触发词。",
                "action": "打开标注台",
            }
        ]
    if not samples:
        return [
            {
                "kind": "unlocatable",
                "title": f"{total_manual} 条补录都没能在原句里定位到两个实体",
                "detail": "补录时手填的实体名要能在这句话里原样出现（或去掉公司后缀后出现），"
                "否则无法判断哪一段是触发词。检查一下补录的写法与原文是否一致。",
                "action": "检查补录",
            }
        ]
    if not candidates:
        return [
            {
                "kind": "baseline",
                "title": f"{len(samples)} 句补录里没找到重复出现的说法",
                "detail": "每句话的说法都不一样时，反推不出通用触发词——这可能是正常的："
                "有些关系本来就靠语序和上下文，不靠固定词。多补几条同类说法再看。",
                "action": "继续标注",
            }
        ]

    out: list[dict[str, str]] = []
    if verified:
        out.append(
            {
                "kind": "verified",
                "title": f"{verified} 个候选已用真实抽取自证",
                "detail": "把这些词加进配置后，人补录的那些关系确实能被抽出来，不是靠统计猜的。"
                "逐个试跑，确认没有带出误抽再写入。",
                "action": "送去试跑",
            }
        )
    else:
        out.append(
            {
                "kind": "unverified",
                "title": "候选还没通过真实抽取验证",
                "detail": "这些片段确实被反复夹在两个实体之间，但加进配置后没抽出对应关系。"
                "可能是触发词离实体太远，或句子被别的规则先占了。试跑看到差异再决定。",
                "action": "送去试跑",
            }
        )
    conflict = [c for c in candidates if c["conflicts"]]
    if conflict:
        word = conflict[0]["trigger"]
        owners = " / ".join(_label(k) for k in conflict[0]["conflicts"])
        out.append(
            {
                "kind": "conflict",
                "title": f"「{word}」已经被「{owners}」占用",
                "detail": "同一个词挂到两类关系上，抽取时谁先命中谁赢。真要加，先用 A/B 试跑"
                "看会不会把原来那类关系的结论抢走。",
                "action": "打开试跑",
            }
        )
    if overbroad:
        top = overbroad[0]
        out.append(
            {
                "kind": "overbroad",
                "title": f"「{top['trigger']}」产出的关系被否掉 {top['rejected']} 次",
                "detail": "补漏之外的另一半：这个词抽出来的结论人认为不该算。考虑收紧成更具体的"
                "说法，而不是直接删——删了会把真正靠它命中的那些也一起丢掉。",
                "action": "查看误抽",
            }
        )
    return out
