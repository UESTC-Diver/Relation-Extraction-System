# -*- coding: utf-8 -*-
"""案卷层：把「一篇文本的一次抽取」组织成一份可交代来源的尽调档案。

为什么要有这一层
----------------
单篇抽取回答的是「这句话里有什么」，尽调要回答的是另外三个问题：
这份标的最值得追的关联是什么、每条结论出自哪份材料的哪一句、
哪些结论根本不是原文写的而是推出来的。

所以案卷层只做三件事，一件事都不多做：

1. **归档**：把已有记录按材料角色归进一个案卷。不复制材料内容——同一份
   记录被多个案卷引用时，抽取结果、人工校正、复核结论始终只有一份。
2. **归并**：同一组头尾关系在多份材料里重复出现时合成一条结论，出处全部
   保留。尽调里「三份材料都这么说」和「只有一份这么说」是完全不同的分量。
3. **推断**：只拿已抽出的三元组做图运算，得出间接关联。

推断关系的三条硬约束
--------------------
- **永不入库**：推断结果每次读案卷时按当前材料重算，不写 relations 表。
  因此它天然不进三元组列表、不进评测集、不影响 P/R/F1，也不需要人工清理。
- **必须带推导链**：每条推断都要能逐步指回具体材料的具体句子；指不回去的
  推断一律不生成。
- **必须自我降级**：推断按强度分级（strong / weak），并附一句人话说明它
  不是原文写的。宁可弱，不可冒充直接结论。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from . import db
from .nlp.entity import canonical_name

# 材料角色：决定案卷视图里的分组与报告小标题，不改变抽取结果本身。
MATERIAL_ROLES: list[str] = [
    "工商登记",
    "股权结构",
    "股权转让",
    "裁判文书",
    "定期报告",
    "公告",
    "新闻稿",
    "合作协议",
    "访谈记录",
    "其他材料",
]

# 权益/控制链：强关系用于判定「间接控制」，弱关系单独成「间接投资」。
_STRONG_EQUITY = {"control", "acquire", "subsidiary", "belong"}
_WEAK_EQUITY = {"invest"}
# 权益族内部才是互斥的：同一对实体不可能既被收购又是收购方。合作与诉讼
# 同属「关系」，但两者并存是真实常态，不能当矛盾报。
_EQUITY_FAMILY = {"acquire", "control", "subsidiary", "belong", "invest"}
# 头尾方向相反的关系：subsidiary 约定为「子公司 → 母公司」，belong 为「下属 → 上级」，
# 归一成「上级 → 下属」时必须反过来，否则整条推导链方向就是错的。
_REVERSED_EQUITY = {"subsidiary", "belong"}

_MAX_DIRECT = 500
_MAX_INFERRED = 200

# 同址推断的收紧条件：只认具体到路/街/大厦/园区/门牌的地点。
# 「总部位于北京」这种省市级别一旦拿来配对，全城公司都会被推成关联方，
# 那不是线索，是噪声。
_ADDRESS_HINTS = ("路", "街", "道", "大厦", "园区", "广场", "号楼", "号", "镇", "港区")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _clean(value: Any, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


# --------------------------------------------------------------------------- #
# 案卷增删改查
# --------------------------------------------------------------------------- #


def _row(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "subject": row["subject"],
        "subject_type": row["subject_type"],
        "note": row["note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_dossiers() -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT d.*, COUNT(dr.record_id) AS material_count
               FROM dossiers d
               LEFT JOIN dossier_records dr ON dr.dossier_id = d.id
               GROUP BY d.id ORDER BY d.id DESC"""
        ).fetchall()
    out = []
    for row in rows:
        item = _row(row)
        item["material_count"] = int(row["material_count"] or 0)
        out.append(item)
    return out


def get_dossier_row(dossier_id: int) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM dossiers WHERE id = ?", (dossier_id,)).fetchone()
    return _row(row) if row else None


def create_dossier(name: str, subject: str = "", subject_type: str = "ORG", note: str = "") -> dict[str, Any]:
    name = _clean(name, 80) or "未命名案卷"
    now = _now()
    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO dossiers (name, subject, subject_type, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, _clean(subject, 64), _clean(subject_type, 16) or "ORG", _clean(note, 400), now, now),
        )
        dossier_id = int(cur.lastrowid)
    return get_dossier_row(dossier_id) or {}


def update_dossier(dossier_id: int, **fields: Any) -> dict[str, Any] | None:
    allowed = {"name", "subject", "subject_type", "note"}
    pairs = [(k, v) for k, v in fields.items() if k in allowed and v is not None]
    if not pairs:
        return get_dossier_row(dossier_id)
    sets = ", ".join(f"{k} = ?" for k, _ in pairs)
    values = [_clean(v, 400) for _, v in pairs]
    with db.connect() as conn:
        cur = conn.execute(
            f"UPDATE dossiers SET {sets}, updated_at = ? WHERE id = ?",
            [*values, _now(), dossier_id],
        )
    return get_dossier_row(dossier_id) if cur.rowcount > 0 else None


def delete_dossier(dossier_id: int) -> bool:
    with db.connect() as conn:
        conn.execute("DELETE FROM dossier_records WHERE dossier_id = ?", (dossier_id,))
        cur = conn.execute("DELETE FROM dossiers WHERE id = ?", (dossier_id,))
    return cur.rowcount > 0


def add_materials(dossier_id: int, record_ids: Iterable[int], role: str = "其他材料") -> dict[str, Any]:
    """把记录归档进案卷；已在案卷里的材料只更新角色，不重复插入。"""
    role = _clean(role, 24) or "其他材料"
    ids: list[int] = []
    for raw in record_ids:
        try:
            rid = int(raw)
        except (TypeError, ValueError):
            continue
        if rid > 0 and rid not in ids:
            ids.append(rid)
    if not ids:
        return {"added": 0, "updated": 0, "missing": [], "materials": []}

    marks = ",".join("?" for _ in ids)
    now = _now()
    with db.connect() as conn:
        existing = {int(r["id"]) for r in conn.execute(f"SELECT id FROM records WHERE id IN ({marks})", ids).fetchall()}
        current = {
            int(r["record_id"])
            for r in conn.execute(
                f"SELECT record_id FROM dossier_records WHERE dossier_id = ? AND record_id IN ({marks})",
                [dossier_id, *ids],
            ).fetchall()
        }
        added, updated = [], []
        for rid in ids:
            if rid not in existing:
                continue
            if rid in current:
                updated.append(rid)
            else:
                added.append(rid)
        conn.executemany(
            """INSERT INTO dossier_records (dossier_id, record_id, role, added_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(dossier_id, record_id) DO UPDATE SET role = excluded.role""",
            [(dossier_id, rid, role, now) for rid in [*added, *updated]],
        )
        if added or updated:
            conn.execute("UPDATE dossiers SET updated_at = ? WHERE id = ?", (now, dossier_id))
        materials = [
            dict(r)
            for r in conn.execute(
                """SELECT dr.record_id, dr.role, dr.added_at, rec.title,
                          rec.relation_count, rec.created_at
                   FROM dossier_records dr JOIN records rec ON rec.id = dr.record_id
                   WHERE dr.dossier_id = ? ORDER BY dr.added_at, dr.record_id""",
                (dossier_id,),
            ).fetchall()
        ]
    return {
        "added": len(added),
        "updated": len(updated),
        "missing": [rid for rid in ids if rid not in existing],
        "materials": materials,
    }


def remove_material(dossier_id: int, record_id: int) -> bool:
    with db.connect() as conn:
        cur = conn.execute(
            "DELETE FROM dossier_records WHERE dossier_id = ? AND record_id = ?",
            (dossier_id, record_id),
        )
        if cur.rowcount > 0:
            conn.execute("UPDATE dossiers SET updated_at = ? WHERE id = ?", (_now(), dossier_id))
    return cur.rowcount > 0


def materials(dossier_id: int) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT dr.record_id, dr.role, dr.added_at, rec.title,
                      rec.relation_count, rec.entity_count, rec.created_at,
                      rec.char_count, rec.source
               FROM dossier_records dr JOIN records rec ON rec.id = dr.record_id
               WHERE dr.dossier_id = ? ORDER BY dr.added_at, dr.record_id""",
            (dossier_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# 直接结论：查关系并按「同一组头尾关系」归并
# --------------------------------------------------------------------------- #


def _direct_rows(dossier_id: int) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT r.record_id, r.head, r.head_canonical, r.head_type,
                      r.relation, r.relation_label, r.tail, r.tail_canonical,
                      r.tail_type, r.confidence, r.evidence, r.sentence_index,
                      r.rule_base, rec.title AS doc_title, dr.role AS material_role
               FROM relations r
               JOIN dossier_records dr
                 ON dr.record_id = r.record_id AND dr.dossier_id = ?
               JOIN records rec ON rec.id = r.record_id
               ORDER BY r.record_id, r.sentence_index, r.id""",
            (dossier_id,),
        ).fetchall()
    out = []
    for r in rows:
        head_norm = r["head_canonical"] or r["head"]
        tail_norm = r["tail_canonical"] or r["tail"]
        out.append(
            {
                "head": r["head"],
                "head_norm": head_norm,
                "head_type": r["head_type"],
                "relation": r["relation"],
                "relation_label": r["relation_label"],
                "tail": r["tail"],
                "tail_norm": tail_norm,
                "tail_type": r["tail_type"],
                "confidence": round(float(r["confidence"] or 0), 2),
                "evidence": r["evidence"],
                "sentence_index": int(r["sentence_index"] or 0),
                "rule_base": r["rule_base"] or "trigger",
                "record_id": r["record_id"],
                "doc_title": r["doc_title"],
                "material_role": r["material_role"],
            }
        )
    return out


def _merge_direct(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一组 (头, 关系, 尾) 在多份材料或同一材料的多个句子里出现时合成一条。

    出处一条都不丢：sources 里保留每条命中材料、角色、原句与句子序号，
    support_count 就是「这件事有几处原文在说」。尽调里这个数字比置信度更硬。
    """
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in rows:
        key = (r["head_norm"], r["relation"], r["tail_norm"])
        item = grouped.get(key)
        if item is None:
            item = grouped[key] = {
                "head": r["head"],
                "head_norm": r["head_norm"],
                "head_type": r["head_type"],
                "relation": r["relation"],
                "relation_label": r["relation_label"],
                "tail": r["tail"],
                "tail_norm": r["tail_norm"],
                "tail_type": r["tail_type"],
                "confidence": r["confidence"],
                "sources": [],
            }
        item["confidence"] = max(item["confidence"], r["confidence"])
        item["sources"].append(
            {
                "record_id": r["record_id"],
                "doc_title": r["doc_title"],
                "role": r["material_role"],
                "evidence": r["evidence"],
                "sentence_index": r["sentence_index"],
                "confidence": r["confidence"],
                "head": r["head"],
                "tail": r["tail"],
                "rule_base": r["rule_base"],
            }
        )
    merged = list(grouped.values())
    for item in merged:
        item["support_count"] = len({s["record_id"] for s in item["sources"]})
        item["evidence_count"] = len(item["sources"])
        item["evidence"] = item["sources"][0]["evidence"]
        item["docs"] = sorted({s["doc_title"] for s in item["sources"]})
    merged.sort(key=lambda x: (-x["support_count"], -x["confidence"], x["head_type"]))
    return merged[:_MAX_DIRECT]


# --------------------------------------------------------------------------- #
# 间接推断：只用已抽三元组做图运算
# --------------------------------------------------------------------------- #


def _equity_edges(direct: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把控制/权益类结论归一成统一的「上级 → 下级」方向。

    返回的每一条边的 source 都指向原始出处，供推导链逐步回溯。
    """
    edges = []
    for d in direct:
        key = d["relation"]
        if key in _STRONG_EQUITY or key in _WEAK_EQUITY:
            parent, child = d["head_norm"], d["tail_norm"]
            if key in _REVERSED_EQUITY:
                # subsidiary / belong 约定为「下级 → 上级」，归一成「上级 → 下级」
                parent, child = child, parent
                parent_name, child_name = d["tail"], d["head"]
                parent_type, child_type = d["tail_type"], d["head_type"]
            else:
                parent_name, child_name = d["head"], d["tail"]
                parent_type, child_type = d["head_type"], d["tail_type"]
            if parent == child:
                continue
            edges.append(
                {
                    "parent": parent,
                    "child": child,
                    "parent_name": parent_name,
                    "child_name": child_name,
                    "parent_type": parent_type,
                    "child_type": child_type,
                    "relation": key,
                    "relation_label": d["relation_label"],
                    "strength": "strong" if key in _STRONG_EQUITY else "weak",
                    "source": d,
                }
            )
    return edges


def _step(d: dict[str, Any]) -> dict[str, Any]:
    """推导链的一步：结论文字 + 可点回去的材料与句子。

    归并后的结论可能有多处出处，这里取第一处作为这条推导链的锚点，
    其余出处仍在 direct 的 sources 里可查。
    """
    src = d["sources"][0]
    return {
        "head": d["head"],
        "relation": d["relation"],
        "relation_label": d["relation_label"],
        "tail": d["tail"],
        "doc_title": src["doc_title"],
        "role": src["role"],
        "record_id": src["record_id"],
        "evidence": d["evidence"],
        "sentence_index": src["sentence_index"],
        "confidence": d["confidence"],
    }


def _infer(direct: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从直接结论推间接关联。四类规则，全部确定性、可逐步回溯。"""
    inferred: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def push(item: dict[str, Any]) -> None:
        key = (item["kind"], item["head"], item["tail"])
        if key in seen or item["head"] == item["tail"]:
            return
        seen.add(key)
        item["id"] = f"inf{len(inferred) + 1}"
        item["inferred"] = True
        # 结构保证：这一项没有任何一条原文直接支持它
        item["not_in_relations"] = True
        inferred.append(item)

    # --- 1. 控制链穿透：A → B → C ---------------------------------------- #
    edges = _equity_edges(direct)
    direct_pairs = {(d["head_norm"], d["tail_norm"]) for d in direct}
    for e1 in edges:
        for e2 in edges:
            if e1["child"] != e2["parent"] or e1["parent"] == e2["child"]:
                continue
            # 已经有直接结论的，不重复生成推断
            if (e1["parent"], e2["child"]) in direct_pairs:
                continue
            strong = e1["strength"] == "strong" and e2["strength"] == "strong"
            conf = round(min(e1["source"]["confidence"], e2["source"]["confidence"]) * (0.8 if strong else 0.55), 2)
            push(
                {
                    "kind": "control_chain",
                    "kind_label": "控制链穿透",
                    "strength": "strong" if strong else "weak",
                    "label": "间接控制" if strong else "间接权益",
                    "head": e1["parent_name"],
                    "head_type": e1["parent_type"],
                    "tail": e2["child_name"],
                    "tail_type": e2["child_type"],
                    "confidence": conf,
                    "basis": (
                        f"{e1['parent_name']} 经 {e1['child_name']} 连到 {e2['child_name']}"
                        f"（{e1['relation_label']} → {e2['relation_label']}）"
                    ),
                    "caveat": (
                        "两跳推断，原文没有任何一句说这两家有直接关系；"
                        "间接控制不等于实际控制，需核对持股比例与协议条款。"
                    ),
                    "path": [_step(e1["source"]), _step(e2["source"])],
                }
            )

    # --- 2. 同一自然人连接两家机构 --------------------------------------- #
    by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in direct:
        if d["relation"] == "employ" and d["head_type"] == "PERSON":
            by_person[d["head_norm"]].append(d)
    for person, rows in by_person.items():
        orgs = {r["tail_norm"]: r for r in rows}
        if len(orgs) < 2:
            continue
        names = list(orgs)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = orgs[names[i]], orgs[names[j]]
                push(
                    {
                        "kind": "common_person",
                        "kind_label": "同一人任职",
                        "strength": "weak",
                        "label": "人事关联",
                        "head": a["tail"],
                        "head_type": a["tail_type"],
                        "tail": b["tail"],
                        "tail_type": b["tail_type"],
                        "confidence": round(min(a["confidence"], b["confidence"]) * 0.7, 2),
                        "basis": f"{person} 同时在两家机构任职",
                        "caveat": "同一人任职只说明人事交集，不构成股权或控制关系。",
                        "path": [_step(a), _step(b)],
                    }
                )

    # --- 3. 同一创始人 --------------------------------------------------- #
    by_founder: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in direct:
        if d["relation"] == "found" and d["head_type"] == "PERSON":
            by_founder[d["head_norm"]].append(d)
    for person, rows in by_founder.items():
        orgs = {r["tail_norm"]: r for r in rows}
        if len(orgs) < 2:
            continue
        names = list(orgs)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = orgs[names[i]], orgs[names[j]]
                push(
                    {
                        "kind": "common_founder",
                        "kind_label": "同一创始人",
                        "strength": "weak",
                        "label": "同源关联",
                        "head": a["tail"],
                        "head_type": a["tail_type"],
                        "tail": b["tail"],
                        "tail_type": b["tail_type"],
                        "confidence": round(min(a["confidence"], b["confidence"]) * 0.7, 2),
                        "basis": f"{person} 是两家机构的创始人",
                        "caveat": "同一创始人早年可能已退出，需核对当前股东与任职。",
                        "path": [_step(a), _step(b)],
                    }
                )

    # --- 4. 同一具体地址 ------------------------------------------------- #
    by_place: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in direct:
        if d["relation"] != "headquarter":
            continue
        place = d["tail_norm"]
        if len(place) >= 5 and any(hint in place for hint in _ADDRESS_HINTS):
            by_place[place].append(d)
    for place, rows in by_place.items():
        orgs = {r["head_norm"]: r for r in rows}
        if len(orgs) < 2:
            continue
        names = list(orgs)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = orgs[names[i]], orgs[names[j]]
                push(
                    {
                        "kind": "same_address",
                        "kind_label": "同址关联",
                        "strength": "weak",
                        "label": "同址",
                        "head": a["head"],
                        "head_type": a["head_type"],
                        "tail": b["head"],
                        "tail_type": b["head_type"],
                        "confidence": round(min(a["confidence"], b["confidence"]) * 0.5, 2),
                        "basis": f"两家机构的总部都记为「{place}」",
                        "caveat": "同址可能只是共用写字楼或注册地址挂靠，关联强度弱，不构成控制关系。",
                        "path": [_step(a), _step(b)],
                    }
                )

    inferred.sort(key=lambda x: (x["strength"] != "strong", -x["confidence"]))
    return inferred[:_MAX_INFERRED]


# --------------------------------------------------------------------------- #
# 疑点：把「这份案卷还不扎实的地方」直接摆出来
# --------------------------------------------------------------------------- #


def _ambiguities(
    direct: list[dict[str, Any]],
    mats: list[dict[str, Any]],
    subject: str,
    subject_type: str = "ORG",
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    # 标的用原文填写（「星海智能科技有限公司」），关系里存的是归一化名
    # （「星海智能科技」）；不归一化就永远匹配不上，孤儿材料会全量误报。
    subject_key = canonical_name(subject, subject_type) if subject else ""

    # 同一对实体被不同材料判成互斥的权益关系：这是必须裁掉的矛盾。
    # 只查权益族内部：19 类关系里绝大多数并不互斥，「既合作又打官司」
    # 是真实常态，把它报成「说法不一致」只会让疑点清单失去可信度。
    pair_rows: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for d in direct:
        pair_rows[tuple(sorted((d["head_norm"], d["tail_norm"])))].append(d)

    for rows in pair_rows.values():
        rels = {r["relation"] for r in rows}
        names = sorted({r["head"] for r in rows} | {r["tail"] for r in rows})
        docs = sorted({s["doc_title"] for r in rows for s in r["sources"]})
        show = rows[0]

        equity = rels & _EQUITY_FAMILY
        if len(equity) >= 2:
            items.append(
                {
                    "type": "conflict",
                    "level": "high",
                    "title": f"{show['head']} 与 {show['tail']} 的权益关系在不同材料里互相矛盾",
                    "detail": "涉及："
                    + " / ".join(sorted({r["relation_label"] for r in rows if r["relation"] in equity})),
                    "docs": docs,
                }
            )

        # 对抗与业务同时成立：不是矛盾，但是尽调最该追的信号
        if "sue" in rels and rels & {"cooperate", "sign", "supply"}:
            items.append(
                {
                    "type": "tension",
                    "level": "high",
                    "title": f"{show['head']} 与 {show['tail']} 同时存在诉讼与业务往来",
                    "detail": "争议与合作并行，需核对时间顺序：诉讼是否发生在合作之后，是否影响履约。",
                    "docs": docs,
                }
            )
        _ = names

    # 单一来源：只有一份材料支撑，且置信度不高 —— 这类结论不能当定论
    for d in direct:
        if d["support_count"] == 1 and d["confidence"] < 0.85:
            items.append(
                {
                    "type": "single_source",
                    "level": "medium",
                    "title": f"{d['head']} — {d['relation_label']} — {d['tail']} 只有一份材料支撑",
                    "detail": f"置信度 {d['confidence']}，出处：{d['docs'][0] if d['docs'] else '—'}",
                    "docs": d["docs"],
                }
            )

    # 材料与标的脱节：归档了却什么都没连上，要么抽错了，要么这份材料没用
    if subject_key:
        linked = {
            s["record_id"] for d in direct if subject_key in (d["head_norm"], d["tail_norm"]) for s in d["sources"]
        }
        for m in mats:
            if m["record_id"] not in linked:
                items.append(
                    {
                        "type": "orphan_material",
                        "level": "medium",
                        "title": f"《{m['title']}》没有连到标的「{subject}」",
                        "detail": f"角色：{m['role']}。可能这份材料与标的无关，也可能抽取时漏了实体。",
                        "docs": [m["title"]],
                    }
                )

    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: (order.get(x["level"], 3), x["type"]))
    return items[:60]


# --------------------------------------------------------------------------- #
# 案卷视图
# --------------------------------------------------------------------------- #


def _guess_subject(direct: list[dict[str, Any]], mats: list[dict[str, Any]]) -> str:
    """没填标的时，取材料关系里出现次数最多的机构名当候选，并标注是猜的。"""
    counter: dict[str, int] = defaultdict(int)
    for d in direct:
        for name, typ in ((d["head"], d["head_type"]), (d["tail"], d["tail_type"])):
            if typ == "ORG":
                counter[name] += 1
    if not counter:
        return ""
    return max(counter.items(), key=lambda kv: kv[1])[0]


def build_view(dossier_id: int) -> dict[str, Any] | None:
    """案卷详情：材料、归并后的直接结论、推断结论、疑点与图数据。

    推断部分每次现算，绝不落库 —— 材料一变，推断自动跟着变，也不会
    污染三元组表与评测集。
    """
    row = get_dossier_row(dossier_id)
    if not row:
        return None
    mats = materials(dossier_id)
    rows = _direct_rows(dossier_id)
    direct = _merge_direct(rows)

    subject = row["subject"].strip()
    subject_auto = False
    if not subject:
        subject = _guess_subject(direct, mats)
        subject_auto = bool(subject)

    inferred = _infer(direct)
    ambiguities = _ambiguities(direct, mats, subject, row["subject_type"] or "ORG")

    nodes: dict[str, dict[str, Any]] = {}
    for d in direct:
        for name, typ in ((d["head"], d["head_type"]), (d["tail"], d["tail_type"])):
            node = nodes.setdefault(name, {"id": name, "name": name, "type": typ, "count": 0})
            node["count"] += 1
    for item in inferred:
        for name, typ in ((item["head"], item["head_type"]), (item["tail"], item["tail_type"])):
            nodes.setdefault(name, {"id": name, "name": name, "type": typ, "count": 0})

    by_role: dict[str, int] = defaultdict(int)
    for m in mats:
        by_role[m["role"]] += 1

    return {
        **row,
        "subject_effective": subject,
        "subject_auto": subject_auto,
        "materials": mats,
        "roles": [{"role": k, "count": v} for k, v in sorted(by_role.items(), key=lambda kv: -kv[1])],
        "direct": direct,
        "inferred": inferred,
        "ambiguities": ambiguities,
        "summary": {
            "materials": len(mats),
            "documents_with_relations": len({d["sources"][0]["record_id"] for d in direct}),
            "relations_raw": len(rows),
            "relations_merged": len(direct),
            "inferred": len(inferred),
            "inferred_strong": sum(1 for i in inferred if i["strength"] == "strong"),
            "entities": len(nodes),
            "ambiguities": len(ambiguities),
            "conflicts": sum(1 for a in ambiguities if a["type"] == "conflict"),
            "tensions": sum(1 for a in ambiguities if a["type"] == "tension"),
        },
        "graph": {
            "nodes": sorted(nodes.values(), key=lambda n: -n["count"]),
            "direct_edges": [
                {
                    "source": d["head"],
                    "target": d["tail"],
                    "label": d["relation_label"],
                    "relation": d["relation"],
                    "kind": "direct",
                    "weight": d["support_count"],
                }
                for d in direct
            ],
            "inferred_edges": [
                {
                    "source": i["head"],
                    "target": i["tail"],
                    "label": i["label"],
                    "relation": i["kind"],
                    "kind": "inferred",
                    "strength": i["strength"],
                }
                for i in inferred
            ],
        },
    }
