# -*- coding: utf-8 -*-
"""2.2.0 回归测试：从标注集反推候选触发词。

守三条线：

1. **只读**：反推绝不能改配置、改三元组、改标注——它只是把人的判断整理成
   一个可以直接拿去试跑的候选，能不能生效由 A/B 试跑与人决定；
2. **只提真漏抽的**：已经注册的触发词不重复提，碎片不冒充候选；
3. **自证不算猜**：标「已自证」的候选，必须真能在加了词之后抽出那条关系。
"""

from __future__ import annotations

# "入主" / "吃下" 都不在任何内置触发词里，拿来当真实的漏抽说法。
HEAD = "星海智能科技有限公司"
TAIL = "云图数据服务有限公司"
OTHER = "恒信资本管理有限公司"


def _record(client, text: str, title: str = "") -> int:
    res = client.post("/api/extract", json={"text": text, "title": title, "save": True})
    assert res.status_code == 200, res.text
    return int(res.json()["record_id"])


def _annotate(client, record_id: int, head: str, tail: str, text: str, relation: str = "acquire") -> None:
    res = client.put(
        f"/api/annotation/records/{record_id}",
        json={
            "items": [
                {
                    "head": head,
                    "relation": relation,
                    "tail": tail,
                    "evidence": text,
                    "verdict": "positive",
                }
            ]
        },
    )
    assert res.status_code == 200, res.text


def _mine(client, **params) -> dict:
    res = client.get("/api/mining/triggers", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def _triggers(view: dict) -> set[str]:
    return {c["trigger"] for c in view["candidates"]}


# --------------------------------------------------------------------------- #
# 空态与无法反推
# --------------------------------------------------------------------------- #


def test_empty_library_gives_baseline(client):
    view = _mine(client)
    assert view["summary"]["manual_total"] == 0
    assert view["candidates"] == []
    assert view["advice"][0]["kind"] == "baseline"


def test_unlocatable_entities_are_reported(client):
    """补录的实体名在原文里找不到，就没法判断哪一段是触发词——如实说，不硬猜。"""
    text = "星海智能科技有限公司入主云图数据服务有限公司。"
    rid = _record(client, text)
    _annotate(client, rid, "不存在的公司甲", "不存在的公司乙", text)

    view = _mine(client)
    assert view["summary"]["manual_total"] == 1
    assert view["summary"]["usable_samples"] == 0
    assert view["candidates"] == []
    assert view["advice"][0]["kind"] == "unlocatable"


def test_single_annotation_does_not_spawn_fragments(client):
    """一条补录的片段会被切成十几个 n-gram，只有整段本身才配当候选。"""
    text = "星海智能科技有限公司入主云图数据服务有限公司。"
    rid = _record(client, text)
    _annotate(client, rid, HEAD, TAIL, text)

    # 只有一条证据时默认不摆出来，免得把「这句话的措辞」当成规则建议
    assert _mine(client)["candidates"] == []
    assert _mine(client)["summary"]["weak_hidden"] == 1

    view = _mine(client, include_weak="true")
    triggers = _triggers(view)
    assert "入主" in triggers
    # 滑窗碎片不能冒充候选，否则一条补录能刷出十几条噪音
    assert "今日宣布" not in triggers
    assert "日宣布入" not in triggers
    weak = [c for c in view["candidates"] if c["weak"]]
    assert all(c["count"] == 1 for c in weak)


# --------------------------------------------------------------------------- #
# 反推与自证
# --------------------------------------------------------------------------- #


def test_repeated_phrase_becomes_verified_candidate(client):
    texts = [
        "星海智能科技有限公司入主云图数据服务有限公司，交易对价为1.2亿元。",
        "2021年6月，星海智能科技有限公司入主云图数据服务有限公司。",
        "星海智能科技有限公司今日宣布入主云图数据服务有限公司。",
    ]
    for text in texts:
        _annotate(client, _record(client, text), HEAD, TAIL, text)

    view = _mine(client)
    top = view["candidates"][0]
    assert top["trigger"] == "入主"
    assert top["count"] == 3
    assert top["verified"] is True
    assert top["relation"] == "acquire"
    assert view["summary"]["verified"] >= 1


def test_substring_collapse_keeps_the_frequent_one(client):
    """「入主」出现 3 次时，「今日宣布入主」只是它的一种上下文，不该单独成条。"""
    texts = [
        "星海智能科技有限公司入主云图数据服务有限公司。",
        "2021年，星海智能科技有限公司入主云图数据服务有限公司。",
        "星海智能科技有限公司昨日入主云图数据服务有限公司。",
        "星海智能科技有限公司今日宣布入主云图数据服务有限公司。",
    ]
    for text in texts:
        _annotate(client, _record(client, text), HEAD, TAIL, text)

    triggers = _triggers(_mine(client))
    assert "入主" in triggers
    assert "今日宣布入主" not in triggers


def test_registered_trigger_is_not_proposed_again(client):
    """「收购」本来就在配置里，提出来给人看纯属浪费。"""
    text = "腾讯控股收购搜狗公司。"
    rid = _record(client, text)
    _annotate(client, rid, "腾讯控股", "搜狗公司", text)

    triggers = _triggers(_mine(client))
    assert "收购" not in triggers
    assert "全资收购" not in triggers


def test_conflict_with_another_relation_is_flagged(client):
    """同一个词挂到两类关系上会互相抢命中，这一点必须在动手前就说明。"""
    texts = [
        "星海智能科技有限公司通过控股方式入主云图数据服务有限公司。",
        "星海智能科技有限公司通过控股方式入主恒信资本管理有限公司。",
    ]
    for text in texts:
        tail = TAIL if "云图" in text else OTHER
        _annotate(client, _record(client, text), HEAD, tail, text)

    view = _mine(client)
    hits = [c for c in view["candidates"] if c["trigger"] == "控股"]
    assert hits, "「控股」被夹在两个实体之间，应当被提出来"
    assert "control" in hits[0]["conflicts"]


def test_mine_is_read_only(client):
    """反推不改库：候选要生效必须走试跑与写入，这条路径不能自己动配置。"""
    text = "星海智能科技有限公司入主云图数据服务有限公司。"
    _annotate(client, _record(client, text), HEAD, TAIL, text)

    from app import db

    def counts() -> tuple[int, int, int]:
        with db.connect() as conn:
            return (
                conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM custom_rules").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0],
            )

    before = counts()
    view = _mine(client, include_weak="true")
    assert view["summary"]["candidates"] >= 1
    assert counts() == before

    rules = client.get("/api/rules").json()
    words = {r["trigger"] for r in rules.get("custom", rules.get("items", []))}
    assert "入主" not in words


# --------------------------------------------------------------------------- #
# 反向信号：误抽
# --------------------------------------------------------------------------- #


def test_rejected_auto_item_becomes_overbroad_signal(client):
    """补漏之外的另一半：哪些词抽出来的结论人认为不该算。"""
    text = "腾讯控股宣布收购搜狗公司。"
    rid = _record(client, text)
    annotation = client.get(f"/api/annotation/records/{rid}").json()
    key = annotation["relations"][0]["relation_key"]

    res = client.put(
        f"/api/annotation/records/{rid}",
        json={"items": [{"relation_key": key, "verdict": "negative"}]},
    )
    assert res.status_code == 200, res.text

    view = _mine(client)
    assert view["summary"]["overbroad"] >= 1
    top = view["overbroad"][0]
    assert top["trigger"] == "收购"
    assert top["rejected"] == 1


# --------------------------------------------------------------------------- #
# 范围与边界
# --------------------------------------------------------------------------- #


def test_set_scope_limits_mining(client):
    text_a = "星海智能科技有限公司入主云图数据服务有限公司。"
    text_b = "星海智能科技有限公司入主云图数据服务有限公司，对价1.2亿元。"
    rid_a = _record(client, text_a, "甲")
    rid_b = _record(client, text_b, "乙")
    _annotate(client, rid_a, HEAD, TAIL, text_a)
    _annotate(client, rid_b, HEAD, TAIL, text_b)

    set_a = client.post("/api/annotation/sets", json={"name": "只看甲", "record_ids": [rid_a]}).json()
    view = _mine(client, set_id=set_a["id"])
    assert view["summary"]["manual_total"] == 1
    assert view["summary"]["set_id"] == set_a["id"]

    full = _mine(client)
    assert full["summary"]["manual_total"] == 2


def test_unknown_set_returns_404(client):
    res = client.get("/api/mining/triggers", params={"set_id": 99999})
    assert res.status_code == 404


def test_verify_can_be_skipped(client):
    """前端要快速刷新时可以不做自证；这时 verified 全是 None，不是 False。"""
    text = "星海智能科技有限公司入主云图数据服务有限公司。"
    _annotate(client, _record(client, text), HEAD, TAIL, text)

    view = _mine(client, verify="false")
    assert view["summary"]["verified"] == 0
    assert all(c["verified"] is None for c in view["candidates"])


def test_entity_order_does_not_matter(client):
    """「A 由 B 实际控制」里触发词在 head 之后，只看两实体中间会漏掉。"""
    texts = [
        "云图数据服务有限公司由星海智能科技有限公司入主。",
        "云图数据服务有限公司于2021年由星海智能科技有限公司入主。",
    ]
    for text in texts:
        # head / tail 与句面顺序相反，仍应定位成功
        _annotate(client, _record(client, text), HEAD, TAIL, text)

    view = _mine(client)
    assert view["summary"]["unlocatable"] == 0
    assert "入主" in _triggers(view)
