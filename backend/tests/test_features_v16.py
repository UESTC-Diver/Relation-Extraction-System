# -*- coding: utf-8 -*-
"""1.6.0 回归测试：自有金标准标注闭环。

守两条线：
1. 标注只影响评测口径，不碰抽取结果——标完再抽，三元组必须一字不差；
2. 「已判定范围」的口径永远不会低于「未判视为漏抽」，否则双口径就成了
   给自己挑好数字的工具。
"""

from __future__ import annotations

TEXT_A = "腾讯控股宣布收购搜狗公司。交易完成后，搜狗公司成为腾讯控股的全资子公司。"
TEXT_B = "王小川出任腾讯控股副总裁。"


def _record(client, text: str, title: str) -> int:
    res = client.post("/api/extract", json={"text": text, "title": title, "save": True})
    assert res.status_code == 200, res.text
    return int(res.json()["record_id"])


def _make_set(client, name: str = "并购案 20 篇", ids: list[int] | None = None) -> dict:
    res = client.post(
        "/api/annotation/sets", json={"name": name, "record_ids": ids or []}
    )
    assert res.status_code == 200, res.text
    return res.json()


def _annotation(client, record_id: int) -> dict:
    res = client.get(f"/api/annotation/records/{record_id}")
    assert res.status_code == 200, res.text
    return res.json()


def _save(client, record_id: int, items: list[dict]) -> dict:
    res = client.put(f"/api/annotation/records/{record_id}", json={"items": items})
    assert res.status_code == 200, res.text
    return res.json()


# --------------------------------------------------------------------------- #
# 标注集
# --------------------------------------------------------------------------- #

def test_set_crud(client):
    created = _make_set(client, "某某收购案")
    assert created["name"] == "某某收购案"
    set_id = created["id"]

    listing = client.get("/api/annotation/sets").json()
    assert listing["total"] == 1
    assert listing["items"][0]["record_count"] == 0

    assert client.get(f"/api/annotation/sets/{set_id}").status_code == 200
    assert client.delete(f"/api/annotation/sets/{set_id}").status_code == 200
    assert client.get(f"/api/annotation/sets/{set_id}").status_code == 404


def test_set_records_add_and_remove(client):
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    created = _make_set(client, ids=[rid])
    set_id = created["id"]
    # 集内按记录 id 倒序，最新导入的排在最前，和「历史记录」一致
    assert any(r["id"] == rid for r in created["records"])

    rid2 = _record(client, TEXT_B, "王小川任职")
    added = client.post(
        f"/api/annotation/sets/{set_id}/records", json={"record_ids": [rid2]}
    ).json()
    assert len(added["records"]) == 2

    # 重复追加幂等：同一篇材料在一个集里只算一次
    again = client.post(
        f"/api/annotation/sets/{set_id}/records", json={"record_ids": [rid2, rid2]}
    ).json()
    assert len(again["records"]) == 2

    after = client.request(
        "DELETE",
        f"/api/annotation/sets/{set_id}/records",
        json={"record_ids": [rid2]},
    ).json()
    assert len(after["records"]) == 1


# --------------------------------------------------------------------------- #
# 单篇标注
# --------------------------------------------------------------------------- #

def test_fresh_record_is_all_unjudged(client):
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    data = _annotation(client, rid)
    assert data["summary"]["auto"] == len(data["relations"]) > 0
    assert data["summary"]["manual"] == 0
    assert data["summary"]["judged"] == 0
    assert data["summary"]["coverage"] == 0.0
    assert all(item["verdict"] == "" for item in data["relations"])


def test_mark_positive_and_negative(client):
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    before = _annotation(client, rid)
    first, second = before["relations"][0], before["relations"][1]

    _save(
        client,
        rid,
        [
            {"relation_key": first["relation_key"], "verdict": "positive"},
            {"relation_key": second["relation_key"], "verdict": "negative"},
        ],
    )
    after = _annotation(client, rid)
    assert after["summary"]["positive"] == 1
    assert after["summary"]["negative"] == 1
    assert after["summary"]["unjudged"] == after["summary"]["auto"] - 2
    assert after["summary"]["coverage"] > 0


def test_manual_supplement_counts_as_gold(client):
    """补录项没有系统指纹，必须由后端生成 key，否则存不进去。"""
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    data = _annotation(client, rid)
    auto_heads = {(r["head"], r["relation"], r["tail"]) for r in data["relations"]}

    saved = _save(
        client,
        rid,
        [
            {
                "verdict": "positive",
                "head": "搜狗公司",
                "relation": "acquire",
                "tail": "腾讯控股",
                "evidence": "（人工补录，系统在这一句漏抽）",
                "sentence_index": 0,
            }
        ],
    )
    assert saved["summary"]["manual"] == 1
    manual = saved["manual"][0]
    assert manual["origin"] == "manual"
    assert manual["relation_key"]
    assert (manual["head"], manual["relation"], manual["tail"]) not in auto_heads


def test_supplement_matching_auto_merges(client):
    """补录的如果系统已经抽到，就归并到那条上，不能在 gold 里出现两份。"""
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    data = _annotation(client, rid)
    first = data["relations"][0]
    saved = _save(
        client,
        rid,
        [
            {
                "verdict": "positive",
                "head": first["head"],
                "relation": first["relation"],
                "tail": first["tail"],
            }
        ],
    )
    assert saved["summary"]["manual"] == 0
    assert saved["summary"]["positive"] == 1
    matched = [
        r for r in saved["relations"] if r["relation_key"] == first["relation_key"]
    ][0]
    assert matched["verdict"] == "positive"
    assert matched["origin"] == "auto"


def test_withdraw_verdict_deletes_row(client):
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    rel = _annotation(client, rid)["relations"][0]
    _save(client, rid, [{"relation_key": rel["relation_key"], "verdict": "positive"}])
    assert _annotation(client, rid)["summary"]["positive"] == 1

    # 空 verdict = 撤回判定，回到未判，而不是存一个 pending
    saved = _save(client, rid, [{"relation_key": rel["relation_key"], "verdict": ""}])
    assert saved["summary"]["positive"] == 0
    assert saved["summary"]["judged"] == 0


def test_invalid_relation_rejected(client):
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    res = client.put(
        f"/api/annotation/records/{rid}",
        json={
            "items": [
                {"verdict": "positive", "head": "甲", "relation": "made_up", "tail": "乙"}
            ]
        },
    )
    assert res.status_code == 400
    assert "19 类" in res.json()["detail"]


def test_annotation_does_not_change_extraction(client):
    """标注是评测侧的事，抽出来的三元组一个字节都不能动。"""
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    before = client.get(f"/api/records/{rid}").json()["relations"]
    data = _annotation(client, rid)
    _save(
        client,
        rid,
        [{"relation_key": r["relation_key"], "verdict": "positive"} for r in data["relations"]],
    )
    after = client.get(f"/api/records/{rid}").json()["relations"]
    assert [(r["head"], r["relation"], r["tail"]) for r in before] == [
        (r["head"], r["relation"], r["tail"]) for r in after
    ]


# --------------------------------------------------------------------------- #
# 评测双口径
# --------------------------------------------------------------------------- #

def test_eval_requires_positive(client):
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    set_id = _make_set(client, ids=[rid])["id"]
    res = client.post("/api/eval", json={"set_id": set_id, "save": False})
    assert res.status_code == 400
    assert "该抽" in res.json()["detail"]


def test_dual_scope_never_inverts(client):
    """只判一半时，已判定口径的 P 必须不低于严格口径。"""
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    set_id = _make_set(client, ids=[rid])["id"]
    data = _annotation(client, rid)
    assert data["summary"]["auto"] >= 2
    _save(
        client,
        rid,
        [{"relation_key": data["relations"][0]["relation_key"], "verdict": "positive"}],
    )

    report = client.post("/api/eval", json={"set_id": set_id, "save": False}).json()["report"]
    assert report["dataset"] == f"annotation:{set_id}"
    assert report["coverage"] < 1.0
    assert report["scoped"] is True
    assert report["skipped_unjudged"] >= 1
    assert report["precision"] >= report["strict"]["precision"]
    assert report["strict"]["scoped"] is False
    assert report["recall"] == 1.0


def test_full_annotation_matches_strict(client):
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    set_id = _make_set(client, ids=[rid])["id"]
    data = _annotation(client, rid)
    _save(
        client,
        rid,
        [{"relation_key": r["relation_key"], "verdict": "positive"} for r in data["relations"]],
    )
    report = client.post("/api/eval", json={"set_id": set_id, "save": False}).json()["report"]
    assert report["coverage"] == 1.0
    assert report["precision"] == report["strict"]["precision"]
    assert report["f1"] == report["strict"]["f1"] == 1.0


def test_builtin_eval_unchanged(client):
    """不传 set_id 时行为必须与 1.5.0 完全一致。"""
    report = client.post("/api/eval", json={"save": False}).json()["report"]
    assert report["dataset"] == "builtin"
    assert report["coverage"] == 1.0
    assert report["scoped"] is False
    assert report["f1"] >= 0.95
    assert "strict" not in report


def test_eval_runs_keep_dataset_apart(client):
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    set_id = _make_set(client, ids=[rid])["id"]
    data = _annotation(client, rid)
    _save(
        client,
        rid,
        [{"relation_key": r["relation_key"], "verdict": "positive"} for r in data["relations"]],
    )

    client.post("/api/eval", json={"save": True})
    client.post("/api/eval", json={"set_id": set_id, "save": True})
    items = client.get("/api/eval/runs").json()["items"]
    datasets = {row["dataset"] for row in items}
    assert "builtin" in datasets
    assert f"annotation:{set_id}" in datasets
    assert all(0.0 <= row["coverage"] <= 1.0 for row in items)


# --------------------------------------------------------------------------- #
# 与复核、删除的关系
# --------------------------------------------------------------------------- #

def test_prefill_from_review(client):
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    review = client.get(f"/api/records/{rid}/review").json()
    first = review["relations"][0]
    client.put(
        f"/api/records/{rid}/review/decisions",
        json={"decisions": [{"relation_key": first["review_key"], "decision": "approved"}]},
    )
    data = _annotation(client, rid)
    assert data["prefill"]
    assert data["prefill"][0]["verdict"] == "positive"
    assert data["prefill"][0]["relation_key"] == first["review_key"]
    # 预填只是建议，不能自动落库成 human 判定
    assert data["summary"]["judged"] == 0


def test_delete_record_clears_annotations(client):
    from app import db

    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    set_id = _make_set(client, ids=[rid])["id"]
    data = _annotation(client, rid)
    _save(client, rid, [{"relation_key": data["relations"][0]["relation_key"], "verdict": "positive"}])

    assert client.delete(f"/api/records/{rid}").status_code == 200
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM annotation_set_records WHERE set_id = ?", (set_id,)
        ).fetchone()[0] == 0


def test_delete_set_keeps_annotations(client):
    """标注挂在材料上，删集不该把材料上的判定一起删掉。"""
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    set_id = _make_set(client, ids=[rid])["id"]
    data = _annotation(client, rid)
    _save(client, rid, [{"relation_key": data["relations"][0]["relation_key"], "verdict": "positive"}])

    assert client.delete(f"/api/annotation/sets/{set_id}").status_code == 200
    assert _annotation(client, rid)["summary"]["positive"] == 1


def test_coverage_endpoint(client):
    rid = _record(client, TEXT_A, "腾讯收购搜狗")
    set_id = _make_set(client, ids=[rid])["id"]
    empty = client.get(f"/api/annotation/sets/{set_id}/coverage").json()
    assert empty["records"] == 1
    assert empty["ready"] is False
    assert empty["coverage"] == 0.0

    data = _annotation(client, rid)
    _save(client, rid, [{"relation_key": data["relations"][0]["relation_key"], "verdict": "positive"}])
    filled = client.get(f"/api/annotation/sets/{set_id}/coverage").json()
    assert filled["ready"] is True
    assert filled["positive"] == 1
    assert 0 < filled["coverage"] <= 1
