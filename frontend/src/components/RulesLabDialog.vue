<template>
  <el-dialog
    :model-value="modelValue"
    width="960px"
    append-to-body
    class="rl-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="onOpen"
  >
    <template #header>
      <div class="rl-head">
        <span class="rl-title">规则实验室</span>
        <span class="rl-sub">先看哪些规则在干活，再从标注里学新说法，最后用 A/B 差异确认</span>
      </div>
    </template>

    <div class="rl-tabs" role="tablist" aria-label="规则实验室视图" @keydown="onTabKeydown">
      <button
        v-for="t in MODES"
        :key="t.key"
        :id="'rl-tab-' + t.key"
        class="rl-tab"
        :class="{ 'is-active': mode === t.key }"
        type="button"
        role="tab"
        :aria-selected="mode === t.key ? 'true' : 'false'"
        :tabindex="mode === t.key ? 0 : -1"
        @click="switchMode(t.key)"
      >
        {{ t.label }}
        <span v-if="t.key === 'insights' && insights" class="rl-tab-count">
          {{ insights.summary.relations }} 条
        </span>
      </button>
    </div>

    <!-- ============ A/B 试跑 ============ -->
    <div v-if="mode === 'trial'" class="rl-trial" role="tabpanel" :aria-labelledby="'rl-tab-trial'">
      <div class="rl-grid">
        <div class="rl-left">
          <h4>试跑文本</h4>
          <div class="rl-profile">
            <label for="rl-profile-select">领域包</label>
            <select
              id="rl-profile-select"
              v-model="profile"
              class="rl-profile-select"
              aria-label="试跑使用的领域包"
            >
              <option v-for="p in profiles" :key="p.key" :value="p.key">{{ p.label }}</option>
            </select>
            <span>{{ activeProfile?.description || '与线上默认配置一致' }}</span>
          </div>
          <el-input
            v-model="text"
            type="textarea"
            :rows="5"
            resize="none"
            placeholder="粘贴一段包含目标关系的中文文本"
            aria-label="试跑文本"
          />
          <p class="rl-hint">用同一段文本跑「当前配置」与「候选配置」，只比较抽出的三元组差异；领域包会同时作用于两边。</p>

          <h4>候选触发词</h4>
          <div class="rl-add">
            <el-select v-model="newKey" placeholder="关系类型" style="width: 158px" aria-label="关系类型">
              <el-option v-for="r in relationTypes" :key="r.key" :label="r.label" :value="r.key" />
            </el-select>
            <el-input v-model="newTrigger" placeholder="领域说法，如「吃下」" aria-label="候选触发词" @keyup.enter="addTrigger" />
            <el-button @click="addTrigger">添加</el-button>
          </div>
          <div class="rl-chips">
            <span v-for="(t, i) in candidates" :key="i" class="rl-chip">
              {{ relationLabel(t.relation_key) }} · {{ t.trigger }}
              <button type="button" :aria-label="`移除 ${t.trigger}`" @click="candidates.splice(i, 1)">×</button>
            </span>
            <span v-if="!candidates.length" class="rl-hint">还没加候选触发词；可先只跑一次当前配置作基线。</span>
          </div>

          <div class="rl-actions">
            <el-button type="primary" :loading="trialing" @click="trial">试跑对比</el-button>
            <el-button :disabled="!candidates.length" @click="apply">应用到当前配置</el-button>
            <el-button @click="saveVersion">存为版本</el-button>
          </div>
        </div>

        <div class="rl-right">
          <h4>对比结果</h4>
          <div v-if="result" class="rl-diff-summary">
            <span>当前 <b>{{ result.before_count }}</b> 条</span>
            <span>候选 <b>{{ result.after_count }}</b> 条</span>
            <span class="rl-plus">新增 {{ result.added.length }}</span>
            <span class="rl-minus">消失 {{ result.removed.length }}</span>
          </div>
          <div v-else class="rl-empty">点「试跑对比」查看差异。</div>
          <div v-if="result" class="rl-diff-list">
            <template v-for="group in diffGroups" :key="group.key">
              <h5 :class="group.cls">{{ group.label }}（{{ group.items.length }}）</h5>
              <p v-for="(r, i) in group.items.slice(0, 12)" :key="i">
                {{ r.head }} <i>— {{ r.relation_label }} →</i> {{ r.tail }}
                <span class="rl-hint">{{ r.evidence }}</span>
              </p>
            </template>
          </div>
        </div>
      </div>

      <div class="rl-versions">
        <h4>配置版本</h4>
        <div v-for="v in versions" :key="v.id" class="rl-version">
          <b>{{ v.name || `版本 #${v.id}` }}</b>
          <span>{{ v.created_at }} · {{ v.rules }} 个触发词 · {{ v.terms }} 个词条</span>
          <el-button link size="small" @click="restore(v.id)">回滚</el-button>
        </div>
        <p v-if="!versions.length" class="rl-hint">还没有快照。存一份再改规则，随时能回到原状。</p>
      </div>
    </div>

    <!-- ============ 规则体检 ============ -->
    <div v-else-if="mode === 'insights'" class="rl-insights" role="tabpanel" :aria-labelledby="'rl-tab-insights'">
      <p v-if="insightsError" class="rl-error" role="alert">{{ insightsError }}</p>
      <div v-else-if="!insights" class="rl-empty">正在读取历史抽取结果…</div>
      <template v-else>
        <div class="rl-summary">
          <div v-for="m in summaryCards" :key="m.label" class="rl-summary-item">
            <b>{{ m.value }}</b>
            <span>{{ m.label }}</span>
          </div>
        </div>

        <h4>系统建议</h4>
        <div class="rl-suggestions">
          <div v-for="s in insights.suggestions" :key="s.kind + s.title" class="rl-suggestion" :class="'is-' + s.kind">
            <div class="rl-suggestion-copy">
              <b>{{ s.title }}</b>
              <p>{{ s.detail }}</p>
            </div>
            <button type="button" class="rl-suggestion-btn" @click="onSuggestion(s)">{{ s.action }} →</button>
          </div>
        </div>

        <h4>命中热区 <span class="rl-h4-note">按历史关系条数排序</span></h4>
        <div class="rl-hot">
          <section v-for="g in hotGroups" :key="g.title" class="rl-hot-col">
            <h5>{{ g.title }}</h5>
            <p v-if="!g.items.length" class="rl-hint">暂无数据</p>
            <div v-for="(it, i) in g.items" :key="i" class="rl-hot-row">
              <span class="rl-hot-name" :title="it.name">{{ it.name }}</span>
              <span class="rl-hot-track" aria-hidden="true">
                <i :style="{ width: barWidth(it.count, g.max) }"></i>
              </span>
              <b>{{ it.count }}</b>
            </div>
          </section>
        </div>

        <h4>从未命中的触发词 <span class="rl-h4-note">点一下带进候选列表试跑</span></h4>
        <div class="rl-unused">
          <button
            v-for="(u, i) in insights.unused_triggers.slice(0, 48)"
            :key="i"
            type="button"
            class="rl-chip rl-chip-btn"
            :title="`把「${u.trigger}」带入 ${u.relation_label} 候选`"
            @click="useUnused(u)"
          >
            {{ u.trigger }} <i>{{ u.relation_label }}</i>
            <em v-if="u.source === 'custom'">自定义</em>
          </button>
          <p v-if="!insights.unused_triggers.length" class="rl-hint">登记在册的触发词都有过命中记录。</p>
        </div>

        <div v-if="insights.deleted_by_relation?.length" class="rl-deleted">
          <h4>人工删除最多的关系</h4>
          <span v-for="d in insights.deleted_by_relation" :key="d.relation" class="rl-chip">
            {{ d.relation_label }} · {{ d.count }} 次
          </span>
        </div>
      </template>
    </div>

    <!-- ============ 学规则 ============ -->
    <div v-else-if="mode === 'mining'" class="rl-mining" role="tabpanel" :aria-labelledby="'rl-tab-mining'">
      <p class="rl-hint rl-mining-intro">
        只读「人工补录 + 判为该抽」的项：取补录原句里两个实体夹住的文字，反复出现的片段就是最可能的触发词。
        标「已自证」的，是加进配置后确实能抽出那条对应的关系。
      </p>

      <p v-if="miningError" class="rl-error" role="alert">{{ miningError }}</p>
      <div v-else-if="!mining" class="rl-empty">正在从标注集反推…</div>
      <template v-else>
        <div class="rl-summary">
          <div v-for="m in miningCards" :key="m.label" class="rl-summary-item">
            <b>{{ m.value }}</b>
            <span>{{ m.label }}</span>
          </div>
        </div>

        <div v-if="mining.advice?.length" class="rl-suggestions">
          <div v-for="a in mining.advice" :key="a.kind + a.title" class="rl-suggestion" :class="'is-' + a.kind">
            <div class="rl-suggestion-copy">
              <b>{{ a.title }}</b>
              <p>{{ a.detail }}</p>
            </div>
          </div>
        </div>

        <h4>候选触发词 <span class="rl-h4-note">点一下带进试跑</span></h4>
        <div v-if="mining.candidates.length" class="rl-cands">
          <div v-for="c in mining.candidates" :key="c.relation + c.trigger" class="rl-cand">
            <div class="rl-cand-head">
              <b>{{ c.trigger }}</b>
              <span class="rl-cand-rel">{{ c.relation_label }}</span>
              <span class="rl-cand-tag" :class="c.verified ? 'is-ok' : 'is-warn'">
                {{ c.verified ? '已自证' : (c.already_hit ? '现有配置已能抽到' : '未自证') }}
              </span>
              <span class="rl-cand-meta">{{ c.count }} 条补录 · {{ c.records }} 篇材料</span>
              <button type="button" class="rl-suggestion-btn" @click="useMining(c)">带去试跑 →</button>
            </div>
            <p v-if="c.examples[0]" class="rl-cand-eg">{{ c.examples[0].sentence }}</p>
            <p v-if="c.conflicts.length" class="rl-cand-warn">
              「{{ c.trigger }}」目前已属于「{{ c.conflicts.map((k) => relationLabel(k)).join(' / ') }}」，加进来会跟它抢同一句话。
            </p>
          </div>
        </div>
        <p v-else class="rl-hint">还没有重复出现的说法。补录几条同类句式再看。</p>

        <div v-if="mining.overbroad?.length" class="rl-deleted">
          <h4>误抽信号 <span class="rl-h4-note">这些词抽出来的关系被判为不该抽</span></h4>
          <span v-for="(o, i) in mining.overbroad" :key="i" class="rl-chip">
            {{ o.trigger }} <i>{{ o.relation_label }}</i> · 否掉 {{ o.rejected }} 次
          </span>
        </div>
      </template>
    </div>

    <template #footer>
      <button v-if="mode === 'insights'" class="rl-refresh" type="button" @click="loadInsights">重新体检</button>
      <button v-else-if="mode === 'mining'" class="rl-refresh" type="button" :disabled="miningLoading" @click="loadMining">
        {{ miningLoading ? '正在反推…' : '重新反推' }}
      </button>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '../api/client'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  schema: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue', 'changed'])

const MODES = [
  { key: 'trial', label: 'A/B 试跑' },
  { key: 'insights', label: '规则体检' },
  { key: 'mining', label: '学规则' },
]
const mode = ref('trial')

const text = ref('腾讯控股吃下搜狗公司，搜狗公司将成为腾讯控股的全资子公司。')
const newKey = ref('')
const newTrigger = ref('')
const candidates = ref([])
const result = ref(null)
const trialing = ref(false)
const versions = ref([])

const profiles = ref(props.schema.profiles || [])
const profile = ref(props.schema.default_profile || 'general')
const activeProfile = computed(() => profiles.value.find((p) => p.key === profile.value) || null)

const insights = ref(null)
const insightsError = ref('')

const mining = ref(null)
const miningError = ref('')
const miningLoading = ref(false)

const relationTypes = computed(() => props.schema.relation_types || [])
const relationLabel = (key) => relationTypes.value.find((r) => r.key === key)?.label || key

const diffGroups = computed(() => {
  if (!result.value) return []
  return [
    { key: 'added', label: '候选新增', cls: 'rl-plus', items: result.value.added },
    { key: 'removed', label: '候选消失', cls: 'rl-minus', items: result.value.removed },
    { key: 'unchanged', label: '保持不变', cls: '', items: result.value.unchanged },
  ]
})

const summaryCards = computed(() => {
  const s = insights.value?.summary || {}
  return [
    { label: '历史关系', value: s.relations ?? 0 },
    { label: '低置信度', value: s.low_confidence ?? 0 },
    { label: '人工补录', value: s.manual ?? 0 },
    { label: '人工删除', value: s.deleted_relations ?? 0 },
    { label: '从未命中词', value: s.unused_triggers ?? 0 },
    { label: '复核驳回', value: s.rejected ?? 0 },
  ]
})

/** 三个热区用同一套「名称 + 条数」形状，避免模板里写三遍分支。 */
const hotGroups = computed(() => {
  const d = insights.value
  if (!d) return []
  const build = (title, items, nameFn) => {
    const rows = (items || []).slice(0, 8).map((it) => ({ name: nameFn(it), count: it.count }))
    return { title, items: rows, max: Math.max(1, ...rows.map((r) => r.count)) }
  }
  return [
    build('触发词', d.hot_triggers, (it) => it.trigger),
    build('命中策略', d.hot_strategies, (it) => it.label),
    build('关系类型', d.hot_relations, (it) => it.relation_label),
  ]
})

const barWidth = (count, max) => `${Math.max(5, Math.round((count / max) * 100))}%`

function onTabKeydown(event) {
  if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const at = MODES.findIndex((m) => m.key === mode.value)
  let next = at
  if (event.key === 'ArrowRight') next = (at + 1) % MODES.length
  if (event.key === 'ArrowLeft') next = (at - 1 + MODES.length) % MODES.length
  if (event.key === 'Home') next = 0
  if (event.key === 'End') next = MODES.length - 1
  switchMode(MODES[next].key)
  document.getElementById('rl-tab-' + MODES[next].key)?.focus()
}

function switchMode(key) {
  mode.value = key
  if (key === 'insights') loadInsights()
  if (key === 'mining' && !mining.value) loadMining()
}

async function onOpen() {
  if (!profiles.value.length) profiles.value = props.schema.profiles || []
  await Promise.all([loadVersions(), loadProfiles()])
  if (mode.value === 'insights') await loadInsights()
  if (mode.value === 'mining' && !mining.value) await loadMining()
}

async function loadProfiles() {
  try {
    const res = await api.getProfiles()
    if (res.items?.length) profiles.value = res.items
  } catch {
    // schema 里已经带了目录，接口失败不影响试跑
    if (!profiles.value.length) profiles.value = props.schema.profiles || []
  }
}

async function loadInsights() {
  insightsError.value = ''
  try {
    insights.value = await api.getInsights()
  } catch (err) {
    insightsError.value = `体检结果读取失败：${err.message}`
  }
}

async function loadMining() {
  if (miningLoading.value) return
  miningError.value = ''
  miningLoading.value = true
  try {
    mining.value = await api.getMiningTriggers()
  } catch (err) {
    miningError.value = `反推失败：${err.message}`
  } finally {
    miningLoading.value = false
  }
}

/** 把候选直接放进试跑候选列表：反推的下一步永远是用 A/B 差异验一遍。 */
function useMining(item) {
  newKey.value = item.relation
  newTrigger.value = item.trigger
  if (!candidates.value.some((c) => c.relation_key === item.relation && c.trigger === item.trigger)) {
    candidates.value.push({ relation_key: item.relation, trigger: item.trigger })
  }
  mode.value = 'trial'
  ElMessage.info(`已带入候选「${item.trigger}」，换一段同时含该说法的文本再试跑`)
}

const miningCards = computed(() => {
  const s = mining.value?.summary || {}
  return [
    { label: '人工补录', value: s.manual_total ?? 0 },
    { label: '可定位原句', value: s.usable_samples ?? 0 },
    { label: '候选触发词', value: s.candidates ?? 0 },
    { label: '已自证', value: s.verified ?? 0 },
    { label: '误抽信号', value: s.overbroad ?? 0 },
  ]
})

function useUnused(item) {
  newKey.value = item.relation
  newTrigger.value = item.trigger
  if (!candidates.value.some((c) => c.relation_key === item.relation && c.trigger === item.trigger)) {
    candidates.value.push({ relation_key: item.relation, trigger: item.trigger })
  }
  mode.value = 'trial'
  ElMessage.info(`已带入候选「${item.trigger}」，换一段含该说法的文本再试跑`)
}

function onSuggestion(s) {
  if (s.kind === 'confidence') {
    ElMessage.info('低置信度关系请在工作台顶栏「复核」里逐条核对')
    return
  }
  if (s.kind === 'baseline') {
    ElMessage.info('先在工作台抽几篇不同领域的文本，体检结论会更具体')
    return
  }
  if (s.kind === 'deleted' && insights.value?.deleted_by_relation?.length) {
    newKey.value = insights.value.deleted_by_relation[0].relation
  }
  if (s.kind === 'coverage') {
    ElMessage.info('在「关系三元组」页展开任一行，可看到它命中的策略')
  }
  mode.value = 'trial'
}

function addTrigger() {
  const trigger = newTrigger.value.trim()
  if (!newKey.value || !trigger) {
    ElMessage.warning('先选关系类型并填写触发词')
    return
  }
  if (candidates.value.some((c) => c.relation_key === newKey.value && c.trigger === trigger)) {
    ElMessage.info('这个候选词已经在列表里')
    return
  }
  candidates.value.push({ relation_key: newKey.value, trigger })
  newTrigger.value = ''
}

async function trial() {
  if (!text.value.trim()) {
    ElMessage.warning('请先输入试跑文本')
    return
  }
  trialing.value = true
  try {
    result.value = await api.trialRules({
      text: text.value,
      triggers: candidates.value,
      profile: profile.value,
    })
    ElMessage.success(`对比完成：${result.value.before_count} → ${result.value.after_count} 条`)
  } catch (err) {
    ElMessage.error(`试跑失败：${err.message}`)
  } finally {
    trialing.value = false
  }
}

async function apply() {
  let ok = 0
  for (const c of candidates.value) {
    try {
      await api.addRule(c.relation_key, c.trigger)
      ok += 1
    } catch (err) {
      ElMessage.warning(`${c.trigger} 未写入：${err.message}`)
    }
  }
  if (ok) {
    ElMessage.success(`已写入 ${ok} 个触发词，下一次抽取立即生效`)
    emit('changed')
    await trial()
    insights.value = null // 体检基于历史结果，规则变了就重算
  }
}

async function loadVersions() {
  try {
    versions.value = (await api.getRuleVersions()).items
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function saveVersion() {
  try {
    await api.saveRuleVersion(`快照 ${new Date().toLocaleString('zh-CN')}`)
    await loadVersions()
    ElMessage.success('配置快照已保存')
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function restore(id) {
  try {
    await api.restoreRuleVersion(id)
    await loadVersions()
    emit('changed')
    insights.value = null
    ElMessage.success('已回滚到该版本')
  } catch (err) {
    ElMessage.error(err.message)
  }
}
</script>

<style scoped>
.rl-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.rl-title { font-size: 13.5px; font-weight: 600; color: var(--ink); }
.rl-sub, .rl-hint { font-size: 11.5px; color: var(--muted); }
.rl-hint { margin: 6px 0 0; line-height: 1.6; }

.rl-tabs { display: inline-flex; gap: 2px; padding: 2px; margin-bottom: 14px; background: var(--surface-3); border-radius: var(--r-sm); }
.rl-tab { padding: 6px 14px; border: 0; border-radius: var(--r-xs); background: transparent; color: var(--ink-2); font-family: inherit; font-size: 12px; cursor: pointer; transition: background var(--dur-press) var(--ease), color var(--dur-press) var(--ease); }
.rl-tab:hover { color: var(--ink); }
.rl-tab.is-active { background: var(--surface); color: var(--ink); font-weight: 600; box-shadow: 0 1px 2px rgba(32, 30, 25, 0.1); }
.rl-tab-count { margin-left: 6px; font-size: 10.5px; color: var(--muted); font-variant-numeric: tabular-nums; }

/* 960 的固定宽在窄屏会整块出屏；max-width 能压过 width 内联样式。 */
:global(.rl-dialog.el-dialog) {
  max-width: calc(100vw - 24px);
}
:global(.rl-dialog .el-dialog__body) {
  max-height: 68vh;
  overflow-y: auto;
}
.rl-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.rl-left, .rl-right { padding: 12px 14px; border: 1px solid var(--line); border-radius: var(--r-sm); background: var(--surface-2); }
.rl-grid h4, .rl-versions h4, .rl-insights h4, .rl-deleted h4 { margin: 0 0 8px; font-size: 11.5px; font-weight: 600; color: var(--ink-2); }
.rl-grid h4:not(:first-child) { margin-top: 16px; }

.rl-profile { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.rl-profile label { font-size: 11px; color: var(--muted); }
.rl-profile-select { height: 28px; padding: 0 8px; font-family: inherit; font-size: 11.5px; color: var(--ink); background: var(--surface); border: 1px solid var(--line-strong); border-radius: var(--r-xs); cursor: pointer; }
.rl-profile span { flex: 1 1 180px; min-width: 0; font-size: 10.5px; color: var(--muted); line-height: 1.5; }

.rl-add { display: flex; gap: 8px; }
.rl-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; min-height: 26px; }
.rl-chip { padding: 3px 8px; font-size: 11px; color: var(--ink-2); background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-xs); }
.rl-chip button { border: none; background: transparent; color: var(--muted); cursor: pointer; font-size: 13px; }
.rl-chip button:hover { color: var(--brand-red); }
.rl-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.rl-diff-summary { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 10px; font-size: 11.5px; color: var(--muted); }
.rl-diff-summary b { color: var(--ink); font-variant-numeric: tabular-nums; }
.rl-plus { color: #15803d; }
.rl-minus { color: var(--brand-red); }
.rl-empty { padding: 28px 8px; text-align: center; font-size: 12px; color: var(--muted); }
.rl-diff-list { max-height: 236px; overflow: auto; }
.rl-diff-list h5 { margin: 10px 0 5px; font-size: 11px; font-weight: 600; color: var(--ink-2); }
.rl-diff-list p { margin: 0 0 5px; font-size: 11.5px; color: var(--ink-2); }
.rl-diff-list i { font-style: normal; color: var(--brand-red); }
.rl-versions { margin-top: 16px; }
.rl-version { display: flex; align-items: center; gap: 12px; min-height: 30px; font-size: 11.5px; border-bottom: 1px solid var(--line); }
.rl-version b { font-weight: 500; color: var(--ink-2); min-width: 160px; }
.rl-version span { color: var(--muted); flex: 1; }

/* ---------- 规则体检 ---------- */
.rl-error { padding: 10px 12px; font-size: 12px; color: var(--danger); background: var(--brand-red-soft); border-radius: var(--r-sm); }
.rl-h4-note { margin-left: 8px; font-weight: 400; font-size: 10.5px; color: var(--muted); }
.rl-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 1px; margin-bottom: 18px; background: var(--line); border-radius: var(--r-sm); overflow: hidden; }
.rl-summary-item { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; background: var(--surface-2); }
.rl-summary-item b { font-size: 18px; font-weight: 600; color: var(--ink); font-variant-numeric: tabular-nums; }
.rl-summary-item span { font-size: 10.5px; color: var(--muted); }

.rl-suggestions { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 10px; margin-bottom: 18px; }
.rl-suggestion { display: flex; align-items: flex-start; gap: 12px; padding: 10px 12px; border-left: 2px solid var(--brand-red); border-radius: 0 var(--r-sm) var(--r-sm) 0; background: var(--surface-2); }
.rl-suggestion.is-baseline { border-left-color: var(--line-strong); }
.rl-suggestion.is-confidence { border-left-color: var(--warn); }
.rl-suggestion-copy { flex: 1; min-width: 0; }
.rl-suggestion-copy b { font-size: 11.5px; font-weight: 600; color: var(--ink); }
.rl-suggestion-copy p { margin: 5px 0 0; font-size: 11px; line-height: 1.65; color: var(--ink-2); }
.rl-suggestion-btn { flex: none; padding: 4px 8px; border: 1px solid var(--line-strong); border-radius: var(--r-xs); background: var(--surface); color: var(--brand-red); font-family: inherit; font-size: 11px; white-space: nowrap; cursor: pointer; transition: background var(--dur-press) var(--ease); }
.rl-suggestion-btn:hover { background: var(--brand-red-soft); }

.rl-hot { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 18px; }
.rl-hot-col { padding: 10px 12px; border: 1px solid var(--line); border-radius: var(--r-sm); background: var(--surface-2); }
.rl-hot-col h5 { margin: 0 0 8px; font-size: 11px; font-weight: 600; color: var(--ink-2); }
.rl-hot-row { display: flex; align-items: center; gap: 8px; margin-bottom: 5px; font-size: 11px; }
.rl-hot-name { flex: 0 0 84px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-2); }
.rl-hot-track { flex: 1; height: 5px; min-width: 20px; border-radius: var(--r-pill); background: var(--surface-3); overflow: hidden; }
.rl-hot-track i { display: block; height: 100%; border-radius: var(--r-pill); background: var(--brand-red); }
.rl-hot-row b { flex: none; width: 24px; text-align: right; font-weight: 500; color: var(--muted); font-variant-numeric: tabular-nums; }

.rl-unused { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }
.rl-chip-btn { font-family: inherit; cursor: pointer; transition: background var(--dur-press) var(--ease), border-color var(--dur-press) var(--ease); }
.rl-chip-btn:hover { background: var(--brand-red-soft); border-color: #e4aca7; }
.rl-chip-btn i { font-style: normal; color: var(--muted); }
.rl-chip-btn em { margin-left: 4px; font-style: normal; font-size: 10px; color: var(--brand-red); }
.rl-deleted { margin-top: 4px; }
.rl-deleted .rl-chip { display: inline-block; margin: 0 6px 6px 0; }
.rl-refresh { margin-right: 10px; padding: 5px 10px; border: 1px solid var(--line-strong); border-radius: var(--r-xs); background: var(--surface); color: var(--ink-2); font-family: inherit; font-size: 12px; cursor: pointer; }
.rl-refresh:hover { color: var(--brand-red); }
.rl-refresh:disabled { color: var(--muted); cursor: default; }
.rl-mining-intro { margin: 0 0 14px; }
.rl-cands { display: grid; gap: 8px; }
.rl-cand { padding: 10px 12px; border: 1px solid var(--line); border-radius: var(--r-sm); background: var(--surface-2); }
.rl-cand-head { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.rl-cand-head b { flex: none; font-size: 13px; font-weight: 600; color: var(--ink); }
.rl-cand-rel { padding: 1px 6px; font-size: 10.5px; color: var(--ink-2); border: 1px solid var(--line-strong); border-radius: var(--r-xs); }
.rl-cand-tag { padding: 1px 6px; font-size: 10.5px; border: 1px solid var(--line-strong); border-radius: var(--r-xs); }
.rl-cand-tag.is-ok { color: var(--ok); }
.rl-cand-tag.is-warn { color: var(--muted); }
.rl-cand-meta { margin-left: auto; font-size: 10.5px; color: var(--muted); }
.rl-cand-eg { margin: 7px 0 0; font-size: 11px; line-height: 1.6; color: var(--ink-2); }
.rl-cand-warn { margin: 6px 0 0; font-size: 10.5px; line-height: 1.6; color: var(--warn); }

@media (max-width: 720px) {
  .rl-dialog { width: 94vw !important; }
  .rl-grid, .rl-suggestions { grid-template-columns: 1fr; }
  /* 一行塞不下时让统计数另起一行，按钮留在第一行右侧，别互相挤 */
  .rl-cand-meta { margin-left: 0; width: 100%; order: 9; }
  .rl-cand-head .rl-suggestion-btn { margin-left: auto; }
  /* 5 个指标排 2 列，最后一张占满整行，不留空格 */
  .rl-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rl-summary-item:last-child:nth-child(odd) { grid-column: 1 / -1; }
  /* 弹窗顶距 + 内容 + 页脚在 390 高屏上会超出视口，内容区再收一点 */
  :global(.rl-dialog .el-dialog__body) { max-height: 58vh; }
}
</style>
