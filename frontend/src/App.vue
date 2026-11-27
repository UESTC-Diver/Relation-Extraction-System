<template>
  <LandingPage v-if="page === 'landing'" />

  <DemoSandbox v-else-if="page === 'demo'" />

  <DossierPage v-else-if="page === 'cases'" />

  <VerifyPage v-else-if="page === 'verify'" />

  <div v-else-if="page === 'missing'" class="missing" role="main">
    <p class="missing-code">404</p>
    <h1 class="missing-title">这一页不存在</h1>
    <p class="missing-note">地址没有对应的页面。首页介绍这套系统，静态试用展示真实样例，工作台用来实际抽取。</p>
    <div class="missing-links">
      <a href="/">返回首页</a>
      <a href="/demo">看静态样例</a>
      <a href="/app">进入工作台</a>
    </div>
  </div>

  <div v-else class="app">
    <a class="skip-link" href="#result-panel">跳到抽取结果</a>

    <header class="appbar">
      <a class="appbar-brand" href="/" title="返回首页" aria-label="中文关系抽取系统，返回首页">
        <svg class="appbar-logo" viewBox="0 0 26 26" fill="none" aria-hidden="true">
          <path
            d="M8.1 8.4 L18.1 11 M8.5 10 L11.2 17.2 M18.4 12.6 L14.6 18.2"
            stroke="#ddd5c2"
            stroke-width="1.3"
            stroke-linecap="round"
          />
          <circle cx="6.6" cy="7.8" r="3.1" fill="#201e19" />
          <circle cx="20.2" cy="10.6" r="3.1" fill="#201e19" />
          <circle cx="13" cy="20" r="3.1" fill="#a8322a" />
        </svg>
        <h1 class="appbar-name">中文关系抽取系统</h1>
      </a>

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
        <button class="btn-quiet" type="button" @click="batchOpen = true">
          <el-icon :size="13"><Files /></el-icon>
          批量抽取
        </button>
        <button class="btn-quiet" type="button" @click="historyOpen = true">
          <el-icon :size="13"><Clock /></el-icon>
          历史记录
        </button>
        <button class="btn-quiet" type="button" @click="knowledgeOpen = true">
          <el-icon :size="13"><Files /></el-icon>
          知识库
        </button>
        <button
          class="btn-quiet"
          type="button"
          :disabled="!activeRecordId"
          :title="activeRecordId ? '逐条复核、定稿并生成只读报告' : '先存入历史再开始复核'"
          aria-label="复核与定稿"
          @click="reviewOpen = true"
        >
          <el-icon :size="13"><EditPen /></el-icon>
          复核<span
            v-if="reviewBadge"
            :style="{ marginLeft: '4px', fontSize: '10px', color: 'var(--accent)', fontVariantNumeric: 'tabular-nums' }"
          >{{ reviewBadge }}</span>
        </button>
        <el-dropdown trigger="click" placement="bottom-end" popper-class="export-menu" @command="onMoreCommand">
          <button class="btn-quiet" type="button" title="更多功能" aria-label="更多功能">
            <el-icon :size="13"><EditPen /></el-icon>
            更多
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="cases">
                <span class="exp-label">尽调案卷</span>
                <span class="exp-hint">多份材料归档成一个标的的关联方核查档案</span>
              </el-dropdown-item>
              <el-dropdown-item command="verify">
                <span class="exp-label">信息甄别</span>
                <span class="exp-hint">网传消息分层核查，标出可疑措辞与证据线索</span>
              </el-dropdown-item>
              <el-dropdown-item command="annotate">
                <span class="exp-label">金标准标注</span>
                <span class="exp-hint">判该抽 / 不该抽、补漏抽，算出自己材料上的 F1</span>
              </el-dropdown-item>
              <el-dropdown-item command="eval">
                <span class="exp-label">效果评测台</span>
                <span class="exp-hint">跑 P / R / F1，看漏抽误抽与回归曲线</span>
              </el-dropdown-item>
              <el-dropdown-item command="rules">
                <span class="exp-label">规则实验室</span>
                <span class="exp-hint">候选触发词 A/B 试跑与配置回滚</span>
              </el-dropdown-item>
              <el-dropdown-item command="import" divided>
                <span class="exp-label">导入项目包</span>
                <span class="exp-hint">文本、校正、词典与规则一次还原</span>
              </el-dropdown-item>
              <el-dropdown-item command="share">
                <span class="exp-label">复制只读报告链接</span>
                <span class="exp-hint">独立页面，不暴露编辑入口</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <input
          ref="projectInput"
          type="file"
          accept=".json,application/json"
          class="sr-only"
          aria-label="选择项目包文件"
          @change="onProjectFile"
        />
      </div>
    </header>

    <main class="layout" :class="{ 'is-compact': compactActive }">
      <section v-if="compactActive && result" class="panel compact-panel" aria-label="当前文本摘要">
        <div class="cp-head">
          <span class="cp-label">当前文本</span>
          <button class="cp-toggle" type="button" @click="toggleCompact(false)" title="展开输入框（Ctrl/⌘ + E）">
            <el-icon :size="12"><ArrowRight /></el-icon>
          </button>
        </div>
        <div class="cp-title" :title="title || '未命名文本'">{{ title || '未命名文本' }}</div>
        <dl class="cp-meta">
          <div><dt>字数</dt><dd>{{ result.stats.char_count }}</dd></div>
          <div><dt>句子</dt><dd>{{ result.stats.sentence_count }}</dd></div>
          <div><dt>实体</dt><dd>{{ result.stats.entity_count }}</dd></div>
          <div><dt>关系</dt><dd>{{ result.stats.relation_count }}</dd></div>
        </dl>
        <button class="btn-quiet cp-edit" type="button" @click="toggleCompact(false)">
          <el-icon :size="13"><EditPen /></el-icon>
          编辑文本
        </button>
        <p v-if="activeRecordId" class="cp-saved">已存入历史 #{{ activeRecordId }}</p>
      </section>

      <section v-else class="panel input-panel">
        <TextWorkbench
          v-model="text"
          v-model:title-value="title"
          :samples="samples"
          :schema="schema"
          :profiles="schema.profiles || []"
          v-model:profile-value="profile"
          v-model:language-value="language"
          :loading="loading"
          @run="runExtract"
          @file="onFile"
          @clear="onClear"
        />
      </section>

      <section
        id="result-panel"
        class="panel result-panel"
        :aria-busy="loading ? 'true' : 'false'"
        tabindex="-1"
      >
        <!-- 新结果落纸：朱红扫光与首页「接口重跑」回显同源。
             key 随结果版本变化，重跑时元素重建即重播，动画不会叠加。 -->
        <div v-if="result" :key="resultVersion" class="result-scan" aria-hidden="true"></div>
        <div class="panel-head">
          <div class="panel-title">
            抽取结果
            <small v-if="result">
              {{ result.stats.char_count }} 字 · {{ result.stats.sentence_count }} 句 ·
              {{ result.stats.elapsed_ms }} ms
            </small>
            <small v-else-if="loading">正在分析…</small>
            <small v-else>等待输入文本</small>
          </div>

          <div class="head-right">
            <div
              v-if="result"
              ref="segmentedRef"
              class="segmented"
              role="tablist"
              aria-label="结果视图切换"
              @keydown="onTabKeydown"
            >
              <span
                class="seg-indicator"
                :class="{ 'is-ready': indicatorReady }"
                :style="indicatorStyle"
                aria-hidden="true"
              ></span>
              <button
                v-for="t in TABS"
                :id="'tab-' + t.name"
                :key="t.name"
                class="seg-item"
                :class="{ 'is-active': tab === t.name }"
                role="tab"
                type="button"
                :aria-selected="tab === t.name ? 'true' : 'false'"
                aria-controls="result-panel"
                :tabindex="tab === t.name ? 0 : -1"
                @click="selectTab(t.name)"
              >
                {{ t.label }}
                <span v-if="t.count !== undefined" class="seg-count">{{ t.count }}</span>
              </button>
            </div>

            <button
              v-if="result"
              class="btn-icon"
              type="button"
              title="复制可复现当前结果的链接"
              aria-label="复制分享链接"
              @click="copyShareLink"
            >
              <el-icon :size="14"><Link /></el-icon>
            </button>

            <el-dropdown
              v-if="result"
              trigger="click"
              placement="bottom-end"
              popper-class="export-menu"
              @command="onExport"
            >
              <button class="btn-icon" type="button" title="导出当前结果" aria-label="导出当前结果">
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
                  <el-dropdown-item command="graphml" divided>
                    <span class="exp-label">关系图谱 GraphML</span>
                    <span class="exp-hint">Gephi / yEd / NetworkX 可直接打开</span>
                  </el-dropdown-item>
                  <el-dropdown-item command="cypher">
                    <span class="exp-label">Neo4j Cypher</span>
                    <span class="exp-hint">MERGE 语句，粘进 Neo4j Browser 即可导入</span>
                  </el-dropdown-item>
                  <el-dropdown-item command="html" divided>
                    <span class="exp-label">单文件 HTML 报告</span>
                    <span class="exp-hint">含统计、图谱、证据与原文，可离线打开</span>
                  </el-dropdown-item>
                  <el-dropdown-item command="project" divided>
                    <span class="exp-label">完整项目包 JSON</span>
                    <span class="exp-hint">文本、校正、词典、触发词与金标准</span>
                  </el-dropdown-item>
                  <el-dropdown-item command="png" divided :disabled="tab !== 'graph'">
                    <span class="exp-label">关系图谱 PNG</span>
                    <span class="exp-hint">{{ tab === 'graph' ? '当前视图直接导出' : '切到图谱页可导出' }}</span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>

          <div v-if="loading" class="load-bar" role="progressbar" aria-label="正在抽取关系"></div>
        </div>

        <p class="sr-only" aria-live="polite">{{ liveMessage }}</p>

        <div v-if="loadError" class="error-strip" role="alert">
          <el-icon :size="13"><WarningFilled /></el-icon>
          <span>{{ loadError }}</span>
          <button class="btn-quiet error-retry" type="button" @click="runExtract()">重试</button>
        </div>

        <div v-else-if="result && !activeRecordId" class="preview-strip">
          <el-icon :size="13"><InfoFilled /></el-icon>
          <span>示例预览 · <b>尚未存入历史</b>，刷新页面不会产生重复记录</span>
          <span class="strip-spacer"></span>
          <button class="btn-quiet strip-btn" type="button" :disabled="loading" @click="saveCurrent">
            存入历史
          </button>
        </div>

        <div v-if="loading && !result" class="result-skeleton" role="status" aria-label="正在抽取">
          <div class="sk-line sk-title"></div>
          <div class="sk-line"></div>
          <div class="sk-line sk-short"></div>
          <div class="sk-grid">
            <div class="sk-card"></div>
            <div class="sk-card"></div>
            <div class="sk-card"></div>
          </div>
          <p class="sk-hint">正在分句、识别实体并匹配关系…</p>
        </div>

        <div
          v-if="result"
          :key="resultVersion"
          class="result-body"
          :class="{ 'is-stale': loading }"
          role="tabpanel"
          :aria-labelledby="'tab-' + tab"
        >
          <EntityAnnotator
            v-if="tab === 'entities'"
            :result="result"
            :schema="schema"
            :link="link"
            @edit-entities="entityFixOpen = true"
          />
          <TripleTable
            v-else-if="tab === 'triples'"
            :relations="editableRelations"
            :schema="schema"
            :entity-filter="entityFilter"
            :sentences="result.sentences || []"
            :record-id="activeRecordId"
            :dirty="dirty"
            :saving="saving"
            :can-undo="undoStack.length > 0"
            :can-redo="redoStack.length > 0"
            :review-map="reviewMap"
            :locked="reviewLocked"
            @locate="onLocate"
            @clear-filter="entityFilter = null"
            @update:relations="onRelationsChange"
            @save="saveCorrections"
            @snapshot="saveAsSnapshot"
            @undo="undo"
            @redo="redo"
          />
          <RelationGraph
            v-else-if="tab === 'graph'"
            ref="graphRef"
            :relations="result.relations || []"
            :schema="schema"
            @focus-entity="onGraphFocus"
          />
          <StatsOverview
            v-else
            :result="result"
            :stats="stats"
            :schema="schema"
            @locate="onLocate"
          />
        </div>

        <div v-else class="hero">
          <svg class="hero-art" viewBox="0 0 240 112" fill="none" aria-hidden="true">
            <path d="M52 56 L96 40 M100 46 L156 62" stroke="#ddd5c2" stroke-width="1.6" stroke-linecap="round" />
            <path d="M52 56 L156 62" stroke="#f6f3ea" stroke-width="1.6" stroke-linecap="round" stroke-dasharray="4 5" />
            <circle cx="44" cy="58" r="14" fill="#fffdf6" stroke="#c4bba6" stroke-width="1.5" />
            <circle cx="44" cy="58" r="4.5" fill="#201e19" />
            <circle cx="106" cy="38" r="17" fill="#fffdf6" stroke="#c4bba6" stroke-width="1.5" />
            <circle cx="106" cy="38" r="5.5" fill="#a8322a" />
            <circle cx="164" cy="66" r="12" fill="#fffdf6" stroke="#c4bba6" stroke-width="1.5" />
            <circle cx="164" cy="66" r="4" fill="#201e19" />
            <rect x="88" y="58" width="44" height="21" rx="6" fill="#ebe5d6" stroke="#ddd5c2" />
            <text x="110" y="72.5" text-anchor="middle" font-size="11" fill="#615d52">收购</text>
          </svg>

          <h2>粘贴一段新闻，自动抽出实体与关系</h2>
          <p class="hero-sub">
            左侧输入文本或上传 .txt 文件，系统将识别<b>人物 / 组织机构 / 地理位置 / 时间 / 金额 / 产品技术</b>
            六类实体，并输出如「腾讯控股 — 收购 — 搜狗公司」的关系三元组与节点关系图。
          </p>

          <div class="hero-steps">
            <div class="step">
              <div>
                <b>输入文本</b>
                <p>粘贴新闻段落，或上传 .txt（支持 UTF-8 / GBK）</p>
              </div>
            </div>
            <div class="step">
              <div>
                <b>自动抽取</b>
                <p>分句 → 实体识别 → 触发词与句式模板匹配</p>
              </div>
            </div>
            <div class="step">
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
      <a href="/" class="footer-home">← 返回首页</a>
    </footer>

    <HistoryDrawer v-model="historyOpen" @load="onLoadRecord" />
    <BatchDialog v-model="batchOpen" @load="onBatchLoad" @finished="refreshStats" />
    <KnowledgeDialog
      v-model="knowledgeOpen"
      :active-record-id="activeRecordId"
      :schema="schema"
      @load="onKnowledgeLoad"
      @focus="onKnowledgeFocus"
    />
    <EvalDialog v-model="evalOpen" />
    <AnnotationDialog
      v-model="annotationOpen"
      :record-id="activeRecordId"
      :relation-types="schema.relation_types || []"
      @saved="refreshStats"
    />
    <RulesLabDialog v-model="rulesOpen" :schema="schema" @changed="refreshStats" />
    <EntityFixDialog
      v-model="entityFixOpen"
      :entities="result?.entities || []"
      :record-id="activeRecordId"
      :schema="schema"
      @saved="onLoadRecord"
    />
    <ReviewDialog
      v-model="reviewOpen"
      :record-id="activeRecordId"
      :title="title"
      @changed="refreshReview"
    />
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ArrowRight,
  Clock,
  Download,
  EditPen,
  Files,
  InfoFilled,
  Link,
  WarningFilled,
} from '@element-plus/icons-vue'
import * as api from './api/client'
import {
  download,
  buildCsv,
  buildJson,
  buildMarkdown,
  buildGraphml,
  buildCypher,
  safeFilename,
} from './utils/export'
import LandingPage from './components/LandingPage.vue'

// 首页是默认入口，保持同步渲染，避免首屏闪烁。工作台组件拆成异步 chunk：
// 访问 / 不下载表格、统计与 ECharts；打开 /app 或切到对应页签时才加载，
// 已解析过的组件定义由 Vue 缓存，不会重复请求。
const TextWorkbench = defineAsyncComponent(() => import('./components/TextWorkbench.vue'))
const EntityAnnotator = defineAsyncComponent(() => import('./components/EntityAnnotator.vue'))
const TripleTable = defineAsyncComponent(() => import('./components/TripleTable.vue'))
const RelationGraph = defineAsyncComponent(() => import('./components/RelationGraph.vue'))
const StatsOverview = defineAsyncComponent(() => import('./components/StatsOverview.vue'))
const HistoryDrawer = defineAsyncComponent(() => import('./components/HistoryDrawer.vue'))
const BatchDialog = defineAsyncComponent(() => import('./components/BatchDialog.vue'))
const KnowledgeDialog = defineAsyncComponent(() => import('./components/KnowledgeDialog.vue'))
const AnnotationDialog = defineAsyncComponent(() => import('./components/AnnotationDialog.vue'))
const EvalDialog = defineAsyncComponent(() => import('./components/EvalDialog.vue'))
const RulesLabDialog = defineAsyncComponent(() => import('./components/RulesLabDialog.vue'))
const EntityFixDialog = defineAsyncComponent(() => import('./components/EntityFixDialog.vue'))
const ReviewDialog = defineAsyncComponent(() => import('./components/ReviewDialog.vue'))
// /demo 是零后端静态沙箱：只在访问该路由时才下载组件与 4 篇真实样例数据，
// 首页与工作台都不为它付体积成本。
const DemoSandbox = defineAsyncComponent(() => import('./components/DemoSandbox.vue'))
// 案卷页同样是独立整页：材料多、推断链长，塞进工作台的弹窗会把两者都挤变形。
const DossierPage = defineAsyncComponent(() => import('./components/DossierPage.vue'))
// 信息甄别是面向日常场景的独立整页，只在访问 /verify 时才下载。
const VerifyPage = defineAsyncComponent(() => import('./components/VerifyPage.vue'))

/**
 * 站点有五个入口：/ 落地页、/demo 静态试用、/app 工作台、/cases 尽调案卷，其余是品牌 404。
 * 后端 SPA catch-all 会把任意路径回落到 index.html，所以直接用 pathname 判断即可。
 * 兼容旧链接：/#entities 这类锚点仍然直达工作台对应页签。
 */
function resolvePage() {
  const p = location.pathname.replace(/\/+$/, '') || '/'
  if (p === '/' || p === '/index.html') {
    return /^#(entities|triples|graph|stats)$/.test(location.hash) ? 'app' : 'landing'
  }
  if (p === '/demo' || p.startsWith('/demo/')) return 'demo'
  if (p === '/cases' || p.startsWith('/cases/')) return 'cases'
  if (p === '/verify' || p.startsWith('/verify/')) return 'verify'
  if (p === '/app' || p.startsWith('/app/')) return 'app'
  return 'missing'
}
const page = ref(resolvePage())

/* SPA 共用一个 index.html，标题与 robots 必须跟着路由走：工作台和 404
   不该被搜索引擎当内容页收录，静态试用页则应当可以索引。 */
const PAGE_META = {
  landing: {
    title: '中文关系抽取系统 · 把每一条关系追溯到原文',
    description: '基于词典与规则模板的中文实体识别与关系抽取系统。6 类实体、19 类关系，每条三元组都附带证据句、触发词与置信度。本地离线运行，效果可用金标准集复现。',
    robots: 'index, follow',
  },
  demo: {
    title: '静态试用 · 中文关系抽取系统',
    description: '不联网、不连后端，用四篇由本机抽取引擎真实运行导出的样例，预演实体、三元组、命中路径与导出结果。',
    robots: 'index, follow',
  },
  cases: {
    title: '尽调案卷 · 中文关系抽取系统',
    description: '把一个标的的多份材料收进一个案卷，按直接结论、推断关联与待补强疑点三层摆开，每条都能回到原句。',
    robots: 'noindex, nofollow',
  },
  verify: {
    title: '信息甄别 · 中文关系抽取系统',
    description: '把一段网传消息拆成可核查的断言，按有据可查、存疑待核、无从核实分层，标出可疑措辞并给出证据线索。',
    robots: 'index, follow',
  },
  app: {
    title: '工作台 · 中文关系抽取系统',
    description: '输入中文文本，识别实体并抽取关系三元组，逐条查看证据句与命中路径。',
    robots: 'noindex, nofollow',
  },
  missing: {
    title: '页面不存在 · 中文关系抽取系统',
    description: '该地址没有对应的页面。',
    robots: 'noindex, nofollow',
  },
}

function applyPageMeta() {
  const meta = PAGE_META[page.value] || PAGE_META.missing
  document.title = meta.title
  for (const [attr, value] of [['description', meta.description], ['robots', meta.robots]]) {
    const el = document.querySelector(`meta[name="${attr}"]`)
    if (el) el.setAttribute('content', value)
  }
}

function onPopstate() {
  page.value = resolvePage()
  applyPageMeta()
}

const SPLIT_KEY = 're.splitPref'

const text = ref('')
const title = ref('')
const profile = ref('general')
const language = ref('zh')
const result = ref(null)
const loading = ref(false)
const tab = ref('entities')
const schema = ref({ entity_types: [], relation_types: [] })
const samples = ref([])
const stats = ref({})
const historyOpen = ref(false)
const activeRecordId = ref(null)
const graphRef = ref(null)
const batchOpen = ref(false)
const knowledgeOpen = ref(false)
const evalOpen = ref(false)
const annotationOpen = ref(false)
const rulesOpen = ref(false)
const entityFixOpen = ref(false)
const reviewOpen = ref(false)
const reviewState = ref(null)
const projectInput = ref(null)

/* 复核进度挂在顶栏；定稿后由后端判定不可编辑，前端只负责禁用入口，
   真正的写入拦截在 PUT /records/{id}/relations 与 /entities 上。 */
const reviewBadge = computed(() => {
  const s = reviewState.value?.summary
  return s?.total ? `${s.reviewed}/${s.total}` : ''
})
const reviewLocked = computed(() => reviewState.value?.editable === false)
const reviewMap = computed(() => {
  const map = {}
  for (const r of reviewState.value?.relations || []) {
    if (!r.decision || r.decision === 'pending') continue
    const key = [
      r.head_canonical || r.head,
      r.relation,
      r.tail_canonical || r.tail,
      r.sentence_index ?? 0,
    ].join('|')
    map[key] = r.decision
  }
  return map
})

/* ---------- 人工校正闭环 ----------
   表格编辑的是 editableRelations；savedRelations 是最近一次保存后的基线，
   两者对比得出 dirty。undo / redo 存整份快照（单篇最多几十条，保留 50 步）。 */
const editableRelations = ref([])
const savedRelations = ref([])
const undoStack = ref([])
const redoStack = ref([])
const saving = ref(false)

const relationSignature = (list) =>
  JSON.stringify(
    (list || []).map((r) => [
      r.id || '', r.head, r.head_type, r.relation, r.tail, r.tail_type,
      r.evidence || '', r.trigger || '', r.confidence, r.sentence_index ?? 0,
      r.rule_base || '',
    ]),
  )

const dirty = computed(
  () => relationSignature(editableRelations.value) !== relationSignature(savedRelations.value),
)

function syncResultRelations(next) {
  if (!result.value) return
  result.value = {
    ...result.value,
    relations: next,
    stats: { ...result.value.stats, relation_count: next.length },
  }
}

function onRelationsChange(next) {
  undoStack.value.push(editableRelations.value.map((r) => ({ ...r })))
  if (undoStack.value.length > 50) undoStack.value.shift()
  redoStack.value = []
  editableRelations.value = next
  syncResultRelations(next)
}

function undo() {
  if (!undoStack.value.length) return
  redoStack.value.push(editableRelations.value.map((r) => ({ ...r })))
  const previous = undoStack.value.pop()
  editableRelations.value = previous
  syncResultRelations(previous)
  liveMessage.value = '已撤销上一步校正'
}

function redo() {
  if (!redoStack.value.length) return
  undoStack.value.push(editableRelations.value.map((r) => ({ ...r })))
  const next = redoStack.value.pop()
  editableRelations.value = next
  syncResultRelations(next)
  liveMessage.value = '已重做校正'
}

/** 与基线比较，给保存后的提示一个可核对的数字。 */
function relationDiff(before, after) {
  const key = (r) => `${r.head}|${r.head_type}|${r.relation}|${r.tail}|${r.tail_type}`
  const b = new Set(before.map(key))
  const a = new Set(after.map(key))
  return {
    added: after.filter((r) => !b.has(key(r))).length,
    removed: before.filter((r) => !a.has(key(r))).length,
  }
}

async function persistCorrections(forceNew = false) {
  if (!result.value || saving.value) return
  saving.value = true
  try {
    const relations = editableRelations.value.map((r) => ({ ...r }))
    const diff = relationDiff(savedRelations.value, relations)
    let recordId = forceNew ? null : activeRecordId.value
    const payload = {
      ...result.value,
      relations,
      stats: { ...result.value.stats, relation_count: relations.length },
    }
    if (recordId) {
      await api.saveRelations(recordId, relations)
    } else {
      const res = await api.saveSnapshot(
        payload,
        forceNew && title.value ? `${title.value}（校正副本）` : title.value,
      )
      recordId = res.record_id
      activeRecordId.value = recordId
    }
    savedRelations.value = relations.map((r) => ({ ...r }))
    await refreshStats()
    syncShareUrl()
    const summary = `已保存：新增 ${diff.added} 条 · 删除 ${diff.removed} 条`
    ElMessage.success(forceNew ? `已另存为记录 #${recordId}，${summary}` : `${summary} · 记录 #${recordId}`)
    liveMessage.value = summary
  } catch (err) {
    ElMessage.error(`保存失败：${err.message}`)
  } finally {
    saving.value = false
  }
}

function saveCorrections() {
  return persistCorrections(false)
}

function saveAsSnapshot() {
  return persistCorrections(true)
}

/* ---------- 可分享的结果深链 ----------
   ?record=<id> 指向历史记录，?q=<实体> 带三元组筛选，页签仍用 #hash。
   replaceState 一律构造完整 pathname + search + hash，避免切页签时把 query 抹掉。 */
function syncShareUrl() {
  if (page.value !== 'app') return
  const url = new URL(location.href)
  if (activeRecordId.value != null) url.searchParams.set('record', String(activeRecordId.value))
  else url.searchParams.delete('record')
  if (entityFilter.value?.name) url.searchParams.set('q', entityFilter.value.name)
  else url.searchParams.delete('q')
  history.replaceState(null, '', url.pathname + url.search + url.hash)
}

async function copyShareLink() {
  syncShareUrl()
  const link = location.href
  try {
    await navigator.clipboard.writeText(link)
    ElMessage.success('链接已复制，打开即可复现当前结果')
  } catch {
    // 非安全上下文 / 权限受限时退回可手动复制的文本
    const input = document.createElement('input')
    input.value = link
    input.style.position = 'fixed'
    input.style.opacity = '0'
    document.body.appendChild(input)
    input.select()
    const ok = document.execCommand?.('copy')
    input.remove()
    ElMessage[ok ? 'success' : 'info'](
      ok ? '链接已复制，打开即可复现当前结果' : `请手动复制地址栏链接：${link}`,
    )
  }
}

/* ---------- 动效编排 ----------
   抽取完成是一次性、有因果的事件：结果容器入场与朱红扫光同时启动，
   容器内部（表格行 / 句子行 / 下拉项）一律不 stagger，切页签也不重播入场。
   resultVersion 只在拿到新结果时递增；重跑时 key 变化让扫光元素重建即重播，
   不叠加、不残留 timer，能扛住连续点击「开始抽取」。 */
const resultVersion = ref(0)
const segmentedRef = ref(null)
const indicatorStyle = ref({ transform: 'translateX(0px) scaleX(0)' })
const indicatorReady = ref(false)

function updateIndicator() {
  const el = segmentedRef.value?.querySelector('.seg-item.is-active')
  if (!el) {
    indicatorReady.value = false
    return
  }
  const x = el.offsetLeft + 8
  const w = Math.max(24, el.offsetWidth - 16)
  // 基准宽 100px，宽度差用 scaleX 表达：整条指示条只动 transform，不触发重排
  indicatorStyle.value = { transform: `translateX(${x}px) scaleX(${w / 100})` }
  indicatorReady.value = true
}

/* 【创新点 2】结果就绪后左栏收窄，把宽度让给正文 */
const compact = ref(false)
const splitPref = ref(localStorage.getItem(SPLIT_KEY) || '')

/* 窄屏（≤1120px）走单列，收窄没有意义且会留下空白行，直接禁用 */
const isNarrow = ref(false)
const compactActive = computed(() => compact.value && !isNarrow.value)

/* 【创新点 1】跨视图穿透：一次点击即定位到证据句 / 下钻到实体 */
const link = ref(null)
const entityFilter = ref(null)
const liveMessage = ref('')
const loadError = ref('')

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
  const url = new URL(location.href)
  // 只改 hash 的写法会把 ?record= / ?q= 一起抹掉，必须拼回完整 URL
  if (url.hash.replace(/^#/, '') !== value) url.hash = value
  history.replaceState(null, '', url.pathname + url.search + url.hash)
})

watch(entityFilter, () => syncShareUrl())

/* ---------- 视图切换（WAI-ARIA tabs：方向键 + Home/End） ---------- */
function selectTab(name) {
  tab.value = name
  if (name !== 'triples') entityFilter.value = null
}

function onTabKeydown(event) {
  const keys = ['ArrowRight', 'ArrowLeft', 'Home', 'End']
  if (!keys.includes(event.key)) return
  event.preventDefault()
  const names = TABS.value.map((t) => t.name)
  const at = names.indexOf(tab.value)
  let next = at
  if (event.key === 'ArrowRight') next = (at + 1) % names.length
  if (event.key === 'ArrowLeft') next = (at - 1 + names.length) % names.length
  if (event.key === 'Home') next = 0
  if (event.key === 'End') next = names.length - 1
  selectTab(names[next])
  nextTick(() => document.getElementById('tab-' + names[next])?.focus())
}

/* ---------- 左栏配比 ---------- */
function toggleCompact(next) {
  compact.value = typeof next === 'boolean' ? next : !compact.value
  splitPref.value = compact.value ? 'compact' : 'full'
  try {
    localStorage.setItem(SPLIT_KEY, splitPref.value)
  } catch {
    /* 隐私模式写入失败不影响主流程 */
  }
}

/* ---------- 联动 ---------- */
/** 定位到某个句子的证据：切到实体标注并高亮该句 */
function onLocate(sentenceIndex) {
  if (sentenceIndex === null || sentenceIndex === undefined) return
  tab.value = 'entities'
  link.value = { kind: 'sentence', value: sentenceIndex, ts: Date.now() }
  liveMessage.value = `已定位到第 ${sentenceIndex + 1} 句`
}

/** 图谱点节点：下钻为「含该实体的三元组」 */
function onGraphFocus(payload) {
  if (!payload) return
  entityFilter.value = payload
  tab.value = 'triples'
  liveMessage.value = `已筛选含「${payload.name}」的三元组`
}

async function refreshStats() {
  try {
    stats.value = await api.getStats()
  } catch {
    /* 统计失败不打断主流程 */
  }
}

/* ---------- 在途抽取的竞态控制 ----------
   连续重抽、上传与清空都可能让旧请求晚于新请求返回。每条请求领一个序号，
   只有序号仍是最新的一条才允许写结果；新请求发起时直接 abort 上一条。 */
let extractSeq = 0
let extractController = null

function cancelPendingExtract() {
  extractSeq += 1
  if (extractController) {
    extractController.abort()
    extractController = null
  }
}

function applyResult(payload, recordId = null) {
  resultVersion.value += 1
  result.value = payload
  activeRecordId.value = recordId
  entityFilter.value = null
  link.value = null
  // 每次换结果都重置校正栈：编辑历史不能跨文档沿用
  editableRelations.value = (payload.relations || []).map((r) => ({ ...r }))
  savedRelations.value = editableRelations.value.map((r) => ({ ...r }))
  undoStack.value = []
  redoStack.value = []
  refreshStats()
  syncShareUrl()
  nextTick(updateIndicator)
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
  cancelPendingExtract()
  const seq = extractSeq
  const controller = new AbortController()
  extractController = controller
  loading.value = true
  loadError.value = ''
  liveMessage.value = '正在抽取，请稍候'
  try {
    const res = await api.extractText(text.value, title.value, save, {
      signal: controller.signal,
      profile: profile.value,
      language: language.value,
    })
    if (seq !== extractSeq) return
    applyResult(res.result, res.record_id)
    liveMessage.value = `抽取完成：${res.result.stats.entity_count} 个实体，${res.result.stats.relation_count} 条关系`
    if (save) {
      ElMessage.success(
        `已存入历史 #${res.record_id}：${res.result.stats.entity_count} 个实体，${res.result.stats.relation_count} 条关系`,
      )
    }
  } catch (err) {
    // 主动取消或被更新的请求取代，都不该弹错误、也不该覆盖已有结果
    if (controller.signal.aborted || seq !== extractSeq) return
    loadError.value = err.message
    liveMessage.value = `抽取失败：${err.message}`
  } finally {
    if (seq === extractSeq) {
      loading.value = false
      extractController = null
    }
  }
}

function saveCurrent() {
  runExtract({ save: true })
}

const EXPORT_MIME = {
  csv: 'text/csv;charset=utf-8',
  json: 'application/json;charset=utf-8',
  md: 'text/markdown;charset=utf-8',
  graphml: 'application/graphml+xml;charset=utf-8',
  cypher: 'text/plain;charset=utf-8',
  html: 'text/html;charset=utf-8',
  project: 'application/json;charset=utf-8',
}

const EXPORT_BUILDERS = {
  csv: buildCsv,
  json: buildJson,
  md: buildMarkdown,
  graphml: buildGraphml,
  cypher: buildCypher,
}

/** 导出当前结果：CSV / JSON / Markdown / GraphML / Cypher 由工具模块生成，
 *  PNG 取自图表实例，HTML 报告与项目包由后端组装（保证与库内真值一致）。 */
async function onExport(kind) {
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
    if (kind === 'html') {
      const payload = activeRecordId.value
        ? { record_id: activeRecordId.value, title: meta.title }
        : { result: data, title: meta.title }
      const file = await api.buildReport(payload)
      download(file.filename, file.html, EXPORT_MIME.html)
      ElMessage.success(`已导出 ${file.filename}`)
      return
    }
    if (kind === 'project') {
      const pkg = await api.exportProject()
      const name = `项目包-${new Date().toISOString().slice(0, 10)}.json`
      download(name, JSON.stringify(pkg, null, 2), EXPORT_MIME.project)
      ElMessage.success(`已导出 ${name}`)
      return
    }

    const file = EXPORT_BUILDERS[kind](data, meta)
    download(file.filename, file.content, EXPORT_MIME[kind])
    ElMessage.success(`已导出 ${file.filename}`)
  } catch (err) {
    ElMessage.error(`导出失败：${err.message}`)
  }
}

/* ---------- 新增功能的入口 ---------- */
async function refreshReview() {
  if (!activeRecordId.value) {
    reviewState.value = null
    return
  }
  try {
    reviewState.value = await api.getReviewState(activeRecordId.value)
  } catch {
    reviewState.value = null
  }
}
watch(activeRecordId, refreshReview, { immediate: true })

async function onMoreCommand(command) {
  if (command === 'cases') {
    // 案卷是独立整页：整页跳转让它的路由、样式与返回路径都自洽，
    // 也避免把只读报告链接与案卷状态混在同一个弹窗里。
    location.href = '/cases'
    return
  }
  if (command === 'verify') {
    location.href = '/verify'
    return
  }
  if (command === 'annotate') annotationOpen.value = true
  if (command === 'eval') evalOpen.value = true
  if (command === 'rules') rulesOpen.value = true
  if (command === 'import') projectInput.value?.click()
  if (command === 'share') await copyReadonlyLink()
}

async function copyReadonlyLink() {
  if (!activeRecordId.value) {
    ElMessage.warning('请先存入历史，再复制只读报告链接')
    return
  }
  try {
    // 签名在服务端算，前端拿不到密钥；生产配置 APP_REPORT_SECRET 后裸 id 会被拒
    const res = await api.createShareLink(activeRecordId.value)
    try {
      await navigator.clipboard.writeText(res.url)
      ElMessage.success('带签名的只读报告链接已复制')
    } catch {
      ElMessage.info(`请手动复制：${res.url}`)
    }
  } catch (err) {
    ElMessage.error(`生成链接失败：${err.message}`)
  }
}

async function onProjectFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  try {
    const payload = JSON.parse(await file.text())
    const res = await api.importProject(payload, 'merge')
    ElMessage.success(`已导入 ${res.records} 篇记录、${res.relations} 条关系`)
    await refreshStats()
  } catch (err) {
    ElMessage.error(`导入失败：${err.message}`)
  } finally {
    event.target.value = ''
  }
}

async function onKnowledgeLoad(id) {
  try {
    onLoadRecord(await api.getRecord(id))
    ElMessage.success(`已载入 #${id}`)
  } catch (err) {
    ElMessage.error(`载入失败：${err.message}`)
  }
}

function onKnowledgeFocus(name) {
  entityFilter.value = { name }
  tab.value = 'triples'
  liveMessage.value = `已筛选含「${name}」的三元组`
}

async function onFile(file) {
  cancelPendingExtract()
  const seq = extractSeq
  const controller = new AbortController()
  extractController = controller
  loading.value = true
  loadError.value = ''
  try {
    const res = await api.extractFile(file, true, {
      signal: controller.signal,
      profile: profile.value,
      language: language.value,
    })
    if (seq !== extractSeq) return
    text.value = res.result.text
    title.value = file.name.replace(/\.[^.]+$/, '')
    applyResult(res.result, res.record_id)
    ElMessage.success(`${file.name} 解析完成：${res.result.stats.relation_count} 条关系`)
  } catch (err) {
    if (controller.signal.aborted || seq !== extractSeq) return
    loadError.value = err.message
    ElMessage.error(err.message)
  } finally {
    if (seq === extractSeq) {
      loading.value = false
      extractController = null
    }
  }
}

function onClear() {
  cancelPendingExtract()
  loading.value = false
  result.value = null
  activeRecordId.value = null
  entityFilter.value = null
  link.value = null
  loadError.value = ''
  editableRelations.value = []
  savedRelations.value = []
  undoStack.value = []
  redoStack.value = []
  syncShareUrl()
}

async function onBatchLoad(recordId) {
  if (!recordId) return
  try {
    const record = await api.getRecord(recordId)
    onLoadRecord(record)
    tab.value = 'triples'
    ElMessage.success(`已载入批量结果 #${recordId}`)
  } catch (err) {
    ElMessage.error(`载入失败：${err.message}`)
  }
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

/* 结果出现 → 若用户未明确要求「始终展开」，收窄左栏 */
watch(result, (value) => {
  if (!value) {
    compact.value = false
    return
  }
  if (splitPref.value !== 'full') compact.value = true
})

/* 页签切换、结果刷新、数量角标变化后，指示条按真实 DOM 位置对齐 */
watch([tab, result], () => nextTick(updateIndicator))

function onGlobalKeydown(event) {
  const mod = event.metaKey || event.ctrlKey
  if (!mod || event.key.toLowerCase() !== 'e') return
  if (!result.value) return
  event.preventDefault()
  toggleCompact()
}

let narrowMq = null
function onNarrowChange(event) {
  isNarrow.value = event.matches
}

onMounted(async () => {
  applyPageMeta()
  window.addEventListener('popstate', onPopstate)
  // 首页、静态试用与 404 不触碰业务接口：后端没启动时也不该在这些页面弹错误
  if (page.value !== 'app') return
  const hashTab = tabFromHash()
  if (hashTab) tab.value = hashTab
  window.addEventListener('keydown', onGlobalKeydown)
  window.addEventListener('resize', updateIndicator)

  narrowMq = window.matchMedia('(max-width: 1120px)')
  isNarrow.value = narrowMq.matches
  narrowMq.addEventListener('change', onNarrowChange)
  try {
    const [sampleList, schemaData, statData] = await Promise.all([
      api.getSamples(),
      api.getSchema(),
      api.getStats(),
    ])
    samples.value = sampleList
    schema.value = schemaData
    stats.value = statData

    // 分享链接优先：?record=12 直接复现那条历史，而不是覆盖成默认示例
    const params = new URLSearchParams(location.search)
    const sharedId = Number(params.get('record'))
    if (Number.isInteger(sharedId) && sharedId > 0) {
      try {
        onLoadRecord(await api.getRecord(sharedId))
      } catch {
        ElMessage.warning(`分享的记录 #${sharedId} 不存在，已载入示例`)
        await loadDefaultSample(sampleList)
      }
    } else {
      await loadDefaultSample(sampleList)
    }

    const filterName = params.get('q')
    if (filterName) {
      entityFilter.value = { name: filterName }
      if (!hashTab) tab.value = 'triples'
    }
    syncShareUrl()
  } catch (err) {
    loadError.value = `后端未连通：${err.message}`
    ElMessage.error(`后端未连通：${err.message}`)
  }
})

async function loadDefaultSample(sampleList) {
  if (!sampleList.length) return
  text.value = sampleList[0].content
  title.value = sampleList[0].title
  // 预览模式：只展示抽取效果，不写历史记录
  await runExtract({ save: false })
}

onBeforeUnmount(() => {
  window.removeEventListener('popstate', onPopstate)
  window.removeEventListener('keydown', onGlobalKeydown)
  window.removeEventListener('resize', updateIndicator)
  narrowMq?.removeEventListener('change', onNarrowChange)
})
</script>

<style scoped>
/* ---------- 站点级：品牌回首页、页脚返回、404 ---------- */
.appbar-brand {
  color: inherit;
  text-decoration: none;
  border-radius: var(--r);
}
.appbar-brand:hover .appbar-name { color: var(--accent); }

.footer {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 16px;
}
.footer-home { color: var(--muted); text-decoration: none; }
.footer-home:hover { color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }

.missing {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 16px;
  max-width: 720px;
  margin: 0 auto;
  padding: 48px 24px;
  background: var(--brand-paper);
  color: var(--brand-ink);
}
.missing-code { font-size: 96px; line-height: 1; font-weight: 700; letter-spacing: -0.05em; color: var(--brand-red); margin: 0; }
.missing-title { font-size: 32px; line-height: 1.25; font-weight: 500; margin: 0; letter-spacing: 0; }
.missing-note { font-size: 16px; line-height: 24px; color: var(--brand-ink-2); margin: 0; }
.missing-links { display: flex; gap: 24px; margin-top: 24px; }
.missing-links a { font-size: 14px; font-weight: 600; color: var(--brand-red); text-underline-offset: 4px; }
.missing-links a:hover { text-decoration: underline; }

.head-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
}

.result-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px 16px 16px;
  overflow: hidden;
}

/* ---------- 加载 / 错误 / 预览条 ---------- */
.error-strip {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  font-size: 12px;
  color: var(--danger);
  background: var(--brand-red-soft);
}

.error-strip span {
  flex: 1;
  min-width: 0;
}

.error-retry {
  height: 24px;
  padding: 0 12px;
  font-size: 12px;
}

.strip-btn {
  height: 24px;
  padding: 0 12px;
  font-size: 12px;
  background: #fff;
}

/* ---------- 收窄后的摘要条【创新点 2】 ---------- */
.compact-panel {
  align-self: start;
  gap: 0;
  padding: 12px 16px 16px;
  overflow: auto;
}

.cp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.cp-label {
  font-size: 12px;
  letter-spacing: 0.8px;
  text-transform: uppercase;
  color: var(--muted);
}

.cp-toggle {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  padding: 0;
  color: var(--muted);
  background: transparent;
  border: none;
  border-radius: var(--r-xs);
  cursor: pointer;
  transition: background var(--dur-color) var(--ease), color var(--dur-color) var(--ease);
}

.cp-toggle:hover {
  background: var(--surface-3);
  color: var(--ink);
}

.cp-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--ink);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.cp-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  margin: 12px 0 12px;
  background: var(--line);
  border-radius: var(--r-sm);
  overflow: hidden;
}

.cp-meta > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  background: var(--surface-2);
}

.cp-meta dt {
  font-size: 12px;
  color: var(--muted);
}

.cp-meta dd {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.cp-edit {
  width: 100%;
  justify-content: center;
  margin-bottom: 8px;
}

.cp-saved {
  margin: 4px 0 0;
  font-size: 12px;
  text-align: center;
  color: var(--muted);
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
  padding: 32px 32px 40px;
}

.hero-art {
  width: 240px;
  height: 112px;
  margin-bottom: 20px;
}

.hero h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--ink);
  letter-spacing: 0.2px;
}

.hero-sub {
  margin: 8px 0 0;
  max-width: 540px;
  font-size: 16px;
  line-height: 1.5;
  color: var(--muted);
}

.hero-sub b {
  color: var(--ink-2);
  font-weight: 500;
}

.hero-steps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-top: 26px;
  width: 100%;
  max-width: 660px;
}

.step {
  display: flex;
  gap: 12px;
  text-align: left;
  padding: 12px 16px;
  border-radius: var(--r);
  background: var(--tone-1);
}

.step b {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}

.step p {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.5;
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
    padding: 24px 16px 32px;
  }
}

@media (max-width: 720px) {
  /* 四个页签加导出按钮在 390px 下有 500+px，独占一行并允许横向滚动，
     不让结果栏把整页撑宽。指示条仍按 offsetLeft 在滚动容器内定位。 */
  .head-right {
    flex-wrap: wrap;
    width: 100%;
  }
  .segmented {
    max-width: 100%;
    overflow-x: auto;
    overflow-y: hidden;
  }
  .seg-item {
    min-height: 44px;
  }
}
</style>
