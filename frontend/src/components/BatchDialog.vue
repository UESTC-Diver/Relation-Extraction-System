<template>
  <el-dialog
    :model-value="modelValue"
    width="760px"
    append-to-body
    class="batch-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <template #header>
      <div class="bd-head">
        <span class="bd-title">批量抽取</span>
        <span class="bd-sub">一次处理多篇文本，并给出跨文档聚合</span>
      </div>
    </template>

    <div class="bd-mode">
      <el-radio-group v-model="mode" size="small" aria-label="批量输入方式">
        <el-radio-button value="files">多个文件</el-radio-button>
        <el-radio-button value="texts">多段文本</el-radio-button>
      </el-radio-group>
      <el-checkbox v-model="save" size="small">写入历史记录</el-checkbox>
      <span class="bd-limit">单批最多 20 篇 · 每篇 ≤ 20000 字 / 2 MB</span>
    </div>

    <div v-if="mode === 'files'" class="bd-input">
      <el-upload
        :auto-upload="false"
        :show-file-list="false"
        multiple
        accept=".txt,.md,.text"
        :on-change="onFileChange"
      >
        <el-button :icon="Upload">选择文本文件</el-button>
      </el-upload>
      <div v-if="files.length" class="bd-files">
        <span v-for="f in files" :key="f.name + f.size" class="bd-file">
          {{ f.name }}
          <button type="button" :aria-label="`移除 ${f.name}`" @click="removeFile(f)">×</button>
        </span>
      </div>
      <p v-else class="bd-placeholder">还没选文件。支持 UTF-8 / GBK / BIG5 / UTF-16，编码自动识别。</p>
    </div>

    <div v-else class="bd-input">
      <el-input
        v-model="textBlocks"
        type="textarea"
        :rows="6"
        resize="none"
        placeholder="用空行分隔多篇文本。例如：&#10;&#10;腾讯控股宣布收购搜狗公司。&#10;&#10;阿里巴巴集团投资饿了么公司。"
        aria-label="多篇文本，用空行分隔"
      />
      <p class="bd-placeholder">已识别 {{ blockCount }} 篇（用空行分隔）</p>
    </div>

    <div class="bd-actions">
      <el-button type="primary" :icon="MagicStick" :loading="running" @click="run">
        {{ running ? '正在逐篇分析…' : '开始批量抽取' }}
      </el-button>
      <el-progress
        v-if="running || report"
        :percentage="progress"
        :stroke-width="4"
        :show-text="false"
        class="bd-progress"
      />
      <span v-if="report" class="bd-summary">
        {{ report.succeeded }} / {{ report.total }} 篇成功 ·
        合计 {{ report.aggregate.relations }} 条关系
      </span>
    </div>

    <div v-if="error" class="bd-error" role="alert">{{ error }}</div>

    <div v-if="report" class="bd-result">
      <el-table :data="report.items" height="200" size="small" class="bd-table">
        <el-table-column type="index" label="#" width="46" />
        <el-table-column label="篇名" min-width="170">
          <template #default="{ row }">
            <span class="bd-name" :title="row.title">{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="entity_count" label="实体" width="70" align="center" />
        <el-table-column prop="relation_count" label="关系" width="70" align="center" />
        <el-table-column label="耗时" width="86" align="center">
          <template #default="{ row }">{{ row.elapsed_ms }} ms</template>
        </el-table-column>
        <el-table-column label="结果" width="132" align="center">
          <template #default="{ row }">
            <span v-if="row.error" class="bd-fail" :title="row.error">失败</span>
            <el-button
              v-else-if="row.record_id"
              link
              size="small"
              @click="loadOne(row)"
            >载入 #{{ row.record_id }}</el-button>
            <span v-else class="bd-note">预览</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="bd-agg">
        <div class="bd-agg-col">
          <h3>跨文档高频实体</h3>
          <div v-if="report.aggregate.top_entities.length" class="bd-chips">
            <span v-for="e in report.aggregate.top_entities" :key="e.name + e.type" class="bd-chip">
              {{ e.name }} <b>{{ e.cnt }}</b>
            </span>
          </div>
          <p v-else class="bd-placeholder">没有可聚合的实体</p>
        </div>
        <div class="bd-agg-col">
          <h3>跨文档高频关系</h3>
          <div v-if="report.aggregate.top_relations.length" class="bd-chips">
            <span v-for="r in report.aggregate.top_relations" :key="r.relation" class="bd-chip">
              {{ r.relation_label }} <b>{{ r.cnt }}</b>
            </span>
          </div>
          <p v-else class="bd-placeholder">没有可聚合的关系</p>
        </div>
      </div>

      <div v-if="report.aggregate.top_pairs.length" class="bd-pairs">
        <h3>最高频三元组</h3>
        <p v-for="p in report.aggregate.top_pairs" :key="p.head + p.relation_label + p.tail">
          {{ p.head }} <i>— {{ p.relation_label }} →</i> {{ p.tail }} <b>×{{ p.cnt }}</b>
        </p>
      </div>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { MagicStick, Upload } from '@element-plus/icons-vue'
import * as api from '../api/client'

defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'load', 'finished'])

const MAX_ITEMS = 20
const mode = ref('files')
const save = ref(true)
const files = ref([])
const textBlocks = ref('')
const running = ref(false)
const progress = ref(0)
const report = ref(null)
const error = ref('')

const blocks = computed(() =>
  textBlocks.value
    .split(/\n\s*\n/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, MAX_ITEMS),
)
const blockCount = computed(() => blocks.value.length)

function onFileChange(uploadFile) {
  const file = uploadFile?.raw
  if (!file) return
  if (!/\.(txt|md|text)$/i.test(file.name)) {
    ElMessage.error(`「${file.name}」不是支持的文本格式`)
    return
  }
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.error(`「${file.name}」超过 2 MB`)
    return
  }
  if (files.value.length >= MAX_ITEMS) {
    ElMessage.warning(`单批最多 ${MAX_ITEMS} 个文件`)
    return
  }
  if (!files.value.some((f) => f.name === file.name && f.size === file.size)) {
    files.value.push(file)
  }
}

function removeFile(file) {
  files.value = files.value.filter((f) => f !== file)
}

async function run() {
  if (running.value) return
  error.value = ''
  report.value = null
  progress.value = 0

  let request
  if (mode.value === 'files') {
    if (!files.value.length) {
      ElMessage.warning('请先选择文本文件')
      return
    }
    request = () =>
      api.batchExtractFiles(files.value, save.value, {
        onProgress: (e) => {
          if (e.total) progress.value = Math.min(90, Math.round((e.loaded / e.total) * 90))
        },
      })
  } else {
    if (!blocks.value.length) {
      ElMessage.warning('请输入至少一段文本')
      return
    }
    const items = blocks.value.map((text, i) => ({
      text,
      title: `第 ${i + 1} 篇 · ${text.slice(0, 12)}${text.length > 12 ? '…' : ''}`,
    }))
    request = () => api.batchExtract(items, save.value)
  }

  running.value = true
  try {
    report.value = await request()
    progress.value = 100
    emit('finished')
    ElMessage.success(`完成 ${report.value.succeeded} 篇，失败 ${report.value.failed} 篇`)
  } catch (err) {
    error.value = err.message
  } finally {
    running.value = false
  }
}

function loadOne(row) {
  emit('load', row.record_id)
  emit('update:modelValue', false)
}
</script>

<style scoped>
.bd-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.bd-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}
.bd-sub {
  font-size: 11.5px;
  color: var(--muted);
}
.bd-mode {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 12px;
}
.bd-limit {
  font-size: 11px;
  color: var(--faint);
  margin-left: auto;
}
.bd-input {
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-2);
}
.bd-files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.bd-file {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 220px;
  padding: 3px 8px;
  font-size: 11.5px;
  color: var(--ink-2);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bd-file button {
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0 2px;
}
.bd-file button:hover {
  color: var(--danger);
}
.bd-placeholder {
  margin: 8px 0 0;
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--muted);
}
.bd-input :deep(.el-textarea__inner) {
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.8;
}
.bd-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 0;
}
.bd-progress {
  flex: 1;
  min-width: 80px;
}
.bd-summary {
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.bd-error {
  padding: 8px 12px;
  font-size: 12px;
  color: var(--danger);
  background: var(--brand-red-soft);
  border-radius: var(--r-sm);
}
.bd-result {
  margin-top: 4px;
}
.bd-table {
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  font-size: 12px;
}
.bd-name {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.bd-fail {
  color: var(--danger);
}
.bd-note {
  color: var(--muted);
}
.bd-agg {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 14px;
}
.bd-agg h3,
.bd-pairs h3 {
  margin: 0 0 7px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ink-2);
}
.bd-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.bd-chip {
  padding: 2px 8px;
  font-size: 11.5px;
  color: var(--ink-2);
  background: var(--surface-3);
  border: 1px solid var(--line);
  border-radius: var(--r-xs);
}
.bd-chip b {
  color: var(--brand-red);
  font-variant-numeric: tabular-nums;
}
.bd-pairs {
  margin-top: 12px;
}
.bd-pairs p {
  margin: 0 0 4px;
  font-size: 11.5px;
  color: var(--ink-2);
}
.bd-pairs i {
  font-style: normal;
  color: var(--muted);
}
.bd-pairs b {
  color: var(--brand-red);
  font-variant-numeric: tabular-nums;
}
@media (max-width: 720px) {
  .bd-agg {
    grid-template-columns: 1fr;
  }
  .bd-limit {
    margin-left: 0;
  }
}
</style>
