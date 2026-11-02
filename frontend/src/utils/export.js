/**
 * 结果导出工具。
 *
 * 三种格式各自的用途：
 * - CSV  : 丢进 Excel 看，或导入 Neo4j / Gephi 做图分析（带 BOM 防中文乱码）
 * - JSON : 程序消费，保留实体、原文与全部统计字段
 * - MD   : 直接粘进报告 / 作业文档，含统计表、实体表、三元组表
 */

const BOM = '\ufeff'
const ILLEGAL_CHARS = /[\\/:*?"<>|\r\n]/g

const TYPE_LABEL = {
  PERSON: '人物',
  ORG: '组织机构',
  LOC: '地理位置',
  TIME: '时间',
  MONEY: '金额',
  PRODUCT: '产品技术',
}

function pad(n) {
  return String(n).padStart(2, '0')
}

export function stamp(date = new Date()) {
  return (
    `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}` +
    `-${pad(date.getHours())}${pad(date.getMinutes())}`
  )
}

/** 去掉文件名里的非法字符，并追加时间戳避免覆盖。 */
export function safeFilename(title, ext) {
  const base = String(title || '未命名')
    .replace(ILLEGAL_CHARS, '_')
    .trim()
    .slice(0, 48)
  return `${base || '未命名'}-${stamp()}.${ext}`
}

export function download(filename, content, mime) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

function csvCell(value) {
  const text = value == null ? '' : String(value)
  if (/[",\r\n]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`
  }
  return text
}

function mdCell(value) {
  return String(value == null ? '' : value)
    .replace(/\|/g, '\\|')
    .replace(/\r?\n/g, ' ')
}

export function buildCsv(result, meta) {
  const header = [
    'head',
    'head_canonical',
    'head_type',
    'relation',
    'relation_label',
    'tail',
    'tail_canonical',
    'tail_type',
    'confidence',
    'trigger',
    'evidence',
  ]
  const rows = (result.relations || []).map((r) => [
    r.head,
    r.head_canonical || r.head,
    r.head_type,
    r.relation,
    r.relation_label,
    r.tail,
    r.tail_canonical || r.tail,
    r.tail_type,
    r.confidence,
    r.trigger || '',
    r.evidence || '',
  ])
  const body = [header, ...rows].map((cols) => cols.map(csvCell).join(',')).join('\r\n')
  return {
    filename: safeFilename(`${meta.title}-三元组`, 'csv'),
    content: BOM + body + '\r\n',
  }
}

export function buildJson(result, meta) {
  const payload = {
    exported_at: new Date().toISOString(),
    record_id: meta.recordId ?? null,
    title: meta.title,
    stats: result.stats || {},
    entity_type_counts: result.entity_type_counts || {},
    relation_type_counts: result.relation_type_counts || {},
    entities: result.entities || [],
    relations: result.relations || [],
    text: result.text || '',
  }
  return {
    filename: safeFilename(meta.title, 'json'),
    content: JSON.stringify(payload, null, 2),
  }
}

export function buildMarkdown(result, meta) {
  const stats = result.stats || {}
  const entities = result.entities || []
  const relations = result.relations || []
  const lines = []

  lines.push(`# ${meta.title}`, '')
  lines.push(
    `> 由中文关系抽取系统生成 · ${new Date().toLocaleString('zh-CN')}` +
      (meta.recordId ? ` · 记录 #${meta.recordId}` : ''),
    '',
  )

  lines.push('## 概览', '', '| 指标 | 数值 |', '| --- | --- |')
  lines.push(`| 字符数 | ${stats.char_count ?? 0} |`)
  lines.push(`| 句子数 | ${stats.sentence_count ?? 0} |`)
  lines.push(`| 实体数 | ${stats.entity_count ?? 0}（去重 ${stats.unique_entity_count ?? '—'}） |`)
  lines.push(`| 关系数 | ${stats.relation_count ?? 0} |`)
  lines.push(`| 抽取耗时 | ${stats.elapsed_ms ?? 0} ms |`, '')

  if (entities.length) {
    lines.push('## 实体清单', '', '| 实体 | 规范化名 | 类型 | 置信度 |', '| --- | --- | --- | --- |')
    const seen = new Set()
    for (const e of entities) {
      const key = `${e.text}|${e.type}`
      if (seen.has(key)) continue
      seen.add(key)
      lines.push(
        `| ${mdCell(e.text)} | ${mdCell(e.canonical || e.text)} | ` +
          `${mdCell(e.type_label || TYPE_LABEL[e.type] || e.type)} | ${e.confidence ?? '—'} |`,
      )
    }
    lines.push('')
  }

  if (relations.length) {
    lines.push('## 关系三元组', '', '| 头实体 | 关系 | 尾实体 | 触发词 | 置信度 |', '| --- | --- | --- | --- | --- |')
    for (const r of relations) {
      lines.push(
        `| ${mdCell(r.head)} | ${mdCell(r.relation_label || r.relation)} | ` +
          `${mdCell(r.tail)} | ${mdCell(r.trigger || '—')} | ${r.confidence ?? '—'} |`,
      )
    }
    lines.push('')

    lines.push('## 抽取证据', '')
    for (const r of relations) {
      lines.push(`- **${r.head} — ${r.relation_label || r.relation} — ${r.tail}**`)
      if (r.evidence) lines.push(`  > ${r.evidence}`)
    }
    lines.push('')
  }

  if (result.text) {
    lines.push('## 原始文本', '', result.text, '')
  }

  return {
    filename: safeFilename(`${meta.title}-分析报告`, 'md'),
    content: lines.join('\n'),
  }
}
