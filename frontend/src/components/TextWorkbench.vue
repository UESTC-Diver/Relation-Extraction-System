<template>
  <div class="workbench">
    <div class="wb-head">
      <div class="panel-title">
        文本输入
        <small>粘贴中文新闻，或上传 .txt</small>
      </div>
      <span class="wb-count" :class="{ 'is-warn': charCount > 18000 }">
        {{ charCount }}<i>/20000</i>
      </span>
    </div>

    <div class="wb-samples">
      <span class="wb-label">示例</span>
      <button
        v-for="s in samples"
        :key="s.id"
        class="sample-chip"
        :class="{ 'is-active': activeSample === s.id }"
        type="button"
        :title="s.title"
        @click="applySample(s)"
      >
        {{ s.title }}
      </button>
    </div>

    <el-input
      v-model="text"
      class="wb-textarea"
      type="textarea"
      :rows="11"
      resize="none"
      maxlength="20000"
      placeholder="例如：9月5日，腾讯控股宣布以每股58美元的价格收购搜狗公司全部流通股，交易总金额约为35亿美元。搜狗公司成立于2004年，总部位于北京，创始人为王小川……"
    />

    <el-input v-model="title" class="wb-title" size="small" placeholder="记录标题（可选，默认截取正文）" clearable />

    <div class="wb-actions">
      <el-upload :auto-upload="false" :show-file-list="false" :on-change="onFile" accept=".txt,.md,.text">
        <el-button :icon="Upload">上传</el-button>
      </el-upload>
      <div class="wb-actions-right">
        <el-button :icon="Delete" @click="clear">清空</el-button>
        <el-button type="primary" :icon="MagicStick" :loading="loading" @click="submit">
          {{ loading ? '分析中…' : '开始抽取' }}
        </el-button>
      </div>
    </div>

    <el-collapse v-model="opened" class="wb-ability">
      <el-collapse-item name="ability">
        <template #title>
          <span class="wb-ability-title">
            <el-icon :size="12"><InfoFilled /></el-icon>
            识别能力 · {{ schema.entity_types?.length || 0 }} 类实体 / {{ schema.relation_types?.length || 0 }} 类关系
          </span>
        </template>
        <div class="ability-block">
          <div class="ability-label">实体类型</div>
          <div class="ability-tags">
            <span
              v-for="t in schema.entity_types || []"
              :key="t.key"
              class="ability-tag"
              :style="{ color: t.color, borderColor: t.color + '3d', background: t.color + '0f' }"
            >
              {{ t.label }}
            </span>
          </div>
        </div>
        <div class="ability-block">
          <div class="ability-label">关系类型</div>
          <div class="ability-tags">
            <span
              v-for="r in schema.relation_types || []"
              :key="r.key"
              class="ability-tag"
              :style="{ color: r.color, borderColor: r.color + '3d', background: r.color + '0f' }"
              :title="r.description"
            >
              {{ r.label }}
            </span>
          </div>
        </div>
        <p class="ability-note">
          引擎为「词典 + 词法规则 + jieba 词性」的离线流水线：先分句，再按机构/地名后缀、人物上下文、职位线索识别实体，
          最后以触发词锚定句式模板（不含 BERT 类模型依赖），结果确定、可解释。
        </p>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, InfoFilled, MagicStick, Upload } from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  titleValue: { type: String, default: '' },
  samples: { type: Array, default: () => [] },
  schema: { type: Object, default: () => ({}) },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'update:titleValue', 'run', 'file', 'clear'])

const opened = ref([])
const activeSample = ref('')

const text = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const title = computed({
  get: () => props.titleValue,
  set: (v) => emit('update:titleValue', v),
})

const charCount = computed(() => (props.modelValue || '').length)

function applySample(sample) {
  activeSample.value = sample.id
  emit('update:modelValue', sample.content)
  emit('update:titleValue', sample.title)
  emit('run')
}

function onFile(uploadFile) {
  const file = uploadFile?.raw
  if (!file) return
  const isText = /\.(txt|md|text)$/i.test(file.name)
  if (!isText) {
    ElMessage.error('仅支持 .txt / .md 文本文件')
    return
  }
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.error('文件不能超过 2 MB')
    return
  }
  emit('file', file)
}

function clear() {
  activeSample.value = ''
  emit('update:modelValue', '')
  emit('update:titleValue', '')
  emit('clear')
}

function submit() {
  if (!props.modelValue.trim()) {
    ElMessage.warning('请先输入或上传一段文本')
    return
  }
  emit('run')
}
</script>

<style scoped>
.workbench {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 11px 14px 12px;
}

.wb-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 22px;
}

.wb-count {
  flex: none;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.2px;
}

.wb-count i {
  font-style: normal;
  color: var(--faint);
}

.wb-count.is-warn {
  color: var(--warn);
}

/* ---------- 示例 ---------- */
.wb-samples {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}

.wb-label {
  flex: none;
  font-size: 11.5px;
  color: var(--muted);
  margin-right: 3px;
}

.sample-chip {
  flex: none;
  max-width: 100%;
  padding: 3px 8px;
  font-family: inherit;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--ink-2);
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.sample-chip:hover {
  background: var(--surface-3);
  border-color: var(--line-strong);
  color: var(--ink);
}

.sample-chip.is-active {
  background: var(--surface);
  border-color: var(--brand);
  color: var(--ink);
  font-weight: 500;
}

/* ---------- 输入区 ---------- */
.wb-textarea {
  flex: 1 1 auto;
  min-height: 190px;
  display: flex;
}

.wb-textarea :deep(.el-textarea__inner) {
  height: 100%;
  padding: 12px 13px;
  font-family: inherit;
  font-size: 13.5px;
  line-height: 1.9;
  color: var(--ink);
  background: var(--surface);
  border-radius: var(--r-sm);
  box-shadow: 0 0 0 1px var(--line) inset;
  resize: none;
}

.wb-textarea :deep(.el-textarea__inner::placeholder) {
  color: var(--faint);
  font-size: 12.5px;
  line-height: 1.9;
}

.wb-title :deep(.el-input__wrapper) {
  border-radius: var(--r-sm);
  padding: 1px 10px;
}

.wb-title :deep(.el-input__inner) {
  font-size: 12.5px;
}

/* ---------- 操作 ---------- */
.wb-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 2px;
}

.wb-actions-right {
  display: flex;
  gap: 6px;
}

.wb-actions :deep(.el-button) {
  height: 30px;
  padding: 0 12px;
  font-size: 12.5px;
}

/* ---------- 能力面板 ---------- */
.wb-ability {
  border-top: 1px solid var(--line);
  border-bottom: none;
}

.wb-ability :deep(.el-collapse-item__header) {
  height: 32px;
  border-bottom: none;
  font-size: 11.5px;
  color: var(--muted);
  background: transparent;
}

.wb-ability :deep(.el-collapse-item__wrap) {
  border-bottom: none;
  background: transparent;
}

.wb-ability :deep(.el-collapse-item__content) {
  padding-bottom: 8px;
}

.wb-ability-title {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.ability-block {
  margin-bottom: 9px;
}

.ability-label {
  font-size: 10.5px;
  color: var(--faint);
  letter-spacing: 0.8px;
  margin-bottom: 5px;
  text-transform: uppercase;
}

.ability-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.ability-tag {
  font-size: 11px;
  line-height: 1.6;
  padding: 1px 7px;
  border-radius: var(--r-xs);
  border: 1px solid transparent;
  cursor: default;
}

.ability-note {
  margin: 4px 0 0;
  font-size: 11px;
  line-height: 1.75;
  color: var(--faint);
}
</style>
