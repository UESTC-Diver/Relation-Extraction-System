# -*- coding: utf-8 -*-
"""案卷报告：单文件 HTML，可打印、可离线、可直接发给人。

与单篇报告的区别只有一处，但这一处是全部意义所在：报告里**直接结论**和
**推断结论**必须分两栏出现，且推断栏必须自带一句「这不是原文写的」。
把两者混在一张表里，等于把猜测冒充证据。
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .report import _STYLE, _esc

_EXTRA_STYLE = """
.vol{display:flex;flex-wrap:wrap;gap:8px 28px;font-size:12.5px;color:var(--muted);margin-top:10px}
.vol b{color:var(--ink2);font-weight:500}
.subj{font-size:15px;color:var(--ink2);margin:6px 0 0}
.inf{border:1px dashed #b9ae95;background:#fbf8ef;padding:14px 18px;margin-top:12px}
.inf-head{font-size:14px;margin-bottom:4px}
.inf-head b{font-weight:500}
.badge{display:inline-block;padding:1px 7px;margin-right:8px;border-radius:3px;
font-size:11px;border:1px dashed #a8322a;color:#a8322a;background:#fdf3f1}
.badge-w{display:inline-block;padding:1px 7px;margin-right:8px;border-radius:3px;
font-size:11px;border:1px solid #ddd5c2;color:#615d52;background:#f1ecdf}
.cav{color:var(--muted);font-size:12px;margin-top:6px;line-height:1.6}
.path{margin:8px 0 0;padding:0;list-style:none;border-left:1px solid #ddd5c2;padding-left:14px}
.path li{font-size:12px;color:var(--ink2);padding:4px 0}
.path .step-doc{color:var(--muted)}
.path .step-eq{color:var(--red)}
.amb{background:var(--surface);border:1px solid var(--line);padding:0}
.amb-item{padding:11px 16px;border-top:1px solid var(--line);font-size:13px}
.amb-item:first-child{border-top:none}
.lv-high{color:#a8322a}.lv-medium{color:#8a5a10}
.amb-x{color:var(--muted);font-size:12px;margin-top:3px}
.disc{background:#fdf3f1;border:1px solid #e8cfc9;padding:14px 18px;font-size:12.5px;
color:var(--ink2);line-height:1.7;margin-top:12px}
.disc b{color:#a8322a;font-weight:500}
.src{margin-top:6px;padding-left:0;list-style:none}
.src li{font-size:12px;color:var(--muted);padding:2px 0 2px 12px;position:relative}
.src li:before{content:"·";position:absolute;left:0;color:var(--red)}
"""


def _graph_svg(view: dict[str, Any]) -> str:
    """以标的为中心的静态图：直接关系实线，推断关系虚线。

    推断边有意识地不标关系名 —— 标了就会和图上的直接结论混读；
    虚线 + 不标字，读图的人一眼能看出「这条是推的」。
    """
    subject = view.get("subject_effective") or ""
    nodes = view.get("graph", {}).get("nodes") or []
    edges = view.get("graph", {}).get("direct_edges") or []
    inferred = view.get("graph", {}).get("inferred_edges") or []
    if len(nodes) < 2:
        return '<p class="note">材料里还没有可成图的关系。</p>'

    center = subject if any(n["name"] == subject for n in nodes) else nodes[0]["name"]
    others = [n["name"] for n in nodes if n["name"] != center][:16]
    truncated = len(nodes) - 1 > len(others)

    # 机构全名动辄八十字，环形半径不够时标签会互相压住。这里同时做三件事：
    # 画布放大、节点名截到 7 字、文字用纸色描边（paint-order），
    # 让标签压到连线上也还能读。
    cx, cy, radius = 360, 205, 172
    pos: dict[str, tuple[float, float]] = {center: (cx, cy)}
    for i, name in enumerate(others):
        angle = -math.pi / 2 + 2 * math.pi * i / max(1, len(others))
        pos[name] = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))

    parts = [
        '<svg viewBox="0 0 720 440" width="100%" role="img" '
        'aria-label="案卷关系图：实线为原文直接支持，虚线为推断" style="display:block">'
    ]
    # 同一对实体之间常有多条关系（既收购又合作还打官司），逐条画会在同一个
    # 中点上叠四个标签，糊成一团。这里先按实体对合并成一条边、一个标签。
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for e in edges:
        key = (e["source"], e["target"])
        item = grouped.setdefault(key, {"labels": [], "weight": 1})
        if e["label"] not in item["labels"]:
            item["labels"].append(e["label"])
        item["weight"] = max(item["weight"], int(e.get("weight") or 1))

    for (source, target), item in grouped.items():
        if source not in pos or target not in pos:
            continue
        x1, y1 = pos[source]
        x2, y2 = pos[target]
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#c4bba6" stroke-width="{1 + min(2, item["weight"] - 1) * 0.6:.1f}"/>'
        )
        labels = item["labels"]
        text = "·".join(labels[:3]) + (" 等" if len(labels) > 3 else "")
        parts.append(
            f'<text x="{(x1 + x2) / 2:.1f}" y="{(y1 + y2) / 2 - 4:.1f}" '
            'text-anchor="middle" font-size="10" fill="#a8322a" '
            'paint-order="stroke" stroke="#fffdf6" stroke-width="3">'
            f'{_esc(text)}</text>'
        )
    for e in inferred:
        if e["source"] not in pos or e["target"] not in pos:
            continue
        x1, y1 = pos[e["source"]]
        x2, y2 = pos[e["target"]]
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            'stroke="#a8322a" stroke-width="1" stroke-dasharray="4 4" opacity="0.75"/>'
        )
    for name, (x, y) in pos.items():
        is_center = name == center
        r = 10 if is_center else 6
        fill = "#a8322a" if is_center else "#fffdf6"
        stroke = "#a8322a" if is_center else "#c4bba6"
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        label = name if len(name) <= 7 else name[:6] + "…"
        weight = "600" if is_center else "400"
        parts.append(
            f'<text x="{x:.1f}" y="{y + r + 15:.1f}" text-anchor="middle" '
            f'font-size="12" font-weight="{weight}" fill="#1e1c18" '
            f'paint-order="stroke" stroke="#fffdf6" stroke-width="4">{_esc(label)}</text>'
        )
    parts.append("</svg>")
    note = '<p class="note">实线＝原文直接支持（线宽表示支撑材料数）；虚线＝推断，不来自任何单句。</p>'
    if truncated:
        note += '<p class="note">节点较多，图中只画了前 17 个，完整清单见表格。</p>'
    return '<div class="graph">' + "".join(parts) + "</div>" + note


def _direct_table(direct: list[dict[str, Any]]) -> str:
    rows = (
        "".join(
            "<tr>"
            f"<td>{_esc(d['head'])}</td>"
            f'<td><span class="tag">{_esc(d["relation_label"])}</span></td>'
            f"<td>{_esc(d['tail'])}</td>"
            f"<td>{_esc(d['support_count'])}</td>"
            f"<td>{_esc(d['confidence'])}</td>"
            f'<td class="evidence">{_esc(", ".join(d["docs"][:3]))}'
            f"{' 等' if len(d['docs']) > 3 else ''}</td>"
            "</tr>"
            for d in direct
        )
        or '<tr><td colspan="6">这批材料里还没有抽出关系</td></tr>'
    )
    return (
        "<table><thead><tr><th>头实体</th><th>关系</th><th>尾实体</th>"
        "<th>支撑材料</th><th>置信度</th><th>出现在</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _evidence_list(direct: list[dict[str, Any]]) -> str:
    """每条直接结论的全部出处。这是「结论能交代」的实物部分。"""
    blocks = []
    for d in direct[:60]:
        srcs = "".join(
            f"<li>《{_esc(s['doc_title'])}》"
            f'<span class="step-doc">（{_esc(s["role"])} · 第 {_esc(s["sentence_index"] + 1)} 句）</span> '
            f"{_esc(s['evidence'])}</li>"
            for s in d["sources"][:6]
        )
        blocks.append(
            '<div class="ex-item">'
            f'<div class="ex-head">{_esc(d["head"])} — {_esc(d["relation_label"])} — {_esc(d["tail"])}</div>'
            f'<ul class="src">{srcs}</ul>'
            "</div>"
        )
    if not blocks:
        return ""
    more = (
        '<p class="note">仅列出前 60 条结论的出处；完整清单在工作台案卷页可逐条展开。</p>' if len(direct) > 60 else ""
    )
    return f'<h2>证据出处</h2><div class="ex-list">{"".join(blocks)}</div>{more}'


def _inferred_html(inferred: list[dict[str, Any]]) -> str:
    if not inferred:
        return (
            "<h2>推断关联</h2>"
            '<p class="note">这批材料里没有可推出的间接关联。'
            "推断只在控制链、同一人任职、同一创始人、同一具体地址四类规则成立时才生成，"
            "推不出来就不写。</p>"
        )
    blocks = []
    for item in inferred:
        strong = item["strength"] == "strong"
        badge = '<span class="badge">推断 · 较强</span>' if strong else '<span class="badge-w">推断 · 较弱</span>'
        steps = "".join(
            f'<li>{_esc(s["head"])} <span class="step-eq">{_esc(s["relation_label"])}</span> '
            f"{_esc(s['tail'])}<br>"
            f'<span class="step-doc">《{_esc(s["doc_title"])}》{_esc(s["role"])}'
            f" · 第 {_esc(s['sentence_index'] + 1)} 句：{_esc(s['evidence'])}</span></li>"
            for s in item["path"]
        )
        blocks.append(
            '<div class="inf">'
            f'<div class="inf-head">{badge}'
            f"{_esc(item['head'])} — <b>{_esc(item['label'])}</b> — {_esc(item['tail'])}"
            f'<span class="badge-w">置信度 {_esc(item["confidence"])}</span></div>'
            f'<div class="ex-kv"><em>依据</em>{_esc(item["basis"])}（{_esc(item["kind_label"])}）</div>'
            f'<ol class="path">{steps}</ol>'
            f'<div class="cav">{_esc(item["caveat"])}</div>'
            "</div>"
        )
    return (
        "<h2>推断关联（不由原文直接支持）</h2>"
        '<div class="disc"><b>先读这段再读下面的结论。</b>'
        "本栏每一条都是把已有三元组做图运算得出的，"
        "原文里没有任何一句话这么说。它们的作用是提示下一步该查什么，"
        "不能作为认定事实的依据，也不计入任何评测指标。</div>" + "".join(blocks)
    )


def _ambiguity_html(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    rows = "".join(
        f'<div class="amb-item"><span class="lv-{_esc(a["level"])}">'
        f"{'需裁决' if a['level'] == 'high' else '待补强'}</span> · {_esc(a['title'])}"
        f'<div class="amb-x">{_esc(a["detail"])}</div></div>'
        for a in items
    )
    return (
        "<h2>未闭环的疑点</h2>"
        f'<div class="amb">{rows}</div>'
        '<p class="note">这一节列的是「这份案卷还不扎实的地方」，不是结论。</p>'
    )


def build_dossier_report(view: dict[str, Any]) -> str:
    summary = view.get("summary") or {}
    subject = view.get("subject_effective") or "（未指定）"
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    mats = view.get("materials") or []
    direct = view.get("direct") or []
    inferred = view.get("inferred") or []
    ambiguities = view.get("ambiguities") or []

    cards = [
        ("材料", summary.get("materials", 0)),
        ("直接结论", summary.get("relations_merged", 0)),
        ("推断关联", summary.get("inferred", 0)),
        ("涉及实体", summary.get("entities", 0)),
        ("疑点", summary.get("ambiguities", 0)),
    ]
    card_html = "".join(f'<div class="card"><b>{_esc(v)}</b><span>{_esc(k)}</span></div>' for k, v in cards)

    mat_rows = (
        "".join(
            f"<tr><td>{_esc(m['title'])}</td>"
            f'<td><span class="tag">{_esc(m["role"])}</span></td>'
            f"<td>{_esc(m['char_count'])}</td><td>{_esc(m['relation_count'])}</td></tr>"
            for m in mats
        )
        or '<tr><td colspan="4">案卷里还没有归档材料</td></tr>'
    )

    auto_note = (
        f' <span class="note">（标的未填写，按材料中出现最多的机构「{_esc(subject)}」推断）</span>'
        if view.get("subject_auto")
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(view.get("name"))} · 尽调案卷</title>
<style>{_STYLE}{_EXTRA_STYLE}</style></head><body><div class="wrap">
<header>
  <p class="eyebrow">尽调案卷 · 关系核查报告</p>
  <h1>{_esc(view.get("name"))}</h1>
  <p class="subj">标的：<b>{_esc(subject)}</b>{auto_note}</p>
  <p class="vol">
    <span>材料 <b>{_esc(summary.get("materials", 0))}</b> 份</span>
    <span>直接结论 <b>{_esc(summary.get("relations_merged", 0))}</b> 条</span>
    <span>推断关联 <b>{_esc(summary.get("inferred", 0))}</b> 条</span>
    <span>生成于 {_esc(generated)}</span>
  </p>
  {f'<p class="meta">备注：{_esc(view.get("note"))}</p>' if view.get("note") else ""}
</header>
<h2>结果概览</h2><div class="cards">{card_html}</div>
<h2>材料清单</h2>
<table><thead><tr><th>材料</th><th>角色</th><th>字数</th><th>关系</th></tr></thead>
<tbody>{mat_rows}</tbody></table>
<h2>关系图</h2>{_graph_svg(view)}
<h2>直接结论（原文可查）</h2>
{_direct_table(direct)}
<p class="note">「支撑材料」是同一结论在几份材料里独立出现，比置信度更能说明分量。</p>
{_evidence_list(direct)}
{_inferred_html(inferred)}
{_ambiguity_html(ambiguities)}
<h2>方法与边界</h2>
<div class="disc">
<b>本报告怎么来的。</b>所有直接结论由本机规则引擎（词典 + 触发词 + 句式模板 + 类型约束）
从上述材料中抽出，每条都能回到具体材料的第几句；没有调用任何云端模型，材料未离开本机。
<b>推断结论的边界。</b>推断只做四类确定性图运算：控制链两跳、同一自然人任职、同一创始人、
同一具体地址。它们不是事实认定，不进入三元组，也不参与准确率评测。
<b>使用建议。</b>把「未闭环的疑点」当作下一轮要补的材料清单：单一来源的结论去要第二份文件，
说法冲突的先看两份文件的出具时间与主体，再决定采信哪一份。
</div>
<footer><span>由文本关系抽取与信息甄别系统 v2.1.0 生成 · 规则驱动，无外部 API</span>
<span>数据不出本机</span></footer>
</div></body></html>"""
