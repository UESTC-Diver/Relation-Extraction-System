<template>
  <div class="app">
    <header class="appbar">
      <div class="appbar-brand">
        <svg class="appbar-logo" viewBox="0 0 26 26" fill="none" aria-hidden="true">
          <path
            d="M8.1 8.4 L18.1 11 M8.5 10 L11.2 17.2 M18.4 12.6 L14.6 18.2"
            stroke="#c9ced4"
            stroke-width="1.3"
            stroke-linecap="round"
          />
          <circle cx="6.6" cy="7.8" r="3.1" fill="#1f2126" />
          <circle cx="20.2" cy="10.6" r="3.1" fill="#1f2126" />
          <circle cx="13" cy="20" r="3.1" fill="#2f5cf6" />
        </svg>
        <div>
          <h1 class="appbar-name">中文关系抽取系统</h1>
          <span class="appbar-sub">规则式 NLP · 6 类实体 · 19 类关系 · 三元组与图谱</span>
        </div>
      </div>

      <div class="appbar-right">
        <div class="appbar-metric">
          <b>{{ stats.records ?? 0 }}</b>
          <span>次抽取</span>
        </div>
        <i class="appbar-divider"></i>
        <div class="appbar-metric">
          <b>{{ stats.relations ?? 0 }}</b>
          <span>条三元组</span>
        </div>
        <button class="btn-quiet" type="button" @click="historyOpen = true">
          <el-icon :size="13"><Clock /></el-icon>
          历史记录
        </button>
      </div>
    </header>

    <main class="layout">
      <section class="panel input-panel">
        <TextWorkbench
          v-model="text"
          v-model:title-value="title"
          :samples="samples"
          :schema="schema"
          :loading="loading"
          @run="runExtract"
          @file="onFile"
          @clear="onClear"
        />
      </section>

      <section class="panel result-panel">
        <div class="panel-head">
          <div class="panel-title">
            抽取结果
            <small v-if="result">
              {{ result.stats.char_count }} 字 · {{ result.stats.sentence_count }} 句 ·
              {{ result.stats.elapsed_ms }} ms
            </small>
            <small v-else>等待输入文本</small>
          </div>

          <div class="head-right">
            <span v-if="activeRecordId" class="rec-id">#{{ activeRecordId }}</span>
            <button
              v-else-if="result"
              class="btn-quiet btn-save"
              type="button"
              :disabled="loading"
              @click="saveCurrent"
            >
              <el-icon :size="13"><Collection /></el-icon>
              存入历史
            </button>

            <div v-if="result" class="segmented">
              <button
                v-for="t in TABS"
                :key="t.name"
                class="seg-item"
                :class="{ 'is-active': tab === t.name }"
                type="button"
                @click="tab = t.name"
              >
                {{ t.label }}
                <span v-if="t.count !== undefined" class="seg-count">{{ t.count }}</span>
              </button>
            </div>

            <el-dropdown
              v-if="result"
              trigger="click"
              placement="bottom-end"
              popper-class="export-menu"
              @command="onExport"
            >
              <button class="btn-icon" type="button" title="导出当前结果">
                <el-icon :size="14"><Download /></el-icon>
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="csv">
                    <span class="exp-label">三元组 CSV</span>
                    <span class="exp-hint">Excel / Neo4j 可直接导入</span>
                  </el-dropdown-item>
                  <el-dropdown-item command="json">
                    <span class="exp-label">完整 JSON</span>
                    <span class="exp-hint">实体 + 三元组 + 原文</span>
                  </el-dropdown-item>
                  <el-dropdown-item command="md" divided>
                    <span class="exp-label">分析报告 Markdown</span>
                    <span class="exp-hint">含统计、实体表、三元组表</span>
                  </el-dropdown-item>
                  <el-dropdown-item command="png" divided :disabled="tab !== 'graph'">
                    <span class="exp-label">关系图谱 PNG</span>
                    <span class="exp-hint">{{ tab === 'graph' ? '当前视图直接导出' : '切到图谱页可导出' }}</span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <div v-if="result" class="result-body">
          <EntityAnnotator v-if="tab === 'entities'" :result="result" :schema="schema" />
          <TripleTable v-else-if="tab === 'triples'" :relations="result.relations || []" :schema="schema" />
          <RelationGraph v-else-if="tab === 'graph'" ref="graphRef" :relations="result.relations || []" :schema="schema" />
          <StatsOverview v-else :result="result" :stats="stats" :schema="schema" />
        </div>

        <div v-else class="hero">
          <svg class="hero-art" viewBox="0 0 240 112" fill="none" aria-hidden="true">
            <path d="M52 56 L96 40 M100 46 L156 62" stroke="#e2e5e9" stroke-width="1.6" stroke-linecap="round" />
            <path d="M52 56 L156 62" stroke="#eef0f2" stroke-width="1.6" stroke-linecap="round" stroke-dasharray="4 5" />
            <circle cx="44" cy="58" r="14" fill="#fff" stroke="#d7dae0" stroke-width="1.5" />
            <circle cx="44" cy="58" r="4.5" fill="#1f2126" />
            <circle cx="106" cy="38" r="17" fill="#fff" stroke="#d7dae0" stroke-width="1.5" />
            <circle cx="106" cy="38" r="5.5" fill="#2f5cf6" />
            <circle cx="164" cy="66" r="12" fill="#fff" stroke="#d7dae0" stroke-width="1.5" />
            <circle cx="164" cy="66" r="4" fill="#1f2126" />
            <rect x="88" y="58" width="44" height="21" rx="6" fill="#f2f3f5" stroke="#e2e5e9" />
            <text x="110" y="72.5" text-anchor="middle" font-size="11" fill="#494f57">收购</text>
          </svg>

          <h2>粘贴一段新闻，自动抽出实体与关系</h2>
          <p class="hero-sub">
            左侧输入文本或上传 .txt 文件，系统将识别<b>人物 / 组织机构 / 地理位置 / 时间 / 金额 / 产品技术</b>
            六类实体，并输出如「腾讯控股 — 收购 — 搜狗公司」的关系三元组与节点关系图。
          </p>

          <div class="hero-steps">
            <div class="step">
              <span class="step-no">1</span>
              <div>
                <b>输入文本</b>
                <p>粘贴新闻段落，或上传 .txt（支持 UTF-8 / GBK）</p>
              </div>
            </div>
            <div class="step">
              <span class="step-no">2</span>
              <div>
                <b>自动抽取</b>
                <p>分句 → 实体识别 → 触发词与句式模板匹配</p>
              </div>
            </div>
            <div class="step">
              <span class="step-no">3</span>
              <div>
                <b>查看结果</b>
                <p>实体高亮、三元组表格、关系图谱、统计洞察</p>
              </div>
            </div>
          </div>
        </div>
      </section>
    </main>

    <footer class="footer">
      FastAPI + SQLite 后端 · Vue 3 + Element Plus 前端 · 规则式中文 NLP 引擎（jieba 分词 + 词典 + 19 类关系模板）
    </footer>

    <HistoryDrawer v-model="historyOpen" @load="onLoadRecord" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Clock, Collection, Download } from '@element-plus/icons-vue'
import * as api from './api/client'
import { download, buildCsv, buildJson, buildMarkdown, safeFilename } from './utils/export'
import TextWorkbench from './components/TextWorkbench.vue'
import EntityAnnotator from './components/EntityAnnotator.vue'
import TripleTable from './components/TripleTable.vue'
import RelationGraph from './components/RelationGraph.vue'
import StatsOverview from './components/StatsOverview.vue'
import HistoryDrawer from './components/HistoryDrawer.vue'

const text = ref('')
const title = ref('')
const result = ref(null)
const loading = ref(false)
const tab = ref('entities')
const schema = ref({ entity_types: [], relation_types: [] })
const samples = ref([])
const stats = ref({})
const historyOpen = ref(false)
const activeRecordId = ref(null)
const graphRef = ref(null)

const TAB_NAMES = ['entities', 'triples', 'graph', 'stats']

const TABS = computed(() => {
  const s = result.value?.stats
  return [
    { name: 'entities', label: '实体标注', count: s ? s.entity_count : undefined },
    { name: 'triples', label: '关系三元组', count: s ? s.relation_count : undefined },
    { name: 'graph', label: '关系图谱' },
    { name: 'stats', label: '统计洞察' },
  ]
})

function tabFromHash() {
  const hash = (location.hash || '').replace(/^#/, '')
  return TAB_NAMES.includes(hash) ? hash : null
}

watch(tab, (value) => {
  if (location.hash.replace(/^#/, '') !== value) {
    history.replaceState(null, '', `#${value}`)
  }
})

async function refreshStats() {
  try {
    stats.value = await api.getStats()
  } catch {
    /* 统计失败不打断主流程 */
  }
}

function applyResult(payload, recordId = null) {
  result.value = payload
  activeRecordId.value = recordId
  refreshStats()
}

/**
 * 执行抽取。save=false 时只在内存中预览，不写历史记录 —— 页面初始化
 * 自动加载示例走的就是这条路，避免每次刷新都往库里塞一条重复数据。
 */
async function runExtract({ save = true } = {}) {
  if (!text.value.trim()) {
    ElMessage.warning('请先输入或上传一段文本')
    return
  }
  loading.value = true
  try {
    const res = await api.extractText(text.value, title.value, save)
    applyResult(res.result, res.record_id)
    if (save) {
      ElMessage.success(
        `已存入历史 #${res.record_id}：${res.result.stats.entity_count} 个实体，${res.result.stats.relation_count} 条关系`,
      )
    }
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    loading.value = false
  }
}

function saveCurrent() {
  runExtract({ save: true })
}

const EXPORT_MIME = {
  csv: 'text/csv;charset=utf-8',
  json: 'application/json;charset=utf-8',
  md: 'text/markdown;charset=utf-8',
}

const EXPORT_BUILDERS = { csv: buildCsv, json: buildJson, md: buildMarkdown }

/** 导出当前结果：CSV / JSON / Markdown 由工具模块生成，PNG 取自图表实例。 */
function onExport(kind) {
  const data = result.value
  if (!data) return
  const meta = { title: title.value || '未命名文本', recordId: activeRecordId.value }

  try {
    if (kind === 'png') {
      const url = graphRef.value?.snapshot?.()
      if (!url) {
        ElMessage.warning('图谱尚未渲染完成，稍后再试')
        return
      }
      const a = document.createElement('a')
      a.href = url
      a.download = safeFilename(`${meta.title}-关系图谱`, 'png')
      a.click()
      ElMessage.success('图谱已导出')
      return
    }

    const file = EXPORT_BUILDERS[kind](data, meta)
    download(file.filename, file.content, EXPORT_MIME[kind])
    ElMessage.success(`已导出 ${file.filename}`)
  } catch (err) {
    ElMessage.error(`导出失败：${err.message}`)
  }
}

async function onFile(file) {
  loading.value = true
  try {
    const res = await api.extractFile(file, true)
    text.value = res.result.text
    title.value = file.name.replace(/\.[^.]+$/, '')
    applyResult(res.result, res.record_id)
    ElMessage.success(`${file.name} 解析完成：${res.result.stats.relation_count} 条关系`)
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    loading.value = false
  }
}

function onClear() {
  result.value = null
  activeRecordId.value = null
}

function onLoadRecord(record) {
  if (!record) {
    if (!result.value) activeRecordId.value = null
    return
  }
  const relations = (record.relations || []).map((r) => ({
    ...r,
    relation_color: '',
  }))
  const relationTypeCounts = {}
  for (const r of relations) relationTypeCounts[r.relation] = (relationTypeCounts[r.relation] || 0) + 1

  const sentenceMap = new Map()
  for (const r of relations) {
    if (!sentenceMap.has(r.sentence_index)) sentenceMap.set(r.sentence_index, r.evidence || '')
  }
  const sentences = [...sentenceMap.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([index, textValue]) => ({ index, text: textValue }))

  text.value = record.text || ''
  title.value = record.title || ''
  applyResult(
    {
      text: record.text,
      entities: record.entities || [],
      relations,
      entity_type_counts: record.entity_type_counts || {},
      relation_type_counts: relationTypeCounts,
      sentences,
      stats: {
        char_count: record.char_count,
        sentence_count: record.sentence_count,
        entity_count: record.entity_count,
        relation_count: record.relation_count,
        elapsed_ms: record.elapsed_ms,
      },
    },
    record.id,
  )
}

onMounted(async () => {
  const hashTab = tabFromHash()
  if (hashTab) tab.value = hashTab
  try {
    const [sampleList, schemaData, statData] = await Promise.all([
      api.getSamples(),
      api.getSchema(),
      api.getStats(),
    ])
    samples.value = sampleList
    schema.value = schemaData
    stats.value = statData
    if (sampleList.length) {
      text.value = sampleList[0].content
      title.value = sampleList[0].title
      // 预览模式：只展示抽取效果，不写历史记录
      await runExtract({ save: false })
    }
  } catch (err) {
    ElMessage.error(`后端未连通：${err.message}`)
  }
})
</script>

<style scoped>
.head-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}

.rec-id {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted);
  background: var(--surface-3);
  border-radius: var(--r-xs);
  padding: 2px 6px;
  letter-spacing: 0.2px;
}

.result-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px 14px 14px;
  overflow: hidden;
}

/* ---------- 空状态 ---------- */
.hero {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 28px 32px 40px;
}

.hero-art {
  width: 240px;
  height: 112px;
  margin-bottom: 20px;
}

.hero h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: var(--ink);
  letter-spacing: 0.2px;
}

.hero-sub {
  margin: 8px 0 0;
  max-width: 540px;
  font-size: 12.5px;
  line-height: 1.85;
  color: var(--muted);
}

.hero-sub b {
  color: var(--ink-2);
  font-weight: 500;
}

.hero-steps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin-top: 26px;
  width: 100%;
  max-width: 660px;
}

.step {
  display: flex;
  gap: 10px;
  text-align: left;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-2);
}

.step-no {
  flex: none;
  width: 20px;
  height: 20px;
  border-radius: var(--r-xs);
  background: var(--surface);
  border: 1px solid var(--line-strong);
  color: var(--ink-2);
  font-size: 11px;
  font-weight: 600;
  display: grid;
  place-items: center;
  font-variant-numeric: tabular-nums;
}

.step b {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
}

.step p {
  margin: 3px 0 0;
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--muted);
}

@media (max-width: 1120px) {
  .result-panel {
    min-height: 560px;
  }
}

@media (max-width: 860px) {
  .panel-head {
    flex-wrap: wrap;
  }
  .hero {
    padding: 24px 18px 32px;
  }
}
</style>
