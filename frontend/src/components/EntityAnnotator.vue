<template>
  <div class="annotator">
    <div class="legend" role="group" aria-label="按实体类型筛选高亮">
      <button
        v-for="t in schema.entity_types || []"
        :key="t.key"
        class="legend-chip"
        :class="{ 'is-off': hidden.includes(t.key), 'is-empty': !typeCounts[t.key] }"
        type="button"
        :disabled="!typeCounts[t.key]"
        :aria-pressed="hidden.includes(t.key) ? 'false' : 'true'"
        :aria-label="`${t.label}，${typeCounts[t.key] || 0} 个${hidden.includes(t.key) ? '，已隐藏' : ''}`"
        @click="toggle(t.key)"
      >
        <i class="dot" :class="{ 'is-hollow': hidden.includes(t.key) }" :style="{ '--c': t.color }"></i>
        <span>{{ t.label }}</span>
        <b>{{ typeCounts[t.key] || 0 }}</b>
      </button>
      <span class="legend-tip">点击类型可隐藏／恢复高亮</span>
    </div>

    <div class="annotator-main">
      <div ref="docRef" class="doc">
        <p
          v-for="block in blocks"
          :key="block.start"
          class="sent"
          :class="{ 'is-focus': focusIndex === block.index && block.index >= 0 }"
          :data-idx="block.index"
        >
          <template v-for="(seg, i) in block.segs" :key="i">
            <span v-if="!seg.type" class="plain">{{ seg.text }}</span>
            <button
              v-else
              type="button"
              class="ent"
              :class="{ 'is-flash': flashKey === seg.key, 'is-dim': hidden.includes(seg.type) }"
              :style="{
                '--c': seg.color,
                '--c-soft': seg.color + '1c',
                '--c-hover': seg.color + '30',
                '--c-line': seg.color + 'a6',
              }"
              :data-type="seg.typeLabel"
              :data-key="seg.key"
              :aria-label="`${seg.text}，实体类型${seg.typeLabel}，回车定位到实体清单`"
              @click="onEntityClick(seg)"
            >{{ seg.text }}</button>
          </template>
          <button
            v-if="block.relCount"
            class="sent-badge"
            type="button"
            :aria-label="`第 ${block.index + 1} 句，含 ${block.relCount} 条关系，点击查看`"
            @click="onSentenceClick(block)"
          >{{ block.relCount }} 条关系</button>
        </p>

        <el-empty v-if="!hasText" description="没有可展示的原文" :image-size="64" />
      </div>

      <aside class="entity-side" aria-label="实体清单">
        <div class="side-head">
          <span>实体清单</span>
          <span class="side-count">{{ uniqueEntities.length }}</span>
        </div>
        <el-scrollbar ref="sideScrollRef" class="side-scroll">
          <button
            v-for="e in uniqueEntities"
            :key="e.key"
            class="entity-row"
            :class="{ 'is-active': flashKey === e.key }"
            type="button"
            :data-ekey="e.key"
            :aria-pressed="flashKey === e.key ? 'true' : 'false'"
            :title="aliasTitle(e)"
            @click="focusEntity(e.key)"
          >
            <i class="dot" :style="{ '--c': colorOf(e.type) }"></i>
            <span class="entity-text">
              <span class="entity-name">{{ e.text }}</span>
              <span class="entity-meta">
                {{ labelOf(e.type) }} · {{ e.count }} 次
                <template v-if="e.aliases.length > 1"> · {{ e.aliases.length }} 种写法</template>
              </span>
            </span>
          </button>
          <el-empty v-if="!uniqueEntities.length" description="未识别到实体" :image-size="64" />
        </el-scrollbar>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  result: { type: Object, default: null },
  schema: { type: Object, default: () => ({}) },
  link: { type: Object, default: null },
})

const hidden = ref([])
const flashKey = ref('')
const focusIndex = ref(-1)
const docRef = ref(null)
const sideScrollRef = ref(null)
let flashTimer = 0
let focusTimer = 0

const typeMap = computed(() => {
  const map = {}
  for (const t of props.schema.entity_types || []) map[t.key] = t
  return map
})

function colorOf(type) {
  return typeMap.value[type]?.color || '#6b7280'
}
function labelOf(type) {
  return typeMap.value[type]?.label || type
}

const hasText = computed(() => Boolean(props.result?.text))
const typeCounts = computed(() => props.result?.entity_type_counts || {})

function toggle(key) {
  if (!typeCounts.value[key]) return
  const i = hidden.value.indexOf(key)
  if (i >= 0) hidden.value.splice(i, 1)
  else hidden.value.push(key)
}

function keyOf(e) {
  // 以规范化名做键：同一机构的不同写法（腾讯控股 / 腾讯公司）归为一个节点
  return `${e.type}:${e.canonical || e.text}`
}

/* ---------- 正文切分：先按实体切片，再按句子成块 ---------- */
const segments = computed(() => {
  const data = props.result
  if (!data) return []
  const text = data.text || ''
  const ents = [...(data.entities || [])].sort((a, b) => a.start - b.start)
  const out = []
  let cursor = 0
  for (const e of ents) {
    if (e.start < cursor) continue
    if (e.start > cursor) {
      out.push({ text: text.slice(cursor, e.start), start: cursor, end: e.start })
    }
    out.push({
      text: text.slice(e.start, e.end),
      start: e.start,
      end: e.end,
      type: e.type,
      color: colorOf(e.type),
      typeLabel: labelOf(e.type),
      key: keyOf(e),
    })
    cursor = e.end
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor), start: cursor, end: text.length })
  return out
})

/**
 * 句子区间。优先用后端给的 start/end 偏移；
 * 历史记录重建的 sentences 没有偏移，退回「按原文顺序匹配」；
 * 两条路都失败就整体返回 null，正文退化为单块渲染 —— 永远保留降级路径。
 */
const sentRanges = computed(() => {
  const data = props.result
  const text = data?.text || ''
  const sents = data?.sentences || []
  if (!sents.length) return null

  const hasOffsets = sents.every(
    (s) => Number.isInteger(s.start) && Number.isInteger(s.end) && s.end > s.start,
  )

  const out = []
  if (hasOffsets) {
    let cursor = 0
    for (const s of sents) {
      // 出现重叠或倒序说明数据不可信，直接放弃句子级渲染
      if (s.start < cursor || s.end > text.length) return null
      out.push({ index: s.index, start: s.start, end: s.end })
      cursor = s.end
    }
    return out
  }

  let cursor = 0
  for (const s of sents) {
    if (!s.text) return null
    const at = text.indexOf(s.text, cursor)
    if (at < 0) return null
    out.push({ index: s.index, start: at, end: at + s.text.length })
    cursor = at + s.text.length
  }
  return out
})

function sliceSegs(segs, start, end) {
  const out = []
  for (const s of segs) {
    if (s.end <= start || s.start >= end) continue
    const a = Math.max(s.start, start)
    const b = Math.min(s.end, end)
    out.push({ ...s, text: s.text.slice(a - s.start, b - s.start) })
  }
  return out
}

const relBySentence = computed(() => {
  const map = {}
  for (const r of props.result?.relations || []) {
    map[r.sentence_index] = (map[r.sentence_index] || 0) + 1
  }
  return map
})

const blocks = computed(() => {
  const data = props.result
  if (!data) return []
  const text = data.text || ''
  const segs = segments.value
  const ranges = sentRanges.value

  const make = (index, start, end) => ({
    index,
    start,
    end,
    segs: sliceSegs(segs, start, end),
    relCount: index >= 0 ? relBySentence.value[index] || 0 : 0,
  })

  if (!ranges) return [make(-1, 0, text.length)]

  const out = []
  let cursor = 0
  for (const r of ranges) {
    if (r.start > cursor) out.push(make(-1, cursor, r.start))
    out.push(make(r.index, r.start, r.end))
    cursor = r.end
  }
  if (cursor < text.length) out.push(make(-1, cursor, text.length))
  return out.filter((b) => b.segs.length)
})

const uniqueEntities = computed(() => {
  const map = new Map()
  for (const e of props.result?.entities || []) {
    const key = keyOf(e)
    const hit = map.get(key)
    if (hit) {
      hit.count += 1
      if (!hit.aliases.includes(e.text)) hit.aliases.push(e.text)
    } else {
      map.set(key, {
        key,
        text: e.canonical || e.text,
        type: e.type,
        count: 1,
        aliases: [e.text],
      })
    }
  }
  return [...map.values()].sort((a, b) => b.count - a.count || a.text.localeCompare(b.text, 'zh'))
})

/** 悬停提示：类型、出现次数，以及被合并掉的其他写法。 */
function aliasTitle(e) {
  const base = `${labelOf(e.type)} · 出现 ${e.count} 次`
  return e.aliases.length > 1 ? `${base}｜已合并写法：${e.aliases.join('、')}` : base
}

const reducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

function scrollTo(selector) {
  const el = docRef.value?.querySelector(selector)
  if (el) {
    el.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'center' })
  }
  return el
}

function focusEntity(key) {
  flashKey.value = key
  scrollTo(`[data-key="${CSS.escape(key)}"]`)
  clearTimeout(flashTimer)
  flashTimer = window.setTimeout(() => {
    if (flashKey.value === key) flashKey.value = ''
  }, 2400)
}

function onEntityClick(seg) {
  flashKey.value = seg.key
  // 反向同步：正文点实体 → 实体清单滚到对应条目
  nextTick(() => {
    const row = sideScrollRef.value?.wrapRef?.querySelector(`[data-ekey="${CSS.escape(seg.key)}"]`)
    row?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'nearest' })
  })
  clearTimeout(flashTimer)
  flashTimer = window.setTimeout(() => {
    if (flashKey.value === seg.key) flashKey.value = ''
  }, 1800)
}

/** 句子角标：由父级决定跳到三元组还是停在本页（当前直接高亮本句） */
const emit = defineEmits(['locate'])
function onSentenceClick(block) {
  focusIndex.value = block.index
  if (block.index >= 0) emit('locate', block.index)
}

/* 【创新点 1】外部（三元组行 / 统计页句子明细）要求定位证据句 */
watch(
  () => props.link,
  (value) => {
    if (!value || value.kind !== 'sentence') return
    focusIndex.value = value.value
    nextTick(() => {
      scrollTo(`[data-idx="${value.value}"]`)
    })
    clearTimeout(focusTimer)
    focusTimer = window.setTimeout(() => {
      focusIndex.value = -1
    }, 2600)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  clearTimeout(flashTimer)
  clearTimeout(focusTimer)
})
</script>

<style scoped>
.annotator {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-height: 0;
}

/* ---------- 图例 ---------- */
.legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  flex: none;
}

.legend-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 24px;
  padding: 0 8px;
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: var(--r-sm);
  font-family: inherit;
  font-size: 11.5px;
  line-height: 1;
  color: var(--ink-2);
  cursor: pointer;
  transition: background var(--dur-press) var(--ease), border-color var(--dur-press) var(--ease), opacity var(--dur-press) var(--ease);
}

.legend-chip:hover:not(:disabled) {
  background: var(--surface-3);
  border-color: var(--line-strong);
}

.legend-chip b {
  font-weight: 600;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  font-size: 11.5px;
}

/* 已隐藏：虚线框 + 空心点，与「本来就没有实体」区分开 */
.legend-chip.is-off {
  border-style: dashed;
  border-color: var(--line-strong);
  background: var(--surface-3);
  color: var(--muted);
}

.legend-chip.is-off b {
  color: var(--muted);
  font-weight: 500;
}

/* 该类型没有实体：不可点，数字为 0 */
.legend-chip.is-empty {
  opacity: 0.55;
  cursor: not-allowed;
}

.legend-tip {
  margin-left: auto;
  font-size: 11px;
  color: var(--muted);
}

.dot {
  flex: none;
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 2px;
  background: var(--c);
}

.dot.is-hollow {
  background: transparent;
  box-shadow: inset 0 0 0 1.5px var(--c);
}

/* ---------- 正文 + 侧栏 ---------- */
.annotator-main {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 248px;
  gap: 10px;
}

.doc {
  min-height: 0;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
  padding: 6px 18px 16px;
}

/* 一句一段：句子级高亮与「N 条关系」角标都依附于它 */
.sent {
  position: relative;
  margin: 0;
  padding: 7px 10px 7px 12px;
  border-left: 2px solid transparent;
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
  font-size: 14px;
  line-height: 1.95;
  color: var(--ink-2);
  letter-spacing: 0.2px;
  transition: background var(--dur-swap) var(--ease), border-color var(--dur-swap) var(--ease);
}

.sent:hover {
  background: var(--surface-2);
}

.sent.is-focus {
  background: #faf1ee;
  border-left-color: var(--accent);
}
/* 证据定位的完成反馈，与首页 lpDraw / 工作台扫光共用同一条曲线与朱色 */
.sent.is-focus::after {
  content: '';
  position: absolute;
  left: 2px;
  right: 0;
  bottom: 2px;
  height: 2px;
  background: var(--brand-red);
  transform-origin: left;
  animation: appRule var(--dur-color) var(--ease) both;
  pointer-events: none;
}

.plain {
  white-space: pre-wrap;
}

/* 实体高亮：浅底色 + 下缘实色条，文字保持墨色，可读性优先。
   用 button 是为了键盘可达；line-height 压到 1.5 让它的盒子高度
   不超过段落行盒（1.95），否则内联块会把行距顶开 */
.ent {
  position: relative;
  display: inline;
  padding: 1px 2px;
  margin: 0 -1px;
  border: none;
  border-radius: 3px;
  font-family: inherit;
  font-size: inherit;
  line-height: 1.5;
  text-align: inherit;
  color: var(--ink);
  background: var(--c-soft);
  box-shadow: inset 0 -2px 0 var(--c-line);
  cursor: pointer;
  white-space: pre-wrap;
  transition: background var(--dur-press) var(--ease), box-shadow var(--dur-press) var(--ease);
}

.ent:hover {
  background: var(--c-hover);
  box-shadow: inset 0 -2px 0 var(--c);
}

/* hover / 键盘聚焦时浮出类型标签；读屏另有 aria-label */
.ent::after {
  content: attr(data-type);
  position: absolute;
  left: 50%;
  bottom: calc(100% + 5px);
  transform: translateX(-50%);
  padding: 2px 6px;
  border-radius: var(--r-xs);
  font-size: 10px;
  font-weight: 500;
  line-height: 1.5;
  letter-spacing: 0.2px;
  white-space: nowrap;
  color: #fff;
  background: var(--c);
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--dur-press) var(--ease);
  z-index: 10;
}

.ent:hover::after,
.ent:focus-visible::after {
  opacity: 1;
}

.ent.is-dim {
  background: transparent;
  box-shadow: inset 0 -2px 0 var(--line-strong);
  color: var(--muted);
}

.ent.is-flash {
  background: var(--c-hover);
  box-shadow: inset 0 -2px 0 var(--c), 0 0 0 3px var(--c-soft);
}

/* 句子角标：这一句抽出了几条关系 */
.sent-badge {
  margin-left: 6px;
  padding: 0 6px;
  height: 17px;
  font-family: inherit;
  font-size: 10.5px;
  line-height: 17px;
  color: var(--ink-2);
  background: var(--surface-3);
  border: 1px solid var(--line);
  border-radius: var(--r-xs);
  cursor: pointer;
  vertical-align: baseline;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  transition: background var(--dur-press) var(--ease), border-color var(--dur-press) var(--ease), color var(--dur-press) var(--ease);
}

.sent-badge:hover {
  background: #f7e9e7;
  border-color: #e4aca7;
  color: #8f2a23;
}

/* ---------- 实体清单 ---------- */
.entity-side {
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
  overflow: hidden;
}

.side-head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 10px;
  height: 34px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ink-2);
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
}

.side-count {
  font-weight: 400;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.side-scroll {
  flex: 1;
  min-height: 0;
  padding: 4px;
}

.entity-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 7px;
  min-height: 34px;
  padding: 4px 6px;
  border: none;
  background: transparent;
  border-radius: var(--r-xs);
  font-family: inherit;
  font-size: 12px;
  color: var(--ink);
  cursor: pointer;
  text-align: left;
  transition: background var(--dur-press) var(--ease);
}

.entity-row:hover {
  background: var(--surface-3);
}

.entity-row.is-active {
  background: var(--surface-3);
  box-shadow: inset 2px 0 0 var(--brand);
}

/* 名称独占一行，类型与次数降到第二行，避免长机构名被截断 */
.entity-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.entity-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.35;
}

.entity-meta {
  font-size: 10.5px;
  line-height: 1.3;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 900px) {
  .annotator-main {
    grid-template-columns: minmax(0, 1fr);
  }
  .entity-side {
    max-height: 200px;
  }
}
</style>
