<template>
  <el-dialog
    v-model="visible"
    title="复核与定稿"
    width="860px"
    class="review-dialog"
    append-to-body
    :close-on-click-modal="false"
    @closed="emit('changed')"
  >
    <template v-if="!recordId">
      <el-empty description="请先抽取并存入历史，再开始复核" :image-size="72" />
    </template>

    <template v-else>
      <div class="rv-head">
        <div class="rv-status" :class="`is-${state.status}`">
          <span class="rv-dot"></span>
          {{ STATUS_LABEL[state.status] || '草稿' }}
        </div>
        <div class="rv-progress">
          <div class="rv-progress-bar">
            <i :style="{ width: percent + '%' }"></i>
          </div>
          <span>已复核 {{ state.summary?.reviewed ?? 0 }} / {{ state.summary?.total ?? 0 }}</span>
        </div>
        <div class="rv-counts">
          <span class="c-ok">通过 {{ state.summary?.approved ?? 0 }}</span>
          <span class="c-q">存疑 {{ state.summary?.questioned ?? 0 }}</span>
          <span class="c-no">驳回 {{ state.summary?.rejected ?? 0 }}</span>
        </div>
      </div>

      <p class="rv-tip">
        逐条核对三元组是否真的来自证据句。定稿后会生成不可变快照，关系与实体不能再改；
        如需改稿，先「解锁」退回复核中。
      </p>

      <div class="rv-toolbar">
        <div class="rv-filters" role="group" aria-label="按复核结论筛选">
          <button
            v-for="f in FILTERS"
            :key="f.value"
            type="button"
            class="rv-filter"
            :class="{ 'is-active': filter === f.value }"
            :aria-pressed="filter === f.value ? 'true' : 'false'"
            @click="filter = f.value"
          >{{ f.label }}</button>
        </div>
        <div class="rv-actions">
          <el-button size="small" :loading="busy" :disabled="!state.editable" @click="save">
            保存结论
          </el-button>
          <el-button
            v-if="state.status === 'draft'"
            size="small"
            :loading="busy"
            @click="changeStatus('in_review')"
          >提交复核</el-button>
          <el-button
            v-if="state.status !== 'final'"
            size="small"
            type="primary"
            :loading="busy"
            @click="finalize"
          >定稿并生成快照</el-button>
          <el-button
            v-else
            size="small"
            :loading="busy"
            @click="changeStatus('in_review')"
          >解锁改稿</el-button>
        </div>
      </div>

      <div class="rv-list" :aria-busy="loading ? 'true' : 'false'">
        <div v-for="row in shown" :key="row.review_key" class="rv-row" :class="`rv-${row.decision}`">
          <div class="rv-line">
            <span class="rv-ent">{{ row.head }}</span>
            <span class="rv-rel">{{ row.relation_label }}</span>
            <span class="rv-ent">{{ row.tail }}</span>
            <span class="rv-conf">{{ (row.confidence * 100).toFixed(0) }}%</span>
          </div>
          <p class="rv-evidence">{{ row.evidence || '（无证据句）' }}</p>
          <div class="rv-controls">
            <div class="rv-choices" role="group" :aria-label="`复核 ${row.head} ${row.relation_label} ${row.tail}`">
              <button
                v-for="c in CHOICES"
                :key="c.value"
                type="button"
                class="rv-choice"
                :class="[`is-${c.value}`, { 'is-on': row.decision === c.value }]"
                :disabled="!state.editable"
                :aria-pressed="row.decision === c.value ? 'true' : 'false'"
                @click="setDecision(row, c.value)"
              >{{ c.label }}</button>
            </div>
            <el-input
              v-model="row.note"
              size="small"
              class="rv-note-input"
              maxlength="200"
              placeholder="批注（可选）"
              :disabled="!state.editable"
              :aria-label="`批注：${row.head} ${row.relation_label} ${row.tail}`"
              @change="touch(row)"
            />
          </div>
        </div>
        <el-empty v-if="!shown.length" description="没有符合条件的三元组" :image-size="64" />
      </div>

      <div class="rv-foot">
        <div class="rv-snapshots">
          <span v-if="state.snapshots?.length">
            定稿快照 {{ state.snapshots.length }} 份 · 最近 {{ state.snapshots[0].created_at }}
          </span>
          <span v-else>还没有定稿快照</span>
        </div>
        <div class="rv-foot-btns">
          <el-button size="small" :loading="busy" @click="copyLink">复制只读报告链接</el-button>
          <el-button size="small" :loading="busy" @click="exportReport">导出离线报告</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '../api/client'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  recordId: { type: Number, default: null },
  title: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'changed'])

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const STATUS_LABEL = { draft: '草稿', in_review: '复核中', final: '已定稿' }
const CHOICES = [
  { value: 'approved', label: '通过' },
  { value: 'questioned', label: '存疑' },
  { value: 'rejected', label: '驳回' },
]
const FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待复核' },
  { value: 'approved', label: '通过' },
  { value: 'questioned', label: '存疑' },
  { value: 'rejected', label: '驳回' },
]

const loading = ref(false)
const busy = ref(false)
const filter = ref('all')
const state = ref({ status: 'draft', editable: true, relations: [], summary: {}, snapshots: [] })
const rows = ref([])

const percent = computed(() => {
  const total = state.value.summary?.total || 0
  if (!total) return 0
  return Math.round(((state.value.summary?.reviewed || 0) / total) * 100)
})

const shown = computed(() =>
  filter.value === 'all' ? rows.value : rows.value.filter((r) => r.decision === filter.value),
)

function applyState(data) {
  state.value = data
  rows.value = (data.relations || []).map((r) => ({
    review_key: r.review_key,
    head: r.head,
    relation_label: r.relation_label,
    tail: r.tail,
    evidence: r.evidence,
    confidence: r.confidence || 0,
    decision: r.decision || 'pending',
    note: r.review_note || '',
    _dirty: false,
  }))
}

async function load() {
  if (!props.recordId) return
  loading.value = true
  try {
    applyState(await api.getReviewState(props.recordId))
  } catch (err) {
    ElMessage.error(`复核状态加载失败：${err.message}`)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      filter.value = 'all'
      load()
    }
  },
)

function touch(row) {
  row._dirty = true
}

function setDecision(row, value) {
  row.decision = row.decision === value ? 'pending' : value
  row._dirty = true
}

async function save() {
  busy.value = true
  try {
    const changed = rows.value.filter((r) => r._dirty)
    const payload = (changed.length ? changed : rows.value).map((r) => ({
      relation_key: r.review_key,
      decision: r.decision,
      note: r.note,
    }))
    applyState(await api.saveReviewDecisions(props.recordId, payload))
    ElMessage.success(`已保存 ${payload.length} 条复核结论`)
    emit('changed')
  } catch (err) {
    ElMessage.error(`保存失败：${err.message}`)
  } finally {
    busy.value = false
  }
}

async function changeStatus(status) {
  busy.value = true
  try {
    applyState(await api.setReviewStatus(props.recordId, status))
    ElMessage.success(`状态已切换为「${STATUS_LABEL[status]}」`)
    emit('changed')
  } catch (err) {
    ElMessage.error(`切换失败：${err.message}`)
  } finally {
    busy.value = false
  }
}

async function finalize() {
  busy.value = true
  try {
    await save()
    applyState(await api.finalizeReview(props.recordId, props.title))
    ElMessage.success('已定稿，三元组与实体已锁定')
    emit('changed')
  } catch (err) {
    ElMessage.error(`定稿失败：${err.message}`)
  } finally {
    busy.value = false
  }
}

async function copyLink() {
  busy.value = true
  try {
    const res = await api.createShareLink(props.recordId)
    const url = res.url
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url)
      ElMessage.success('带签名的只读报告链接已复制')
    } else {
      ElMessage.info(`请手动复制：${url}`)
    }
  } catch (err) {
    ElMessage.error(`生成链接失败：${err.message}`)
  } finally {
    busy.value = false
  }
}

function download(filename, content, mime) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

async function exportReport() {
  busy.value = true
  try {
    const file = await api.buildReport({ record_id: props.recordId, title: props.title })
    download(file.filename, file.html, 'text/html;charset=utf-8')
    ElMessage.success('已导出含复核结论的离线报告')
  } catch (err) {
    ElMessage.error(`导出失败：${err.message}`)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.rv-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
}

.rv-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: var(--r-sm);
  font-size: 12px;
  color: var(--ink-2);
  background: var(--surface-3);
  white-space: nowrap;
}

.rv-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--muted);
}

.rv-status.is-in_review .rv-dot { background: #b45309; }
.rv-status.is-final .rv-dot { background: #a8322a; }
.rv-status.is-final { color: #8f2a23; background: #f7e9e7; }

.rv-progress {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.rv-progress-bar {
  width: 120px;
  height: 4px;
  border-radius: 2px;
  background: var(--surface-3);
  overflow: hidden;
}

.rv-progress-bar i {
  display: block;
  height: 100%;
  background: var(--accent);
  transition: width var(--dur-swap) var(--ease);
}

.rv-counts {
  display: flex;
  gap: 12px;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.c-ok { color: #2f6b3a; }
.c-q { color: #8a5a10; }
.c-no { color: #a8322a; }

.rv-tip {
  margin: 12px 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--muted);
}

.rv-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.rv-filters {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  background: var(--surface-3);
  border-radius: var(--r-sm);
}

.rv-filter {
  padding: 4px 10px;
  border: none;
  border-radius: var(--r-xs);
  background: transparent;
  font-family: inherit;
  font-size: 11.5px;
  color: var(--ink-2);
  cursor: pointer;
}

.rv-filter.is-active {
  background: var(--surface);
  color: var(--ink);
  font-weight: 500;
}

.rv-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.rv-list {
  max-height: 46vh;
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
}

.rv-row {
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
}

.rv-row:last-child { border-bottom: none; }

.rv-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 13px;
}

.rv-ent { font-weight: 500; color: var(--ink); }

.rv-rel {
  padding: 1px 7px;
  border-radius: var(--r-xs);
  font-size: 11.5px;
  color: #8f2a23;
  background: #f7e9e7;
}

.rv-conf {
  margin-left: auto;
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.rv-evidence {
  margin: 6px 0 10px;
  padding-left: 9px;
  border-left: 2px solid var(--line-strong);
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--muted);
}

.rv-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.rv-choices { display: inline-flex; gap: 4px; }

.rv-choice {
  min-width: 46px;
  min-height: 26px;
  padding: 0 8px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-xs);
  background: var(--surface);
  font-family: inherit;
  font-size: 11.5px;
  color: var(--ink-2);
  cursor: pointer;
  transition: background var(--dur-press) var(--ease), color var(--dur-press) var(--ease);
}

.rv-choice:disabled { opacity: 0.45; cursor: not-allowed; }
.rv-choice.is-approved.is-on { color: #2f6b3a; background: #e6f2e6; border-color: #9bc9a4; }
.rv-choice.is-questioned.is-on { color: #8a5a10; background: #fdf0d5; border-color: #e0bd77; }
.rv-choice.is-rejected.is-on { color: #a8322a; background: #f7e2e0; border-color: #e4aca7; }

.rv-note-input { flex: 1; min-width: 180px; }

.rv-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  font-size: 11.5px;
  color: var(--muted);
}

.rv-foot-btns { display: flex; gap: 6px; flex-wrap: wrap; }

@media (max-width: 720px) {
  .rv-progress-bar { width: 72px; }
  .rv-note-input { min-width: 100%; }
  .rv-choice { min-height: 44px; }
  .rv-filter { min-height: 36px; }
}
</style>
