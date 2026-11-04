<template>
  <el-drawer
    :model-value="modelValue"
    size="400px"
    direction="rtl"
    :with-header="true"
    class="history-drawer"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="refresh"
  >
    <template #header>
      <div class="hd-head">
        <span class="hd-title">抽取历史</span>
        <span class="hd-count">{{ total }} 条</span>
      </div>
    </template>

    <div class="hd-toolbar">
      <el-input
        v-model="keyword"
        size="small"
        placeholder="按标题或正文搜索"
        clearable
        :prefix-icon="Search"
        @keyup.enter="refresh"
        @clear="refresh"
      />
      <el-button size="small" :icon="Delete" @click="confirmClear">清空</el-button>
    </div>

    <div v-loading="loading" class="hd-list">
      <div
        v-for="item in items"
        :key="item.id"
        class="hd-item"
        :class="{ 'is-active': activeId === item.id }"
      >
        <button
          class="hd-item-main"
          type="button"
          :aria-label="`载入「${item.title || '未命名记录'}」，${item.entity_count} 个实体，${item.relation_count} 条关系`"
          @click="open(item.id)"
        >
          <span class="hd-item-title">{{ item.title || '未命名记录' }}</span>
          <span class="hd-item-meta">
            <span class="hd-time">{{ item.created_at }}</span>
            <span class="hd-sep">·</span>
            <span>{{ item.entity_count }} 实体</span>
            <span class="hd-sep">·</span>
            <span>{{ item.relation_count }} 关系</span>
            <span v-if="item.source === 'file'" class="badge">文件</span>
          </span>
          <span class="hd-chevron" aria-hidden="true">›</span>
        </button>
        <el-popconfirm title="删除这条记录？删除后不可恢复。" @confirm="remove(item.id)">
          <template #reference>
            <button class="hd-del" type="button" :aria-label="`删除「${item.title || '未命名记录'}」`">
              删除
            </button>
          </template>
        </el-popconfirm>
      </div>

      <el-empty v-if="!loading && !items.length" description="还没有抽取记录" :image-size="72" />
    </div>

    <div class="hd-footer" v-if="total > pageSize">
      <el-pagination
        size="small"
        layout="prev, pager, next"
        :page-size="pageSize"
        :total="total"
        :current-page="page"
        @current-change="onPage"
      />
    </div>
  </el-drawer>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Search } from '@element-plus/icons-vue'
import * as api from '../api/client'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'load'])

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 12
const keyword = ref('')
const loading = ref(false)
const activeId = ref(null)

async function refresh() {
  loading.value = true
  try {
    const data = await api.getRecords({ limit: pageSize, offset: (page.value - 1) * pageSize, keyword: keyword.value })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    loading.value = false
  }
}

function onPage(p) {
  page.value = p
  refresh()
}

async function open(id) {
  try {
    const record = await api.getRecord(id)
    activeId.value = id
    emit('load', record)
    emit('update:modelValue', false)
    ElMessage.success('已载入历史记录')
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function remove(id) {
  try {
    await api.deleteRecord(id)
    if (activeId.value === id) activeId.value = null
    ElMessage.success('已删除')
    refresh()
    emit('load', null)
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function confirmClear() {
  if (!total.value) {
    ElMessage.warning('当前没有历史记录')
    return
  }
  try {
    await ElMessageBox.confirm(`将删除全部 ${total.value} 条历史记录，此操作不可撤销。`, '清空历史记录', {
      confirmButtonText: '清空',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    const res = await api.clearRecords()
    ElMessage.success(`已清空 ${res.removed} 条记录`)
    page.value = 1
    activeId.value = null
    refresh()
    emit('load', null)
  } catch (err) {
    ElMessage.error(err.message)
  }
}

defineExpose({ refresh })
</script>

<style scoped>
.hd-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.hd-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}

.hd-count {
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.hd-toolbar {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}

.hd-toolbar :deep(.el-input__wrapper),
.hd-toolbar :deep(.el-button) {
  height: 28px;
  min-height: 28px;
  font-size: 12px;
  border-radius: var(--r-sm);
}

.hd-toolbar :deep(.el-button) {
  padding: 0 10px;
}

/* ---------- 列表 ---------- */
.hd-list {
  display: flex;
  flex-direction: column;
  min-height: 140px;
}

.hd-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 6px 3px 4px;
  border-bottom: 1px solid var(--line);
  border-radius: var(--r-sm);
  transition: background 0.12s ease;
}

.hd-item:hover {
  background: var(--surface-3);
}

.hd-item.is-active {
  background: var(--surface-3);
  box-shadow: inset 2px 0 0 var(--brand);
}

/* 整行即「载入」按钮：键盘可达，不再依赖 hover 才出现的链接 */
.hd-item-main {
  flex: 1;
  min-width: 0;
  display: block;
  position: relative;
  padding: 6px 16px 6px 4px;
  border: none;
  background: transparent;
  border-radius: var(--r-xs);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

/* 行末的 › 提示"整行可载入"，避免只剩一个"删除"看着像删除列表 */
.hd-chevron {
  position: absolute;
  right: 1px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 15px;
  line-height: 1;
  color: var(--faint);
  transition: color 0.12s ease, transform 0.12s ease;
}

.hd-item:hover .hd-chevron,
.hd-item-main:focus-visible .hd-chevron {
  color: var(--ink-2);
  transform: translateY(-50%) translateX(1px);
}

.hd-item-title {
  display: block;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.5;
}

.hd-item-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-top: 2px;
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.hd-time {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: -0.2px;
}

.hd-sep {
  color: var(--faint);
}

.badge {
  margin-left: 2px;
  padding: 0 5px;
  border-radius: var(--r-xs);
  font-size: 10px;
  color: var(--ink-2);
  background: var(--surface);
  border: 1px solid var(--line);
}

/* 删除：常显但低对比，hover / 聚焦时才提示危险色 */
.hd-del {
  flex: none;
  height: 24px;
  padding: 0 7px;
  font-family: inherit;
  font-size: 11px;
  color: var(--muted);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-xs);
  cursor: pointer;
  transition: color 0.14s ease, background 0.14s ease, border-color 0.14s ease;
}

.hd-del:hover,
.hd-del:focus-visible {
  color: var(--danger);
  background: #fdf6f6;
  border-color: #f3dddd;
}

.hd-footer {
  display: flex;
  justify-content: center;
  padding-top: 10px;
}
</style>
