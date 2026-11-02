<template>
  <div class="annotator">
    <div class="legend">
      <button
        v-for="t in schema.entity_types || []"
        :key="t.key"
        class="legend-chip"
        :class="{ 'is-off': hidden.includes(t.key), 'is-empty': !typeCounts[t.key] }"
        type="button"
        @click="toggle(t.key)"
      >
        <i class="dot" :style="{ background: t.color }"></i>
        <span>{{ t.label }}</span>
        <b>{{ typeCounts[t.key] || 0 }}</b>
      </button>
      <span class="legend-tip">点击切换显示</span>
    </div>

    <div class="annotator-main">
      <div class="doc">
        <p class="doc-text">
          <template v-for="(seg, i) in segments" :key="i">
            <span v-if="!seg.type" class="plain">{{ seg.text }}</span>
            <span
              v-else
              :id="'ent-' + seg.key"
              class="ent"
              :class="{ 'is-flash': flashKey === seg.key, 'is-dim': hidden.includes(seg.type) }"
              :style="{
                '--c': seg.color,
                '--c-soft': seg.color + '1c',
                '--c-hover': seg.color + '30',
                '--c-line': seg.color + 'a6',
              }"
              :data-type="seg.typeLabel"
              @click="onEntityClick(seg)"
            >
              {{ seg.text }}
            </span>
          </template>
        </p>
      </div>

      <aside class="entity-side">
        <div class="side-head">
          <span>实体清单</span>
          <span class="side-count">{{ uniqueEntities.length }}</span>
        </div>
        <el-scrollbar class="side-scroll">
          <button
            v-for="e in uniqueEntities"
            :key="e.key"
            class="entity-row"
            :class="{ 'is-active': flashKey === e.key }"
            type="button"
            :title="aliasTitle(e)"
            @click="focusEntity(e.key)"
          >
            <i class="dot" :style="{ background: colorOf(e.type) }"></i>
            <span class="entity-text">
              <span class="entity-name">
                {{ e.text }}
                <i v-if="e.aliases.length > 1" class="merge-mark" aria-hidden="true"></i>
              </span>
              <span class="entity-meta">{{ labelOf(e.type) }} · {{ e.count }} 次</span>
            </span>
          </button>
          <el-empty v-if="!uniqueEntities.length" description="未识别到实体" :image-size="64" />
        </el-scrollbar>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  result: { type: Object, default: null },
  schema: { type: Object, default: () => ({}) },
})

const hidden = ref([])
const flashKey = ref('')

const typeMap = computed(() => {
  const map = {}
  for (const t of props.schema.entity_types || []) map[t.key] = t
  return map
})

function colorOf(type) {
  return typeMap.value[type]?.color || '#64748b'
}
function labelOf(type) {
  return typeMap.value[type]?.label || type
}

function toggle(key) {
  const i = hidden.value.indexOf(key)
  if (i >= 0) hidden.value.splice(i, 1)
  else hidden.value.push(key)
}

function keyOf(e) {
  // 以规范化名做键：同一机构的不同写法（腾讯控股 / 腾讯公司）归为一个节点
  return `${e.type}:${e.canonical || e.text}`
}

const segments = computed(() => {
  const data = props.result
  if (!data) return []
  const text = data.text || ''
  const ents = [...(data.entities || [])].sort((a, b) => a.start - b.start)
  const out = []
  let cursor = 0
  for (const e of ents) {
    if (e.start < cursor) continue
    if (e.start > cursor) out.push({ text: text.slice(cursor, e.start) })
    out.push({
      text: text.slice(e.start, e.end),
      type: e.type,
      color: colorOf(e.type),
      typeLabel: labelOf(e.type),
      key: keyOf(e),
    })
    cursor = e.end
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor) })
  return out
})

const typeCounts = computed(() => props.result?.entity_type_counts || {})

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

function focusEntity(key) {
  flashKey.value = key
  const el = document.getElementById('ent-' + key)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  window.setTimeout(() => {
    if (flashKey.value === key) flashKey.value = ''
  }, 2200)
}

function onEntityClick(seg) {
  flashKey.value = seg.key
  window.setTimeout(() => {
    if (flashKey.value === seg.key) flashKey.value = ''
  }, 1600)
}
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
  transition: background 0.15s ease, border-color 0.15s ease, opacity 0.15s ease;
}

.legend-chip:hover {
  background: var(--surface-3);
  border-color: var(--line-strong);
}

.legend-chip b {
  font-weight: 600;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  font-size: 11.5px;
}

.legend-chip.is-off {
  opacity: 0.4;
  text-decoration: line-through;
}

.legend-chip.is-empty {
  opacity: 0.45;
}

.legend-tip {
  margin-left: auto;
  font-size: 11px;
  color: var(--faint);
}

.dot {
  flex: none;
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 2px;
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
  padding: 16px 18px;
}

.doc-text {
  margin: 0;
  font-size: 14px;
  line-height: 2.1;
  color: var(--ink-2);
  letter-spacing: 0.2px;
}

.plain {
  white-space: pre-wrap;
}

/* 实体高亮：浅底色 + 下缘实色条，文字保持墨色，可读性优先 */
.ent {
  position: relative;
  padding: 1px 2px;
  margin: 0 -1px;
  border-radius: 3px;
  color: var(--ink);
  background: var(--c-soft);
  box-shadow: inset 0 -2px 0 var(--c-line);
  cursor: pointer;
  white-space: pre-wrap;
  transition: background 0.14s ease, box-shadow 0.14s ease;
}

.ent:hover {
  background: var(--c-hover);
  box-shadow: inset 0 -2px 0 var(--c);
}

/* hover 浮出类型标签，替代原先每个实体后面的小字 */
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
  transition: opacity 0.12s ease;
  z-index: 10;
}

.ent:hover::after {
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
  padding: 3px 6px;
  border: none;
  background: transparent;
  border-radius: var(--r-xs);
  font-family: inherit;
  font-size: 12px;
  color: var(--ink);
  cursor: pointer;
  text-align: left;
  transition: background 0.12s ease;
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
  display: flex;
  align-items: center;
  gap: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.35;
}

.entity-meta {
  font-size: 10.5px;
  line-height: 1.3;
  color: var(--faint);
  font-variant-numeric: tabular-nums;
}

/* 合并标记：该实体在原文中有多种写法，已归一 */
.merge-mark {
  flex: none;
  width: 5px;
  height: 5px;
  border-radius: 1px;
  background: var(--line-strong);
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
