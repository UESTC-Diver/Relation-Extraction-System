<template>
  <el-dialog
    :model-value="modelValue"
    width="900px"
    append-to-body
    class="ev-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="loadAll"
  >
    <template #header>
      <div class="ev-head">
        <span class="ev-title">效果评测</span>
        <span class="ev-sub">在人工金标准集上跑 P / R / F1，留痕做回归对比</span>
      </div>
    </template>

    <div class="ev-bar">
      <el-select v-model="datasetKey" class="ev-select" aria-label="选择评测数据集" @change="onDataset">
        <el-option label="内置金标准集" value="builtin" />
        <el-option
          v-for="s in datasets"
          :key="s.id"
          :label="`我的标注：${s.name}`"
          :value="`annotation:${s.id}`"
        />
      </el-select>
      <span class="ev-muted">{{ datasetHint }}</span>
      <el-button type="primary" :loading="running" @click="run">运行评测</el-button>
      <el-button @click="loadHistory">刷新历史</el-button>
    </div>

    <div v-if="report" class="ev-pane">
      <div v-if="report.coverage < 1" class="ev-scope">
        <b>标注完整度 {{ Math.round(report.coverage * 100) }}%</b>
        <span>
          已判定范围内 P {{ report.precision }} · R {{ report.recall }} · F1 {{ report.f1 }}
        </span>
        <span v-if="report.strict">
          若把未判视为漏抽，下界 P {{ report.strict.precision }} · F1 {{ report.strict.f1 }}
        </span>
      </div>
      <div class="ev-cards">
        <div v-for="c in cards" :key="c.label" class="ev-card">
          <b>{{ c.value }}</b><span>{{ c.label }}</span>
        </div>
      </div>

      <div class="ev-history">
        <h4>F1 回归曲线（本数据集最近 {{ scopedRuns.length }} 次）</h4>
        <svg v-if="scopedRuns.length > 1" viewBox="0 0 620 92" class="ev-spark" role="img" aria-label="F1 历史变化">
          <polyline :points="sparkPoints" fill="none" stroke="#a8322a" stroke-width="2" />
          <circle v-for="(p, i) in sparkDots" :key="i" :cx="p.x" :cy="p.y" r="3" fill="#a8322a" />
        </svg>
        <p v-else class="ev-muted">再跑一次评测就能看到趋势</p>
      </div>

      <div class="ev-columns">
        <div>
          <h4>分关系类型</h4>
          <el-table :data="report.per_relation" height="190" size="small" class="ev-table">
            <el-table-column prop="label" label="关系" min-width="100" />
            <el-table-column prop="gold" label="金标" width="62" align="center" />
            <el-table-column prop="pred" label="预测" width="62" align="center" />
            <el-table-column prop="f1" label="F1" width="70" align="center" />
          </el-table>
        </div>
        <div>
          <h4>逐条用例</h4>
          <el-table :data="report.per_case" height="190" size="small" class="ev-table">
            <el-table-column prop="title" label="用例" min-width="130" />
            <el-table-column prop="tp" label="命中" width="62" align="center" />
            <el-table-column prop="fp" label="误抽" width="62" align="center" />
            <el-table-column prop="fn" label="漏抽" width="62" align="center" />
          </el-table>
        </div>
      </div>

      <div class="ev-errors">
        <div class="ev-switch">
          <button :class="{ 'is-active': errorTab === 'misses' }" type="button" @click="errorTab = 'misses'">
            漏抽 {{ report.misses.length }}
          </button>
          <button :class="{ 'is-active': errorTab === 'spurious' }" type="button" @click="errorTab = 'spurious'">
            误抽 {{ report.spurious.length }}
          </button>
          <button class="ev-history-btn" type="button" @click="showHistory = !showHistory">
            {{ showHistory ? '收起历史' : '查看历史' }}
          </button>
        </div>
        <div class="ev-error-list">
          <p v-for="(item, i) in errorRows" :key="i">
            <span class="ev-case">{{ item.case }}</span>
            {{ item.head }} <i>— {{ item.relation_label }} →</i> {{ item.tail }}
            <span v-if="item.evidence" class="ev-muted">｜{{ item.evidence }}</span>
          </p>
          <p v-if="!errorRows.length" class="ev-muted">这一类没有错误</p>
        </div>
      </div>

      <div v-if="showHistory" class="ev-runs">
        <h4>历史评测</h4>
        <button v-for="r in scopedRuns" :key="r.id" class="ev-run" type="button" @click="openRun(r.id)">
          #{{ r.id }} · {{ r.created_at }} · F1 {{ r.f1 }} · P {{ r.precision }} · R {{ r.recall }}
          <span v-if="r.coverage < 1" class="ev-run-cov">完整度 {{ Math.round(r.coverage * 100) }}%</span>
        </button>
      </div>
    </div>
    <div v-else class="ev-empty">点「运行评测」开始。指标算法与命令行 <code>python eval/run_eval.py</code> 共用同一份实现。</div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '../api/client'

defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue'])

const goldTotal = ref(0)
const report = ref(null)
const runs = ref([])
const datasets = ref([])
const datasetKey = ref('builtin')
const running = ref(false)
const errorTab = ref('misses')
const showHistory = ref(false)

const datasetHint = computed(() => {
  if (datasetKey.value === 'builtin') return `内置金标准 ${goldTotal.value} 条用例`
  const one = datasets.value.find((d) => `annotation:${d.id}` === datasetKey.value)
  return one ? `${one.record_count} 篇材料 · 先判完再跑才有意义` : '这个标注集已不存在'
})

// 两条曲线混在一起没有可比性：内置集和自己的材料，口径本来就不一样
const scopedRuns = computed(() =>
  runs.value.filter((r) => (r.dataset || 'builtin') === datasetKey.value),
)

const cards = computed(() => {
  const r = report.value
  if (!r) return []
  return [
    { label: 'Precision', value: r.precision },
    { label: 'Recall', value: r.recall },
    { label: 'F1', value: r.f1 },
    { label: 'Macro-F1', value: r.macro_f1 },
    { label: '命中 / 误抽 / 漏抽', value: `${r.tp} / ${r.fp} / ${r.fn}` },
  ]
})
const errorRows = computed(() =>
  report.value ? report.value[errorTab.value].slice(0, 30) : [],
)

const sparkDots = computed(() => {
  const values = [...scopedRuns.value].reverse().map((r) => r.f1)
  if (values.length < 2) return []
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 1)
  const span = max - min || 1
  return values.map((v, i) => ({
    x: 20 + (i * 580) / (values.length - 1),
    y: 80 - ((v - min) / span) * 62,
  }))
})
const sparkPoints = computed(() => sparkDots.value.map((p) => `${p.x},${p.y}`).join(' '))

async function loadAll() {
  try {
    const [gold, history, sets] = await Promise.all([
      api.getEvalGold(),
      api.getEvalRuns(),
      api.getAnnotationSets(),
    ])
    goldTotal.value = gold.total
    runs.value = history.items
    datasets.value = sets.items
    if (datasetKey.value !== 'builtin') {
      const alive = sets.items.some((s) => `annotation:${s.id}` === datasetKey.value)
      if (!alive) datasetKey.value = 'builtin'
    }
  } catch (err) {
    ElMessage.error(`加载失败：${err.message}`)
  }
}

function onDataset() {
  report.value = null
}

async function run() {
  running.value = true
  try {
    const payload = { save: true }
    if (datasetKey.value !== 'builtin') {
      payload.set_id = Number(datasetKey.value.split(':')[1])
    }
    const res = await api.runEval(payload)
    report.value = res.report
    runs.value = (await api.getEvalRuns()).items
    const tail = res.report.coverage < 1 ? `（标注完整度 ${Math.round(res.report.coverage * 100)}%）` : ''
    ElMessage.success(`评测完成：F1 ${res.report.f1}${tail}`)
  } catch (err) {
    ElMessage.error(`评测失败：${err.message}`)
  } finally {
    running.value = false
  }
}

async function loadHistory() {
  try {
    runs.value = (await api.getEvalRuns()).items
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function openRun(id) {
  try {
    const detail = await api.getEvalRun(id)
    report.value = detail.report
    datasetKey.value = detail.dataset || 'builtin'
    ElMessage.success(`已载入 #${id} 的评测结果`)
  } catch (err) {
    ElMessage.error(err.message)
  }
}

watch(() => report.value, () => { errorTab.value = 'misses' })
</script>

<style scoped>
.ev-head { display: flex; align-items: baseline; gap: 10px; }
.ev-title { font-size: 13.5px; font-weight: 600; color: var(--ink); }
.ev-sub, .ev-muted { font-size: 11.5px; color: var(--muted); }
.ev-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.ev-select { width: 220px; }
.ev-bar .ev-muted { margin-right: auto; }
.ev-scope {
  display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
  padding: 9px 11px; margin-bottom: 12px; font-size: 11.5px; color: var(--ink-2);
  background: var(--surface-2); border-left: 2px solid var(--brand-red); border-radius: var(--r-xs);
}
.ev-scope b { font-weight: 500; color: var(--brand-red); }
.ev-run-cov { margin-left: 6px; color: var(--muted); }
.ev-cards { display: grid; grid-template-columns: repeat(5, 1fr); gap: 1px; background: var(--line); border: 1px solid var(--line); border-radius: var(--r-sm); overflow: hidden; }
.ev-card { padding: 12px; background: var(--surface-2); }
.ev-card b { display: block; font-size: 19px; font-weight: 500; font-variant-numeric: tabular-nums; color: var(--ink); }
.ev-card span { font-size: 11px; color: var(--muted); }
.ev-history { margin-top: 14px; }
.ev-history h4, .ev-columns h4, .ev-runs h4 { margin: 0 0 7px; font-size: 11.5px; font-weight: 600; color: var(--ink-2); }
.ev-spark { width: 100%; height: 92px; background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--r-sm); }
.ev-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 14px; }
.ev-table { border: 1px solid var(--line); border-radius: var(--r-sm); font-size: 12px; }
.ev-errors { margin-top: 16px; }
.ev-switch { display: flex; gap: 6px; border-bottom: 1px solid var(--line); }
.ev-switch button {
  min-height: 32px; padding: 0 12px; font-size: 11.5px; font-family: inherit;
  color: var(--muted); background: transparent; border: none;
  border-bottom: 2px solid transparent; cursor: pointer;
}
.ev-switch button.is-active { color: var(--brand-red); border-bottom-color: var(--brand-red); }
.ev-history-btn { margin-left: auto; color: var(--brand-red) !important; }
.ev-error-list { max-height: 160px; overflow: auto; padding: 8px 4px; }
.ev-error-list p { margin: 0 0 5px; font-size: 11.5px; color: var(--ink-2); }
.ev-error-list i { font-style: normal; color: var(--brand-red); }
.ev-case { display: inline-block; min-width: 62px; color: var(--muted); }
.ev-runs { margin-top: 12px; }
.ev-run {
  display: block; width: 100%; min-height: 28px; padding: 4px 8px; text-align: left;
  font-size: 11px; font-family: inherit; color: var(--ink-2); background: transparent;
  border: none; border-radius: var(--r-xs); cursor: pointer;
}
.ev-run:hover { background: var(--surface-3); }
.ev-empty { padding: 40px 16px; text-align: center; font-size: 12px; color: var(--muted); }
.ev-empty code { font-family: var(--font-mono, monospace); color: var(--ink-2); }
:global(.ev-dialog.el-dialog) {
  max-width: calc(100vw - 24px);
}
:global(.ev-dialog .el-dialog__body) {
  max-height: 72vh;
  overflow: auto;
}

@media (max-width: 720px) {
  .ev-cards { grid-template-columns: repeat(2, 1fr); }
  .ev-columns { grid-template-columns: 1fr; }
}
</style>
