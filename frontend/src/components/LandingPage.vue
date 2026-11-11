<template>
  <!--
    首页是可交付产品入口：只留界面本身能表达的内容，不写说明、评测与作业式陈述。
    视觉方向仍是 borrowed-category（seed 687035355）的中文报纸校样：纸色、红笔、边注栏。
    两个创新模块：① 接口契约面板（点句子看输出字段，可调用 /api/extract 复现）
    ② 纸墨朱主视觉价值段（Figma AI 生成，接替原「运行」命令屏的深色锚点）。
    其余全部是标准控件 + 动效增强。
  -->
  <div class="lp">
    <a class="lp-skip" href="#lp-main">跳到主要内容</a>

    <!-- ===================== 导航：纯色一行，无玻璃、无浮岛 ===================== -->
    <header class="lp-nav-wrap" :class="{ 'is-scrolled': scrolled }">
      <nav class="lp-nav" aria-label="页面导航">
        <a class="lp-wordmark" href="/" aria-label="中文关系抽取系统，返回首页">
          <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
            <rect x="3" y="5" width="22" height="24" rx="1.5" fill="#f6f3ea" />
            <path d="M7 12h14M7 17h10M7 22h14" stroke="#1e1c18" stroke-width="1.4" stroke-linecap="round" opacity=".55" />
            <path d="M9 24.5 24 24.5" stroke="#a8322a" stroke-width="2" stroke-linecap="round" />
            <circle cx="24" cy="24.5" r="3.2" fill="#a8322a" />
          </svg>
          <span>中文关系抽取系统</span>
        </a>

        <div class="lp-nav-links" :class="{ 'is-open': menuOpen }" :id="menuId">
          <a
            v-for="(item, i) in navItems"
            :key="item.href"
            :href="item.href"
            :aria-current="activeSection === item.href ? 'location' : undefined"
            :style="{ '--stagger': `${i * 60}ms` }"
            @click="closeMenu"
          >{{ item.label }}</a
          >
          <a class="lp-nav-mobile-cta" href="/app">进入工作台</a>
        </div>

        <a class="lp-nav-cta" href="/app">进入工作台 <span aria-hidden="true">→</span></a>

        <button
          class="lp-menu-toggle"
          type="button"
          :aria-expanded="menuOpen"
          :aria-controls="menuId"
          :aria-label="menuOpen ? '关闭导航菜单' : '打开导航菜单'"
          @click="menuOpen = !menuOpen"
        >
          <span></span><span></span>
        </button>
      </nav>
      <span class="lp-progress" :style="{ '--p': progress }" aria-hidden="true"></span>
    </header>

    <main id="lp-main">
      <!-- ===================== 首屏：通栏头条 + 接口契约面板 ===================== -->
      <section class="lp-hero" aria-labelledby="lp-headline">
        <div class="lp-frame">
          <h1 id="lp-headline" class="lp-headline">
            <!-- 390px 下换一句同样具体的短文案，而不是把字号压到看不出层级 -->
            <span class="lp-headline-wide">
              <span class="lp-mask"><span class="lp-mask-in">从一段中文新闻，</span></span>
              <span class="lp-mask"><span class="lp-mask-in lp-mask-in-2">抽出带出处的三元组。</span></span>
            </span>
            <span class="lp-headline-narrow">
              <span class="lp-mask"><span class="lp-mask-in">抽出三元组，</span></span>
              <span class="lp-mask"><span class="lp-mask-in lp-mask-in-2">附上原文出处。</span></span>
            </span>
            <span class="lp-headline-rule" aria-hidden="true"></span>
          </h1>

          <div class="lp-hero-row">
            <p class="lp-sub reveal" :style="{ '--d': '80ms' }">
              词典与规则模板驱动的中文实体识别与关系抽取，本机处理，每条结果都能回到原文。
            </p>
            <a class="lp-cta reveal" :style="{ '--d': '160ms' }" href="/app">
              进入工作台
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M4 12h15M13 6l6 6-6 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </a>
          </div>
        </div>

        <!-- 【创新点 1】接口契约面板：真实抽取结果 + 字段名/值，可调用真实接口复现 -->
        <div class="lp-sheet-wrap" id="proof-sheet">
          <div class="lp-frame">
            <div class="lp-sheet reveal" :class="{ 'is-done': runState === 'done' }" :style="{ '--d': '120ms' }" data-ui>
              <span v-if="runState === 'done'" :key="pulseKey" class="lp-sheet-pulse" aria-hidden="true"></span>
              <div class="lp-sheet-head">
                <div>
                  <h2 class="lp-sheet-title">{{ demo.title }}</h2>
                </div>
                <div class="lp-sheet-actions">
                  <span class="lp-cap lp-sheet-count">
                    {{ demo.stats.char_count }} 字 · {{ demo.stats.sentence_count }} 句 ·
                    {{ demo.stats.entity_count }} 实体 · {{ demo.stats.relation_count }} 关系
                  </span>
                  <button
                    class="lp-run"
                    type="button"
                    :disabled="runState === 'running'"
                    :aria-label="runState === 'running' ? '正在请求接口' : '调用 /api/extract 重新抽取'"
                    @click="runLiveExtract"
                  >
                    {{ runState === 'running' ? '正在请求…' : '调用接口重跑' }}
                  </button>
                </div>
              </div>

              <div class="lp-sheet-body">
                <!-- 原文：逐句，实体用红笔标记 -->
                <div class="lp-original" :class="{ 'is-replaying': replaying }">
                  <span class="lp-sent-marker" :style="{ transform: `translateY(${sentMarkerY}px)` }" aria-hidden="true"></span>
                  <button
                    v-for="(s, si) in sentences"
                    :key="s.index"
                    :ref="(el) => setSentRef(el, s.index)"
                    class="lp-sent"
                    :class="{ 'is-active': activeSentence === s.index }"
                    type="button"
                    :aria-pressed="activeSentence === s.index"
                    :aria-label="`第 ${s.index + 1} 句，抽出 ${relationsFor(s.index).length} 条关系`"
                    :style="{ '--si': `${si * 60}ms` }"
                    @click="activeSentence = s.index"
                  >
                    <span class="lp-sent-no lp-cap">{{ s.index + 1 }}</span>
                    <span class="lp-sent-text">
                      <template v-for="(frag, fi) in fragmentsFor(s)" :key="fi">
                        <mark v-if="frag.type === 'ent'" class="lp-ent" :title="`${frag.label}：${frag.text}`">{{ frag.text }}</mark>
                        <template v-else>{{ frag.text }}</template>
                      </template>
                    </span>
                    <span v-if="relationsFor(s.index).length" class="lp-sent-count lp-cap">
                      {{ relationsFor(s.index).length }} 条
                    </span>
                  </button>
                </div>

                <!-- 结果字段：这一句抽出了什么，字段名与 API 返回一致 -->
                <aside class="lp-margin" aria-live="polite">
                  <p class="lp-cap lp-margin-label">第 {{ activeSentence + 1 }} 句 · 输出字段</p>
                  <Transition name="lp-field-swap" mode="out-in">
                    <div :key="activeSentence" class="lp-margin-content">
                      <p v-if="!relationsFor(activeSentence).length" class="lp-margin-empty">
                        这句没有匹配到关系模板。
                      </p>
                      <div v-for="(rel, ri) in relationsFor(activeSentence)" :key="ri" class="lp-note" :style="{ '--ri': `${ri * 50}ms` }">
                        <p class="lp-note-triple">
                          <b>{{ rel.head }}</b>
                          <span class="lp-note-rel">{{ rel.label }}</span>
                          <b>{{ rel.tail }}</b>
                        </p>
                        <dl class="lp-fields lp-cap">
                          <div><dt>relation</dt><dd>{{ rel.key }}</dd></div>
                          <div><dt>confidence</dt><dd>{{ rel.confidence.toFixed(2) }}</dd></div>
                          <div><dt>trigger</dt><dd>「{{ rel.trigger }}」</dd></div>
                          <div><dt>sentence_index</dt><dd>{{ rel.sentence_index }}</dd></div>
                          <div><dt>evidence</dt><dd>{{ rel.evidence }}</dd></div>
                        </dl>
                      </div>
                    </div>
                  </Transition>
                </aside>
              </div>

              <p v-if="runState === 'error'" class="lp-inline-error" role="alert">
                接口未响应（{{ runError }}），当前显示的是内置示例结果。
              </p>
              <p v-else-if="runState === 'done'" class="lp-inline-ok" role="status">
                HTTP {{ runMeta?.status }} · {{ runMeta?.sentences }} 句 · {{ runMeta?.relations }} 关系 · {{ runMeta?.ms }} ms
              </p>
            </div>
          </div>
        </div>
      </section>

      <!-- ===================== 价值段：主视觉接替深色锚点 ===================== -->
      <section id="closing" class="lp-section lp-closesec" aria-label="产品主张">
        <div class="lp-frame">
          <div class="lp-close-copy reveal">
            <h2 class="lp-h2">每一条关系，都能回到原文</h2>
            <p class="lp-body">把一段中文文本交给它，拿回可核对的实体、关系与证据句。点开任意一条，就能看见它从哪句话来。</p>
            <a class="lp-close-link" href="#method">看它怎么工作 <span aria-hidden="true">↓</span></a>
            <p class="lp-cap lp-close-note">本机处理 · 数据不出本机</p>
          </div>
        </div>
      </section>

      <!-- ===================== 能力：常驻详情切换器（点击固定，不再随鼠标消失） ===================== -->
      <section id="capabilities" class="lp-section lp-capabilities" aria-labelledby="lp-cap-title">
        <div class="lp-frame">
          <div class="lp-sec-head reveal">
            <h2 id="lp-cap-title" class="lp-h2">能力</h2>
          </div>

          <div class="lp-cap-layout" data-ui>
            <div class="lp-cap-nav">
              <label class="lp-cap-search">
                <span class="lp-sr">筛选能力</span>
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <circle cx="10.5" cy="10.5" r="6.5" stroke="currentColor" stroke-width="1.6" />
                  <path d="m15.5 15.5 5 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
                </svg>
                <input
                  v-model="query"
                  type="search"
                  placeholder="筛选"
                  autocomplete="off"
                  aria-describedby="lp-cap-hint"
                  @keydown.down.prevent="moveSelection(1)"
                  @keydown.up.prevent="moveSelection(-1)"
                />
              </label>
              <p id="lp-cap-hint" class="lp-sr">上下方向键切换能力，右侧详情会同步更新。</p>

              <div class="lp-cap-list">
                <span class="lp-cap-marker" :style="{ transform: `translateY(${capIndicatorY}px)` }" aria-hidden="true"></span>
                <button
                  v-for="(item, i) in filtered"
                  :key="item.name"
                  :ref="(el) => setCapRef(el, i)"
                  class="lp-cap-item reveal"
                  :class="{ 'is-selected': i === selected }"
                  type="button"
                  :aria-pressed="i === selected"
                  :style="{ '--d': `${i * 40}ms` }"
                  @click="selected = i"
                >
                  <span class="lp-cap-name">{{ item.name }}</span>
                  <span class="lp-cap-fact lp-cap">{{ item.fact }}</span>
                </button>
              </div>
            </div>

            <div class="lp-cap-panel reveal" :style="{ '--d': '120ms' }" aria-live="polite">
              <Transition name="lp-cap-swap" mode="out-in">
                <div v-if="filtered.length" :key="selected" class="lp-cap-detail">
                  <div class="lp-cap-heading">
                    <h3 class="lp-cap-title">{{ filtered[selected].name }}</h3>
                    <span class="lp-cap-fact-inline lp-cap">{{ filtered[selected].fact }}</span>
                  </div>
                  <span class="lp-cap-rule" aria-hidden="true"></span>
                  <p class="lp-cap-text lp-body">{{ filtered[selected].detail }}</p>
                  <a class="lp-cap-link" href="/app">在工作台使用 <span aria-hidden="true">→</span></a>
                </div>
                <div v-else key="cap-empty" class="lp-cap-detail">
                  <h3 class="lp-cap-title">没有匹配项</h3>
                  <p class="lp-cap-text lp-body">清空筛选即可返回完整列表。</p>
                </div>
              </Transition>
            </div>
          </div>
        </div>
      </section>

      <!-- ===================== 结果看板：真实三元组 ===================== -->
      <section class="lp-section lp-board-sec" aria-labelledby="lp-board-title">
        <div class="lp-frame">
          <div class="lp-sec-head reveal">
            <h2 id="lp-board-title" class="lp-h2">真实输出样例</h2>
          </div>

          <div class="lp-board" data-ui>
            <div
              v-for="(rel, i) in demo.relations"
              :key="`${rel.key}-${i}`"
              class="lp-board-row reveal"
              :class="{ 'is-open': openRow === i }"
              :style="{ '--d': `${i * 40}ms` }"
            >
              <button
                class="lp-board-btn"
                type="button"
                :aria-expanded="openRow === i"
                :aria-controls="`lp-board-detail-${i}`"
                @click="openRow = openRow === i ? -1 : i"
              >
                <span class="lp-board-head">{{ rel.head }}</span>
                <span class="lp-board-rel" :style="{ '--rel-color': rel.color }">{{ rel.label }}</span>
                <span class="lp-board-tail">{{ rel.tail }}</span>
                <span class="lp-board-conf lp-cap">{{ rel.confidence.toFixed(2) }}</span>
                <span class="lp-board-sent lp-cap">第 {{ rel.sentence_index + 1 }} 句</span>
              </button>
              <div v-show="openRow === i" :id="`lp-board-detail-${i}`" class="lp-board-detail">
                <p class="lp-cap">证据句</p>
                <p class="lp-body">{{ rel.evidence }}</p>
                <p class="lp-cap">触发词「{{ rel.trigger }}」 · 规则类型 {{ rel.key }}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ===================== 原理：散乱 → 收束 → 有序 ===================== -->
      <section id="method" class="lp-section lp-method" aria-labelledby="lp-method-title">
        <div class="lp-frame">
          <div class="lp-sec-head reveal">
            <h2 id="lp-method-title" class="lp-h2">处理流程</h2>
          </div>

          <div class="lp-diagram reveal" aria-hidden="true">
            <svg viewBox="0 0 1200 260" preserveAspectRatio="xMidYMid meet" role="presentation">
              <rect
                v-for="(d, i) in dots"
                :key="i"
                :x="d.x"
                :y="d.y"
                :width="d.w"
                :height="d.h"
                :fill="d.fill"
                rx="1"
              />
            </svg>
          </div>

          <div class="lp-method-cols">
            <div v-for="(step, i) in methodSteps" :key="step.name" class="lp-method-col reveal" :style="{ '--d': `${i * 80}ms` }">
              <h3 class="lp-h3">{{ step.name }}</h3>
              <p class="lp-body">{{ step.detail }}</p>
            </div>
          </div>
        </div>
      </section>

      <!-- ===================== 界面一览：四张真实截图 ===================== -->
      <section class="lp-section lp-views" aria-labelledby="lp-views-title">
        <div class="lp-frame">
          <div class="lp-sec-head reveal">
            <h2 id="lp-views-title" class="lp-h2">工作台的四个视图</h2>
          </div>
          <div class="lp-view-grid">
            <figure v-for="(v, i) in views" :key="v.src" class="lp-view reveal" :style="{ '--d': `${i * 80}ms` }">
              <div class="lp-view-img" :style="{ '--ix': v.x, '--iy': v.y }">
                <img :src="v.src" :alt="v.alt" width="1440" height="900" loading="lazy" />
              </div>
              <figcaption class="lp-cap">{{ v.caption }}</figcaption>
            </figure>
          </div>
        </div>
      </section>

      <!-- ===================== 边界说明：诚实的 risk reversal ===================== -->
      <section id="scope" class="lp-section lp-scope" aria-labelledby="lp-scope-title">
        <div class="lp-frame">
          <div class="lp-scope-card reveal">
            <h2 id="lp-scope-title" class="lp-h3">适用范围与已知限制</h2>
            <div class="lp-scope-cols">
              <div>
                <p class="lp-cap lp-scope-label">适合</p>
                <ul>
                  <li v-for="x in scopeYes" :key="x" class="lp-body">{{ x }}</li>
                </ul>
              </div>
              <div>
                <p class="lp-cap lp-scope-label">尚不支持</p>
                <ul>
                  <li v-for="x in scopeNo" :key="x" class="lp-body">{{ x }}</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ===================== FAQ ===================== -->
      <section id="faq" class="lp-section lp-faq" aria-labelledby="lp-faq-title">
        <div class="lp-frame">
          <div class="lp-sec-head reveal">
            <h2 id="lp-faq-title" class="lp-h2">常见问题</h2>
          </div>
          <div class="lp-faq-stack">
            <div
              v-for="(item, i) in faqs"
              :key="i"
              class="lp-faq-card reveal"
              :class="{ 'is-open': openFaq === i }"
              :style="{ '--d': `${i * 40}ms` }"
            >
              <button
                class="lp-faq-q"
                type="button"
                :aria-expanded="openFaq === i"
                :aria-controls="`lp-faq-a-${i}`"
                @click="openFaq = openFaq === i ? -1 : i"
              >
                <span class="lp-faq-topic lp-cap">{{ item.topic }}</span>
                <span class="lp-faq-text">{{ item.q }}</span>
                <span class="lp-faq-sign" aria-hidden="true">{{ openFaq === i ? '−' : '+' }}</span>
              </button>
              <div :id="`lp-faq-a-${i}`" class="lp-faq-a" v-show="openFaq === i">
                <p class="lp-body">{{ item.a }}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ===================== 结尾 CTA：整条就是一个按钮 ===================== -->
      <a class="lp-final" href="/app" aria-label="进入工作台，开始抽取">
        <span class="lp-frame lp-final-inner">
          <svg class="lp-final-arrow" viewBox="0 0 64 64" fill="none" aria-hidden="true">
            <path d="M12 52 52 12M22 12h30v30" stroke="currentColor" stroke-width="4" stroke-linecap="square" />
          </svg>
          <span class="lp-final-word">进入工作台</span>
        </span>
      </a>
    </main>

    <!-- ===================== 页脚：品牌名作为收尾大字 ===================== -->
    <footer class="lp-footer">
      <div class="lp-frame">
        <div class="lp-footer-top">
          <p class="lp-cap">中文实体识别与关系抽取</p>
          <a class="lp-cap" href="#lp-main">回到顶部 ↑</a>
        </div>
        <p class="lp-footer-word">中文关系抽取系统</p>
        <div class="lp-footer-meta lp-cap">
          <span>本机处理 · 数据不出本机</span>
          <span>2026 · <a href="/app">进入工作台 →</a></span>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch, nextTick } from 'vue'
import demoData from '../data/landing-demo.json'

/* ------------------------------------------------------------------
   真实数据：全部来自 backend/eval/gold.json、REPORT.md 与 pipeline 输出
   ------------------------------------------------------------------ */
const demo = demoData.sample
const menuId = 'lp-nav-links'

const navItems = [
  { label: '能力', href: '#capabilities' },
  { label: '流程', href: '#method' },
  { label: '边界', href: '#scope' },
  { label: '常见问题', href: '#faq' },
]

const capabilities = [
  { name: '实体标注', fact: '6 类实体', detail: '人物、组织机构、地理位置、时间、金额、产品技术。正文彩色高亮，右侧清单可按类型显隐，点实体反向定位。' },
  { name: '关系三元组', fact: '19 类关系', detail: '输出头实体、关系、尾实体，并附置信度、触发词、证据句与所用规则。支持按类型、置信度和关键词筛选。' },
  { name: '证据链穿透', fact: '一次点击', detail: '三元组行的「原文」按钮跳回实体标注并高亮证据句；图谱节点下钻到三元组；统计页句子行同样可定位。' },
  { name: '关系图谱', fact: '2 种布局', detail: 'ECharts 力导向与环形布局，可拖拽、缩放、合并同义实体，点节点即可查看含该实体的全部关系。' },
  { name: '统计洞察', fact: '4 类图表', detail: '实体类型分布、关系类型分布、句级关系数与全库累计，句子明细可直接点开定位原文。' },
  { name: '编码识别', fact: '4 种编码', detail: '上传 UTF-8、GB18030、UTF-16、BIG5 文本时逐个解码并按字符分布打分取最优，不再静默产生乱码。' },
  { name: '结果导出', fact: '4 种格式', detail: 'CSV 带 BOM 可直接用 Excel 打开，另有完整 JSON、Markdown 分析报告与图谱 PNG。' },
  { name: '历史复现', fact: 'SQLite 持久化', detail: '主动抽取或点「存入历史」才写库，支持检索、载入复现、单条删除与一键清空；初始示例只作预览不入库。' },
]

const methodSteps = [
  { name: '分句', detail: '按中文标点切出句子并记录起止偏移，后续所有结果都用这个偏移回指原文，不做字符串模糊匹配。' },
  { name: '识别', detail: 'jieba 分词叠加实体词典与正则，识别 6 类实体；机构名递归剥离后缀做归一，重叠候选按置信度消解。' },
  { name: '匹配', detail: '触发词与句式模板按类型约束配对，附带轻量指代消解与主语链继承，输出带证据句的三元组。' },
]

// 同一批截图用不同取景，避免四张都停在「抽取结果」顶部
const views = [
  { src: '/media/view-entities.png', x: '-20%', y: '-8%', caption: '实体标注：正文高亮 6 类实体，右侧清单按类型显隐', alt: '实体标注视图截图，左侧为文本输入面板，中间为带实体高亮的新闻正文，右侧为实体清单' },
  { src: '/media/view-triples.png', x: '-34%', y: '-22%', caption: '关系三元组：每行都能展开看证据句', alt: '三元组表格视图截图，含关系类型筛选、置信度三档与原文定位按钮' },
  { src: '/media/view-graph.png', x: '-16%', y: '-30%', caption: '关系图谱：点节点下钻到对应三元组', alt: '力导向关系图谱截图，节点与连线展示实体间关系' },
  { src: '/media/view-stats.png', x: '-24%', y: '-14%', caption: '统计洞察：分布、句级关系数与全库累计', alt: '统计洞察视图截图，含指标条、分布卡片与句子明细' },
]

const scopeYes = [
  '中文财经与科技新闻中的显式关系',
  '需要逐条核对出处、解释规则来源的场景',
  '完全离线的本地部署与演示',
  '需要把结果导出成 CSV / JSON / Markdown 继续处理',
]
const scopeNo = [
  '词典未收录的小众机构名与生僻人名',
  '跨句推理、隐式语义与反讽等需要语境推断的表达',
  '19 类关系之外的语义（会被丢弃而非误报）',
  '人工校正已抽出的关系（当前为只读结果）',
]

const faqs = [
  { topic: '离线', q: '需要联网吗？', a: '不需要。分句、实体识别与关系抽取全部在本机完成，没有外部 API 调用。' },
  { topic: '数据', q: '粘贴的文字存在哪里？', a: '只写本机的 backend/data/app.db。示例仅作预览，只有主动抽取或存入历史才会落库。' },
  { topic: '输入', q: '支持哪些文件和编码？', a: '.txt、.md、.text，单个文件不超过 2 MB，自动识别 UTF-8、GB18030、UTF-16 与 BIG5。' },
  { topic: '边界', q: '抽错了能手动改吗？', a: '暂时不能，结果是只读的。可以补词典与模板后重新抽取。' },
  { topic: '部署', q: '可以挂到公网吗？', a: '不建议。这是单机单用户设计，没有账号体系与权限隔离。' },
  { topic: '入口', q: '首页和工作台怎么切换？', a: '首页在 /，工作台在 /app；工作台左上角品牌可返回首页。' },
]

/* ------------------------------------------------------------------
   接口契约面板
   ------------------------------------------------------------------ */
const sentences = ref(demo.sentences)
const entities = ref(demo.entities)
const relations = ref(demo.relations)
const sourceText = ref(demo.text)
const activeSentence = ref(0)
const sentRefs = ref([])
const sentMarkerY = ref(0)
function setSentRef(el, i) { if (el) sentRefs.value[i] = el }
const runState = ref('idle') // idle | running | done | error
const runError = ref('')
const runMeta = ref(null)
const pulseKey = ref(0)
const replaying = ref(false)

function relationsFor(idx) {
  return relations.value.filter((r) => r.sentence_index === idx)
}

function fragmentsFor(sent) {
  const list = entities.value
    .filter((e) => e.start >= sent.start && e.end <= sent.end)
    .sort((a, b) => a.start - b.start)
  const out = []
  let cursor = sent.start
  for (const e of list) {
    if (e.start < cursor) continue
    if (e.start > cursor) out.push({ type: 'text', text: sourceText.value.slice(cursor, e.start) })
    out.push({ type: 'ent', text: sourceText.value.slice(e.start, e.end), label: e.label || e.type_label || '实体' })
    cursor = e.end
  }
  if (cursor < sent.end) out.push({ type: 'text', text: sourceText.value.slice(cursor, sent.end) })
  if (!out.length) out.push({ type: 'text', text: sent.text })
  return out
}

async function runLiveExtract() {
  if (runState.value === 'running') return
  runState.value = 'running'
  runError.value = ''
  try {
    const t0 = performance.now()
    const res = await fetch('/api/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: demo.text, title: demo.title, save: false }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    const r = data.result || data
    if (!r.sentences || !r.entities || !r.relations) throw new Error('返回结构不完整')
    sentences.value = r.sentences
    entities.value = r.entities
    relations.value = r.relations.map((x) => ({
      ...x,
      label: x.relation_label || x.label || x.relation,
      color: x.color || '#a8322a',
    }))
    sourceText.value = r.text || demo.text
    activeSentence.value = 0
    runMeta.value = {
      status: res.status,
      sentences: sentences.value.length,
      relations: relations.value.length,
      ms: Math.round(performance.now() - t0),
    }
    pulseKey.value += 1
    replay()
    runState.value = 'done'
  } catch (err) {
    runError.value = err.message || '未知错误'
    runState.value = 'error'
  }
}

let replayTimer = null
function replay() {
  if (prefersReduced.value) return
  replaying.value = false
  clearTimeout(replayTimer)
  nextTick(() => {
    replaying.value = true
    replayTimer = setTimeout(() => { replaying.value = false }, 900)
  })
}

/* ------------------------------------------------------------------
   能力切换器：点击或键盘固定选中，hover 只做视觉，不再抢选中态。
   右侧详情常驻，选中变化只换内容，避免出现「按一下就消失」的空卡片。
   ------------------------------------------------------------------ */
const query = ref('')
const selected = ref(0)
const capRefs = ref([])
const capIndicatorY = ref(0)
function setCapRef(el, i) { if (el) capRefs.value[i] = el }
const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return capabilities
  return capabilities.filter((c) => `${c.name}${c.fact}${c.detail}`.toLowerCase().includes(q))
})
watch(filtered, (list) => { if (selected.value >= list.length) selected.value = 0 })
function moveSelection(delta) {
  const n = filtered.value.length
  if (!n) return
  selected.value = (selected.value + delta + n) % n
}

/* 两条红色指示条都用 transform 跟随真实行位置，不写死行高，换行也不脱节 */
function syncIndicators() {
  nextTick(() => {
    const capEl = capRefs.value[selected.value]
    if (capEl) capIndicatorY.value = capEl.offsetTop + (capEl.offsetHeight - 32) / 2
    const sentEl = sentRefs.value[activeSentence.value] || sentRefs.value[0]
    if (sentEl) sentMarkerY.value = sentEl.offsetTop + (sentEl.offsetHeight - 28) / 2
  })
}
watch([selected, filtered, activeSentence], syncIndicators)

/* ------------------------------------------------------------------
   其他交互状态
   ------------------------------------------------------------------ */
const openRow = ref(2)
const openFaq = ref(0)
const menuOpen = ref(false)
watch(menuOpen, (open) => {
  document.body.style.overflow = open ? 'hidden' : ''
})
const scrolled = ref(false)
const activeSection = ref('')
const progress = ref(0)

function closeMenu() { menuOpen.value = false }

/* ------------------------------------------------------------------
   动效：默认全部可见；只有 JS 成功挂载且未开启 reduced-motion 才启用入场
   ------------------------------------------------------------------ */
const prefersReduced = ref(false)
let navObserver = null
let onScroll = null
let syncFrame = 0
let revealEls = []

/* 入场统一在一次 rAF 里按位置判定，不用 IntersectionObserver。
   IO 只在阈值被穿越时回调；PageDown、锚点跳转或自动化整屏滚动会让元素从
   「视口下方 100px」直接落到「视口上方 800px」，两端都不相交，回调一次都不发，
   这些区块就会永远停在 opacity:0。直接读 getBoundingClientRect 没有这个漏洞。 */
function syncScrollState() {
  syncFrame = 0
  const enterLine = window.innerHeight - 48
  for (const el of revealEls) {
    if (el.classList.contains('is-in')) continue
    if (el.getBoundingClientRect().top < enterLine) el.classList.add('is-in')
  }
}
function queueSync() {
  if (syncFrame) return
  syncFrame = requestAnimationFrame(syncScrollState)
}
function onResize() {
  queueSync()
  syncIndicators()
}

onMounted(() => {
  document.body.classList.add('lp-active')
  prefersReduced.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  onScroll = () => {
    scrolled.value = window.scrollY > 12
    const max = document.documentElement.scrollHeight - window.innerHeight
    progress.value = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0
    if (!prefersReduced.value) queueSync()
  }
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('resize', onResize, { passive: true })
  onScroll()

  // CSS 默认态就是终态：无脚本、脚本报错、动效偏好关闭时内容都完整可读。
  // 指示条仍需对齐真实行位置，只是不再有过渡。
  if (prefersReduced.value) {
    syncIndicators()
    return
  }

  document.documentElement.classList.add('lp-anim')
  revealEls = [...document.querySelectorAll('.lp .reveal')]
  queueSync()
  syncIndicators()

  // 只用来高亮导航当前区块，不控制任何内容的可见性
  navObserver = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) activeSection.value = `#${e.target.id}`
    }
  }, { rootMargin: '-25% 0px -65% 0px' })
  document.querySelectorAll('.lp section[id]').forEach((el) => navObserver.observe(el))
})

onBeforeUnmount(() => {
  document.body.classList.remove('lp-active')
  document.body.style.overflow = ''
  document.documentElement.classList.remove('lp-anim')
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', onResize)
  cancelAnimationFrame(syncFrame)
  clearTimeout(replayTimer)
  navObserver?.disconnect()
})

/* ------------------------------------------------------------------
   原理图点阵：确定性坐标，三段密度表达散乱 → 收束 → 有序
   ------------------------------------------------------------------ */
const dots = computed(() => {
  const out = []
  for (let i = 0; i < 54; i++) {
    out.push({ x: 10 + ((i * 37) % 360), y: 14 + ((i * 61) % 224), w: 9, h: 9, fill: '#d8d2c4' })
  }
  for (let r = 0; r < 3; r++) {
    for (let c = 0; c < 18; c++) {
      out.push({ x: 420 + c * 20, y: 100 + r * 15, w: 10, h: 10, fill: '#8d887b' })
    }
  }
  for (let r = 0; r < 6; r++) {
    for (let c = 0; c < 6; c++) {
      out.push({ x: 820 + c * 58, y: 28 + r * 38, w: 11, h: 11, fill: '#a8322a' })
    }
  }
  return out
})
</script>

<style scoped>
/* ============================================================
   首页视觉世界：中文报纸校样（只保留纸色、红笔与边注栏，不进入文案）
   五档字号 14/16/20/32/56 由 :root 的 --brand-scale-1..5 统一提供
   间距只用 2·4·8·12·16·24·32·48·64·96；圆角沿用全站唯一决定 4px
   一个强调色：校改红 #a8322a，面积 ≤10%；色值由 :root 的 --brand-* 统一提供
   ============================================================ */
.lp {
  /* 色值不再在首页另立一套：全部取自 styles.css :root 的 --brand-*，
     首页与工作台因此共用同一张纸、同一支朱笔。 */
  --paper: var(--brand-paper);
  --paper-2: var(--brand-paper-2);
  --paper-3: var(--brand-paper-3);
  --surface: var(--brand-surface);
  --ink: var(--brand-ink);
  --ink-2: var(--brand-ink-2);
  --muted: var(--brand-muted);
  --red: var(--brand-red);
  --red-soft: var(--brand-red-soft);
  --dark: var(--brand-dark);
  --r: 4px;
  /* 动效不再在首页另立一套：曲线与全部时长档继承 :root 的 --ease / --dur-*，
     与工作台共用同一套节奏（单一真相源见 styles.css）。 */
  --frame: min(1280px, calc(100% - 96px));

  min-height: 100svh;
  background: var(--paper);
  color: var(--ink);
  /* 字体继承 body 的 --font-sans：本地 Space Grotesk + 中文系统栈，离线零依赖 */
  font-size: 16px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  /* 中文标点禁则与中西文间距交给浏览器，不再靠负字距挤压方块字 */
  line-break: strict;
  text-spacing-trim: space-first;
}

.lp * { box-sizing: border-box; }
.lp :focus-visible { outline: 2px solid var(--red); outline-offset: 3px; border-radius: 2px; }
.lp ::selection { background: var(--red); color: #fff; }
/* 不设全局 a 颜色：`.lp a` 的特异性会压过按钮自己的 color，导致黑底黑字 */
.lp a { text-decoration: none; }
.lp button { font-family: inherit; font-size: inherit; }
/* reset 用裸标签选择器：带 .lp 前缀会压过下面所有 class 的 margin 设置 */
p, h1, h2, h3, ul, dl, dt, dd, figure { margin: 0; }
ul { padding: 0; list-style: none; }
.lp code { font-size: 1em; padding: 1px 4px; background: var(--paper-2); border-radius: 2px; }
.lp b { font-weight: 600; }
/* 命名文本样式用单类，别加 .lp 前缀：否则区块内的局部改色永远盖不过它 */
/* 五档字号：56 展示 / 32 区块 / 20 小标题 / 16 正文 / 14 元信息。
   中文方块字不用负字距；大字号用较轻字重，靠尺度和留白建立层级。 */
.lp-cap { font-size: var(--brand-scale-1); line-height: 20px; color: var(--muted); font-variant-numeric: tabular-nums; }
.lp-body { font-size: var(--brand-scale-2); line-height: 26px; color: var(--ink-2); max-width: 34em; }
.lp-h2 { font-size: var(--brand-scale-4); line-height: 1.25; font-weight: 500; letter-spacing: 0; text-wrap: balance; }
.lp-h3 { font-size: var(--brand-scale-3); line-height: 28px; font-weight: 600; letter-spacing: 0; }
.lp-sr {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; /* taste-skill-ignore: 读屏隐藏文本 */
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
.lp-frame { width: var(--frame); margin-inline: auto; }
.lp-skip {
  position: absolute; left: 16px; top: -64px; z-index: 100;
  padding: 8px 12px; background: var(--ink); color: #fff; font-size: 14px;
}
.lp-skip:focus { top: 12px; }

/* ---------- 导航 ---------- */
.lp-nav-wrap { position: sticky; top: 0; z-index: 50; background: var(--paper); }
/* 被动的阅读进度反馈：只改 transform，无过渡，滚动时不产生额外动画 */
.lp-progress {
  position: absolute; left: 0; bottom: 0; width: 100%; height: 2px;
  background: var(--red); transform: scaleX(var(--p, 0)); transform-origin: left;
}
.lp-nav {
  width: var(--frame); margin-inline: auto; height: 64px;
  display: flex; align-items: center; justify-content: space-between; gap: 24px;
}
.lp-wordmark { display: inline-flex; align-items: center; gap: 8px; color: var(--ink); font-size: 16px; font-weight: 600; letter-spacing: -0.02em; }
.lp-wordmark svg { width: 28px; height: 28px; flex: none; }
.lp-nav-links { display: flex; align-items: center; gap: 32px; }
.lp-nav-links a { font-size: 14px; line-height: 20px; color: var(--ink-2); transition: color var(--dur-color) var(--ease); }
.lp-nav-links a:hover { color: var(--red); }
.lp-nav-links a[aria-current='location'] { color: var(--red); font-weight: 600; }
.lp-nav-mobile-cta { display: none; }
.lp-nav-cta {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 8px 12px; background: var(--ink); color: var(--paper);
  font-size: 14px; font-weight: 600; border-radius: var(--r);
  transition: background var(--dur-color) var(--ease), transform var(--dur-press) var(--ease);
}
.lp-nav-cta:hover { background: var(--red); }
.lp-nav-cta:active { transform: scale(0.98); }
.lp-menu-toggle { display: none; }

/* ---------- 首屏 ---------- */
.lp-hero { padding-top: 48px; }
.lp-headline {
  max-width: 20em; font-size: var(--brand-scale-5); line-height: 1.16; font-weight: 500;
  letter-spacing: 0; text-wrap: balance;
}
.lp-headline-wide, .lp-headline-narrow { display: block; }
.lp-headline-narrow { display: none; }
/* 招牌动作：标题遮罩上浮结束后，红笔从左向右划出一次 */
.lp-headline-rule {
  display: block; width: min(100%, 340px); height: 3px; margin-top: 24px;
  background: var(--red); transform: scaleX(1); transform-origin: left;
}
html.lp-anim .lp-headline-rule {
  transform: scaleX(0);
  animation: lpDraw var(--dur-entrance) var(--ease) var(--dur-move) forwards;
}
@keyframes lpDraw { to { transform: scaleX(1); } }
.lp-mask { display: block; overflow: hidden; padding-bottom: 0.08em; }
/* 终态是默认：没有脚本、脚本报错、动效关闭时标题都必须完整可读 */
.lp-mask-in { display: block; transform: none; }
html.lp-anim .lp-mask-in {
  transform: translateY(105%);
  animation: lpRise var(--dur-entrance) var(--ease) forwards;
}
html.lp-anim .lp-mask-in-2 { animation-delay: calc(var(--stagger-step) * 2); }
@keyframes lpRise { to { transform: translateY(0); } }

.lp-hero-row {
  display: flex; align-items: flex-end; justify-content: space-between; gap: 48px;
  margin-top: 32px;
}
/* 20px：首屏这行承担「这是什么」的说明，字号要达到可读的正文上限 */
.lp-sub { max-width: 34em; font-size: 20px; line-height: 30px; color: var(--ink-2); text-wrap: pretty; }
.lp-cta {
  flex: none; display: inline-flex; align-items: center; gap: 16px;
  padding: 16px 24px; background: var(--red); color: #fff;
  font-size: 16px; font-weight: 600; border-radius: var(--r);
  transition: background var(--dur-color) var(--ease), transform var(--dur-press) var(--ease);
}
.lp-cta svg { width: 20px; height: 20px; }
.lp-cta:hover { background: var(--ink); }
.lp-cta:active { transform: scale(0.98); }
/* ---------- 接口契约面板：真实界面片段 ---------- */
.lp-sheet-wrap { margin-top: 56px; padding-bottom: 96px; }
.lp-sheet { position: relative; background: var(--brand-surface); border-radius: var(--r); overflow: hidden; }
/* 接口重跑成功后，一条红线从面板左端扫到右端再淡出：一次性的完成反馈 */
.lp-sheet-pulse {
  position: absolute; left: 0; top: 0; z-index: 2; width: 100%; height: 3px;
  background: var(--red); transform-origin: left; pointer-events: none;
  animation: lpPulse var(--dur-scan) var(--ease) both;
}
@keyframes lpPulse {
  from { transform: scaleX(0); opacity: 1; }
  to { transform: scaleX(1); opacity: 0; }
}
.lp-sheet-head {
  display: flex; align-items: flex-end; justify-content: space-between; gap: 24px;
  padding: 24px 32px; background: var(--paper-2);
}
.lp-sheet-title { font-size: 20px; line-height: 28px; font-weight: 600; letter-spacing: 0; }
.lp-sheet-actions { display: flex; align-items: center; gap: 24px; }
.lp-sheet-count { white-space: nowrap; }
.lp-run {
  flex: none; padding: 8px 12px; background: var(--ink); color: var(--paper);
  font-size: 14px; font-weight: 600; border: 0; border-radius: var(--r); cursor: pointer;
  transition: background var(--dur-color) var(--ease), transform var(--dur-press) var(--ease);
}
.lp-run:hover:not(:disabled) { background: var(--red); }
.lp-run:active:not(:disabled) { transform: scale(0.98); }
.lp-run:disabled { opacity: 0.45; cursor: progress; }
.lp-sheet-body { display: grid; grid-template-columns: minmax(0, 1fr) 360px; }
.lp-original { position: relative; padding: 24px 32px 32px; }
/* 一根红线在句子之间滑动，比每行各画一条更能表达「当前读到哪句」 */
.lp-sent-marker {
  position: absolute; left: 32px; top: 0; width: 3px; height: 28px;
  background: var(--red); transform: translateY(0);
  transition: transform var(--dur-swap) var(--ease); pointer-events: none;
}
.lp-sent {
  position: relative;
  display: grid; grid-template-columns: 24px minmax(0, 1fr) auto;
  align-items: start; gap: 12px; width: 100%;
  padding: 12px 8px; margin: 0; border: 0; background: transparent;
  text-align: left; font-size: 16px; line-height: 24px; color: var(--ink);
  cursor: pointer; border-radius: var(--r);
  transition: background var(--dur-color) var(--ease);
}
.lp-sent:hover { background: var(--paper-2); }
.lp-sent.is-active { background: var(--red-soft); }
.lp-sent-no { padding-top: 4px; color: var(--red); font-weight: 600; }
.lp-sent-text { text-wrap: pretty; }
.lp-ent {
  padding: 0 1px; background: transparent; color: inherit;
  border-bottom: 2px solid var(--red); border-radius: 0;
}
.lp-sent.is-active .lp-ent { background: #fdf1ee; }
.lp-sent-count { padding-top: 4px; white-space: nowrap; color: var(--red); font-weight: 600; }
.lp-margin { padding: 24px 24px 32px; background: var(--paper); }
.lp-margin-label { color: var(--red); font-weight: 600; margin-bottom: 16px; }
.lp-margin-empty { font-size: 14px; line-height: 20px; color: var(--ink-2); }
.lp-note { padding: 12px 0; }
.lp-note + .lp-note { margin-top: 4px; padding-top: 16px; }
.lp-note-triple { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; font-size: 16px; line-height: 24px; }
.lp-note-rel { color: var(--red); font-size: 14px; font-weight: 600; }
.lp-fields { margin-top: 8px; display: grid; gap: 4px; }
.lp-fields > div { display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: 8px; }
.lp-fields dt { color: var(--muted); }
.lp-fields dd { color: var(--ink); overflow-wrap: anywhere; }
.lp-inline-error, .lp-inline-ok {
  padding: 12px 32px; font-size: 14px; line-height: 20px;
}
.lp-inline-error { background: var(--red-soft); color: #7a221c; }
.lp-inline-ok { background: var(--paper-2); color: var(--ink-2); }

/* 切换句子时字段内容交叉淡入，每条三元组错峰 50ms */
.lp-field-swap-enter-active { transition: opacity var(--dur-swap) var(--ease), transform var(--dur-swap) var(--ease); }
.lp-field-swap-leave-active { transition: opacity var(--dur-press) var(--ease), transform var(--dur-press) var(--ease); }
.lp-field-swap-enter-from { opacity: 0; transform: translateY(10px); }
.lp-field-swap-leave-to { opacity: 0; transform: translateY(-6px); }
html.lp-anim .lp-margin-content .lp-note {
  animation: lpFieldIn var(--dur-swap) var(--ease) both;
  animation-delay: var(--ri, 0ms);
}
@keyframes lpFieldIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}

/* 逐句浮现（交互反馈，不是装饰） */
.lp-original.is-replaying .lp-sent {
  animation: lpSentIn var(--dur-move) var(--ease) both;
  animation-delay: var(--si);
}
@keyframes lpSentIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}

/* ---------- 价值段：Figma AI 生成的纸墨朱主视觉，接替原「运行」命令屏 ----------
   图本身无可读文字 / Logo，左侧留白承载主张；只在窄屏加纯色遮罩保证对比度。 */
.lp-closesec {
  position: relative;
  isolation: isolate;
  background: var(--dark) url('/media/lp-closing.jpg') center center / cover no-repeat;
  color: var(--paper);
}
.lp-closesec .lp-frame { position: relative; z-index: 1; }
.lp-close-copy { max-width: 520px; }
.lp-closesec .lp-h2 { color: var(--paper); max-width: 18em; }
.lp-closesec .lp-body { color: rgba(246, 243, 234, 0.86); max-width: 34em; margin-top: 16px; }
.lp-close-link {
  display: inline-flex; align-items: center; gap: 8px;
  min-height: 44px; margin-top: 32px;
  color: var(--paper); font-size: var(--brand-scale-2); font-weight: 500;
  text-underline-offset: 6px;
  transition: color var(--dur-color) var(--ease);
}
.lp-close-link:hover { color: #e4aca7; }
.lp-close-link:focus-visible { outline: 2px solid var(--paper); outline-offset: 4px; }
.lp-close-note { margin-top: 24px; color: rgba(246, 243, 234, 0.62); }
/* ---------- 通用区块 ---------- */
.lp-section { padding: 96px 0; }
.lp-sec-head { margin-bottom: 48px; }

/* ---------- 能力：左右分栏，右侧详情常驻 ---------- */
.lp-capabilities { background: var(--paper-2); }
.lp-cap-layout {
  display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 0.9fr);
  gap: 48px; align-items: start;
}
.lp-cap-search {
  display: flex; align-items: center; gap: 12px;
  padding: 8px 16px; background: var(--brand-surface); border-radius: var(--r);
}
.lp-cap-search svg { width: 20px; height: 20px; color: var(--muted); flex: none; }
.lp-cap-search input {
  flex: 1; min-width: 0; height: 44px; border: 0; outline: 0; background: transparent;
  font-family: inherit; font-size: 20px; line-height: 28px; color: var(--ink);
}
.lp-cap-search input::placeholder { color: var(--muted); }
.lp-cap-list { position: relative; margin-top: 24px; }
.lp-cap-marker {
  position: absolute; left: 0; top: 0; width: 3px; height: 32px;
  background: var(--red); transform: translateY(0);
  transition: transform var(--dur-swap) var(--ease); pointer-events: none;
}
.lp-cap-item {
  display: flex; align-items: baseline; justify-content: space-between; gap: 24px;
  width: 100%; padding: 12px 16px; border: 0; background: transparent; color: var(--ink);
  text-align: left; cursor: pointer; border-radius: var(--r);
  transition: background var(--dur-hover) var(--ease), color var(--dur-hover) var(--ease);
}
.lp-cap-item.is-selected { color: var(--red); }
.lp-cap-name { font-size: 32px; line-height: 1.25; font-weight: 500; letter-spacing: 0; }
.lp-cap-fact { color: var(--muted); white-space: nowrap; }
.lp-cap-item.is-selected .lp-cap-fact { color: var(--red); }
@media (hover: hover) and (pointer: fine) {
  .lp-cap-item:not(.is-selected):hover { background: rgba(168, 50, 42, 0.06); }
}

.lp-cap-panel {
  position: sticky; top: 96px;
  display: flex; flex-direction: column; justify-content: center;
  min-height: 320px; padding: 32px; background: var(--brand-surface); border-radius: var(--r);
}
.lp-cap-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.lp-cap-fact-inline { color: var(--red); font-weight: 600; white-space: nowrap; }
.lp-cap-title { font-size: 32px; line-height: 1.25; font-weight: 500; letter-spacing: 0; }
.lp-cap-rule {
  display: block; width: 64px; height: 3px; margin: 24px 0;
  background: var(--red); transform: scaleX(1); transform-origin: left;
}
html.lp-anim .lp-cap-rule { animation: lpCapRule var(--dur-move) var(--ease) both; }
@keyframes lpCapRule { from { transform: scaleX(0); } to { transform: scaleX(1); } }
.lp-cap-text { max-width: 30em; }
.lp-cap-link {
  display: inline-flex; align-items: center; gap: 8px; margin-top: 32px;
  color: var(--red); font-size: 16px; font-weight: 600;
}
.lp-cap-link span { display: inline-block; transition: transform var(--dur-hover) var(--ease); }
@media (hover: hover) and (pointer: fine) {
  .lp-cap-link:hover span { transform: translateX(4px); }
}
/* 详情切换：旧内容上移淡出、新内容上移淡入，总时长 340ms */
.lp-cap-swap-enter-active { transition: opacity var(--dur-swap) var(--ease), transform var(--dur-swap) var(--ease); }
.lp-cap-swap-leave-active { transition: opacity var(--dur-press) var(--ease), transform var(--dur-press) var(--ease); }
.lp-cap-swap-enter-from { opacity: 0; transform: translateY(12px); }
.lp-cap-swap-leave-to { opacity: 0; transform: translateY(-8px); }

/* ---------- 结果看板 ---------- */
.lp-board { display: flex; flex-direction: column; gap: 4px; }
.lp-board-row { background: var(--paper-2); border-radius: var(--r); overflow: hidden; transition: background var(--dur-color) var(--ease); }
.lp-board-row.is-open { background: var(--dark); color: var(--paper); }
.lp-board-btn {
  display: grid; grid-template-columns: minmax(120px, 1.2fr) minmax(100px, 0.8fr) minmax(120px, 1.2fr) 64px 80px;
  align-items: center; gap: 16px; width: 100%; min-height: 72px;
  padding: 12px 24px; border: 0; background: transparent; color: inherit;
  text-align: left; cursor: pointer; font-size: 16px;
  transition: background var(--dur-color) var(--ease);
}
.lp-board-btn:hover { background: rgba(168, 50, 42, 0.06); }
.lp-board-row.is-open .lp-board-btn:hover { background: rgba(255, 255, 255, 0.06); }
.lp-board-head, .lp-board-tail { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* 19 类关系的真实配色只做 4px 色条，文字恒用墨色：
   亮绿 #10b981 配白字只有 2.5:1，实色底 + 白字在 19 个色相里无法保证可读 */
.lp-board-rel {
  display: inline-flex; align-items: center; gap: 8px;
  width: fit-content; padding: 4px 8px 4px 6px;
  background: var(--paper-2); color: var(--ink);
  font-size: 14px; font-weight: 600; border-radius: var(--r);
}
.lp-board-rel::before {
  content: ''; flex: none; width: 4px; height: 14px;
  background: var(--rel-color); border-radius: 2px;
}
.lp-board-conf, .lp-board-sent { color: var(--muted); }
.lp-board-row.is-open .lp-board-conf, .lp-board-row.is-open .lp-board-sent { color: rgba(246, 243, 234, 0.7); }
.lp-board-detail { padding: 0 24px 24px; }
.lp-board-detail .lp-body { color: var(--paper); max-width: 34em; margin: 8px 0; }
.lp-board-detail .lp-cap { color: rgba(246, 243, 234, 0.7); }

/* ---------- 原理 ---------- */
.lp-method { background: var(--paper-2); }
.lp-diagram { padding: 32px; background: var(--brand-surface); border-radius: var(--r); }
.lp-diagram svg { display: block; width: 100%; height: auto; }
.lp-method-cols { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 48px; margin-top: 32px; }
.lp-method-col .lp-body { margin-top: 8px; text-wrap: pretty; }

/* ---------- 四个视图 ---------- */
.lp-views { background: var(--paper-2); }
.lp-view-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; align-items: start; }
.lp-view { background: var(--brand-surface); border-radius: var(--r); overflow: hidden; }
/* 界面片段要放大裁切：整张 1440×900 缩到 460px 宽，字会小到读不出来 */
.lp-view-img { position: relative; aspect-ratio: 16 / 9; overflow: hidden; }
.lp-view-img img { position: absolute; width: 175%; height: auto; left: var(--ix, -20%); top: var(--iy, -8%); display: block; }
.lp-view figcaption { padding: 12px 16px; }

/* ---------- 边界说明卡 ---------- */
.lp-scope { padding-top: 0; }
.lp-scope-card {
  width: min(760px, 100%); margin-inline: auto; padding: 48px;
  background: var(--brand-surface); border-radius: var(--r); transform: rotate(-1deg);
}
.lp-scope-card > .lp-h3 { margin-bottom: 32px; }
.lp-scope-cols { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 32px; }
.lp-scope-label { color: var(--red); font-weight: 600; margin-bottom: 12px; }
.lp-scope-cols li { padding: 6px 0 6px 16px; position: relative; }
.lp-scope-cols li::before { content: ''; position: absolute; left: 0; top: 16px; width: 5px; height: 5px; background: var(--red); border-radius: 50%; }
.lp-scope-foot { margin-top: 32px; }

/* ---------- FAQ ---------- */
/* 标准手风琴：不用负 margin 叠卡。上一版堆叠会把相邻问题的文字压在一起 */
.lp-faq { background: var(--paper-2); }
.lp-faq-stack { display: flex; flex-direction: column; gap: 8px; }
.lp-faq-card {
  background: var(--brand-surface); border-radius: var(--r); padding: 16px 24px 20px;
  transition: background var(--dur-color) var(--ease);
}
.lp-faq-card:nth-child(3n + 2) { background: var(--paper); }
.lp-faq-card:nth-child(3n + 3) { background: #f1ebdd; }
.lp-faq-card.is-open { background: var(--brand-surface); }
/* 分类词与问题同一行，不做标题上方的小标签 */
.lp-faq-q {
  display: flex; align-items: center; gap: 16px;
  width: 100%; padding: 4px 0; border: 0; background: transparent; color: var(--ink);
  text-align: left; font-size: 20px; line-height: 28px; font-weight: 600; cursor: pointer;
}
.lp-faq-topic { flex: none; color: var(--red); font-weight: 600; }
.lp-faq-text { flex: 1; min-width: 0; }
.lp-faq-sign { flex: none; color: var(--red); font-size: 20px; }
.lp-faq-a { max-width: 34em; padding: 8px 0 4px; }

/* ---------- 结尾 CTA ---------- */
.lp-final { display: block; background: var(--red); color: #fff; transition: background var(--dur-color) var(--ease); }
.lp-final:hover, .lp-final:focus-visible { background: var(--ink); }
.lp-final-inner { display: block; position: relative; min-height: 220px; padding: 48px 0 32px; }
.lp-final-arrow { position: absolute; right: 0; top: 32px; width: 64px; height: 64px; }
.lp-final-word {
  display: block; position: absolute; left: 0; bottom: 24px;
  font-size: 32px; line-height: 1.25; font-weight: 500; letter-spacing: 0;
}

/* ---------- 页脚 ---------- */
.lp-footer { background: var(--dark); color: var(--paper); padding: 48px 0 32px; }
.lp-footer-top { display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.lp-footer .lp-cap { color: rgba(246, 243, 234, 0.62); }
.lp-footer-top a:hover { color: var(--paper); }
.lp-footer-word { font-size: 32px; line-height: 1.25; font-weight: 500; letter-spacing: 0; margin: 48px 0 32px; }
.lp-footer-meta { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px 32px; }
.lp-footer-meta a { color: var(--paper); }
.lp-footer-meta a:hover { text-decoration: underline; text-underline-offset: 4px; }

/* ---------- 入场：默认可见，JS 就绪后才启用隐藏 ----------
   用 CSS animation 而不是 transition：animationstart 是每个区块真实的入场事件，
   也保证整屏跳滚时「从视口下方直接跨到上方」的区块不会卡在隐藏态。
   both 填充让 delay 期间保持起始态、结束后保持终态。 */
.reveal { opacity: 1; transform: none; }
html.lp-anim .reveal { opacity: 0; transform: translateY(32px); }
html.lp-anim .reveal.is-in {
  animation: lpReveal var(--dur-entrance) var(--ease) both;
  animation-delay: var(--d, 0ms);
}
@keyframes lpReveal {
  from { opacity: 0; transform: translateY(32px); }
  to { opacity: 1; transform: none; }
}
/* 分类型编排：标题遮罩揭开、卡片轻微放大、列表行横向错峰滑入 */
html.lp-anim .lp-sec-head.reveal.is-in { animation-name: lpUnveil; }
@keyframes lpUnveil {
  from { opacity: 0; clip-path: inset(0 0 100% 0); transform: translateY(12px); }
  to { opacity: 1; clip-path: inset(0 0 0 0); transform: none; }
}
html.lp-anim .lp-view.reveal.is-in,
html.lp-anim .lp-faq-card.reveal.is-in { animation-name: lpScaleIn; animation-duration: var(--dur-entrance); }
@keyframes lpScaleIn {
  from { opacity: 0; transform: scale(0.97); }
  to { opacity: 1; transform: none; }
}
html.lp-anim .lp-board-row.reveal.is-in,
html.lp-anim .lp-cap-item.reveal.is-in,
html.lp-anim .lp-method-col.reveal.is-in { animation-name: lpSlideIn; animation-duration: var(--dur-entrance); }
@keyframes lpSlideIn {
  from { opacity: 0; transform: translateX(-16px); }
  to { opacity: 1; transform: none; }
}
/* 倾斜的边界卡保留自己的旋转，不能被通用入场抹平 */
html.lp-anim .lp-scope-card.reveal.is-in { animation-name: lpTiltIn; }
@keyframes lpTiltIn {
  from { opacity: 0; transform: translateY(32px) rotate(-1deg); }
  to { opacity: 1; transform: rotate(-1deg); }
}

/* ---------- 无障碍：动效偏好 ---------- */
@media (prefers-reduced-motion: reduce) {
  .lp *, .lp *::before, .lp *::after { animation: none !important; transition: none !important; }
  .lp-mask-in { transform: none !important; }
  .lp-headline-rule, .lp-cap-rule { transform: scaleX(1) !important; }
  .reveal { opacity: 1 !important; transform: none !important; clip-path: none !important; }
  .lp-field-swap-enter-active, .lp-field-swap-leave-active,
  .lp-cap-swap-enter-active, .lp-cap-swap-leave-active { transition: none !important; }
}

/* ---------- 窄屏 ---------- */
@media (max-width: 1100px) {
  .lp { --frame: min(100% - 48px, 1280px); }
  .lp-headline { font-size: 40px; }
  .lp-sheet-body { grid-template-columns: minmax(0, 1fr); }
  .lp-margin { background: var(--paper); }
  .lp-method-cols { gap: 24px; }
  .lp-cap-layout { gap: 32px; }
  .lp-board-btn { grid-template-columns: minmax(90px, 1.2fr) minmax(80px, 0.8fr) minmax(90px, 1.2fr) 48px; }
  .lp-board-sent { display: none; }
  .lp-sheet-head { flex-direction: column; align-items: flex-start; }
  .lp-sheet-actions { flex-direction: column; align-items: flex-start; gap: 12px; }
}

@media (max-width: 760px) {
  .lp { --frame: calc(100% - 32px); }
  .lp-nav { height: 56px; }
  .lp-wordmark span { font-size: 14px; }
  .lp-nav-cta { display: none; }
  .lp-menu-toggle {
    display: flex; flex-direction: column; justify-content: center; gap: 6px;
    width: 40px; height: 40px; padding: 8px; border: 0; background: transparent; cursor: pointer;
  }
  .lp-menu-toggle span {
    display: block; width: 100%; height: 2px; background: var(--ink);
    transition: transform var(--dur-hover) var(--ease);
  }
  .lp-menu-toggle[aria-expanded='true'] span:first-child { transform: translateY(4px) rotate(45deg); }
  .lp-menu-toggle[aria-expanded='true'] span:last-child { transform: translateY(-4px) rotate(-45deg); }
  .lp-nav-links {
    position: fixed; inset: 0; z-index: 60; display: flex; flex-direction: column;
    align-items: flex-start; justify-content: center; gap: 24px; padding: 32px;
    background: var(--dark); color: var(--paper);
    visibility: hidden; opacity: 0; transform: translateY(-16px);
    transition: opacity var(--dur-color) var(--ease), transform var(--dur-press) var(--ease), visibility 0s linear var(--dur-move);
  }
  .lp-nav-links.is-open { visibility: visible; opacity: 1; transform: none; transition-delay: 0s; }
  .lp-nav-links a {
    font-size: 24px; line-height: 32px; color: var(--paper);
    opacity: 0; transform: translateY(24px);
    transition: opacity var(--dur-move) var(--ease), transform var(--dur-move) var(--ease), color var(--dur-color) var(--ease);
  }
  .lp-nav-links.is-open a {
    opacity: 1; transform: none;
    transition-delay: var(--stagger, 0ms);
  }
  .lp-nav-links.is-open a[aria-current='location'] { color: #ff9d94; }
  .lp-nav-mobile-cta { display: inline-flex !important; margin-top: 24px; color: #ff9d94 !important; }
  .lp-headline-wide { display: none; }
  .lp-headline-narrow { display: block; }
  .lp-headline { font-size: 32px; }
  .lp-h2 { font-size: var(--brand-scale-4); }
  .lp-hero { padding-top: 32px; }
  .lp-hero-row { flex-direction: column; align-items: flex-start; gap: 24px; }
  .lp-headline-rule { margin-top: 16px; }
  .lp-sheet-head { flex-direction: column; align-items: flex-start; padding: 24px; }
  .lp-sheet-actions { flex-direction: column; align-items: flex-start; gap: 12px; }
  .lp-original { padding: 16px; }
  .lp-margin { padding: 24px 16px; }
  .lp-sent { grid-template-columns: 20px minmax(0, 1fr); gap: 8px; font-size: 16px; }
  .lp-sent-count { display: none; }
  .lp-sent-marker { left: 16px; }
  .lp-section { padding: 64px 0; }
  /* 窄屏 cover 会把右侧朱红笔触推到文案后面，加一层纯色遮罩保住 4.5:1 */
  .lp-closesec::before {
    content: ''; position: absolute; inset: 0; z-index: 0;
    background: rgba(32, 30, 25, 0.72);
  }
  .lp-close-copy { max-width: none; }
  .lp-fields > div { grid-template-columns: 108px minmax(0, 1fr); }
  .lp-cap-layout { grid-template-columns: 1fr; gap: 24px; }
  .lp-cap-panel { position: static; min-height: 240px; padding: 24px; }
  .lp-cap-item { padding: 12px 8px; }
  .lp-cap-name { font-size: 24px; }
  .lp-board-btn { grid-template-columns: minmax(0, 1fr) minmax(0, 0.8fr) minmax(0, 1fr); gap: 8px; padding: 12px; font-size: 14px; }
  .lp-board-conf { display: none; }
  .lp-method-cols { grid-template-columns: 1fr; gap: 24px; }
  .lp-diagram { padding: 16px; }
  .lp-view-grid { grid-template-columns: 1fr; }
  .lp-scope-card { padding: 32px 24px; transform: rotate(-1deg); }
  .lp-scope-cols { grid-template-columns: 1fr; gap: 24px; }
  .lp-faq-card { padding: 16px; }
  .lp-faq-topic { display: none; }
  .lp-faq-q { gap: 8px; }
  .lp-faq-sign { font-size: 20px; }
  .lp-final-inner { min-height: 280px; }
  .lp-final-word { bottom: 16px; }
  .lp-final-arrow { width: 40px; height: 40px; }
  .lp-footer-word { margin: 64px 0 48px; }
  .lp-footer-meta { flex-direction: column; }
}
</style>
