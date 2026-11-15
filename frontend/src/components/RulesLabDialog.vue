<template>
  <el-dialog
    :model-value="modelValue"
    width="900px"
    append-to-body
    class="rl-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="loadVersions"
  >
    <template #header>
      <div class="rl-head">
        <span class="rl-title">规则实验室</span>
        <span class="rl-sub">改触发词先看 A/B 差异，确认有效再落库</span>
      </div>
    </template>

    <div class="rl-grid">
      <div class="rl-left">
        <h4>试跑文本</h4>
        <el-input
          v-model="text"
          type="textarea"
          :rows="5"
          resize="none"
          placeholder="粘贴一段包含目标关系的中文文本"
          aria-label="试跑文本"
        />
        <p class="rl-hint">用同一段文本跑「当前配置」与「候选配置」，只比较抽出的三元组差异。</p>

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

    <template #footer>
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

const text = ref('腾讯控股吃下搜狗公司，搜狗公司将成为腾讯控股的全资子公司。')
const newKey = ref('')
const newTrigger = ref('')
const candidates = ref([])
const result = ref(null)
const trialing = ref(false)
const versions = ref([])

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
    result.value = await api.trialRules({ text: text.value, triggers: candidates.value })
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
    ElMessage.success('已回滚到该版本')
  } catch (err) {
    ElMessage.error(err.message)
  }
}
</script>

<style scoped>
.rl-head { display: flex; align-items: baseline; gap: 10px; }
.rl-title { font-size: 13.5px; font-weight: 600; color: var(--ink); }
.rl-sub, .rl-hint { font-size: 11.5px; color: var(--muted); }
.rl-hint { margin: 6px 0 0; line-height: 1.6; }
.rl-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.rl-left, .rl-right { padding: 12px 14px; border: 1px solid var(--line); border-radius: var(--r-sm); background: var(--surface-2); }
.rl-grid h4, .rl-versions h4 { margin: 0 0 8px; font-size: 11.5px; font-weight: 600; color: var(--ink-2); }
.rl-grid h4:not(:first-child) { margin-top: 16px; }
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
@media (max-width: 720px) {
  .rl-grid { grid-template-columns: 1fr; }
}
</style>
