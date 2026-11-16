# -*- coding: utf-8 -*-
"""2.1.0 回归测试：案卷层与间接推断。

守两条线，两条都是产品承诺而不是实现细节：

1. **推断永不入库**：案卷视图里的推断关系不能出现在 relations 表、
   记录详情或评测输入里。这不是靠调用方自觉，而是靠「只在读视图时现算」
   这个结构保证；一旦有人把推断写进表，下面的用例就会红。
2. **推断必须自我降级**：控制链方向不能反（subsidiary 约定为子公司→母公司），
   同址推断不能凭「总部位于北京」这种省市级别把全城公司连成一片。
"""

from __future__ import annotations

from app.nlp.lexicon import RELATION_MAP

TEXT = "占位原文用于构造记录，不参与断言。"


def _rel(
    head: str,
    key: str,
    tail: str,
    head_type: str = "ORG",
    tail_type: str = "ORG",
    conf: float = 0.9,
    evidence: str = "原句",
    idx: int = 0,
) -> dict:
    return {
        "head": head,
        "head_type": head_type,
        "relation": key,
        "relation_label": RELATION_MAP[key].label,
        "tail": tail,
        "tail_type": tail_type,
        "confidence": conf,
        "evidence": evidence,
        "trigger": "",
        "sentence_index": idx,
        "rule_base": "trigger",
    }


def _record(relations: list[dict], title: str) -> int:
    from app import db

    result = {
        "text": TEXT,
        "relations": relations,
        "entities": [],
        "stats": {
            "char_count": len(TEXT),
            "sentence_count": 1,
            "entity_count": 0,
            "elapsed_ms": 1.0,
        },
        "entity_type_counts": {},
    }
    return db.save_record(result, source="test", title=title)


def _dossier(client, name: str = "甲案卷", subject: str = "星河智能科技有限公司") -> dict:
    res = client.post("/api/dossiers", json={"name": name, "subject": subject, "subject_type": "ORG"})
    assert res.status_code == 200, res.text
    return res.json()


def _attach(client, dossier_id: int, record_ids: list[int], role: str = "工商登记") -> dict:
    res = client.post(
        f"/api/dossiers/{dossier_id}/records",
        json={"record_ids": record_ids, "role": role},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _view(client, dossier_id: int) -> dict:
    res = client.get(f"/api/dossiers/{dossier_id}")
    assert res.status_code == 200, res.text
    return res.json()


# --------------------------------------------------------------------------- #
# 增删改查与材料归档
# --------------------------------------------------------------------------- #


def test_dossier_crud(client):
    row = _dossier(client, "并购尽调", "星河智能科技有限公司")
    assert row["id"] > 0

    listed = client.get("/api/dossiers").json()
    assert listed["total"] == 1
    assert listed["items"][0]["material_count"] == 0
    assert "工商登记" in listed["roles"]

    updated = client.put(f"/api/dossiers/{row['id']}", json={"name": "并购尽调（二版）"}).json()
    assert updated["name"] == "并购尽调（二版）"

    assert client.delete(f"/api/dossiers/{row['id']}").status_code == 200
    assert client.get(f"/api/dossiers/{row['id']}").status_code == 404
    assert client.get("/api/dossiers").json()["total"] == 0


def test_material_attach_is_idempotent_and_checks_existence(client):
    rid = _record([_rel("星河智能科技有限公司", "control", "云图数据有限公司")], "股权结构")
    row = _dossier(client)

    first = _attach(client, row["id"], [rid])
    assert first["added"] == 1

    again = _attach(client, row["id"], [rid], role="公告")
    assert again["added"] == 0 and again["updated"] == 1
    view = _view(client, row["id"])
    assert view["summary"]["materials"] == 1
    assert view["materials"][0]["role"] == "公告"

    missing = client.post(f"/api/dossiers/{row['id']}/records", json={"record_ids": [99999], "role": "公告"})
    assert missing.status_code == 404


def test_materials_are_shared_not_copied(client):
    """同一份记录被两个案卷引用时，改正三元组两边同步看到。"""
    rid = _record([_rel("星河智能科技有限公司", "control", "云图数据有限公司")], "股权结构")
    a = _dossier(client, "A 卷")
    b = _dossier(client, "B 卷")
    _attach(client, a["id"], [rid])
    _attach(client, b["id"], [rid])

    from app import db

    db.replace_relations(rid, [_rel("星河智能科技有限公司", "acquire", "云图数据有限公司")])
    for dossier_id in (a["id"], b["id"]):
        view = _view(client, dossier_id)
        assert view["direct"][0]["relation"] == "acquire"


def test_direct_relations_merge_across_materials(client):
    """同一组头尾关系出现在两份材料里，合成一条并记下支撑份数。"""
    r1 = _record([_rel("星河智能科技有限公司", "control", "云图数据有限公司", conf=0.8)], "股权结构")
    r2 = _record([_rel("星河智能科技有限公司", "control", "云图数据有限公司", conf=0.9)], "定期报告")
    row = _dossier(client)
    _attach(client, row["id"], [r1, r2])

    view = _view(client, row["id"])
    assert view["summary"]["relations_raw"] == 2
    assert view["summary"]["relations_merged"] == 1
    item = view["direct"][0]
    assert item["support_count"] == 2
    assert item["evidence_count"] == 2
    assert item["confidence"] == 0.9
    assert len(item["sources"]) == 2


def test_remove_material_keeps_record(client):
    rid = _record([_rel("星河智能科技有限公司", "control", "云图数据有限公司")], "股权结构")
    row = _dossier(client)
    _attach(client, row["id"], [rid])
    assert client.delete(f"/api/dossiers/{row['id']}/records/{rid}").status_code == 200
    assert _view(client, row["id"])["summary"]["materials"] == 0
    assert client.get(f"/api/records/{rid}").status_code == 200


# --------------------------------------------------------------------------- #
# 推断：结构与方向
# --------------------------------------------------------------------------- #


def test_inferred_never_written_to_relations(client):
    """推断只活在视图里：调用前后 relations 表行数不变，记录详情也看不到。"""
    from app import db

    rid = _record(
        [
            _rel("星河控股集团有限公司", "control", "星河智能科技有限公司"),
            _rel("星河智能科技有限公司", "control", "云图数据有限公司"),
        ],
        "股权结构",
    )
    row = _dossier(client)
    _attach(client, row["id"], [rid])

    before = client.get("/api/stats").json()["relations"]
    view = _view(client, row["id"])
    after = client.get("/api/stats").json()["relations"]
    assert before == after == 2

    assert view["summary"]["inferred"] == 1
    inferred = view["inferred"][0]
    assert inferred["not_in_relations"] is True
    assert inferred["kind"] == "control_chain"
    assert inferred["head"] == "星河控股集团有限公司"
    assert inferred["tail"] == "云图数据有限公司"

    record = db.get_record(rid)
    pairs = {(r["head"], r["relation"], r["tail"]) for r in record["relations"]}
    assert ("星河控股集团有限公司", "control", "云图数据有限公司") not in pairs
    assert len(record["relations"]) == 2


def test_inferred_is_stable_across_reads(client):
    rid = _record(
        [
            _rel("星河控股集团有限公司", "control", "星河智能科技有限公司"),
            _rel("星河智能科技有限公司", "control", "云图数据有限公司"),
        ],
        "股权结构",
    )
    row = _dossier(client)
    _attach(client, row["id"], [rid])
    first = _view(client, row["id"])["inferred"]
    second = _view(client, row["id"])["inferred"]
    assert first == second
    assert len(first) == 1


def test_subsidiary_direction_is_reversed(client):
    """subsidiary 约定为「子公司 → 母公司」，归一后父在上，链才不会倒着走。"""
    rid = _record(
        [
            _rel("星河智能科技有限公司", "subsidiary", "星河控股集团有限公司"),
            _rel("云图数据有限公司", "subsidiary", "星河智能科技有限公司"),
        ],
        "股权结构",
    )
    row = _dossier(client)
    _attach(client, row["id"], [rid])

    view = _view(client, row["id"])
    chains = [i for i in view["inferred"] if i["kind"] == "control_chain"]
    assert len(chains) == 1
    assert chains[0]["head"] == "星河控股集团有限公司"
    assert chains[0]["tail"] == "云图数据有限公司"
    assert len(chains[0]["path"]) == 2


def test_direct_pair_is_not_reported_as_inferred(client):
    """已经有直接结论的两家，不再生成一条同向推断。"""
    rid = _record(
        [
            _rel("星河控股集团有限公司", "control", "星河智能科技有限公司"),
            _rel("星河智能科技有限公司", "control", "云图数据有限公司"),
            _rel("星河控股集团有限公司", "control", "云图数据有限公司"),
        ],
        "股权结构",
    )
    row = _dossier(client)
    _attach(client, row["id"], [rid])
    view = _view(client, row["id"])
    assert not [i for i in view["inferred"] if i["kind"] == "control_chain"]


def test_common_person_and_founder(client):
    rid = _record(
        [
            _rel("周敏", "employ", "星河智能科技有限公司", "PERSON", "ORG"),
            _rel("周敏", "employ", "云图数据有限公司", "PERSON", "ORG"),
            _rel("李承宇", "found", "星河智能科技有限公司", "PERSON", "ORG"),
            _rel("李承宇", "found", "云图数据有限公司", "PERSON", "ORG"),
        ],
        "新闻稿",
    )
    row = _dossier(client)
    _attach(client, row["id"], [rid], role="新闻稿")
    kinds = {i["kind"] for i in _view(client, row["id"])["inferred"]}
    assert {"common_person", "common_founder"} <= kinds


def test_same_address_needs_street_level_place(client):
    """省市级地址不触发同址推断：否则同城公司会被连成一片。"""
    broad = _record(
        [
            _rel("星河智能科技有限公司", "headquarter", "北京市", "ORG", "LOC"),
            _rel("云图数据有限公司", "headquarter", "北京市", "ORG", "LOC"),
        ],
        "工商登记",
    )
    row = _dossier(client)
    _attach(client, row["id"], [broad])
    assert not [i for i in _view(client, row["id"])["inferred"] if i["kind"] == "same_address"]

    narrow = _record(
        [
            _rel("恒信科技有限公司", "headquarter", "深圳市南山区科技园路8号", "ORG", "LOC"),
            _rel("恒昌数据有限公司", "headquarter", "深圳市南山区科技园路8号", "ORG", "LOC"),
        ],
        "工商登记",
    )
    other = _dossier(client, "乙案卷", "恒信科技有限公司")
    _attach(client, other["id"], [narrow])
    hits = [i for i in _view(client, other["id"])["inferred"] if i["kind"] == "same_address"]
    assert len(hits) == 1
    assert hits[0]["strength"] == "weak"


# --------------------------------------------------------------------------- #
# 疑点
# --------------------------------------------------------------------------- #


def test_orphan_material_matches_canonical_subject(client):
    """标的按原文填写，关系里存的是归一化名，不能因此全量误报孤儿材料。"""
    linked = _record([_rel("星河智能科技有限公司", "control", "云图数据有限公司")], "股权结构")
    orphan = _record([_rel("恒信资本管理有限公司", "acquire", "云图数据有限公司")], "股权转让")
    row = _dossier(client, subject="星河智能科技有限公司")
    _attach(client, row["id"], [linked])
    _attach(client, row["id"], [orphan], role="股权转让")

    view = _view(client, row["id"])
    orphans = [a for a in view["ambiguities"] if a["type"] == "orphan_material"]
    assert len(orphans) == 1
    assert "股权转让" in orphans[0]["title"]


def test_tension_when_sue_and_cooperate_coexist(client):
    r1 = _record([_rel("星河智能科技有限公司", "sue", "云图数据有限公司")], "裁判文书")
    r2 = _record([_rel("星河智能科技有限公司", "cooperate", "云图数据有限公司")], "合作公告")
    row = _dossier(client)
    _attach(client, row["id"], [r1], role="裁判文书")
    _attach(client, row["id"], [r2], role="公告")

    view = _view(client, row["id"])
    tensions = [a for a in view["ambiguities"] if a["type"] == "tension"]
    assert len(tensions) == 1
    # 合作与诉讼并存是真实常态，不该被报成「权益关系互相矛盾」
    assert not [a for a in view["ambiguities"] if a["type"] == "conflict"]


def test_conflict_inside_equity_family(client):
    r1 = _record([_rel("星河智能科技有限公司", "control", "云图数据有限公司")], "股权结构")
    r2 = _record([_rel("星河智能科技有限公司", "acquire", "云图数据有限公司")], "公告")
    row = _dossier(client)
    _attach(client, row["id"], [r1])
    _attach(client, row["id"], [r2], role="公告")

    conflicts = [a for a in _view(client, row["id"])["ambiguities"] if a["type"] == "conflict"]
    assert len(conflicts) == 1
    assert "控股" in conflicts[0]["detail"] or "收购" in conflicts[0]["detail"]


def test_subject_is_guessed_when_missing(client):
    rid = _record(
        [
            _rel("星河智能科技有限公司", "control", "云图数据有限公司"),
            _rel("星河智能科技有限公司", "cooperate", "恒信数据有限公司"),
        ],
        "股权结构",
    )
    row = _dossier(client, name="未填标的", subject="")
    _attach(client, row["id"], [rid])
    view = _view(client, row["id"])
    assert view["subject_auto"] is True
    assert view["subject_effective"] == "星河智能科技有限公司"


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #


def test_report_keeps_inferred_in_its_own_section(client):
    rid = _record(
        [
            _rel("星河控股集团有限公司", "control", "星河智能科技有限公司"),
            _rel("星河智能科技有限公司", "control", "云图数据有限公司"),
        ],
        "股权结构",
    )
    row = _dossier(client)
    _attach(client, row["id"], [rid])

    res = client.get(f"/api/dossiers/{row['id']}/report")
    assert res.status_code == 200
    html = res.text
    assert "推断关联（不由原文直接支持）" in html
    assert "不能作为认定事实的依据" in html
    assert "间接控制" in html
    # 推断不能混进直接结论表：表里只有原文抽出的那两条
    direct_table = html.split("证据出处")[0].split("直接结论（原文可查）")[1]
    assert "间接控制" not in direct_table


def test_report_404_for_missing_dossier(client):
    assert client.get("/api/dossiers/99999/report").status_code == 404


# --------------------------------------------------------------------------- #
# 生命周期
# --------------------------------------------------------------------------- #


def test_delete_record_drops_material_but_keeps_dossier(client):
    rid = _record([_rel("星河智能科技有限公司", "control", "云图数据有限公司")], "股权结构")
    row = _dossier(client)
    _attach(client, row["id"], [rid])
    assert client.delete(f"/api/records/{rid}").status_code == 200

    view = _view(client, row["id"])
    assert view["summary"]["materials"] == 0
    assert view["direct"] == []


def test_clear_records_clears_dossiers(client):
    rid = _record([_rel("星河智能科技有限公司", "control", "云图数据有限公司")], "股权结构")
    row = _dossier(client)
    _attach(client, row["id"], [rid])
    assert client.delete("/api/records").status_code == 200
    assert client.get("/api/dossiers").json()["total"] == 0


def test_seed_is_idempotent(client):
    first = client.post("/api/dossiers/seed")
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["summary"]["materials"] == 6
    assert payload["summary"]["inferred"] >= 1

    second = client.post("/api/dossiers/seed")
    assert second.status_code == 200
    assert second.json()["id"] == payload["id"]
    assert client.get("/api/dossiers").json()["total"] == 1


def test_empty_dossier_view_does_not_crash(client):
    row = _dossier(client, name="空案卷", subject="")
    view = _view(client, row["id"])
    assert view["summary"]["materials"] == 0
    assert view["direct"] == [] and view["inferred"] == []
    assert view["subject_effective"] == ""
    html = client.get(f"/api/dossiers/{row['id']}/report").text
    assert "还没有归档材料" in html
