/**
 * 实体归一与人工校正后的实体补全。
 *
 * 这些函数不依赖 Vue / DOM，方便用 Vitest 直接测试。
 */

const ORG_SUFFIXES = ['股份有限公司', '有限责任公司', '有限公司', '集团公司', '集团', '控股', '公司']

/** 与后端 canonical_name 保持一致：反复剥离机构后缀，至少保留 2 个字。 */
export function canonicalize(text, type) {
  if (type !== 'ORG') return text
  let result = text
  for (;;) {
    const suffix = ORG_SUFFIXES.find((s) => result.endsWith(s) && result.length - s.length >= 2)
    if (!suffix) return result
    result = result.slice(0, -suffix.length)
  }
}

export function entityKey(type, canonical, text) {
  return `${type}:${canonical || text}`
}

/** 找出 value 在 text 中的所有不重叠出现位置。 */
export function findOccurrences(text, value) {
  if (!text || !value) return []
  const spans = []
  let from = 0
  while (from <= text.length - value.length) {
    const idx = text.indexOf(value, from)
    if (idx < 0) break
    spans.push([idx, idx + value.length])
    from = idx + value.length
  }
  return spans
}

export function sentenceIndexAt(sentences, start) {
  const hit = (sentences || []).find(
    (s) => Number.isInteger(s.start) && Number.isInteger(s.end) && s.start <= start && start < s.end,
  )
  return hit ? hit.index : -1
}

/** 0 是合法的第一句；-1 / null / undefined 都表示未指定证据句。 */
export function hasSentenceIndex(row) {
  return Number.isInteger(row?.sentence_index) && row.sentence_index >= 0
}

export function normalizeSentenceIndex(value) {
  return Number.isInteger(value) && value >= 0 ? value : -1
}

/**
 * 人工校正可能引用自动识别没覆盖到的实体。这里按原文补实体，并重算
 * 实体数 / 类型分布，返回新的实体数组与统计，不修改入参。
 */
export function syncEntities({
  text = '',
  entities = [],
  sentences = [],
  relations = [],
  entityTypes = [],
  now = Date.now(),
}) {
  const base = entities.filter((e) => e.source !== 'manual')
  const occupied = base
    .filter((e) => Number.isInteger(e.start) && Number.isInteger(e.end))
    .map((e) => [e.start, e.end])
  const known = new Set(base.map((e) => entityKey(e.type, e.canonical, e.text)))
  const metaMap = new Map(entityTypes.map((t) => [t.key, t]))
  const added = []
  let seq = 0

  const consider = (value, type, canonical) => {
    if (!value || !type) return
    const key = entityKey(type, canonical, value)
    if (known.has(key)) return
    known.add(key)
    const meta = metaMap.get(type) || {}
    for (const [start, end] of findOccurrences(text, value)) {
      if (occupied.some(([s, e]) => start < e && s < end)) continue
      occupied.push([start, end])
      added.push({
        id: `manual-e${now}-${(seq += 1)}`,
        text: value,
        canonical: canonical || value,
        type,
        type_label: meta.label || type,
        color: meta.color || '#64748b',
        start,
        end,
        sentence_index: sentenceIndexAt(sentences, start),
        source: 'manual',
        confidence: 1,
      })
    }
  }

  for (const r of relations) {
    consider(r.head, r.head_type, r.head_canonical)
    consider(r.tail, r.tail_type, r.tail_canonical)
  }

  const merged = [...base, ...added].sort((a, b) => (a.start ?? 0) - (b.start ?? 0))
  const entityTypeCounts = {}
  for (const t of entityTypes) entityTypeCounts[t.key] = 0
  for (const e of merged) entityTypeCounts[e.type] = (entityTypeCounts[e.type] || 0) + 1

  return {
    entities: merged,
    entityTypeCounts,
    entityCount: merged.length,
    uniqueEntityCount: new Set(merged.map((e) => e.text)).size,
  }
}
