# -*- coding: utf-8 -*-
"""知识库、质量闭环与交付能力的查询层。

所有跨记录统计都基于 relations 已有的 head_canonical / tail_canonical，
不额外维护一份可能失同步的实体表；写路径统一走 db.connect()，
让统计缓存失效、连接复用与事务语义保持和原有数据层一致。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from . import db

_FLAT_ENTITY_SQL = """
SELECT COALESCE(NULLIF(r.head_canonical, ''), r.head) AS name,
       r.head_type AS type, r.record_id AS record_id,
       rec.created_at AS created_at, r.head AS alias
FROM relations r JOIN records rec ON rec.id = r.record_id
UNION ALL
SELECT COALESCE(NULLIF(r.tail_canonical, ''), r.tail) AS name,
       r.tail_type AS type, r.record_id AS record_id,
       rec.created_at AS created_at, r.tail AS alias
FROM relations r JOIN records rec ON rec.id = r.record_id
"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# 标签
# --------------------------------------------------------------------------- #

def list_tags() -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT tags FROM records WHERE tags IS NOT NULL AND tags != ''"
        ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        for tag in db._split_tags(row["tags"]):
            counts[tag] = counts.get(tag, 0) + 1
    return [
        {"tag": tag, "count": cnt}
        for tag, cnt in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def set_record_tags(record_id: int, tags: list[str]) -> list[str] | None:
    clean = []
    for raw in tags or []:
        tag = str(raw).strip().replace(",", "／")[:24]
        if tag and tag not in clean:
            clean.append(tag)
    value = ",".join(clean[:12])
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE records SET tags = ? WHERE id = ?", (value, record_id)
        )
    return clean if cur.rowcount > 0 else None


# --------------------------------------------------------------------------- #
# 全局实体检索与画像
# --------------------------------------------------------------------------- #

def global_entities(q: str = "", entity_type: str = "", limit: int = 40) -> dict[str, Any]:
    conditions: list[str] = []
    params: list[Any] = []
    if q:
        conditions.append("name LIKE ?")
        params.append(f"%{q}%")
    if entity_type:
        conditions.append("type = ?")
        params.append(entity_type)
    having = "HAVING " + " AND ".join(conditions) if conditions else ""
    sql = f"""
        SELECT name, type, COUNT(*) AS cnt, COUNT(DISTINCT record_id) AS docs,
               MIN(created_at) AS first_seen, MAX(created_at) AS last_seen,
               GROUP_CONCAT(DISTINCT alias) AS aliases
        FROM ({_FLAT_ENTITY_SQL}) flat
        GROUP BY name, type
        {having}
        ORDER BY cnt DESC, name ASC
    """
    with db.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    items = []
    for row in rows:
        aliases = [a for a in (row["aliases"] or "").split(",") if a and a != row["name"]]
        items.append({
            "name": row["name"], "type": row["type"], "count": row["cnt"],
            "documents": row["docs"], "first_seen": row["first_seen"],
            "last_seen": row["last_seen"], "aliases": aliases[:8],
        })
    return {"total": len(items), "items": items[: max(1, min(limit, 200))]}


def entity_profile(name: str) -> dict[str, Any]:
    sql = f"""
        SELECT r.*, rec.title AS doc_title, rec.created_at AS doc_created
        FROM relations r JOIN records rec ON rec.id = r.record_id
        WHERE COALESCE(NULLIF(r.head_canonical, ''), r.head) = ?
           OR COALESCE(NULLIF(r.tail_canonical, ''), r.tail) = ?
        ORDER BY rec.created_at DESC, r.id DESC
    """
    with db.connect() as conn:
        rows = conn.execute(sql, (name, name)).fetchall()

    aliases: set[str] = set()
    entity_type = ""
    documents: dict[int, dict] = {}
    relations: list[dict] = []
    timeline: dict[str, int] = {}
    for r in rows:
        head = r["head_canonical"] or r["head"]
        tail = r["tail_canonical"] or r["tail"]
        outgoing = head == name
        if outgoing:
            aliases.add(r["head"])
            entity_type = entity_type or r["head_type"]
        if tail == name:
            aliases.add(r["tail"])
            entity_type = entity_type or r["tail_type"]
        documents[r["record_id"]] = {
            "id": r["record_id"], "title": r["doc_title"],
            "created_at": r["doc_created"],
        }
        day = (r["doc_created"] or "")[:10]
        if day:
            timeline[day] = timeline.get(day, 0) + 1
        relations.append({
            "direction": "out" if outgoing else "in",
            "other": tail if outgoing else head,
            "other_type": r["tail_type"] if outgoing else r["head_type"],
            "relation": r["relation"], "relation_label": r["relation_label"],
            "confidence": round(float(r["confidence"]), 2),
            "evidence": r["evidence"], "sentence_index": r["sentence_index"],
            "record_id": r["record_id"], "doc_title": r["doc_title"],
            "rule_base": r["rule_base"],
        })
    return {
        "name": name, "type": entity_type,
        "aliases": sorted(a for a in aliases if a != name),
        "appearances": len(rows),
        "documents": sorted(documents.values(), key=lambda d: d["created_at"], reverse=True),
        "relations": relations[:200], "relation_total": len(relations),
        "timeline": [{"date": d, "count": c} for d, c in sorted(timeline.items())],
    }


def global_graph(relation: str = "", limit: int = 120) -> dict[str, Any]:
    where, params = "", []
    if relation:
        where, params = "WHERE relation = ?", [relation]
    sql = f"""
        SELECT COALESCE(NULLIF(head_canonical, ''), head) AS h,
               COALESCE(NULLIF(tail_canonical, ''), tail) AS t,
               head_type AS ht, tail_type AS tt,
               relation, relation_label, COUNT(*) AS cnt,
               COUNT(DISTINCT record_id) AS docs
        FROM relations {where}
        GROUP BY h, t, ht, tt, relation, relation_label
        ORDER BY cnt DESC, h ASC
        LIMIT ?
    """
    with db.connect() as conn:
        rows = conn.execute(sql, [*params, max(1, min(limit, 400))]).fetchall()

    nodes: dict[str, dict] = {}
    links = []
    for r in rows:
        for key, typ in ((r["h"], r["ht"]), (r["t"], r["tt"])):
            node = nodes.setdefault(key, {"id": key, "name": key, "type": typ, "count": 0})
            node["count"] += r["cnt"]
        links.append({
            "source": r["h"], "target": r["t"],
            "relation": r["relation"], "label": r["relation_label"],
            "count": r["cnt"], "documents": r["docs"],
        })
    return {
        "nodes": sorted(nodes.values(), key=lambda n: -n["count"]),
        "links": links,
        "node_count": len(nodes), "link_count": len(links),
        "truncated": len(rows) >= max(1, min(limit, 400)),
    }


def conflicts(limit: int = 30) -> dict[str, Any]:
    """同一实体对在不同文档里被判成不同关系，交给人工裁决。"""
    sql = """
        SELECT COALESCE(NULLIF(head_canonical, ''), head) AS h,
               COALESCE(NULLIF(tail_canonical, ''), tail) AS t,
               relation, relation_label, record_id, evidence, confidence
        FROM relations
    """
    with db.connect() as conn:
        rows = conn.execute(sql).fetchall()
    grouped: dict[tuple[str, str], dict] = {}
    for r in rows:
        a, b = r["h"], r["t"]
        key = (a, b) if a <= b else (b, a)
        item = grouped.setdefault(key, {"head": key[0], "tail": key[1], "items": []})
        item["items"].append({
            "relation": r["relation"], "relation_label": r["relation_label"],
            "record_id": r["record_id"], "evidence": r["evidence"],
            "confidence": round(float(r["confidence"]), 2),
        })
    result = []
    for item in grouped.values():
        labels = {i["relation"] for i in item["items"]}
        if len(labels) > 1:
            result.append({
                **item, "relation_count": len(labels),
                "documents": len({i["record_id"] for i in item["items"]}),
            })
    result.sort(key=lambda x: (-x["relation_count"], -len(x["items"])))
    return {"total": len(result), "items": result[: max(1, min(limit, 100))]}


def review_queue(threshold: float = 0.8, limit: int = 50) -> dict[str, Any]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT r.id, r.record_id, rec.title AS doc_title,
                      r.head, r.tail, r.relation, r.relation_label,
                      r.confidence, r.evidence, r.sentence_index, r.rule_base
               FROM relations r JOIN records rec ON rec.id = r.record_id
               WHERE r.confidence < ?
               ORDER BY r.confidence ASC, r.id DESC LIMIT ?""",
            (threshold, max(1, min(limit, 200))),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM relations WHERE confidence < ?", (threshold,)
        ).fetchone()["c"]
    return {
        "threshold": threshold, "total": total,
        "items": [
            {**dict(r), "confidence": round(float(r["confidence"]), 2)}
            for r in rows
        ],
    }


# --------------------------------------------------------------------------- #
# 评测历史
# --------------------------------------------------------------------------- #

def save_eval_run(report: dict) -> int:
    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO eval_runs (created_at, cases, tp, fp, fn,
                                      precision, recall, f1, macro_f1, report_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _now(), report.get("cases", 0), report.get("tp", 0),
                report.get("fp", 0), report.get("fn", 0),
                report.get("precision", 0), report.get("recall", 0),
                report.get("f1", 0), report.get("macro_f1", 0),
                json.dumps(report, ensure_ascii=False),
            ),
        )
    return int(cur.lastrowid)


def _eval_row(row, full: bool = False) -> dict[str, Any]:
    data = {
        "id": row["id"], "created_at": row["created_at"], "cases": row["cases"],
        "tp": row["tp"], "fp": row["fp"], "fn": row["fn"],
        "precision": row["precision"], "recall": row["recall"],
        "f1": row["f1"], "macro_f1": row["macro_f1"],
    }
    if full:
        data["report"] = json.loads(row["report_json"] or "{}")
    return data


def list_eval_runs(limit: int = 30) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_runs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),)
        ).fetchall()
    return [_eval_row(r) for r in rows]


def get_eval_run(run_id: int) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
    return _eval_row(row, full=True) if row else None


# --------------------------------------------------------------------------- #
# 规则实验室：配置快照与回滚
# --------------------------------------------------------------------------- #

def save_rule_version(name: str) -> int:
    rules = db.list_custom_rules()
    terms = db.list_custom_terms()
    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO rule_versions (name, created_at, rules_json, terms_json)
               VALUES (?, ?, ?, ?)""",
            (
                (name or f"配置 {_now()}")[:60], _now(),
                json.dumps([{"relation_key": r["relation_key"], "trigger": r["trigger"]} for r in rules],
                           ensure_ascii=False),
                json.dumps([{"text": t["text"], "type": t["type"]} for t in terms],
                           ensure_ascii=False),
            ),
        )
    return int(cur.lastrowid)


def list_rule_versions() -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM rule_versions ORDER BY id DESC LIMIT 50"
        ).fetchall()
    return [
        {
            "id": r["id"], "name": r["name"], "created_at": r["created_at"],
            "rules": len(json.loads(r["rules_json"] or "[]")),
            "terms": len(json.loads(r["terms_json"] or "[]")),
        }
        for r in rows
    ]


def restore_rule_version(version_id: int) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM rule_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if not row:
            return None
        rules = json.loads(row["rules_json"] or "[]")
        terms = json.loads(row["terms_json"] or "[]")
        conn.execute("DELETE FROM custom_rules")
        conn.execute("DELETE FROM custom_terms")
        conn.executemany(
            "INSERT OR IGNORE INTO custom_rules (relation_key, trigger, created_at) VALUES (?, ?, ?)",
            [(r["relation_key"], r["trigger"], _now()) for r in rules],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO custom_terms (text, type, created_at) VALUES (?, ?, ?)",
            [(t["text"], t["type"], _now()) for t in terms],
        )
    return {"id": version_id, "name": row["name"], "rules": len(rules), "terms": len(terms)}


# --------------------------------------------------------------------------- #
# 实体级校正
# --------------------------------------------------------------------------- #

def replace_entities(
    record_id: int, entities: list[dict], corrections: list[dict]
) -> bool:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT entity_count FROM records WHERE id = ?", (record_id,)
        ).fetchone()
        if not row:
            return False
        previous = int(row["entity_count"] or 0)
        conn.execute(
            "UPDATE records SET entities_json = ?, entity_count = ? WHERE id = ?",
            (json.dumps(entities, ensure_ascii=False), len(entities), record_id),
        )
        db._bump_counters(conn, entities=len(entities) - previous)
        conn.executemany(
            """INSERT INTO entity_corrections
               (record_id, original, corrected, entity_type, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (record_id, str(c.get("original", ""))[:64],
                 str(c.get("corrected", ""))[:64],
                 str(c.get("type", ""))[:20], _now())
                for c in corrections
            ],
        )
    return True


def list_entity_corrections(record_id: int) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM entity_corrections WHERE record_id = ? ORDER BY id DESC LIMIT 50",
            (record_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# 后台任务
# --------------------------------------------------------------------------- #

def create_task(kind: str, total: int) -> str:
    task_id = uuid.uuid4().hex[:16]
    now = _now()
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO tasks (id, kind, status, done, total, created_at, updated_at)
               VALUES (?, ?, 'running', 0, ?, ?, ?)""",
            (task_id, kind, total, now, now),
        )
    return task_id


def update_task(task_id: str, **fields: Any) -> None:
    allowed = {"status", "done", "total", "result_json", "error"}
    pairs = [(k, v) for k, v in fields.items() if k in allowed]
    if not pairs:
        return
    sets = ", ".join(f"{k} = ?" for k, _ in pairs)
    values = [
        json.dumps(v, ensure_ascii=False) if k == "result_json" and not isinstance(v, str) else v
        for k, v in pairs
    ]
    with db.connect() as conn:
        conn.execute(
            f"UPDATE tasks SET {sets}, updated_at = ? WHERE id = ?",
            [*values, _now(), task_id],
        )


def _task_row(row, full: bool = False) -> dict[str, Any]:
    data = {
        "id": row["id"], "kind": row["kind"], "status": row["status"],
        "done": row["done"], "total": row["total"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "error": row["error"],
    }
    if full:
        data["result"] = json.loads(row["result_json"] or "{}")
    return data


def get_task(task_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _task_row(row, full=True) if row else None


def list_tasks(limit: int = 20) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (max(1, min(limit, 50)),),
        ).fetchall()
    return [_task_row(r) for r in rows]


def fail_stale_tasks() -> None:
    """服务重启后内存里的 worker 已不存在，把残留 running 任务标成失败。"""
    with db.connect() as conn:
        conn.execute(
            "UPDATE tasks SET status = 'failed', error = ?, updated_at = ? WHERE status = 'running'",
            ("服务重启，后台任务中断", _now()),
        )


# --------------------------------------------------------------------------- #
# 项目包：换机器完整复原材料与配置
# --------------------------------------------------------------------------- #

def export_project() -> dict[str, Any]:
    with db.connect() as conn:
        records = [dict(r) for r in conn.execute(
            """SELECT id, title, text, source, char_count, sentence_count,
                      entity_count, relation_count, entity_types, entities_json,
                      elapsed_ms, created_at, tags
               FROM records ORDER BY id"""
        ).fetchall()]
        relations = [dict(r) for r in conn.execute(
            "SELECT * FROM relations ORDER BY record_id, id"
        ).fetchall()]
        terms = [dict(r) for r in conn.execute(
            "SELECT text, type FROM custom_terms ORDER BY id"
        ).fetchall()]
        rules = [dict(r) for r in conn.execute(
            "SELECT relation_key, trigger FROM custom_rules ORDER BY id"
        ).fetchall()]
        versions = [dict(r) for r in conn.execute(
            "SELECT name, created_at, rules_json, terms_json FROM rule_versions ORDER BY id"
        ).fetchall()]
        eval_runs = [dict(r) for r in conn.execute(
            "SELECT created_at, cases, tp, fp, fn, precision, recall, f1, macro_f1 "
            "FROM eval_runs ORDER BY id"
        ).fetchall()]

    gold = []
    try:
        from pathlib import Path
        gold_path = Path(__file__).resolve().parent.parent / "eval" / "gold.json"
        gold = json.loads(gold_path.read_text(encoding="utf-8")).get("cases", [])
    except (OSError, ValueError):
        pass

    return {
        "format": "cn-re-project",
        "version": 1,
        "exported_at": _now(),
        "records": records,
        "relations": relations,
        "custom_terms": terms,
        "custom_rules": rules,
        "rule_versions": versions,
        "eval_runs": eval_runs,
        "gold": gold,
    }


def import_project(payload: dict, mode: str = "merge") -> dict[str, Any]:
    records = payload.get("records") or []
    relations = payload.get("relations") or []
    if not isinstance(records, list) or not isinstance(relations, list):
        raise ValueError("项目包缺少 records / relations 列表")
    if not records:
        raise ValueError("项目包里没有任何记录")
    if len(records) > 5000 or len(relations) > 200000:
        raise ValueError("项目包过大，拒绝导入")

    from .nlp.entity import canonical_name

    with db.connect() as conn:
        if mode == "replace":
            conn.execute("DELETE FROM relations")
            conn.execute("DELETE FROM records")
            conn.execute("DELETE FROM custom_terms")
            conn.execute("DELETE FROM custom_rules")

        id_map: dict[int, int] = {}
        for rec in records:
            cur = conn.execute(
                """INSERT INTO records (title, text, source, char_count,
                       sentence_count, entity_count, relation_count, entity_types,
                       entities_json, elapsed_ms, created_at, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(rec.get("title", ""))[:200], str(rec.get("text", "")),
                    str(rec.get("source", "text"))[:40],
                    int(rec.get("char_count", 0)), int(rec.get("sentence_count", 0)),
                    int(rec.get("entity_count", 0)), int(rec.get("relation_count", 0)),
                    str(rec.get("entity_types", "{}")), str(rec.get("entities_json", "[]")),
                    float(rec.get("elapsed_ms", 0)), str(rec.get("created_at", _now())),
                    str(rec.get("tags", "")),
                ),
            )
            id_map[int(rec.get("id", 0))] = int(cur.lastrowid)

        inserted = 0
        for rel in relations:
            new_id = id_map.get(int(rel.get("record_id", 0)))
            if not new_id:
                continue
            head = str(rel.get("head", ""))
            tail = str(rel.get("tail", ""))
            head_type = str(rel.get("head_type", "ORG"))
            tail_type = str(rel.get("tail_type", "ORG"))
            conn.execute(
                """INSERT INTO relations (record_id, head, head_canonical, head_type,
                       relation, relation_label, tail, tail_canonical, tail_type,
                       confidence, evidence, trigger, sentence_index, rule_base)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id, head, str(rel.get("head_canonical") or canonical_name(head, head_type)),
                    head_type, str(rel.get("relation", "")), str(rel.get("relation_label", "")),
                    tail, str(rel.get("tail_canonical") or canonical_name(tail, tail_type)),
                    tail_type, float(rel.get("confidence", 0)), str(rel.get("evidence", "")),
                    str(rel.get("trigger", "")), int(rel.get("sentence_index", 0)),
                    str(rel.get("rule_base", "trigger")),
                ),
            )
            inserted += 1

        for term in payload.get("custom_terms") or []:
            conn.execute(
                "INSERT OR IGNORE INTO custom_terms (text, type, created_at) VALUES (?, ?, ?)",
                (str(term.get("text", ""))[:64], str(term.get("type", "ORG"))[:20], _now()),
            )
        for rule in payload.get("custom_rules") or []:
            conn.execute(
                "INSERT OR IGNORE INTO custom_rules (relation_key, trigger, created_at) VALUES (?, ?, ?)",
                (str(rule.get("relation_key", ""))[:40], str(rule.get("trigger", ""))[:24], _now()),
            )
        for ver in payload.get("rule_versions") or []:
            conn.execute(
                """INSERT INTO rule_versions (name, created_at, rules_json, terms_json)
                   VALUES (?, ?, ?, ?)""",
                (str(ver.get("name", ""))[:60], str(ver.get("created_at", _now())),
                 str(ver.get("rules_json", "[]")), str(ver.get("terms_json", "[]"))),
            )
        _ = payload.get("eval_runs") or []
        # 导入后按库内真值重算计数，不信任包里携带的汇总数字
        db._rebuild_counters(conn)
        db._invalidate_overview()
        if db.fts_enabled():
            try:
                conn.execute("INSERT INTO records_fts(records_fts) VALUES('rebuild')")
            except Exception:
                pass

    return {
        "mode": mode, "records": len(records), "relations": inserted,
        "custom_terms": len(payload.get("custom_terms") or []),
        "custom_rules": len(payload.get("custom_rules") or []),
        "id_map": {str(k): v for k, v in id_map.items()},
    }
