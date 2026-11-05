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
          aria-label="按关系类型筛选"
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
          aria-label="搜索实体或关系"
          class="kw"
        />

        <div class="conf-seg" role="group" aria-label="按置信度筛选">
          <button
            v-for="p in CONF_PRESETS"
            :key="p.value"
            class="conf-item"
            :class="{ 'is-active': minConf === p.value }"
            type="button"
            :aria-pressed="minConf === p.value ? 'true' : 'false'"
            @click="minConf = p.value"
          >
            {{ p.label }}
          </button>
        </div>

        <button
          v-if="entityFilter"
          class="filter-chip"
          type="button"
          :title="`取消「${entityFilter.name}」筛选`"
          @click="emit('clear-filter')"
        >
          实体：{{ entityFilter.name }}
          <el-icon :size="11"><Close /></el-icon>
        </button>
      </div>

      <div class="tb-right">
        <span v-if="dirty" class="dirty-flag">未保存</span>
        <span class="count"><b>{{ filtered.length }}</b> / {{ relations.length }} 条</span>
        <el-button :icon="Plus" @click="openAdd">新增</el-button>
        <el-button
          type="primary"
          :icon="Check"
          :loading="saving"
          :disabled="!dirty || !recordId"
          :title="recordId ? '保存校正到历史记录' : '请先存入历史'"
          @click="emit('save')"
        >
          保存校正
        </el-button>
        <el-button :icon="Download" @click="exportCsv">导出 CSV</el-button>
      </div>
    </div>

    <div class="table-wrap">
      <el-table
        :data="filtered"
        height="100%"
        :empty-text="emptyText"
        row-key="_rid"
      >
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

        <el-table-column label="关系" width="132" align="center">
          <template #default="{ row }">
            <span class="rel-pill" :style="pillStyle(row.relation)">{{ row.relation_label }}</span>
            <span v-if="row.rule_base === 'manual'" class="manual-tag">人工</span>
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

        <el-table-column label="操作" width="150" align="center">
          <template #default="{ row }">
            <div class="row-actions">
              <button
                class="locate-btn"
                type="button"
                :aria-label="`定位第 ${(row.sentence_index ?? 0) + 1} 句证据句`"
                :title="`第 ${(row.sentence_index ?? 0) + 1} 句 · 跳到原文`"
                @click="emit('locate', row.sentence_index)"
              >
                原文
              </button>
              <el-button link size="small" @click="openEdit(row)">编辑</el-button>
              <el-popconfirm
                title="删除这条三元组？"
                confirm-button-text="删除"
                cancel-button-text="取消"
                @confirm="remove(row)"
              >
                <template #reference>
                  <el-button link size="small" class="r-del">删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogOpen"
      :title="editingIndex !== null ? '编辑三元组' : '新增三元组'"
      width="580px"
      append-to-body
      class="triple-dialog"
    >
      <el-form label-width="86px" class="triple-form" @submit.prevent>
        <div class="form-grid">
          <el-form-item label="头实体">
            <el-input v-model="form.head" maxlength="64" placeholder="实体名称" />
          </el-form-item>
          <el-form-item label="头实体类型">
            <el-select v-model="form.head_type">
              <el-option v-for="t in typeOptions" :key="t.key" :label="t.label" :value="t.key" />
            </el-select>
          </el-form-item>
          <el-form-item label="关系">
            <el-select v-model="form.relation">
              <el-option v-for="r in schema.relation_types || []" :key="r.key" :label="r.label" :value="r.key" />
            </el-select>
          </el-form-item>
          <el-form-item label="尾实体">
            <el-input v-model="form.tail" maxlength="64" placeholder="实体名称" />
          </el-form-item>
          <el-form-item label="尾实体类型">
            <el-select v-model="form.tail_type">
              <el-option v-for="t in typeOptions" :key="t.key" :label="t.label" :value="t.key" />
            </el-select>
          </el-form-item>
          <el-form-item label="证据句">
            <el-select
              v-model="form.sentence_index"
              clearable
              placeholder="选择原文句子（可选）"
              @change="onSentencePick"
            >
              <el-option
                v-for="s in sortedSentences"
                :key="s.index"
                :label="`第 ${s.index + 1} 句 · ${shortText(s.text)}`"
                :value="s.index"
              />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="证据文本">
          <el-input
            v-model="form.evidence"
            type="textarea"
            :rows="2"
            placeholder="选择句子后可自动带入，也可手工填写"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" @click="confirm">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Close, Download, Plus, Search } from '@element-plus/icons-vue'

const props = defineProps({
  relations: { type: Array, default: () => [] },
  schema: { type: Object, default: () => ({}) },
  entityFilter: { type: Object, default: null },
  sentences: { type: Array, default: () => [] },
  recordId: { type: Number, default: null },
  dirty: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
})

const emit = defineEmits(['locate', 'clear-filter', 'update:relations', 'save'])

const picked = ref([])
const keyword = ref('')
const minConf = ref(0)

const CONF_PRESETS = [
  { value: 0, label: '全部' },
  { value: 0.75, label: '≥ 0.75' },
  { value: 0.9, label: '≥ 0.90' },
]

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
      color: relMap.value[key]?.color || '#6b7280',
    }))
    .sort((a, b) => b.count - a.count)
})

const typeOptions = computed(() => props.schema.entity_types || [])
const sortedSentences = computed(() => [...props.sentences].sort((a, b) => a.index - b.index))

function emptyForm() {
  return {
    head: '',
    head_type: 'ORG',
    relation: props.schema.relation_types?.[0]?.key || 'acquire',
    tail: '',
    tail_type: 'ORG',
    sentence_index: null,
    evidence: '',
  }
}

const dialogOpen = ref(false)
const editingIndex = ref(null)
const form = ref(emptyForm())

const ORG_SUFFIXES = ['股份有限公司', '有限责任公司', '有限公司', '集团公司', '集团', '控股', '公司']

/** 与后端 canonical_name 保持一致，保存前导出的 CSV 也使用规范化名。 */
function canonicalize(text, type) {
  if (type !== 'ORG') return text
  let result = text
  for (;;) {
    const suffix = ORG_SUFFIXES.find((s) => result.endsWith(s) && result.length - s.length >= 2)
    if (!suffix) return result
    result = result.slice(0, -suffix.length)
  }
}

function shortText(text) {
  const value = String(text || '').replace(/\s+/g, ' ').trim()
  return value.length > 30 ? `${value.slice(0, 30)}…` : value
}

function onSentencePick(index) {
  if (index == null) return
  const sentence = props.sentences.find((s) => s.index === index)
  if (sentence) form.value.evidence = sentence.text
}

function openAdd() {
  editingIndex.value = null
  form.value = emptyForm()
  dialogOpen.value = true
}

function openEdit(row) {
  editingIndex.value = row._idx
  form.value = {
    head: row.head,
    head_type: row.head_type,
    relation: row.relation,
    tail: row.tail,
    tail_type: row.tail_type,
    sentence_index: row.sentence_index ?? null,
    evidence: row.evidence || '',
  }
  dialogOpen.value = true
}

function confirm() {
  const head = form.value.head.trim()
  const tail = form.value.tail.trim()
  if (!head || !tail) {
    ElMessage.warning('头实体和尾实体不能为空')
    return
  }
  if (!form.value.relation) {
    ElMessage.warning('请选择关系类型')
    return
  }
  const relation = relMap.value[form.value.relation]
  const original = editingIndex.value !== null ? props.relations[editingIndex.value] : null
  const headCanonical =
    original && original.head === head && original.head_type === form.value.head_type
      ? original.head_canonical || head
      : canonicalize(head, form.value.head_type)
  const tailCanonical =
    original && original.tail === tail && original.tail_type === form.value.tail_type
      ? original.tail_canonical || tail
      : canonicalize(tail, form.value.tail_type)
  const sentenceIndex =
    typeof form.value.sentence_index === 'number' ? form.value.sentence_index : 0

  const row = {
    id: original?.id || `manual-${Date.now()}`,
    head,
    head_canonical: headCanonical,
    head_type: form.value.head_type,
    relation: form.value.relation,
    relation_label: relation?.label || form.value.relation,
    relation_color: relation?.color || '',
    tail,
    tail_canonical: tailCanonical,
    tail_type: form.value.tail_type,
    confidence: 1,
    evidence: form.value.evidence.trim(),
    trigger: '人工校正',
    sentence_index: sentenceIndex,
    rule_base: 'manual',
  }

  const next =
    editingIndex.value !== null
      ? props.relations.map((r, i) =>
          i === editingIndex.value ? { ...r, ...row, id: r.id || row.id } : r,
        )
      : [row, ...props.relations]
  emit('update:relations', next)
  dialogOpen.value = false
  ElMessage.success(editingIndex.value !== null ? '已修改，记得保存校正' : '已新增，记得保存校正')
}

function remove(row) {
  emit(
    'update:relations',
    props.relations.filter((_, i) => i !== row._idx),
  )
  ElMessage.success('已删除，记得保存校正')
}

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  const ef = props.entityFilter
  return props.relations
    .map((r, i) => ({ ...r, _rid: r.id || `row-${i}`, _idx: i }))
    .filter((r) => {
      if (picked.value.length && !picked.value.includes(r.relation)) return false
      if (r.confidence < minConf.value) return false
      if (ef && r.head !== ef.name && r.tail !== ef.name) {
        if (r.head_canonical !== ef.name && r.tail_canonical !== ef.name) return false
      }
      if (!kw) return true
      return [r.head, r.tail, r.relation_label, r.evidence, r.trigger]
        .join(' ')
        .toLowerCase()
        .includes(kw)
    })
})

const emptyText = computed(() => {
  if (!props.relations.length) return '这段文本没有抽出关系，换一段包含「收购 / 投资 / 任职 / 总部位于」等表述的文本试试'
  if (props.entityFilter) return `「${props.entityFilter.name}」没有关系记录，点上方标签取消筛选`
  return '没有符合条件的三元组，试试放宽置信度或清空搜索'
})

function typeLabel(type) {
  return entityMap.value[type]?.label || type
}

function tagStyle(type) {
  const color = entityMap.value[type]?.color || '#6b7280'
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
  return '#6b7280'
}

const RULE_LABEL = {
  pattern: '句式模板',
  trigger: '触发词',
  passive: '被动句',
  conjunction: '并列结构',
  postmodifier: '后置定语',
  attributive: '职位线索',
  coref: '指代消解',
  chain: '主语链',
  manual: '人工校正',
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
  min-width: 0;
}

.rel-select {
  width: 178px;
}

.kw {
  width: 164px;
}

/* 置信度：三档互斥按钮，替代拖不准的连续滑杆 */
.conf-seg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  height: 28px;
  background: var(--surface-3);
  border-radius: var(--r-sm);
}

.conf-item {
  height: 24px;
  padding: 0 8px;
  border: none;
  background: transparent;
  border-radius: var(--r-xs);
  font-family: inherit;
  font-size: 11.5px;
  color: var(--ink-2);
  cursor: pointer;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  transition: background 0.14s ease, color 0.14s ease;
}

.conf-item:hover {
  color: var(--ink);
}

.conf-item.is-active {
  background: var(--surface);
  color: var(--ink);
  font-weight: 500;
  box-shadow: 0 1px 2px rgba(16, 18, 22, 0.1);
}

/* 图谱下钻带过来的实体筛选 */
.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 8px;
  font-family: inherit;
  font-size: 11.5px;
  color: #1d3fb8;
  background: #eef2ff;
  border: 1px solid #c7d2f8;
  border-radius: var(--r-sm);
  cursor: pointer;
  white-space: nowrap;
}

.filter-chip:hover {
  background: #e3e9ff;
}

.tb-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.dirty-flag {
  font-size: 10.5px;
  color: #b45309;
  background: #fef3c7;
  border: 1px solid #fcd34d;
  border-radius: var(--r-xs);
  padding: 1px 6px;
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
  color: var(--muted);
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
  color: var(--muted);
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

.manual-tag {
  display: inline-block;
  margin-left: 4px;
  padding: 0 5px;
  border-radius: var(--r-xs);
  font-size: 10px;
  color: #7c3aed;
  background: #7c3aed12;
  border: 1px solid #7c3aed33;
}

.row-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.row-actions :deep(.el-button) {
  height: 22px;
  padding: 0 3px;
  font-size: 11.5px;
}

.row-actions :deep(.r-del:hover) {
  color: var(--danger);
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

/* 【创新点 1】定位原文：把“这关系凭什么抽出来”压到一次点击 */
.locate-btn {
  height: 22px;
  padding: 0 8px;
  font-family: inherit;
  font-size: 11px;
  color: var(--ink-2);
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-xs);
  cursor: pointer;
  transition: background 0.14s ease, border-color 0.14s ease, color 0.14s ease;
}

.locate-btn:hover {
  background: #eef2ff;
  border-color: #c7d2f8;
  color: #1d3fb8;
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
  color: var(--muted);
}

.meta-item b {
  font-weight: 500;
  color: var(--ink-2);
  font-variant-numeric: tabular-nums;
}

/* ---------- 新增 / 编辑弹窗 ---------- */
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: 12px;
}

.triple-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.triple-form :deep(.el-form-item__label) {
  font-size: 12px;
  color: var(--muted);
}

.triple-form :deep(.el-input__wrapper),
.triple-form :deep(.el-select__wrapper) {
  min-height: 30px;
  height: 30px;
  font-size: 12.5px;
  border-radius: var(--r-sm);
}

.triple-form :deep(.el-select) {
  width: 100%;
}

.triple-form :deep(.el-textarea__inner) {
  font-size: 12.5px;
  border-radius: var(--r-sm);
}

@media (max-width: 860px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
