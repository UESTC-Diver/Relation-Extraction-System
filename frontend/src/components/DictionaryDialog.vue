<template>
  <el-dialog
    :model-value="modelValue"
    width="620px"
    append-to-body
    class="dict-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="load"
  >
    <template #header>
      <div class="dict-head">
        <span class="dict-title">领域配置</span>
        <span class="dict-count">{{ tab === 'terms' ? `${terms.length} 个词条` : `${rules.length} 个触发词` }}</span>
      </div>
    </template>

    <div class="dict-switch">
      <el-radio-group v-model="tab" size="small" aria-label="配置类型">
        <el-radio-button value="terms">实体词典</el-radio-button>
        <el-radio-button value="rules">关系触发词</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 实体词典：补充内置词典未覆盖的机构 / 人名 / 地名 -->
    <div v-if="tab === 'terms'">
      <div class="dict-add">
        <el-input
          v-model="newText"
          maxlength="32"
          placeholder="词条，如：恒瑞医药"
          clearable
          @keyup.enter="add"
        />
        <el-select v-model="newType" class="dict-type">
          <el-option v-for="t in typeOptions" :key="t.key" :label="t.label" :value="t.key" />
        </el-select>
        <el-button type="primary" :icon="Plus" :loading="adding" @click="add">添加</el-button>
      </div>

      <p class="dict-hint">
        自定义词条在抽取时优先参与实体识别，适合补充内置词典未覆盖的机构 / 人名 / 地名。
        添加后重新抽取即可生效。
      </p>

      <div v-loading="loading" class="dict-list">
        <div v-for="term in terms" :key="term.id" class="dict-row">
          <i class="dict-dot" :style="{ background: colorOf(term.type) }"></i>
          <span class="dict-text">{{ term.text }}</span>
          <span class="dict-tag">{{ labelOf(term.type) }}</span>
          <el-button link size="small" class="dict-del" @click="remove(term)">删除</el-button>
        </div>
        <el-empty v-if="!loading && !terms.length" description="还没有自定义词条" :image-size="64" />
      </div>
    </div>

    <!-- 关系触发词：给 19 类内置规则追加领域说法，不用改 Python -->
    <div v-else>
      <div class="dict-add">
        <el-select v-model="ruleKey" class="rule-rel" placeholder="选择关系类型">
          <el-option
            v-for="r in relationTypes"
            :key="r.key"
            :label="r.label"
            :value="r.key"
          />
        </el-select>
        <el-input
          v-model="newTrigger"
          maxlength="24"
          placeholder="新触发词，如：战略注资"
          clearable
          @keyup.enter="addRule"
        />
        <el-button type="primary" :icon="Plus" :loading="adding" @click="addRule">添加</el-button>
      </div>

      <p class="dict-hint">
        触发词追加到内置关系规则，保存后下一次抽取立即生效，无需重启。
        句式模板仍由代码维护；改触发词只影响匹配范围，不会新增或改动 19 类关系目录。
      </p>

      <div class="rule-builtin">
        <span class="rule-label">{{ currentRelation?.label || '关系' }} · 内置触发词</span>
        <div class="rule-chips">
          <span v-for="t in currentRelation?.triggers || []" :key="t" class="rule-chip">{{ t }}</span>
        </div>
      </div>

      <div v-loading="loading" class="dict-list">
        <div v-for="rule in rules" :key="rule.id" class="dict-row">
          <i class="dict-dot" :style="{ background: colorOfRelation(rule.relation_key) }"></i>
          <span class="dict-text">{{ rule.trigger }}</span>
          <span class="dict-tag">{{ labelOfRelation(rule.relation_key) }}</span>
          <el-button link size="small" class="dict-del" @click="removeRule(rule)">删除</el-button>
        </div>
        <el-empty v-if="!loading && !rules.length" description="还没有自定义触发词" :image-size="64" />
      </div>
    </div>

    <template #footer>
      <el-button v-if="(tab === 'terms' && terms.length) || (tab === 'rules' && rules.length)" link class="dict-clear" @click="clearAll">
        清空{{ tab === 'terms' ? '词典' : '触发词' }}
      </el-button>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import * as api from '../api/client'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  schema: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue', 'changed'])

const tab = ref('terms')
const terms = ref([])
const rules = ref([])
const relationTypes = ref([])
const loading = ref(false)
const adding = ref(false)
const newText = ref('')
const newType = ref('ORG')
const newTrigger = ref('')
const ruleKey = ref('acquire')

const typeOptions = computed(() => props.schema.entity_types || [])
const currentRelation = computed(() =>
  relationTypes.value.find((r) => r.key === ruleKey.value),
)

function labelOf(type) {
  return typeOptions.value.find((t) => t.key === type)?.label || type
}
function colorOf(type) {
  return typeOptions.value.find((t) => t.key === type)?.color || '#64748b'
}
function labelOfRelation(key) {
  return relationTypes.value.find((r) => r.key === key)?.label || key
}
function colorOfRelation(key) {
  return relationTypes.value.find((r) => r.key === key)?.color || '#64748b'
}

async function load() {
  loading.value = true
  try {
    const [dict, ruleData] = await Promise.all([api.getDictionary(), api.getRules()])
    terms.value = dict.items || []
    rules.value = ruleData.items || []
    relationTypes.value = ruleData.relation_types || props.schema.relation_types || []
    if (relationTypes.value.length && !relationTypes.value.some((r) => r.key === ruleKey.value)) {
      ruleKey.value = relationTypes.value[0].key
    }
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    loading.value = false
  }
}

async function add() {
  const text = newText.value.trim()
  if (text.length < 2) {
    ElMessage.warning('词条至少需要 2 个字符')
    return
  }
  adding.value = true
  try {
    const term = await api.addDictionaryTerm(text, newType.value)
    if (term.duplicate) {
      ElMessage.info('该词条已存在')
    } else {
      ElMessage.success(`已添加「${text}」`)
      emit('changed')
    }
    newText.value = ''
    load()
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    adding.value = false
  }
}

async function addRule() {
  const trigger = newTrigger.value.trim()
  if (trigger.length < 2) {
    ElMessage.warning('触发词至少需要 2 个字符')
    return
  }
  adding.value = true
  try {
    const rule = await api.addRule(ruleKey.value, trigger)
    ElMessage.success(
      rule.duplicate
        ? `「${trigger}」已存在`
        : `已给「${labelOfRelation(ruleKey.value)}」追加「${trigger}」，重新抽取即生效`,
    )
    newTrigger.value = ''
    emit('changed')
    load()
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    adding.value = false
  }
}

async function remove(term) {
  try {
    await api.deleteDictionaryTerm(term.id)
    ElMessage.success(`已删除「${term.text}」`)
    emit('changed')
    load()
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function removeRule(rule) {
  try {
    await api.deleteRule(rule.id)
    ElMessage.success(`已删除「${rule.trigger}」`)
    emit('changed')
    load()
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function clearAll() {
  const isTerm = tab.value === 'terms'
  try {
    await ElMessageBox.confirm(
      `将清空全部${isTerm ? '自定义词条' : '自定义触发词'}，此操作不可撤销。`,
      isTerm ? '清空词典' : '清空触发词',
      { confirmButtonText: '清空', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    const res = isTerm ? await api.clearDictionary() : await api.clearRules()
    ElMessage.success(`已清空 ${res.removed} 项`)
    emit('changed')
    load()
  } catch (err) {
    ElMessage.error(err.message)
  }
}

defineExpose({ load })
</script>

<style scoped>
.dict-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.dict-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}

.dict-count {
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.dict-switch {
  margin-bottom: 12px;
}

.dict-add {
  display: flex;
  gap: 6px;
}

.dict-type {
  width: 108px;
  flex: none;
}

.rule-rel {
  width: 140px;
  flex: none;
}

.dict-add :deep(.el-input__wrapper),
.dict-add :deep(.el-select__wrapper),
.dict-add :deep(.el-button) {
  min-height: 30px;
  height: 30px;
  font-size: 12.5px;
  border-radius: var(--r-sm);
}

.dict-hint {
  margin: 9px 0 10px;
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--faint);
}

.rule-builtin {
  margin-bottom: 10px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-2);
}

.rule-label {
  display: block;
  margin-bottom: 6px;
  font-size: 10.5px;
  letter-spacing: 0.6px;
  color: var(--muted);
}

.rule-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-height: 76px;
  overflow: auto;
}

.rule-chip {
  padding: 1px 6px;
  font-size: 11px;
  color: var(--ink-2);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-xs);
}

.dict-list {
  max-height: 260px;
  min-height: 80px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  padding: 4px;
}

.dict-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--line);
  font-size: 12.5px;
}

.dict-row:last-child {
  border-bottom: none;
}

.dict-dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 2px;
}

.dict-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink);
}

.dict-tag {
  flex: none;
  font-size: 10.5px;
  color: var(--muted);
  background: var(--surface-3);
  border-radius: var(--r-xs);
  padding: 1px 6px;
}

.dict-del {
  flex: none;
  font-size: 11.5px;
  color: var(--faint);
}

.dict-del:hover {
  color: var(--danger);
}

.dict-clear {
  float: left;
  font-size: 12px;
  color: var(--faint);
}

.dict-clear:hover {
  color: var(--danger);
}

@media (max-width: 720px) {
  .dict-add {
    flex-wrap: wrap;
  }
  .dict-type,
  .rule-rel {
    width: 100%;
  }
}
</style>
