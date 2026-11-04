# -*- coding: utf-8 -*-
"""SQLite 持久化层。

表结构
------
records    : 一次抽取任务（原文 + 统计 + 实体快照）
relations  : 该任务抽出的三元组，行式存储便于统计查询
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# 默认落在 backend/data/app.db；测试或部署时可用 APP_DB_PATH 指向别处
DB_PATH = Path(os.environ.get("APP_DB_PATH") or Path(__file__).resolve().parent.parent / "data" / "app.db")
DATA_DIR = DB_PATH.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL DEFAULT '',
    text          TEXT    NOT NULL,
    source        TEXT    NOT NULL DEFAULT 'text',
    char_count    INTEGER NOT NULL DEFAULT 0,
    sentence_count INTEGER NOT NULL DEFAULT 0,
    entity_count  INTEGER NOT NULL DEFAULT 0,
    relation_count INTEGER NOT NULL DEFAULT 0,
    entity_types  TEXT    NOT NULL DEFAULT '{}',
    entities_json TEXT    NOT NULL DEFAULT '[]',
    elapsed_ms    REAL    NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS relations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id    INTEGER NOT NULL,
    head         TEXT    NOT NULL,
    head_canonical TEXT  NOT NULL DEFAULT '',
    head_type    TEXT    NOT NULL,
    relation     TEXT    NOT NULL,
    relation_label TEXT  NOT NULL,
    tail         TEXT    NOT NULL,
    tail_canonical TEXT  NOT NULL DEFAULT '',
    tail_type    TEXT    NOT NULL,
    confidence   REAL    NOT NULL DEFAULT 0,
    evidence     TEXT    NOT NULL DEFAULT '',
    trigger      TEXT    NOT NULL DEFAULT '',
    sentence_index INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (record_id) REFERENCES records (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_relations_record ON relations (record_id);
CREATE INDEX IF NOT EXISTS idx_relations_key ON relations (relation);
CREATE INDEX IF NOT EXISTS idx_records_created ON records (created_at DESC);
"""

# 依赖归一化字段的索引，必须在 _migrate 补列之后才能创建
INDEX_AFTER_MIGRATE = """
CREATE INDEX IF NOT EXISTS idx_relations_head ON relations (head_canonical);
"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL：读写不互斥，避免一个写请求把全库锁死
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    # 并发写入时最多等待 5 秒，而不是立刻抛 database is locked
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """为旧库补齐归一化字段，并回填历史数据（幂等）。"""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(relations)")}
    missing = [c for c in ("head_canonical", "tail_canonical") if c not in cols]
    if not missing:
        return
    for col in missing:
        conn.execute(f"ALTER TABLE relations ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")

    from .nlp.entity import canonical_name

    rows = conn.execute(
        "SELECT id, head, head_type, tail, tail_type FROM relations"
    ).fetchall()
    conn.executemany(
        "UPDATE relations SET head_canonical = ?, tail_canonical = ? WHERE id = ?",
        [
            (
                canonical_name(r["head"], r["head_type"]),
                canonical_name(r["tail"], r["tail_type"]),
                r["id"],
            )
            for r in rows
        ],
    )


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.executescript(INDEX_AFTER_MIGRATE)


def save_record(
    result: dict[str, Any],
    source: str = "text",
    title: str = "",
    store_relations: bool = True,
) -> int:
    stats = result.get("stats", {})
    entities = result.get("entities", [])
    if not title:
        title = (result.get("text", "")[:24] + "…") if len(result.get("text", "")) > 24 else result.get("text", "")
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO records (title, text, source, char_count, sentence_count,
                                 entity_count, relation_count, entity_types,
                                 entities_json, elapsed_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                result.get("text", ""),
                source,
                stats.get("char_count", 0),
                stats.get("sentence_count", 0),
                stats.get("entity_count", 0),
                stats.get("relation_count", 0),
                json.dumps(result.get("entity_type_counts", {}), ensure_ascii=False),
                json.dumps(entities, ensure_ascii=False),
                stats.get("elapsed_ms", 0.0),
                _now(),
            ),
        )
        record_id = int(cur.lastrowid)
        if store_relations:
            from .nlp.entity import canonical_name

            conn.executemany(
                """
                INSERT INTO relations (record_id, head, head_canonical, head_type,
                                       relation, relation_label, tail, tail_canonical,
                                       tail_type, confidence, evidence, trigger,
                                       sentence_index)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        record_id,
                        r["head"],
                        r.get("head_canonical") or canonical_name(r["head"], r["head_type"]),
                        r["head_type"],
                        r["relation"],
                        r["relation_label"],
                        r["tail"],
                        r.get("tail_canonical") or canonical_name(r["tail"], r["tail_type"]),
                        r["tail_type"],
                        float(r.get("confidence", 0)),
                        r.get("evidence", ""),
                        r.get("trigger", ""),
                        int(r.get("sentence_index", 0)),
                    )
                    for r in result.get("relations", [])
                ],
            )
    return record_id


def _record_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "text": row["text"],
        "source": row["source"],
        "char_count": row["char_count"],
        "sentence_count": row["sentence_count"],
        "entity_count": row["entity_count"],
        "relation_count": row["relation_count"],
        "elapsed_ms": row["elapsed_ms"],
        "created_at": row["created_at"],
    }


def list_records(limit: int = 20, offset: int = 0, keyword: str = "") -> dict[str, Any]:
    where, params = "", []
    if keyword:
        where = "WHERE text LIKE ? OR title LIKE ?"
        params = [f"%{keyword}%", f"%{keyword}%"]
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM records {where}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM records {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return {"total": total, "items": [_record_row(r) for r in rows]}


def get_record(record_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if not row:
            return None
        rels = conn.execute(
            "SELECT * FROM relations WHERE record_id = ? ORDER BY confidence DESC, id ASC",
            (record_id,),
        ).fetchall()
    data = _record_row(row)
    data["entities"] = json.loads(row["entities_json"] or "[]")
    data["entity_type_counts"] = json.loads(row["entity_types"] or "{}")
    data["relations"] = [
        {
            "id": f"r{r['id']}",
            "head": r["head"],
            "head_canonical": r["head_canonical"] or r["head"],
            "head_type": r["head_type"],
            "tail": r["tail"],
            "tail_canonical": r["tail_canonical"] or r["tail"],
            "tail_type": r["tail_type"],
            "relation": r["relation"],
            "relation_label": r["relation_label"],
            "confidence": round(float(r["confidence"]), 2),
            "evidence": r["evidence"],
            "trigger": r["trigger"],
            "sentence_index": r["sentence_index"],
        }
        for r in rels
    ]
    return data


def delete_record(record_id: int) -> bool:
    with connect() as conn:
        conn.execute("DELETE FROM relations WHERE record_id = ?", (record_id,))
        cur = conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
    return cur.rowcount > 0


def clear_records() -> int:
    with connect() as conn:
        conn.execute("DELETE FROM relations")
        cur = conn.execute("DELETE FROM records")
    return cur.rowcount


def overview() -> dict[str, Any]:
    with connect() as conn:
        totals = conn.execute(
            """
            SELECT COUNT(*) AS records,
                   COALESCE(SUM(char_count), 0) AS chars,
                   COALESCE(SUM(entity_count), 0) AS entities,
                   COALESCE(SUM(relation_count), 0) AS relations,
                   COALESCE(AVG(elapsed_ms), 0) AS avg_ms
            FROM records
            """
        ).fetchone()
        top_relations = conn.execute(
            """
            SELECT relation, relation_label, COUNT(*) AS cnt
            FROM relations GROUP BY relation, relation_label
            ORDER BY cnt DESC LIMIT 10
            """
        ).fetchall()
        top_entities = conn.execute(
            """
            SELECT name, type, COUNT(*) AS cnt FROM (
                SELECT COALESCE(NULLIF(head_canonical, ''), head) AS name,
                       head_type AS type FROM relations
                UNION ALL
                SELECT COALESCE(NULLIF(tail_canonical, ''), tail) AS name,
                       tail_type AS type FROM relations
            ) GROUP BY name, type ORDER BY cnt DESC LIMIT 10
            """
        ).fetchall()
        recent = conn.execute(
            "SELECT id, title, relation_count, created_at FROM records ORDER BY id DESC LIMIT 5"
        ).fetchall()
    return {
        "records": totals["records"],
        "chars": totals["chars"],
        "entities": totals["entities"],
        "relations": totals["relations"],
        "avg_ms": round(totals["avg_ms"], 1),
        "top_relations": [dict(r) for r in top_relations],
        "top_entities": [dict(r) for r in top_entities],
        "recent": [dict(r) for r in recent],
    }
