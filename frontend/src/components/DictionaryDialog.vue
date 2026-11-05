<template>
  <el-dialog
    :model-value="modelValue"
    width="560px"
    append-to-body
    class="dict-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="load"
  >
    <template #header>
      <div class="dict-head">
        <span class="dict-title">自定义实体词典</span>
        <span class="dict-count">{{ terms.length }} 个词条</span>
      </div>
    </template>

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

    <template #footer>
      <el-button v-if="terms.length" link class="dict-clear" @click="clearAll">清空全部</el-button>
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

const terms = ref([])
const loading = ref(false)
const adding = ref(false)
const newText = ref('')
const newType = ref('ORG')

const typeOptions = computed(() => props.schema.entity_types || [])

function labelOf(type) {
  return typeOptions.value.find((t) => t.key === type)?.label || type
}
function colorOf(type) {
  return typeOptions.value.find((t) => t.key === type)?.color || '#64748b'
}

async function load() {
  loading.value = true
  try {
    const data = await api.getDictionary()
    terms.value = data.items || []
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

async function clearAll() {
  try {
    await ElMessageBox.confirm('将清空全部自定义词条，此操作不可撤销。', '清空词典', {
      confirmButtonText: '清空',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    const res = await api.clearDictionary()
    ElMessage.success(`已清空 ${res.removed} 个词条`)
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

.dict-add {
  display: flex;
  gap: 6px;
}

.dict-type {
  width: 108px;
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

.dict-list {
  max-height: 300px;
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
</style>
