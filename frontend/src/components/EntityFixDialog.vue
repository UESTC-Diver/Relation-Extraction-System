<template>
  <el-dialog
    :model-value="modelValue"
    width="780px"
    append-to-body
    class="ef-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="reset"
  >
    <template #header>
      <div class="ef-head">
        <span class="ef-title">实体校正</span>
        <span class="ef-sub">改边界、类型与归一写法，写回历史记录</span>
      </div>
    </template>

    <div v-if="!recordId" class="ef-warn" role="alert">
      当前结果是预览态。请先点「存入历史」或「保存校正」，再回来修改实体。
    </div>

    <div class="ef-legend">
      <span>原文写法</span><span>类型</span><span>归一写法</span><span></span>
    </div>
    <div class="ef-list">
      <div v-for="(e, i) in rows" :key="i" class="ef-row">
        <el-input v-model="e.text" size="small" :aria-label="`第 ${i + 1} 个实体名称`" />
        <el-select v-model="e.type" size="small" :aria-label="`第 ${i + 1} 个实体类型`">
          <el-option v-for="t in entityTypes" :key="t.key" :label="t.label" :value="t.key" />
        </el-select>
        <el-input v-model="e.canonical" size="small" :aria-label="`第 ${i + 1} 个归一写法`" />
        <button type="button" :aria-label="`删除第 ${i + 1} 个实体`" @click="rows.splice(i, 1)">×</button>
      </div>
      <p v-if="!rows.length" class="ef-muted">没有实体。可以点下方按钮手工添加一条。</p>
    </div>

    <div class="ef-bar">
      <el-button size="small" @click="addRow">添加实体</el-button>
      <span class="ef-muted">共 {{ rows.length }} 条 · 归一写法用于合并同一实体的不同称呼</span>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :disabled="!recordId" :loading="saving" @click="save">保存实体校正</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '../api/client'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  entities: { type: Array, default: () => [] },
  recordId: { type: Number, default: null },
  schema: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const rows = ref([])
const saving = ref(false)
let original = []

const entityTypes = computed(() => props.schema.entity_types || [])

function reset() {
  original = props.entities.map((e) => ({ ...e }))
  rows.value = props.entities.map((e) => ({
    ...e,
    text: e.text || '',
    type: e.type || 'ORG',
    canonical: e.canonical || e.text || '',
  }))
}

function addRow() {
  rows.value.push({ text: '', type: 'ORG', canonical: '' })
}

async function save() {
  if (!props.recordId) return
  const cleaned = rows.value
    .map((r) => ({ ...r, text: (r.text || '').trim(), canonical: (r.canonical || r.text || '').trim() }))
    .filter((r) => r.text)
  if (cleaned.some((r) => !r.canonical)) {
    ElMessage.warning('归一写法不能为空')
    return
  }
  const corrections = []
  cleaned.forEach((r, i) => {
    const before = original[i]
    if (!before || before.text !== r.text || before.canonical !== r.canonical || before.type !== r.type) {
      corrections.push({
        original: before?.text || '',
        corrected: r.canonical,
        type: r.type,
      })
    }
  })
  saving.value = true
  try {
    const record = await api.saveEntities(props.recordId, cleaned, corrections)
    ElMessage.success(`已保存 ${cleaned.length} 个实体，记录 ${corrections.length} 处改动`)
    emit('saved', record)
    emit('update:modelValue', false)
  } catch (err) {
    ElMessage.error(`保存失败：${err.message}`)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.ef-head { display: flex; align-items: baseline; gap: 10px; }
.ef-title { font-size: 13.5px; font-weight: 600; color: var(--ink); }
.ef-sub, .ef-muted { font-size: 11.5px; color: var(--muted); }
.ef-warn { padding: 9px 12px; margin-bottom: 12px; font-size: 12px; color: var(--danger); background: var(--brand-red-soft); border-radius: var(--r-sm); }
.ef-legend, .ef-row { display: grid; grid-template-columns: 1.3fr 0.9fr 1.2fr 28px; gap: 8px; align-items: center; }
.ef-legend { margin-bottom: 6px; font-size: 11px; color: var(--muted); }
.ef-list { max-height: 340px; overflow: auto; padding: 4px; border: 1px solid var(--line); border-radius: var(--r-sm); background: var(--surface-2); }
.ef-row { margin-bottom: 6px; }
.ef-row button { border: none; background: transparent; color: var(--muted); cursor: pointer; font-size: 17px; }
.ef-row button:hover { color: var(--brand-red); }
.ef-bar { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
@media (max-width: 720px) {
  .ef-legend { display: none; }
  .ef-row { grid-template-columns: 1fr 1fr; }
}
</style>
