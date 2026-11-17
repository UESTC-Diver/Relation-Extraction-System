# -*- coding: utf-8 -*-
"""生成单文件、无外部依赖的 HTML 报告。

不引 CDN、不写 JS、不嵌 base64 大图：所有内容（含关系网络 SVG）都在
一个 .html 里，双击即可离线打开，也能直接作为邮件附件发给别人。
"""

from __future__ import annotations

import html
import math
from datetime import datetime
from typing import Any

_STYLE = """
:root{--paper:#f6f3ea;--surface:#fffdf6;--shade:#ebe5d6;--ink:#1e1c18;
--ink2:#3c3830;--muted:#615d52;--red:#a8322a;--line:#ddd5c2}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
font-size:15px;line-height:1.7}
.wrap{max-width:960px;margin:0 auto;padding:48px 32px 72px}
header{border-bottom:2px solid var(--ink);padding-bottom:20px;margin-bottom:32px}
.eyebrow{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--red);margin:0 0 8px}
h1{font-size:32px;font-weight:500;line-height:1.25;margin:0 0 10px;letter-spacing:0}
.meta{font-size:13px;color:var(--muted)}
h2{font-size:20px;font-weight:500;margin:40px 0 14px;padding-left:12px;
border-left:3px solid var(--red)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;
background:var(--line);border:1px solid var(--line);border-radius:4px;overflow:hidden}
.card{background:var(--surface);padding:16px}
.card b{display:block;font-size:26px;font-weight:500;font-variant-numeric:tabular-nums}
.card span{font-size:12px;color:var(--muted)}
table{width:100%;border-collapse:collapse;background:var(--surface);
border:1px solid var(--line);font-size:13px}
th{text-align:left;font-weight:500;color:var(--muted);background:var(--shade);
padding:9px 12px;white-space:nowrap}
td{padding:9px 12px;border-top:1px solid var(--line);vertical-align:top}
tr:nth-child(even) td{background:#faf8f1}
.tag{display:inline-block;padding:1px 7px;border-radius:3px;background:var(--shade);
color:var(--ink2);font-size:12px}
.evidence{color:var(--muted);font-size:12px;line-height:1.55}
.doc{background:var(--surface);border:1px solid var(--line);padding:20px 24px;
white-space:pre-wrap;line-height:1.9;font-size:15px}
.graph{background:var(--surface);border:1px solid var(--line);padding:8px}
.note{font-size:12px;color:var(--muted);margin-top:8px}
.rv{border:1px solid var(--line);background:var(--surface);padding:14px 20px}
.rv-bar{font-size:12.5px;color:var(--muted);padding-bottom:8px}
.rv-item{padding:9px 0;border-top:1px solid var(--line);font-size:13px}
.rv-badge{display:inline-block;min-width:42px;padding:1px 7px;margin-right:10px;
border-radius:3px;font-size:11px;text-align:center}
.rv-ok{background:#e6f2e6;color:#2f6b3a}
.rv-q{background:#fdf0d5;color:#8a5a10}
.rv-no{background:#f7e2e0;color:#a8322a}
.rv-note{color:var(--muted);font-size:12px;margin-left:8px}
.ex-list{background:var(--surface);border:1px solid var(--line)}
.ex-item{padding:12px 16px;border-top:1px solid var(--line);font-size:12.5px;line-height:1.7}
.ex-item:first-child{border-top:none}
.ex-head{font-weight:500;color:var(--ink);margin-bottom:4px}
.ex-kv{color:var(--ink2)}
.ex-kv em{font-style:normal;color:var(--muted);display:inline-block;min-width:64px}
.ex-formula{color:var(--red);font-variant-numeric:tabular-nums}
footer{margin-top:56px;padding-top:16px;border-top:1px solid var(--line);
font-size:12px;color:var(--muted);display:flex;justify-content:space-between;gap:16px}
footer a{color:var(--red)}
@media print{body{background:#fff}.wrap{padding:0}h2{break-after:avoid}table{break-inside:auto}}
@media(max-width:600px){.wrap{padding:24px 16px}h1{font-size:24px}}
"""


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _graph_svg(relations: list[dict], limit: int = 12) -> str:
    """静态环形关系图：纯 SVG，不依赖 ECharts 或任何脚本。"""
    pairs: dict[tuple[str, str, str], int] = {}
    nodes: list[str] = []
    for r in relations:
        head = r.get("head_canonical") or r.get("head") or ""
        tail = r.get("tail_canonical") or r.get("tail") or ""
        if not head or not tail:
            continue
        if head not in nodes and len(nodes) < limit:
            nodes.append(head)
        if tail not in nodes and len(nodes) < limit:
            nodes.append(tail)
        if head in nodes and tail in nodes:
            key = (head, tail, _esc(r.get("relation_label", "")))
            pairs[key] = pairs.get(key, 0) + 1
    if len(nodes) < 2:
        return '<p class="note">关系节点不足，略过网络图。</p>'

    cx, cy, radius = 330, 190, 140
    pos = {}
    for i, name in enumerate(nodes):
        angle = -math.pi / 2 + 2 * math.pi * i / len(nodes)
        pos[name] = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))

    parts = [
        '<svg viewBox="0 0 660 380" width="100%" role="img" '
        'aria-label="关系网络示意图" style="display:block">'
    ]
    for (head, tail, label), cnt in list(pairs.items())[:40]:
        x1, y1 = pos[head]
        x2, y2 = pos[tail]
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            'stroke="#c4bba6" stroke-width="1"/>'
        )
        if label:
            parts.append(
                f'<text x="{(x1 + x2) / 2:.1f}" y="{(y1 + y2) / 2 - 4:.1f}" '
                'text-anchor="middle" font-size="10" fill="#a8322a">'
                f'{_esc(label)}</text>'
            )
    for name, (x, y) in pos.items():
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="#fffdf6" '
            'stroke="#a8322a" stroke-width="1.5"/>'
        )
        label = name if len(name) <= 8 else name[:7] + "…"
        parts.append(
            f'<text x="{x:.1f}" y="{y + 24:.1f}" text-anchor="middle" '
            f'font-size="12" fill="#1e1c18">{_esc(label)}</text>'
        )
    parts.append("</svg>")
    return '<div class="graph">' + "".join(parts) + "</div>"


_REVIEW_STATUS = {"draft": "草稿", "in_review": "复核中", "final": "已定稿"}
_REVIEW_LABEL = {
    "approved": "通过", "questioned": "存疑", "rejected": "驳回", "pending": "待复核",
}
_REVIEW_CLS = {"approved": "rv-ok", "questioned": "rv-q", "rejected": "rv-no"}


def _review_html(review: dict | None) -> str:
    """把人工复核结论渲染成独立区块；草稿且无结论时整段不出现。"""
    if not review:
        return ""
    summary = review.get("summary") or {}
    bar = (
        f"状态：{_esc(_REVIEW_STATUS.get(review.get('status'), '草稿'))}"
        f" · 已复核 {_esc(summary.get('reviewed', 0))}/{_esc(summary.get('total', 0))}"
        f" · 通过 {_esc(summary.get('approved', 0))}"
        f" · 存疑 {_esc(summary.get('questioned', 0))}"
        f" · 驳回 {_esc(summary.get('rejected', 0))}"
    )
    rows = []
    for item in review.get("relations") or []:
        decision = item.get("decision", "pending")
        label = _esc(_REVIEW_LABEL.get(decision, "待复核"))
        cls = _REVIEW_CLS.get(decision, "")
        head = _esc(item.get("head"))
        relation = _esc(item.get("relation_label"))
        tail = _esc(item.get("tail"))
        note = item.get("review_note") or ""
        note_html = f'<span class="rv-note">批注：{_esc(note)}</span>' if note else ""
        rows.append(
            f'<div class="rv-item"><span class="rv-badge {cls}">{label}</span>'
            f"{head} — {relation} — {tail}{note_html}</div>"
        )
    body = "".join(rows) or '<div class="rv-item">还没有逐条结论</div>'
    return f'<h2>复核结论</h2><div class="rv"><div class="rv-bar">{bar}</div>{body}</div>'


def _explanation_html(relations: list[dict]) -> str:
    """「为什么抽出来」：把每条关系的命中路径与置信度构成写进离线报告。"""
    from .nlp.explanation import explain

    rows = []
    for r in relations:
        exp = r.get("explanation") or explain(r)
        parts = exp.get("confidence_parts") or {}
        template = exp.get("template")
        template_html = (
            f'<div class="ex-kv"><em>命中模板</em>{_esc(template)}</div>' if template else ""
        )
        rows.append(
            '<div class="ex-item">'
            f'<div class="ex-head">{_esc(r.get("head"))} — '
            f'{_esc(r.get("relation_label") or r.get("relation"))} — '
            f'{_esc(r.get("tail"))}</div>'
            f'<div class="ex-kv"><em>抽取策略</em>{_esc(exp.get("strategy"))}'
            f'（{_esc(exp.get("strategy_how"))}）</div>'
            f'<div class="ex-kv"><em>命中触发词</em>{_esc(exp.get("matched"))}</div>'
            f'{template_html}'
            f'<div class="ex-kv"><em>类型约束</em>{_esc(exp.get("type_constraint"))}</div>'
            f'<div class="ex-kv"><em>置信度</em>'
            f'<span class="ex-formula">{_esc(parts.get("formula", ""))}</span></div>'
            "</div>"
        )
    if not rows:
        return ""
    return (
        "<h2>为什么抽出来</h2>"
        '<p class="note">每条关系列出命中的策略、触发词、类型约束与置信度构成；'
        "句式模板命中会额外给出模板骨架。</p>"
        f'<div class="ex-list">{"".join(rows)}</div>'
    )


def build_report_html(
    data: dict, readonly_link: bool = False, review: dict | None = None
) -> str:
    stats = data.get("stats") or {}
    relations = data.get("relations") or []
    entities = data.get("entities") or []
    title = data.get("title") or "未命名文本"
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    record_id = data.get("record_id") or data.get("id")

    cards = [
        ("字数", stats.get("char_count", 0)),
        ("句子", stats.get("sentence_count", 0)),
        ("实体", stats.get("entity_count", len(entities))),
        ("关系", stats.get("relation_count", len(relations))),
        ("耗时", f"{stats.get('elapsed_ms', 0)} ms"),
    ]
    card_html = "".join(
        f'<div class="card"><b>{_esc(v)}</b><span>{_esc(k)}</span></div>' for k, v in cards
    )

    counts: dict[str, int] = {}
    for r in relations:
        label = r.get("relation_label") or r.get("relation") or ""
        counts[label] = counts.get(label, 0) + 1
    dist_html = "".join(
        f"<tr><td>{_esc(label)}</td><td>{cnt}</td></tr>"
        for label, cnt in sorted(counts.items(), key=lambda kv: -kv[1])
    ) or '<tr><td colspan="2">本次未抽出关系</td></tr>'

    rel_rows = "".join(
        "<tr>"
        f"<td>{_esc(r.get('head'))}</td>"
        f"<td><span class=\"tag\">{_esc(r.get('relation_label') or r.get('relation'))}</span></td>"
        f"<td>{_esc(r.get('tail'))}</td>"
        f"<td>{_esc(round(float(r.get('confidence') or 0), 2))}</td>"
        f"<td class=\"evidence\">{_esc(r.get('evidence'))}</td>"
        "</tr>"
        for r in relations
    ) or '<tr><td colspan="5">本次未抽出关系</td></tr>'

    ent_rows = "".join(
        f"<tr><td>{_esc(e.get('text'))}</td>"
        f"<td><span class=\"tag\">{_esc(e.get('type'))}</span></td>"
        f"<td>{_esc(e.get('canonical') or e.get('text'))}</td></tr>"
        for e in entities[:200]
    ) or '<tr><td colspan="3">本次未识别到实体</td></tr>'

    footer_right = (
        f'<a href="/app?record={_esc(record_id)}">在工作台打开 →</a>'
        if readonly_link and record_id
        else "本机处理 · 数据不出本机"
    )
    review_html = _review_html(review)
    explanation_html = _explanation_html(relations)
    profile_label = data.get("profile_label") or ""
    profile_note = f" · 领域包：{_esc(profile_label)}" if profile_label else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} · 关系抽取报告</title>
<style>{_STYLE}</style></head><body><div class="wrap">
<header>
  <p class="eyebrow">中文关系抽取系统 · 分析报告</p>
  <h1>{_esc(title)}</h1>
  <p class="meta">生成于 {_esc(generated)}
  {f'· 历史记录 #{_esc(record_id)}' if record_id else '· 预览结果（未入库）'}{profile_note}</p>
</header>
<h2>结果概览</h2><div class="cards">{card_html}</div>
{review_html}
<h2>关系网络</h2>{_graph_svg(relations)}
<p class="note">静态示意图，按归一化后的实体合并；完整可交互图谱请在工作台查看。</p>
<h2>关系类型分布</h2>
<table><thead><tr><th>关系类型</th><th>条数</th></tr></thead><tbody>{dist_html}</tbody></table>
<h2>关系三元组与证据句</h2>
<table><thead><tr><th>头实体</th><th>关系</th><th>尾实体</th><th>置信度</th><th>证据句</th></tr></thead>
<tbody>{rel_rows}</tbody></table>
{explanation_html}
<h2>实体清单</h2>
<table><thead><tr><th>原文写法</th><th>类型</th><th>归一写法</th></tr></thead>
<tbody>{ent_rows}</tbody></table>
<h2>原文</h2><div class="doc">{_esc(data.get('text', ''))}</div>
<footer><span>由中文关系抽取系统生成 · 规则驱动，无外部 API</span><span>{footer_right}</span></footer>
</div></body></html>"""
