# -*- coding: utf-8 -*-
"""金标准标注存储层：把「已抽过的材料」变成可复现的评测数据。

和复核刻意分开：复核判断「这篇能不能交付」，标注判断「这套规则准不准」。
两套状态不合并——一篇材料可以定稿交付了，标注结论仍然要独立成立，否则
「评测集」会被交付流程的松紧程度污染，F1 就不可比了。

唯一的交集是允许一次性预填：把已通过/已驳回的复核结论转成标注建议，
但来源标记为 inferred，人改过之后才变 human。
"""

from __future__ import annotations

from typing import Any

from . import db
from .nlp.entity import canonical_name
from .nlp.lexicon import RELATION_MAP
from .review_store import relation_key

VERDICTS = ("positive", "negative")


def _norm(name: str) -> str:
    return canonical_name(name or "", "ORG")


def _label(relation: str) -> str:
    rule = RELATION_MAP.get(relation)
    return rule.label if rule else relation


def _make_key(head: str, relation: str, tail: str, sentence_index: int = -1) -> str:
    return relation_key(
        {
            "head_canonical": _norm(head),
            "relation": relation,
            "tail_canonical": _norm(tail),
            "sentence_index": sentence_index,
        }
    )


def _dedup(values: list[Any]) -> list[int]:
    out: list[int] = []
    for value in values:
        try:
            rid = int(value)
        except (TypeError, ValueError):
            continue
        if rid > 0 and rid not in out:
            out.append(rid)
    return out


# --------------------------------------------------------------------------- #
# 标注集
# --------------------------------------------------------------------------- #

def create_set(name: str, note: str = "", record_ids: list[int] | None = None) -> dict:
    clean = (name or "").strip()[:80] or "未命名标注集"
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO annotation_sets (name, note, created_at) VALUES (?, ?, ?)",
            (clean, (note or "").strip()[:300], db._now()),
        )
        set_id = int(cur.lastrowid)
        for rid in _dedup(record_ids or []):
            conn.execute(
                "INSERT OR IGNORE INTO annotation_set_records (set_id, record_id) VALUES (?, ?)",
                (set_id, rid),
            )
    return get_set(set_id) or {}


def list_sets() -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT s.id, s.name, s.note, s.created_at,
                      COUNT(sr.record_id) AS record_count
               FROM annotation_sets s
               LEFT JOIN annotation_set_records sr ON sr.set_id = s.id
               GROUP BY s.id ORDER BY s.id DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_set(set_id: int) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM annotation_sets WHERE id = ?", (set_id,)).fetchone()
        if not row:
            return None
        recs = conn.execute(
            """SELECT rc.id, rc.title, rc.char_count, rc.relation_count, rc.source,
                      rc.created_at,
                      (SELECT COUNT(*) FROM annotations a WHERE a.record_id = rc.id) AS judged
               FROM annotation_set_records sr
               JOIN records rc ON rc.id = sr.record_id
               WHERE sr.set_id = ? ORDER BY rc.id DESC""",
            (set_id,),
        ).fetchall()
    return {**dict(row), "records": [dict(r) for r in recs]}


def delete_set(set_id: int) -> bool:
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM annotation_sets WHERE id = ?", (set_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM annotation_set_records WHERE set_id = ?", (set_id,))
        conn.execute("DELETE FROM annotation_sets WHERE id = ?", (set_id,))
    return True


def add_records(set_id: int, record_ids: list[int]) -> dict | None:
    if not get_set(set_id):
        return None
    with db.connect() as conn:
        existing = {
            r["id"] for r in conn.execute("SELECT id FROM records")
        }
        for rid in _dedup(record_ids):
            if rid in existing:
                conn.execute(
                    "INSERT OR IGNORE INTO annotation_set_records (set_id, record_id) VALUES (?, ?)",
                    (set_id, rid),
                )
    return get_set(set_id)


def remove_records(set_id: int, record_ids: list[int]) -> dict | None:
    if not get_set(set_id):
        return None
    with db.connect() as conn:
        for rid in _dedup(record_ids):
            conn.execute(
                "DELETE FROM annotation_set_records WHERE set_id = ? AND record_id = ?",
                (set_id, rid),
            )
    return get_set(set_id)


# --------------------------------------------------------------------------- #
# 单篇标注
# --------------------------------------------------------------------------- #

def _rows(record_id: int) -> dict[str, dict]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM annotations WHERE record_id = ?", (record_id,)
        ).fetchall()
    return {r["relation_key"]: dict(r) for r in rows}


def _prefill(record_id: int) -> list[dict]:
    """把已通过/已驳回的复核结论转成标注建议；存疑的不猜。"""
    from . import review_store

    state = review_store.get_state(record_id)
    if not state:
        return []
    mapping = {"approved": "positive", "rejected": "negative"}
    out = []
    for rel in state["relations"]:
        verdict = mapping.get(rel.get("decision", ""))
        if not verdict:
            continue
        out.append(
            {
                "relation_key": rel["review_key"],
                "verdict": verdict,
                "note": rel.get("review_note", ""),
            }
        )
    return out


def get_record_annotation(record_id: int) -> dict | None:
    record = db.get_record(record_id)
    if not record:
        return None
    saved = _rows(record_id)
    auto: list[dict] = []
    seen: set[str] = set()
    for rel in record["relations"]:
        key = relation_key(rel)
        seen.add(key)
        item = saved.get(key, {})
        auto.append(
            {
                "relation_key": key,
                "head": rel.get("head", ""),
                "relation": rel.get("relation", ""),
                "relation_label": rel.get("relation_label") or _label(rel.get("relation", "")),
                "tail": rel.get("tail", ""),
                "evidence": rel.get("evidence", ""),
                "sentence_index": rel.get("sentence_index", -1),
                "confidence": rel.get("confidence", 0),
                "trigger": rel.get("trigger", ""),
                "origin": "auto",
                "verdict": item.get("verdict", ""),
                "source": item.get("source", ""),
                "note": item.get("note", ""),
            }
        )
    manual = [
        {
            "relation_key": key,
            "head": item["head"],
            "relation": item["relation"],
            "relation_label": _label(item["relation"]),
            "tail": item["tail"],
            "evidence": item["evidence"],
            "sentence_index": item["sentence_index"],
            "confidence": None,
            "trigger": "",
            "origin": "manual",
            "verdict": item["verdict"],
            "source": item["source"],
            "note": item["note"],
        }
        for key, item in saved.items()
        if key not in seen
    ]
    total = len(auto) + len(manual)
    positive = sum(1 for x in auto + manual if x["verdict"] == "positive")
    negative = sum(1 for x in auto + manual if x["verdict"] == "negative")
    unjudged = sum(1 for x in auto if not x["verdict"])
    return {
        "record_id": record_id,
        "title": record.get("title", ""),
        "text": record.get("text", ""),
        "relations": auto,
        "manual": manual,
        "summary": {
            "total": total,
            "auto": len(auto),
            "manual": len(manual),
            "positive": positive,
            "negative": negative,
            "unjudged": unjudged,
            "judged": total - unjudged,
            "coverage": round((total - unjudged) / total, 3) if total else 1.0,
        },
        "prefill": _prefill(record_id),
    }


def save_record_annotation(record_id: int, items: list[dict]) -> dict | None:
    record = db.get_record(record_id)
    if not record:
        return None
    auto_map = {relation_key(r): r for r in record["relations"]}
    # 归一三元组 → 系统那条的指纹，用来把「补的其实就是系统已抽到的」归并掉
    auto_triples = {
        (_norm(rel.get("head", "")), rel.get("relation", ""), _norm(rel.get("tail", ""))): key
        for key, rel in auto_map.items()
    }
    now = db._now()
    with db.connect() as conn:
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("relation_key") or "").strip()[:32]
            head = str(item.get("head") or "").strip()[:80]
            relation = str(item.get("relation") or "").strip()[:40]
            tail = str(item.get("tail") or "").strip()[:80]
            evidence = str(item.get("evidence") or "")[:500]
            try:
                sentence_index = int(item.get("sentence_index", -1))
            except (TypeError, ValueError):
                sentence_index = -1

            # 补录时若补的正是系统已经抽到的关系，归并到那条上：gold 里出现两条
            # 一模一样的关系，既不增加信息，也会让清单看起来像出了 bug。
            if not key and head and relation and tail:
                key = auto_triples.get((_norm(head), relation, _norm(tail))) or _make_key(
                    head, relation, tail, sentence_index
                )

            source_rel = auto_map.get(key)
            if source_rel is not None:
                # 自动命中项的元数据一律以库里那份为准：前端只需要传指纹 + 判定，
                # 免得实体名被前端拼错写进 gold，评测从此对不上。
                head = str(source_rel.get("head") or "")[:80]
                relation = str(source_rel.get("relation") or "")[:40]
                tail = str(source_rel.get("tail") or "")[:80]
                evidence = str(source_rel.get("evidence") or "")[:500]
                try:
                    sentence_index = int(source_rel.get("sentence_index", -1))
                except (TypeError, ValueError):
                    sentence_index = -1
            if not key:
                continue

            verdict = str(item.get("verdict") or "").strip()
            # 空 verdict 表示「撤回判定」，删行回到未判状态，而不是存一个 pending。
            if not verdict:
                conn.execute(
                    "DELETE FROM annotations WHERE record_id = ? AND relation_key = ?",
                    (record_id, key),
                )
                continue
            if verdict not in VERDICTS:
                continue

            origin = "auto" if source_rel is not None else "manual"
            if origin == "manual" and not (head and relation and tail):
                continue
            source = "inferred" if item.get("source") == "inferred" else "human"
            conn.execute(
                """INSERT INTO annotations
                       (record_id, relation_key, verdict, origin, source, head, relation,
                        tail, sentence_index, evidence, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(record_id, relation_key) DO UPDATE SET
                       verdict = excluded.verdict, origin = excluded.origin,
                       source = excluded.source, head = excluded.head,
                       relation = excluded.relation, tail = excluded.tail,
                       sentence_index = excluded.sentence_index,
                       evidence = excluded.evidence, note = excluded.note,
                       created_at = excluded.created_at""",
                (
                    record_id,
                    key,
                    verdict,
                    origin,
                    source,
                    head,
                    relation,
                    tail,
                    sentence_index,
                    evidence,
                    str(item.get("note") or "")[:300],
                    now,
                ),
            )
    return get_record_annotation(record_id)


def clear_record_annotation(record_id: int) -> bool:
    with db.connect() as conn:
        conn.execute("DELETE FROM annotations WHERE record_id = ?", (record_id,))
    return True


# --------------------------------------------------------------------------- #
# 覆盖度与评测数据
# --------------------------------------------------------------------------- #

def coverage(set_id: int) -> dict | None:
    data = get_set(set_id)
    if not data:
        return None
    ids = [r["id"] for r in data["records"]]
    if not ids:
        return {
            "set_id": set_id,
            "name": data["name"],
            "records": 0,
            "auto": 0,
            "manual": 0,
            "positive": 0,
            "negative": 0,
            "unjudged": 0,
            "judged": 0,
            "coverage": 0.0,
            "ready": False,
        }
    marks = ",".join("?" * len(ids))
    with db.connect() as conn:
        auto = conn.execute(
            f"SELECT COUNT(*) AS n FROM relations WHERE record_id IN ({marks})", ids
        ).fetchone()["n"]
        stat = conn.execute(
            f"""SELECT COUNT(*) AS judged,
                       SUM(CASE WHEN verdict = 'positive' THEN 1 ELSE 0 END) AS positive,
                       SUM(CASE WHEN verdict = 'negative' THEN 1 ELSE 0 END) AS negative,
                       SUM(CASE WHEN origin = 'manual' THEN 1 ELSE 0 END) AS manual
                FROM annotations WHERE record_id IN ({marks})""",
            ids,
        ).fetchone()
    judged = int(stat["judged"] or 0)
    manual = int(stat["manual"] or 0)
    auto = int(auto or 0)
    total = auto + manual
    # 补录项本身就是判定结果，只有系统自动抽出的才存在「未判」
    unjudged = max(0, total - judged)
    return {
        "set_id": set_id,
        "name": data["name"],
        "records": len(ids),
        "auto": auto,
        "manual": manual,
        "positive": int(stat["positive"] or 0),
        "negative": int(stat["negative"] or 0),
        "unjudged": unjudged,
        "judged": judged,
        "coverage": round(judged / total, 3) if total else 0.0,
        "ready": int(stat["positive"] or 0) > 0,
    }


def gold_cases(set_id: int) -> tuple[list[dict], dict[str, set]]:
    """把标注集转成 evaluate() 的用例，并给出「已判定范围」过滤表。

    返回的 scope 里是归一后的三元组：判过 negative 的也在里面，因为
    「已判定范围」要过滤的是「没判过的预测」，不是「判错的预测」。
    """
    data = get_set(set_id)
    if not data:
        return [], {}
    cases: list[dict] = []
    scope: dict[str, set] = {}
    for rec in data["records"]:
        record = db.get_record(rec["id"])
        if not record:
            continue
        case_id = f"record-{rec['id']}"
        rows = _rows(rec["id"]).values()
        positives = [
            (a["head"], a["relation"], a["tail"]) for a in rows if a["verdict"] == "positive"
        ]
        cases.append(
            {
                "id": case_id,
                "title": record.get("title", ""),
                "text": record.get("text", ""),
                "relations": positives,
            }
        )
        scope[case_id] = {
            (_norm(a["head"]), a["relation"], _norm(a["tail"])) for a in rows
        }
    return cases, scope
