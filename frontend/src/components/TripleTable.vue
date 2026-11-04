<template>
  <div class="triples">
    <div class="triples-toolbar">
      <div class="tb-left">
        <el-select
          v-model="picked"
          multiple
          collapse-tags
          collapse-tags-tooltip
          clearable
          placeholder="全部关系类型"
          class="rel-select"
        >
          <el-option
            v-for="r in relationOptions"
            :key="r.key"
            :label="`${r.label}（${r.count}）`"
            :value="r.key"
          >
            <span class="opt">
              <i class="dot" :style="{ background: r.color }"></i>
              {{ r.label }}
              <b>{{ r.count }}</b>
            </span>
          </el-option>
        </el-select>

        <el-input
          v-model="keyword"
          placeholder="搜索实体 / 关系"
          clearable
          :prefix-icon="Search"
          class="kw"
        />

        <div class="conf">
          <span class="conf-label">置信度 ≥ {{ minConf.toFixed(2) }}</span>
          <el-slider v-model="minConf" :min="0.5" :max="0.99" :step="0.01" />
        </div>
      </div>

      <div class="tb-right">
        <span class="count"><b>{{ filtered.length }}</b> / {{ relations.length }} 条</span>
        <el-button :icon="Download" @click="exportCsv">导出 CSV</el-button>
      </div>
    </div>

    <div class="table-wrap">
      <el-table :data="filtered" height="100%" empty-text="没有符合条件的三元组">
        <el-table-column type="expand" width="30">
          <template #default="{ row }">
            <div class="evidence-block">
              <div class="evidence-quote">{{ row.evidence || '（无证据句）' }}</div>
              <div class="evidence-meta">
                <span class="meta-item">
                  <em>触发词</em>
                  <b>{{ row.trigger || '—' }}</b>
                </span>
                <span class="meta-item">
                  <em>抽取引擎</em>
                  <b>{{ ruleLabel(row.rule_base) }}</b>
                </span>
                <span class="meta-item">
                  <em>所在句</em>
                  <b>第 {{ (row.sentence_index ?? 0) + 1 }} 句</b>
                </span>
                <span class="meta-item">
                  <em>置信度</em>
                  <b>{{ (row.confidence * 100).toFixed(0) }}%</b>
                </span>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="头实体" min-width="150">
          <template #default="{ row }">
            <span class="cell-ent" :style="tagStyle(row.head_type)">{{ row.head }}</span>
            <span class="cell-type">{{ typeLabel(row.head_type) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="关系" width="106" align="center">
          <template #default="{ row }">
            <span class="rel-pill" :style="pillStyle(row.relation)">{{ row.relation_label }}</span>
          </template>
        </el-table-column>

        <el-table-column label="尾实体" min-width="150">
          <template #default="{ row }">
            <span class="cell-ent" :style="tagStyle(row.tail_type)">{{ row.tail }}</span>
            <span class="cell-type">{{ typeLabel(row.tail_type) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="置信度" width="118" sortable :sort-by="(r) => r.confidence">
          <template #default="{ row }">
            <div class="conf-cell">
              <el-progress
                :percentage="Math.round(row.confidence * 100)"
                :stroke-width="3"
                :show-text="false"
                :color="confColor(row.confidence)"
              />
              <span class="conf-num" :style="{ color: confColor(row.confidence) }">
                {{ (row.confidence * 100).toFixed(0) }}%
              </span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="触发词" width="96" align="center">
          <template #default="{ row }">
            <span class="trigger">{{ row.trigger || '—' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Search } from '@element-plus/icons-vue'

const props = defineProps({
  relations: { type: Array, default: () => [] },
  schema: { type: Object, default: () => ({}) },
})

const picked = ref([])
const keyword = ref('')
const minConf = ref(0.5)

const entityMap = computed(() => {
  const map = {}
  for (const t of props.schema.entity_types || []) map[t.key] = t
  return map
})

const relMap = computed(() => {
  const map = {}
  for (const r of props.schema.relation_types || []) map[r.key] = r
  return map
})

const relationOptions = computed(() => {
  const counter = new Map()
  for (const r of props.relations) counter.set(r.relation, (counter.get(r.relation) || 0) + 1)
  return [...counter.entries()]
    .map(([key, count]) => ({
      key,
      count,
      label: relMap.value[key]?.label || key,
      color: relMap.value[key]?.color || '#64748b',
    }))
    .sort((a, b) => b.count - a.count)
})

const filtered = computed(() => {
  const kw = keyword.value.trim()
  return props.relations.filter((r) => {
    if (picked.value.length && !picked.value.includes(r.relation)) return false
    if (r.confidence < minConf.value) return false
    if (!kw) return true
    return [r.head, r.tail, r.relation_label, r.evidence, r.trigger]
      .join(' ')
      .toLowerCase()
      .includes(kw.toLowerCase())
  })
})

function typeLabel(type) {
  return entityMap.value[type]?.label || type
}

function tagStyle(type) {
  const color = entityMap.value[type]?.color || '#64748b'
  return { color: 'var(--ink)', background: color + '14', borderColor: color + '33' }
}

function pillStyle(key) {
  const color = relMap.value[key]?.color || '#4f46e5'
  return { color, background: color + '12', borderColor: color + '33' }
}

/* 三档，而不是四档绿黄橙 */
function confColor(v) {
  if (v >= 0.9) return '#15803d'
  if (v >= 0.75) return '#b45309'
  return '#9aa1a9'
}

const RULE_LABEL = {
  pattern: '句式模板',
  trigger: '触发词',
  passive: '被动句',
  conjunction: '并列结构',
  postmodifier: '后置定语',
  attributive: '职位线索',
  coref: '指代消解',
}

function ruleLabel(base) {
  return RULE_LABEL[base] || base || '—'
}

function exportCsv() {
  if (!filtered.value.length) {
    ElMessage.warning('当前没有可导出的三元组')
    return
  }
  const header = ['头实体', '头实体类型', '关系', '尾实体', '尾实体类型', '置信度', '触发词', '证据句']
  const lines = filtered.value.map((r) => [
    r.head,
    typeLabel(r.head_type),
    r.relation_label,
    r.tail,
    typeLabel(r.tail_type),
    r.confidence.toFixed(2),
    r.trigger || '',
    r.evidence || '',
  ])
  const esc = (v) => `"${String(v).replace(/"/g, '""')}"`
  const csv = [header, ...lines].map((row) => row.map(esc).join(',')).join('\r\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `关系三元组_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success(`已导出 ${filtered.value.length} 条三元组`)
}
</script>

<style scoped>
.triples {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-height: 0;
}

/* ---------- 工具栏 ---------- */
.triples-toolbar {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.tb-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.rel-select {
  width: 190px;
}

.kw {
  width: 172px;
}

.conf {
  display: flex;
  align-items: center;
  gap: 9px;
}

.conf-label {
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.conf :deep(.el-slider) {
  width: 92px;
  --el-slider-height: 3px;
  --el-slider-button-size: 12px;
}

.tb-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.count {
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.count b {
  color: var(--ink);
  font-weight: 600;
  font-size: 12.5px;
}

.tb-left :deep(.el-input__wrapper),
.tb-right :deep(.el-button),
.tb-left :deep(.el-select__wrapper) {
  min-height: 28px;
  height: 28px;
  font-size: 12px;
  border-radius: var(--r-sm);
}

.tb-right :deep(.el-button) {
  padding: 0 10px;
}

.opt {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.opt b {
  color: var(--faint);
  font-weight: 500;
  font-size: 11px;
}

.dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 2px;
}

/* ---------- 表格 ---------- */
.table-wrap {
  flex: 1;
  min-height: 0;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  overflow: hidden;
  background: var(--surface);
}

.table-wrap :deep(.el-table) {
  --el-table-row-hover-bg-color: var(--surface-2);
  font-size: 12.5px;
}

.table-wrap :deep(.el-table th.el-table__cell) {
  height: 36px;
  padding: 0;
  font-size: 11.5px;
  font-weight: 500;
  color: var(--muted);
  letter-spacing: 0.2px;
  background: var(--surface-2);
}

.table-wrap :deep(.el-table td.el-table__cell) {
  height: 44px;
  padding: 0;
  border-bottom: 1px solid var(--line);
}

.table-wrap :deep(.el-table__cell .cell) {
  padding: 0 12px;
  line-height: 1.5;
}

.table-wrap :deep(.el-table__expand-icon) {
  width: 18px;
  height: 18px;
  margin-left: 6px;
  border-radius: var(--r-xs);
  font-size: 11px;
  color: var(--muted);
  transition: background 0.14s ease, color 0.14s ease;
}

.table-wrap :deep(.el-table__expand-icon:hover) {
  background: var(--surface-3);
  color: var(--ink);
}

.table-wrap :deep(.el-table__expand-icon--expanded) {
  color: var(--ink);
}

.table-wrap :deep(.el-table__expanded-cell) {
  padding: 0 !important;
  background: var(--surface-2);
}

.cell-ent {
  display: inline-block;
  padding: 1px 6px;
  border-radius: var(--r-xs);
  border: 1px solid transparent;
  font-size: 12.5px;
  font-weight: 500;
}

.cell-type {
  margin-left: 5px;
  font-size: 10.5px;
  color: var(--faint);
}

.rel-pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: var(--r-xs);
  border: 1px solid transparent;
  font-size: 11.5px;
  font-weight: 500;
  white-space: nowrap;
}

.conf-cell {
  display: flex;
  align-items: center;
  gap: 7px;
}

.conf-cell :deep(.el-progress) {
  flex: 1;
  min-width: 0;
}

.conf-num {
  flex: none;
  width: 28px;
  text-align: right;
  font-size: 11.5px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.trigger {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
  padding: 1px 6px;
  border-radius: var(--r-xs);
  font-size: 11px;
  color: var(--ink-2);
  background: var(--surface-3);
}

/* ---------- 展开区 ---------- */
.evidence-block {
  padding: 12px 16px 13px 46px;
  border-bottom: 1px solid var(--line);
}

.evidence-quote {
  padding-left: 10px;
  border-left: 2px solid var(--line-strong);
  font-size: 12.5px;
  line-height: 1.85;
  color: var(--ink-2);
  letter-spacing: 0.1px;
}

.evidence-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 10px;
  padding-left: 12px;
}

.meta-item {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  font-size: 11.5px;
}

.meta-item em {
  font-style: normal;
  color: var(--faint);
}

.meta-item b {
  font-weight: 500;
  color: var(--ink-2);
  font-variant-numeric: tabular-nums;
}
</style>
