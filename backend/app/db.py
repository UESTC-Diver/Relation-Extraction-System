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

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
# 允许用环境变量把库指向别处：跑测试时指向 tmp_path，就不会污染真实 app.db
DB_PATH = Path(os.environ.get("APP_DB_PATH", DATA_DIR / "app.db"))

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
    rule_base    TEXT    NOT NULL DEFAULT 'trigger',
    FOREIGN KEY (record_id) REFERENCES records (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_relations_record ON relations (record_id);
CREATE INDEX IF NOT EXISTS idx_relations_key ON relations (relation);
CREATE INDEX IF NOT EXISTS idx_records_created ON records (created_at DESC);

-- 用户自定义实体词典（全局共享，抽取时优先于规则识别）
CREATE TABLE IF NOT EXISTS custom_terms (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT    NOT NULL UNIQUE,
    type       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

-- 用户自定义关系触发词：给 19 类内置规则追加领域说法，不用改 Python 重新发版
CREATE TABLE IF NOT EXISTS custom_rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    relation_key TEXT    NOT NULL,
    trigger      TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    UNIQUE (relation_key, trigger)
);

-- 全库聚合的增量计数：避免 /api/stats 每次对 records 做全表 SUM / AVG。
-- 单行表，启动时从 records 重算一次保证与历史库一致，之后由写路径增量维护。
CREATE TABLE IF NOT EXISTS counters (
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    records   INTEGER NOT NULL DEFAULT 0,
    chars     INTEGER NOT NULL DEFAULT 0,
    entities  INTEGER NOT NULL DEFAULT 0,
    relations INTEGER NOT NULL DEFAULT 0,
    sum_ms    REAL    NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO counters (id) VALUES (1);
"""

# 依赖归一化字段的索引，必须在 _migrate 补列之后才能创建
INDEX_AFTER_MIGRATE = """
CREATE INDEX IF NOT EXISTS idx_relations_head ON relations (head_canonical);
"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


import threading
import time

# 连接按线程复用：FastAPI 的同步端点跑在线程池里，每个工作线程留一条连接，
# 避免每请求 open/close 一遍并重设 PRAGMA（journal_mode 还是个库级写操作）。
_local = threading.local()
_wal_ready: set[str] = set()
_wal_lock = threading.Lock()

_OVERVIEW_TTL = 5.0
_overview_cache: tuple[str, float, dict] | None = None


def _invalidate_overview() -> None:
    global _overview_cache
    _overview_cache = None


# --------------------------------------------------------------------------- #
# 全文检索（FTS5 trigram）
#
# 默认 unicode61 分词器把连续汉字当成一个词，"搜狗公司" 搜不到 "搜狗公司宣布"；
# trigram 按 3 字符滑窗建索引，天然支持中文子串，且可用 MATCH 走索引而不是
# LIKE '%kw%' 全表扫描。SQLite 未编入 FTS5 或版本 < 3.34 时自动退回 LIKE。
# --------------------------------------------------------------------------- #
_FTS_READY = False

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS records_fts
    USING fts5(title, text, content='records', content_rowid='id', tokenize='trigram');

CREATE TRIGGER IF NOT EXISTS records_fts_ai AFTER INSERT ON records BEGIN
    INSERT INTO records_fts(rowid, title, text) VALUES (new.id, new.title, new.text);
END;
CREATE TRIGGER IF NOT EXISTS records_fts_ad AFTER DELETE ON records BEGIN
    INSERT INTO records_fts(records_fts, rowid, title, text)
        VALUES ('delete', old.id, old.title, old.text);
END;
CREATE TRIGGER IF NOT EXISTS records_fts_au AFTER UPDATE OF title, text ON records BEGIN
    INSERT INTO records_fts(records_fts, rowid, title, text)
        VALUES ('delete', old.id, old.title, old.text);
    INSERT INTO records_fts(rowid, title, text) VALUES (new.id, new.title, new.text);
END;
"""


def _setup_fts(conn: sqlite3.Connection) -> None:
    """建外部内容全文索引并回填历史数据；不支持的环境静默降级。"""
    global _FTS_READY
    if sqlite3.sqlite_version_info < (3, 34, 0):
        return
    try:
        conn.executescript(_FTS_SCHEMA)
        # 每次启动对齐一次：外部内容表不自行感知建表前已有的行
        conn.execute("INSERT INTO records_fts(records_fts) VALUES('rebuild')")
        _FTS_READY = True
    except sqlite3.Error:
        _FTS_READY = False


def _fts_where(keyword: str) -> tuple[str, list[str]] | None:
    """把用户输入转成安全的 FTS MATCH 短语；不适合走索引时返回 None。"""
    if not _FTS_READY or len(keyword) < 3:
        # trigram 至少 3 个字符才生成词元，短词用 LIKE 反而更快也更准
        return None
    if any(ch in keyword for ch in '"*^:(){}') or keyword.strip() != keyword:
        return None
    phrase = '"' + keyword.replace('"', '""') + '"'
    return "WHERE id IN (SELECT rowid FROM records_fts WHERE records_fts MATCH ?)", [phrase]


# --------------------------------------------------------------------------- #
# 增量统计计数
# --------------------------------------------------------------------------- #

def _rebuild_counters(conn: sqlite3.Connection) -> None:
    """启动时按 records 真值重算，兼容旧库与手工改库。"""
    row = conn.execute(
        """SELECT COUNT(*) AS records,
                  COALESCE(SUM(char_count), 0) AS chars,
                  COALESCE(SUM(entity_count), 0) AS entities,
                  COALESCE(SUM(relation_count), 0) AS relations,
                  COALESCE(SUM(elapsed_ms), 0) AS sum_ms
           FROM records"""
    ).fetchone()
    conn.execute(
        """UPDATE counters SET records = ?, chars = ?, entities = ?,
                               relations = ?, sum_ms = ? WHERE id = 1""",
        (row["records"], row["chars"], row["entities"], row["relations"], row["sum_ms"]),
    )


def _bump_counters(
    conn: sqlite3.Connection,
    records: int = 0,
    chars: int = 0,
    entities: int = 0,
    relations: int = 0,
    sum_ms: float = 0.0,
) -> None:
    conn.execute(
        """UPDATE counters SET records = records + ?, chars = chars + ?,
                               entities = entities + ?, relations = relations + ?,
                               sum_ms = sum_ms + ? WHERE id = 1""",
        (records, chars, entities, relations, sum_ms),
    )


def _record_totals(conn: sqlite3.Connection, record_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT char_count, entity_count, relation_count, elapsed_ms
           FROM records WHERE id = ?""",
        (record_id,),
    ).fetchone()


def _connection() -> sqlite3.Connection:
    path = str(DB_PATH)
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == path:
        return conn
    if conn is not None:
        # APP_DB_PATH 换了（测试切临时库）：旧连接必须丢掉，否则会串库
        conn.close()
        _invalidate_overview()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # journal_mode 写在数据库文件头里，同一个库设一次就够；
    # 另外三条是连接级设置，每条新连接都要设。
    with _wal_lock:
        if path not in _wal_ready:
            conn.execute("PRAGMA journal_mode = WAL")
            _wal_ready.add(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    _local.conn = conn
    _local.path = path
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = _connection()
    changes_before = conn.total_changes
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    # 有写入就让统计缓存失效；纯读（列表 / 详情 / 统计）保留缓存
    if conn.total_changes != changes_before:
        _invalidate_overview()


def _migrate(conn: sqlite3.Connection) -> None:
    """为旧库补齐归一化字段与抽取来源，并回填历史数据（幂等）。"""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(relations)")}
    missing = [c for c in ("head_canonical", "tail_canonical") if c not in cols]
    if missing:
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

    # 人工校正需要区分自动抽取与手工录入
    if "rule_base" not in cols:
        conn.execute(
            "ALTER TABLE relations ADD COLUMN rule_base TEXT NOT NULL DEFAULT 'trigger'"
        )


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.executescript(INDEX_AFTER_MIGRATE)
        _setup_fts(conn)
        _rebuild_counters(conn)


def _insert_relations(
    conn: sqlite3.Connection, record_id: int, relations: list[dict[str, Any]]
) -> None:
    if not relations:
        return
    from .nlp.entity import canonical_name

    conn.executemany(
        """
        INSERT INTO relations (record_id, head, head_canonical, head_type,
                               relation, relation_label, tail, tail_canonical,
                               tail_type, confidence, evidence, trigger,
                               sentence_index, rule_base)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                r.get("rule_base") or "trigger",
            )
            for r in relations
        ],
    )


def save_record(
    result: dict[str, Any],
    source: str = "text",
    title: str = "",
    store_relations: bool = True,
) -> int:
    stats = result.get("stats", {})
    entities = result.get("entities", [])
    relations = result.get("relations", [])
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
                len(relations),
                json.dumps(result.get("entity_type_counts", {}), ensure_ascii=False),
                json.dumps(entities, ensure_ascii=False),
                stats.get("elapsed_ms", 0.0),
                _now(),
            ),
        )
        record_id = int(cur.lastrowid)
        if store_relations:
            _insert_relations(conn, record_id, relations)
        _bump_counters(
            conn,
            records=1,
            chars=stats.get("char_count", 0),
            entities=stats.get("entity_count", 0),
            relations=len(relations),
            sum_ms=float(stats.get("elapsed_ms", 0.0)),
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
        # 优先走 trigram 全文索引；短词或不支持 FTS5 的环境退回 LIKE。
        fts = _fts_where(keyword)
        where, params = fts or ("WHERE text LIKE ? OR title LIKE ?", [f"%{keyword}%", f"%{keyword}%"])
    with connect() as conn:
        try:
            total = conn.execute(f"SELECT COUNT(*) AS c FROM records {where}", params).fetchone()["c"]
            # 只取列表要用的列：text 与 entities_json 可能各有上万字，
            # SELECT * 会把它们白白读进内存再丢掉。
            rows = conn.execute(
                f"""SELECT id, title, substr(text, 1, 200) AS text, source,
                           char_count, sentence_count, entity_count, relation_count,
                           elapsed_ms, created_at
                    FROM records {where} ORDER BY id DESC LIMIT ? OFFSET ?""",
                [*params, limit, offset],
            ).fetchall()
        except sqlite3.Error:
            # MATCH 语法意外报错时不能让搜索整个挂掉，退回最保守的 LIKE
            where, params = "WHERE text LIKE ? OR title LIKE ?", [f"%{keyword}%", f"%{keyword}%"]
            total = conn.execute(f"SELECT COUNT(*) AS c FROM records {where}", params).fetchone()["c"]
            rows = conn.execute(
                f"""SELECT id, title, substr(text, 1, 200) AS text, source,
                           char_count, sentence_count, entity_count, relation_count,
                           elapsed_ms, created_at
                    FROM records {where} ORDER BY id DESC LIMIT ? OFFSET ?""",
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
            "rule_base": r["rule_base"] or "trigger",
        }
        for r in rels
    ]
    return data


def replace_relations(
    record_id: int,
    relations: list[dict[str, Any]],
    entities: list[dict[str, Any]] | None = None,
) -> bool:
    """用人工校正后的三元组整体替换某条历史记录的关系，并同步计数。

    entities 不为 None 时一并更新实体快照，保证记录列表里的实体数与
    PUT 之后的实际实体清单一致。
    """
    with connect() as conn:
        totals = _record_totals(conn, record_id)
        if not totals:
            return False
        old_entities = int(totals["entity_count"] or 0)
        old_relations = int(totals["relation_count"] or 0)
        conn.execute("DELETE FROM relations WHERE record_id = ?", (record_id,))
        _insert_relations(conn, record_id, relations)

        new_entities = old_entities if entities is None else len(entities)
        if entities is None:
            conn.execute(
                "UPDATE records SET relation_count = ? WHERE id = ?",
                (len(relations), record_id),
            )
        else:
            counts: dict[str, int] = {}
            for e in entities:
                etype = e.get("type")
                if etype:
                    counts[etype] = counts.get(etype, 0) + 1
            conn.execute(
                "UPDATE records SET relation_count = ?, entity_count = ?, "
                "entities_json = ?, entity_types = ? WHERE id = ?",
                (
                    len(relations),
                    len(entities),
                    json.dumps(entities, ensure_ascii=False),
                    json.dumps(counts, ensure_ascii=False),
                    record_id,
                ),
            )
        _bump_counters(
            conn,
            entities=new_entities - old_entities,
            relations=len(relations) - old_relations,
        )
    return True


def delete_record(record_id: int) -> bool:
    with connect() as conn:
        totals = _record_totals(conn, record_id)
        conn.execute("DELETE FROM relations WHERE record_id = ?", (record_id,))
        cur = conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        if cur.rowcount > 0 and totals:
            _bump_counters(
                conn,
                records=-1,
                chars=-int(totals["char_count"] or 0),
                entities=-int(totals["entity_count"] or 0),
                relations=-int(totals["relation_count"] or 0),
                sum_ms=-float(totals["elapsed_ms"] or 0.0),
            )
    return cur.rowcount > 0


def clear_records() -> int:
    with connect() as conn:
        conn.execute("DELETE FROM relations")
        cur = conn.execute("DELETE FROM records")
        conn.execute(
            """UPDATE counters SET records = 0, chars = 0, entities = 0,
                                   relations = 0, sum_ms = 0 WHERE id = 1"""
        )
    return cur.rowcount


def overview() -> dict[str, Any]:
    """全库聚合：读多写少，做 5 秒短缓存；任何写操作由 connect() 主动失效。"""
    global _overview_cache
    key = str(DB_PATH)
    now = time.monotonic()
    if (
        _overview_cache
        and _overview_cache[0] == key
        and now - _overview_cache[1] < _OVERVIEW_TTL
    ):
        return _overview_cache[2]

    with connect() as conn:
        # 总量来自增量计数表，不再对 records 全表 SUM/AVG；
        # 热门榜仍是按 relations 分组，但整段结果有 5 秒缓存。
        totals = conn.execute(
            """SELECT records, chars, entities, relations,
                      CASE WHEN records > 0 THEN sum_ms / records ELSE 0 END AS avg_ms
               FROM counters WHERE id = 1"""
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
    data = {
        "records": totals["records"],
        "chars": totals["chars"],
        "entities": totals["entities"],
        "relations": totals["relations"],
        "avg_ms": round(totals["avg_ms"], 1),
        "top_relations": [dict(r) for r in top_relations],
        "top_entities": [dict(r) for r in top_entities],
        "recent": [dict(r) for r in recent],
    }
    _overview_cache = (key, now, data)
    return data


# --------------------------------------------------------------------------- #
# 自定义实体词典
# --------------------------------------------------------------------------- #

def list_custom_terms() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, text, type, created_at FROM custom_terms ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def add_custom_term(text: str, term_type: str) -> dict[str, Any]:
    """新增词条；已存在时返回原记录并标记 duplicate。"""
    with connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO custom_terms (text, type, created_at) VALUES (?, ?, ?)",
            (text, term_type, _now()),
        )
        row = conn.execute(
            "SELECT id, text, type, created_at FROM custom_terms WHERE text = ?", (text,)
        ).fetchone()
    data = dict(row)
    data["duplicate"] = cur.rowcount == 0
    return data


def delete_custom_term(term_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM custom_terms WHERE id = ?", (term_id,))
    return cur.rowcount > 0


def clear_custom_terms() -> int:
    with connect() as conn:
        cur = conn.execute("DELETE FROM custom_terms")
    return cur.rowcount


# --------------------------------------------------------------------------- #
# 自定义关系触发词
# --------------------------------------------------------------------------- #

def list_custom_rules() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, relation_key, trigger, created_at
               FROM custom_rules ORDER BY relation_key, id"""
        ).fetchall()
    return [dict(r) for r in rows]


def custom_triggers_by_relation() -> dict[str, list[str]]:
    """按关系 key 聚成 {key: [触发词...]}，供抽取流水线热更新索引。"""
    grouped: dict[str, list[str]] = {}
    for row in list_custom_rules():
        grouped.setdefault(row["relation_key"], []).append(row["trigger"])
    return grouped


def add_custom_rule(relation_key: str, trigger: str) -> dict[str, Any]:
    with connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO custom_rules (relation_key, trigger, created_at) VALUES (?, ?, ?)",
            (relation_key, trigger, _now()),
        )
        row = conn.execute(
            "SELECT id, relation_key, trigger, created_at FROM custom_rules WHERE relation_key = ? AND trigger = ?",
            (relation_key, trigger),
        ).fetchone()
    data = dict(row)
    data["duplicate"] = cur.rowcount == 0
    return data


def delete_custom_rule(rule_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM custom_rules WHERE id = ?", (rule_id,))
    return cur.rowcount > 0


def clear_custom_rules() -> int:
    with connect() as conn:
        cur = conn.execute("DELETE FROM custom_rules")
    return cur.rowcount


# --------------------------------------------------------------------------- #
# 批量结果的跨文档聚合
# --------------------------------------------------------------------------- #

def aggregate_records(record_ids: list[int]) -> dict[str, Any]:
    """对一组刚抽出的记录做跨文档统计：热门实体、热门关系、高频三元组。"""
    ids = [int(i) for i in record_ids if i]
    empty = {
        "records": 0, "entities": 0, "relations": 0,
        "top_entities": [], "top_relations": [], "top_pairs": [], "documents": [],
    }
    if not ids:
        return empty
    marks = ",".join("?" for _ in ids)
    with connect() as conn:
        totals = conn.execute(
            f"""SELECT COUNT(*) AS records,
                       COALESCE(SUM(entity_count), 0) AS entities,
                       COALESCE(SUM(relation_count), 0) AS relations
                FROM records WHERE id IN ({marks})""",
            ids,
        ).fetchone()
        docs = conn.execute(
            f"SELECT id, title, relation_count FROM records WHERE id IN ({marks}) ORDER BY id",
            ids,
        ).fetchall()
        top_relations = conn.execute(
            f"""SELECT relation, relation_label, COUNT(*) AS cnt FROM relations
                WHERE record_id IN ({marks}) GROUP BY relation, relation_label
                ORDER BY cnt DESC LIMIT 8""",
            ids,
        ).fetchall()
        top_entities = conn.execute(
            f"""SELECT name, type, COUNT(*) AS cnt FROM (
                    SELECT COALESCE(NULLIF(head_canonical, ''), head) AS name,
                           head_type AS type FROM relations WHERE record_id IN ({marks})
                    UNION ALL
                    SELECT COALESCE(NULLIF(tail_canonical, ''), tail) AS name,
                           tail_type AS type FROM relations WHERE record_id IN ({marks})
                ) GROUP BY name, type ORDER BY cnt DESC LIMIT 10""",
            [*ids, *ids],
        ).fetchall()
        top_pairs = conn.execute(
            f"""SELECT COALESCE(NULLIF(head_canonical, ''), head) AS head,
                       relation_label,
                       COALESCE(NULLIF(tail_canonical, ''), tail) AS tail,
                       COUNT(*) AS cnt FROM relations WHERE record_id IN ({marks})
                GROUP BY head, relation_label, tail ORDER BY cnt DESC LIMIT 8""",
            ids,
        ).fetchall()
    return {
        "records": totals["records"],
        "entities": totals["entities"],
        "relations": totals["relations"],
        "top_relations": [dict(r) for r in top_relations],
        "top_entities": [dict(r) for r in top_entities],
        "top_pairs": [dict(r) for r in top_pairs],
        "documents": [dict(r) for r in docs],
    }


def db_size_bytes() -> int:
    try:
        return DB_PATH.stat().st_size
    except OSError:
        return 0


def fts_enabled() -> bool:
    return _FTS_READY
