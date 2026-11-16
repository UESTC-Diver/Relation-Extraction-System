<template>
  <el-dialog
    :model-value="modelValue"
    width="1000px"
    append-to-body
    class="an-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="boot"
  >
    <template #header>
      <div class="an-head">
        <span class="an-title">金标准标注</span>
        <span class="an-sub">
          判「该抽 / 不该抽」，并把系统漏掉的补上——只判对错不补漏，recall 永远算不出来
        </span>
      </div>
    </template>

    <div class="an-bar">
      <el-select
        v-model="setId"
        placeholder="选择标注集"
        class="an-select"
        aria-label="选择标注集"
        @change="loadSet"
      >
        <el-option
          v-for="s in sets"
          :key="s.id"
          :label="`${s.name}（${s.record_count} 篇）`"
          :value="s.id"
        />
      </el-select>
      <el-button @click="createSet">新建标注集</el-button>
      <el-button v-if="setId" text @click="removeSet">删除此集</el-button>

      <div v-if="coverage" class="an-cov">
        <div class="an-cov-bar"><i :style="{ width: pct(coverage.coverage) }"></i></div>
        <span class="an-cov-text">
          已判 {{ coverage.judged }} / {{ coverage.auto + coverage.manual }} · {{ pct(coverage.coverage) }}
        </span>
      </div>

      <el-button
        v-if="recordId && setDetail && !inSet"
        text
        type="primary"
        class="an-attach"
        @click="attachCurrent"
      >
        把当前这篇加进来
      </el-button>
    </div>

    <div v-if="!sets.length" class="an-empty">
      <p>还没有标注集。标注集就是一批材料——比如「某某收购案 20 篇」。</p>
      <el-button type="primary" @click="createSet">建第一个</el-button>
    </div>

    <div v-else-if="!setId" class="an-empty">选一个标注集开始，或新建一个。</div>

    <div v-else class="an-body">
      <div class="an-list">
        <button
          v-for="r in setDetail?.records || []"
          :key="r.id"
          type="button"
          class="an-item"
          :class="{ 'is-active': r.id === activeId }"
          @click="openRecord(r.id)"
        >
          <b>{{ r.title || `记录 ${r.id}` }}</b>
          <span>{{ r.judged }} / {{ r.relation_count }} 已判</span>
        </button>
        <p v-if="!setDetail?.records?.length" class="an-hint">这个集还没有材料</p>
      </div>

      <div v-if="detail" class="an-pane">
        <div class="an-pane-head">
          <b>{{ detail.title || `记录 ${detail.record_id}` }}</b>
          <span class="an-muted">
            系统抽出 {{ detail.summary.auto }} 条 · 补录 {{ detail.summary.manual }} 条 ·
            未判 {{ detail.summary.unjudged }} 条
          </span>
          <el-button
            v-if="detail.prefill.length"
            text
            type="primary"
            class="an-prefill"
            @click="prefill"
          >
            沿用 {{ detail.prefill.length }} 条复核结论
          </el-button>
        </div>

        <div class="an-rows">
          <div
            v-for="row in rows"
            :key="row.key"
            class="an-row"
            :class="{ 'is-positive': row.verdict === 'positive', 'is-negative': row.verdict === 'negative' }"
          >
            <div class="an-acts">
              <button
                type="button"
                :class="{ on: row.verdict === 'positive' }"
                :aria-pressed="row.verdict === 'positive'"
                @click="mark(row, 'positive')"
              >
                该抽
              </button>
              <button
                type="button"
                :class="{ on: row.verdict === 'negative' }"
                :aria-pressed="row.verdict === 'negative'"
                @click="mark(row, 'negative')"
              >
                不该抽
              </button>
            </div>
            <div class="an-main">
              <p class="an-triple">
                {{ row.head }} <i>—{{ row.relation_label }}→</i> {{ row.tail }}
              </p>
              <p class="an-evi">{{ row.evidence || '（无证据句）' }}</p>
            </div>
            <div class="an-marks">
              <span v-if="row.origin === 'manual'" class="an-tag">补录</span>
              <span v-if="row.source === 'inferred'" class="an-tag is-inferred">继承复核</span>
              <span v-if="row.confidence" class="an-conf">{{ (row.confidence * 100).toFixed(0) }}%</span>
            </div>
          </div>
          <p v-if="!rows.length" class="an-hint">这篇系统一条都没抽出来，可以直接补录。</p>
        </div>

        <div v-if="adding" class="an-form">
          <el-input v-model="form.head" placeholder="头实体" class="an-f-head" />
          <el-select v-model="form.relation" placeholder="关系" class="an-f-rel">
            <el-option
              v-for="r in relationTypes"
              :key="r.key"
              :label="r.label"
              :value="r.key"
            />
          </el-select>
          <el-input v-model="form.tail" placeholder="尾实体" class="an-f-tail" />
          <el-input v-model="form.evidence" placeholder="证据句（可留空）" class="an-f-evi" />
          <el-button type="primary" @click="addManual">加入</el-button>
          <el-button text @click="adding = false">取消</el-button>
        </div>
        <el-button v-else class="an-add-btn" @click="adding = true">+ 补一条系统漏抽的</el-button>
      </div>

      <div v-else class="an-pane an-hint">从左边选一篇材料开始标注</div>
    </div>

    <template #footer>
      <span v-if="dirtyCount" class="an-dirty">{{ dirtyCount }} 条未保存</span>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
      <el-button type="primary" :disabled="!detail || !dirtyCount" @click="save">保存判定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '../api/client'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  recordId: { type: Number, default: null },
  relationTypes: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const sets = ref([])
const setId = ref(null)
const setDetail = ref(null)
const coverage = ref(null)
const detail = ref(null)
const activeId = ref(null)
const adding = ref(false)
const draft = reactive({})
const extra = ref([])
const form = reactive({ head: '', tail: '', relation: '', evidence: '' })

function pct(v) {
  return `${Math.round((v || 0) * 100)}%`
}

const inSet = computed(
  () => !!props.recordId && (setDetail.value?.records || []).some((r) => r.id === props.recordId),
)

// 系统抽出的 + 已补录的 + 本次还没保存的新补录，统一成一个可判列表
const rows = computed(() => {
  if (!detail.value) return []
  const auto = detail.value.relations.map((r) => ({
    key: r.relation_key,
    head: r.head,
    tail: r.tail,
    relation: r.relation,
    relation_label: r.relation_label,
    evidence: r.evidence,
    confidence: r.confidence,
    origin: r.origin,
    source: r.source,
    verdict: draft[r.relation_key]?.verdict ?? r.verdict,
  }))
  const manual = detail.value.manual.map((r) => ({
    key: r.relation_key,
    head: r.head,
    tail: r.tail,
    relation: r.relation,
    relation_label: r.relation_label,
    evidence: r.evidence,
    confidence: null,
    origin: r.origin,
    source: r.source,
    verdict: draft[r.relation_key]?.verdict ?? r.verdict,
  }))
  // 补录项置顶：那是人刚补的，最需要立刻确认；埋在长列表末尾等于没显示
  return [...extra.value, ...manual, ...auto]
})

const dirtyCount = computed(
  () => Object.values(draft).filter((v) => v.verdict !== undefined).length + extra.value.length,
)

async function boot() {
  for (const k of Object.keys(draft)) delete draft[k]
  extra.value = []
  detail.value = null
  activeId.value = null
  await loadSets()
  if (!setId.value && sets.value.length) setId.value = sets.value[0].id
  if (setId.value) await loadSet()
}

async function loadSets() {
  try {
    const res = await api.getAnnotationSets()
    sets.value = res.items
    if (setId.value && !sets.value.some((s) => s.id === setId.value)) setId.value = null
  } catch (err) {
    ElMessage.error(`加载标注集失败：${err.message}`)
  }
}

async function loadSet() {
  if (!setId.value) return
  try {
    const [data, cov] = await Promise.all([
      api.getAnnotationSet(setId.value),
      api.getAnnotationCoverage(setId.value),
    ])
    setDetail.value = data
    coverage.value = cov
    // 有当前记录且在这个集里就打开它；否则直接打开第一篇，别让右侧空白等用户去点
    const preferred =
      props.recordId && data.records.some((r) => r.id === props.recordId)
        ? props.recordId
        : data.records[0]?.id
    if (preferred) await openRecord(preferred)
  } catch (err) {
    ElMessage.error(`加载失败：${err.message}`)
  }
}

async function openRecord(id) {
  activeId.value = id
  adding.value = false
  extra.value = []
  for (const k of Object.keys(draft)) delete draft[k]
  try {
    detail.value = await api.getRecordAnnotation(id)
  } catch (err) {
    ElMessage.error(`读取标注失败：${err.message}`)
    detail.value = null
  }
}

function mark(row, verdict) {
  draft[row.key] = {
    verdict: row.verdict === verdict ? '' : verdict,
    source: row.source === 'inferred' ? 'inferred' : 'human',
  }
}

function prefill() {
  for (const item of detail.value.prefill) {
    if (draft[item.relation_key]) continue
    draft[item.relation_key] = { verdict: item.verdict, source: 'inferred' }
  }
  ElMessage.success('已填成待保存状态，确认后点「保存判定」')
}

function addManual() {
  if (!form.head.trim() || !form.tail.trim() || !form.relation) {
    ElMessage.warning('头实体、关系、尾实体都要填')
    return
  }
  const head = form.head.trim()
  const tail = form.tail.trim()
  const dup = rows.value.some(
    (r) => r.head === head && r.relation === form.relation && r.tail === tail,
  )
  if (dup) {
    ElMessage.warning('这条已经在列表里了，直接给它判「该抽」就行')
    return
  }
  extra.value.unshift({
    key: `new-${Date.now()}-${extra.value.length}`,
    head,
    tail,
    relation: form.relation,
    relation_label: props.relationTypes.find((r) => r.key === form.relation)?.label || form.relation,
    evidence: form.evidence.trim(),
    confidence: null,
    origin: 'manual',
    source: 'human',
    verdict: 'positive',
    isNew: true,
    sentence_index: -1,
  })
  form.head = ''
  form.tail = ''
  form.relation = ''
  form.evidence = ''
  adding.value = false
}

async function save() {
  if (!detail.value) return
  const items = []
  for (const row of rows.value) {
    const change = draft[row.key]
    if (row.isNew) {
      items.push({
        verdict: 'positive',
        head: row.head,
        relation: row.relation,
        tail: row.tail,
        evidence: row.evidence,
        sentence_index: -1,
      })
      continue
    }
    if (!change) continue
    items.push({
      relation_key: row.key,
      verdict: change.verdict,
      source: change.source,
    })
  }
  if (!items.length) {
    ElMessage.info('没有需要保存的改动')
    return
  }
  try {
    detail.value = await api.saveRecordAnnotation(activeId.value, items)
    for (const k of Object.keys(draft)) delete draft[k]
    extra.value = []
    coverage.value = await api.getAnnotationCoverage(setId.value)
    setDetail.value = await api.getAnnotationSet(setId.value)
    emit('saved')
    ElMessage.success('判定已保存')
  } catch (err) {
    ElMessage.error(`保存失败：${err.message}`)
  }
}

async function createSet() {
  try {
    const { value } = await ElMessageBox.prompt(
      '给这批材料起个名字，例如「某某收购案 20 篇」',
      '新建标注集',
      { inputValue: '', confirmButtonText: '创建', cancelButtonText: '取消' },
    )
    const ids = props.recordId ? [props.recordId] : []
    const data = await api.createAnnotationSet({ name: value || '', record_ids: ids })
    await loadSets()
    setId.value = data.id
    await loadSet()
    ElMessage.success('标注集已创建')
  } catch (err) {
    if (err !== 'cancel') ElMessage.error(`创建失败：${err.message || err}`)
  }
}

async function removeSet() {
  if (!setId.value) return
  try {
    await ElMessageBox.confirm(
      '删除标注集不会删掉材料，也不会删掉材料上的判定。',
      '删除标注集',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await api.deleteAnnotationSet(setId.value)
    setId.value = null
    setDetail.value = null
    coverage.value = null
    detail.value = null
    await loadSets()
    ElMessage.success('已删除')
  } catch (err) {
    ElMessage.error(`删除失败：${err.message}`)
  }
}

async function attachCurrent() {
  try {
    setDetail.value = await api.addAnnotationRecords(setId.value, [props.recordId])
    coverage.value = await api.getAnnotationCoverage(setId.value)
    await openRecord(props.recordId)
    ElMessage.success('已加入这个集')
  } catch (err) {
    ElMessage.error(`加入失败：${err.message}`)
  }
}
</script>

<style scoped>
.an-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.an-title { font-size: 13.5px; font-weight: 600; color: var(--ink); }
.an-sub { font-size: 11.5px; color: var(--muted); }
.an-muted { font-size: 11.5px; color: var(--muted); }
.an-hint { font-size: 12px; color: var(--muted); padding: 12px 4px; }

.an-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.an-select { width: 220px; }
.an-cov { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.an-cov-bar { width: 120px; height: 5px; background: var(--surface-3); border-radius: 3px; overflow: hidden; }
.an-cov-bar i { display: block; height: 100%; background: var(--brand-red); transition: width 220ms var(--ease, ease); }
.an-cov-text { font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }
.an-attach { margin-left: 4px; }

.an-empty { padding: 36px 12px; text-align: center; font-size: 12px; color: var(--muted); }
.an-empty p { margin: 0 0 12px; }

.an-body { display: grid; grid-template-columns: 250px 1fr; gap: 14px; min-height: 380px; }
.an-list {
  border: 1px solid var(--line); border-radius: var(--r-sm);
  background: var(--surface-2); padding: 6px; max-height: 460px; overflow: auto;
}
.an-item {
  display: block; width: 100%; padding: 8px 9px; margin-bottom: 2px; text-align: left;
  font-family: inherit; background: transparent; border: none; border-radius: var(--r-xs);
  cursor: pointer; color: var(--ink-2);
}
.an-item b { display: block; font-size: 12px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.an-item span { font-size: 10.5px; color: var(--muted); font-variant-numeric: tabular-nums; }
.an-item:hover { background: var(--surface-3); }
.an-item.is-active { background: var(--brand-paper); box-shadow: inset 2px 0 0 var(--brand-red); }

.an-pane { border: 1px solid var(--line); border-radius: var(--r-sm); padding: 12px; min-width: 0; }
.an-pane-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.an-pane-head b { font-size: 12.5px; font-weight: 600; color: var(--ink); }
.an-prefill { margin-left: auto; }

.an-rows { max-height: 330px; overflow: auto; }
.an-row {
  display: grid; grid-template-columns: 116px 1fr auto; gap: 10px; align-items: start;
  padding: 8px; border-bottom: 1px solid var(--line);
}
.an-row:last-child { border-bottom: none; }
.an-row.is-positive { background: color-mix(in srgb, var(--brand-red) 5%, transparent); }
.an-row.is-negative { background: var(--surface-2); }
.an-acts { display: flex; gap: 4px; }
.an-acts button {
  min-height: 26px; padding: 0 8px; font-size: 11px; font-family: inherit;
  color: var(--muted); background: var(--surface-2);
  border: 1px solid var(--line); border-radius: var(--r-xs); cursor: pointer;
}
.an-acts button:hover { color: var(--ink); border-color: var(--line-strong, var(--line)); }
.an-acts button.on { color: #fff; background: var(--brand-red); border-color: var(--brand-red); }
.an-acts button:nth-child(2).on { background: var(--ink-2); border-color: var(--ink-2); }

.an-main { min-width: 0; }
.an-triple { margin: 0 0 3px; font-size: 12.5px; color: var(--ink); }
.an-triple i { font-style: normal; color: var(--brand-red); }
.an-evi {
  margin: 0; font-size: 11px; color: var(--muted); line-height: 1.55;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.an-marks { display: flex; flex-direction: column; align-items: flex-end; gap: 3px; }
.an-tag {
  padding: 1px 5px; font-size: 10px; color: var(--brand-red);
  background: color-mix(in srgb, var(--brand-red) 10%, transparent); border-radius: 3px;
}
.an-tag.is-inferred { color: var(--ink-2); background: var(--surface-3); }
.an-conf { font-size: 10.5px; color: var(--muted); font-variant-numeric: tabular-nums; }

.an-add-btn { margin-top: 10px; }
.an-form { display: grid; grid-template-columns: 1fr 150px 1fr; gap: 8px; margin-top: 10px; }
.an-form .an-f-evi { grid-column: 1 / 3; }
.an-dirty { margin-right: auto; font-size: 11.5px; color: var(--brand-red); }

:global(.an-dialog.el-dialog) {
  max-width: calc(100vw - 24px);
}
:global(.an-dialog .el-dialog__body) {
  max-height: 72vh;
  overflow: auto;
}

@media (max-width: 760px) {
  .an-body { grid-template-columns: 1fr; }
  .an-list { max-height: 180px; }
  .an-row { grid-template-columns: 1fr; }
  .an-form { grid-template-columns: 1fr; }
  .an-form .an-f-evi { grid-column: auto; }
}
</style>
