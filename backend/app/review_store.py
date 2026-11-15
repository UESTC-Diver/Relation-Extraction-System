# -*- coding: utf-8 -*-
"""复核闭环存储层：逐条决策、状态流转与定稿快照。

单独成模块，避免把 db.py 再撑大；连接仍走 db.connect()，沿用同一套
WAL、线程复用与统计缓存失效机制。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import db

STATUSES = ("draft", "in_review", "final")
DECISIONS = ("approved", "questioned", "rejected", "pending")

# 定稿必须走 /finalize（会写不可变快照），不能靠改状态绕过；
# final 只能退回 in_review 解锁改稿。
_ALLOWED_TRANSITIONS = {
    "draft": {"in_review"},
    "in_review": {"draft"},
    "final": {"in_review"},
}


def relation_key(rel: dict[str, Any]) -> str:
    """给三元组一个稳定指纹，用于跨保存 / 载入对齐人工结论。

    用归一实体 + 关系 key + 证据句序号：改了实体或关系后指纹会变，旧结论
    自动失效 —— 这比绑定行 id 更诚实，内容改了本来就该重新复核。
    """
    head = rel.get("head_canonical") or rel.get("head") or ""
    tail = rel.get("tail_canonical") or rel.get("tail") or ""
    raw = f"{head}|{rel.get('relation', '')}|{tail}|{rel.get('sentence_index', 0)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _status(conn, record_id: int) -> str | None:
    row = conn.execute("SELECT review_status FROM records WHERE id = ?", (record_id,)).fetchone()
    return row["review_status"] if row else None


def is_final(record_id: int) -> bool:
    with db.connect() as conn:
        return _status(conn, record_id) == "final"


def get_state(record_id: int) -> dict[str, Any] | None:
    """状态、每条关系的指纹与结论、进度汇总、快照列表。"""
    record = db.get_record(record_id)
    if not record:
        return None
    with db.connect() as conn:
        status = _status(conn, record_id) or "draft"
        rows = conn.execute(
            """SELECT relation_key, decision, note, reviewer, updated_at
               FROM review_decisions WHERE record_id = ?""",
            (record_id,),
        ).fetchall()
        snaps = conn.execute(
            """SELECT id, created_at, title FROM review_snapshots
               WHERE record_id = ? ORDER BY id DESC""",
            (record_id,),
        ).fetchall()
    decisions = {r["relation_key"]: dict(r) for r in rows}
    relations = []
    for rel in record["relations"]:
        key = relation_key(rel)
        saved = decisions.get(key, {})
        relations.append(
            {
                **rel,
                "review_key": key,
                "decision": saved.get("decision", "pending"),
                "review_note": saved.get("note", ""),
            }
        )
    counts = {d: 0 for d in DECISIONS}
    for rel in relations:
        decision = rel["decision"] if rel["decision"] in counts else "pending"
        counts[decision] += 1
    return {
        "record_id": record_id,
        "status": status,
        "editable": status != "final",
        "relations": relations,
        "decisions": decisions,
        "summary": {
            "total": len(relations),
            **counts,
            "reviewed": len(relations) - counts["pending"],
        },
        "snapshots": [dict(s) for s in snaps],
    }


def save_decisions(record_id: int, items: list[dict], reviewer: str = "") -> dict:
    with db.connect() as conn:
        current = _status(conn, record_id)
        if current is None:
            return {"error": "记录不存在"}
        if current == "final":
            return {"error": "已定稿的记录不能修改复核结论，请先解锁"}
        now = db._now()
        for item in items:
            key = str(item.get("relation_key") or "").strip()[:32]
            decision = str(item.get("decision") or "pending")
            if not key or decision not in DECISIONS:
                continue
            if decision == "pending":
                conn.execute(
                    "DELETE FROM review_decisions WHERE record_id = ? AND relation_key = ?",
                    (record_id, key),
                )
                continue
            conn.execute(
                """INSERT INTO review_decisions
                       (record_id, relation_key, decision, note, reviewer, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(record_id, relation_key) DO UPDATE SET
                       decision = excluded.decision, note = excluded.note,
                       reviewer = excluded.reviewer, updated_at = excluded.updated_at""",
                (
                    record_id,
                    key,
                    decision,
                    str(item.get("note") or "")[:500],
                    reviewer[:40],
                    now,
                ),
            )
    return get_state(record_id) or {}


def set_status(record_id: int, status: str) -> dict | None:
    if status not in STATUSES:
        return None
    with db.connect() as conn:
        current = _status(conn, record_id)
        if current is None:
            return None
        if status != current and status not in _ALLOWED_TRANSITIONS.get(current, set()):
            return {"error": f"不允许从 {current} 直接切换到 {status}"}
        conn.execute("UPDATE records SET review_status = ? WHERE id = ?", (status, record_id))
    return get_state(record_id)


def finalize(record_id: int, title: str = "") -> dict | None:
    """定稿：把当前三元组、实体与结论写成不可变快照，然后置 final。"""
    state = get_state(record_id)
    if not state:
        return None
    if state["status"] == "final":
        return {"error": "这条记录已经定稿"}
    record = db.get_record(record_id)
    entities = record["entities"] if record else []
    with db.connect() as conn:
        if _status(conn, record_id) == "final":
            return {"error": "这条记录已经定稿"}
        cur = conn.execute(
            """INSERT INTO review_snapshots
                   (record_id, created_at, title, relations_json, entities_json, decisions_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                record_id,
                db._now(),
                (title or "")[:120],
                json.dumps(state["relations"], ensure_ascii=False),
                json.dumps(entities, ensure_ascii=False),
                json.dumps(list(state["decisions"].values()), ensure_ascii=False),
            ),
        )
        conn.execute("UPDATE records SET review_status = 'final' WHERE id = ?", (record_id,))
        snapshot_id = int(cur.lastrowid)
    return {"snapshot_id": snapshot_id, **(get_state(record_id) or {})}


def get_snapshot(record_id: int, snapshot_id: int) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM review_snapshots WHERE id = ? AND record_id = ?",
            (snapshot_id, record_id),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "record_id": row["record_id"],
        "created_at": row["created_at"],
        "title": row["title"],
        "relations": json.loads(row["relations_json"] or "[]"),
        "entities": json.loads(row["entities_json"] or "[]"),
        "decisions": json.loads(row["decisions_json"] or "[]"),
    }


def report_review(record_id: int | None) -> dict | None:
    """离线报告用的精简复核信息；草稿且没有任何结论时不显示该区块。"""
    if not record_id:
        return None
    state = get_state(record_id)
    if not state:
        return None
    if state["status"] == "draft" and state["summary"]["reviewed"] == 0:
        return None
    return {
        "status": state["status"],
        "summary": state["summary"],
        "relations": [
            {
                "head": r["head"],
                "relation_label": r["relation_label"],
                "tail": r["tail"],
                "decision": r["decision"],
                "review_note": r["review_note"],
            }
            for r in state["relations"]
            if r["decision"] != "pending"
        ],
    }
