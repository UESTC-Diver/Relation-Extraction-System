<template>
  <div class="ds">
    <a class="ds-skip" href="#ds-main">跳到主要内容</a>

    <header class="ds-nav">
      <a class="ds-wordmark" href="/" aria-label="文本关系抽取与信息甄别系统，返回首页">
        <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
          <rect x="3" y="5" width="22" height="24" rx="1.5" fill="#fffdf6" />
          <path d="M7 12h14M7 17h10M7 22h14" stroke="#1e1c18" stroke-width="1.4" stroke-linecap="round" opacity=".55" />
          <path d="M9 24.5 24 24.5" stroke="#a8322a" stroke-width="2" stroke-linecap="round" />
          <circle cx="24" cy="24.5" r="3.2" fill="#a8322a" />
        </svg>
        <span>文本关系抽取与信息甄别系统</span>
      </a>
      <nav class="ds-nav-links" aria-label="页面导航">
        <a href="/">首页</a>
        <a href="/app">进入工作台</a>
      </nav>
      <span class="ds-badge">零后端 · 断网可用</span>
    </header>

    <main id="ds-main" class="ds-main">
      <section class="ds-intro">
        <p class="ds-eyebrow">静态试用沙箱</p>
        <h1>先看结果长什么样，再决定要不要跑自己的文本。</h1>
        <p class="ds-lede">
          下面四篇的结果全部由本机抽取引擎真实运行后导出。这个页面不调用任何接口、不上传任何文字：
          切换样例、点句子、看命中路径、导出，都在浏览器里完成。
        </p>
        <div class="ds-boundary" role="note">
          <b>边界</b>
          <span>这里只能看预置样例，不能输入自己的文本。要抽自己的材料，请<a href="/app">进入工作台</a>在本机运行。</span>
        </div>
      </section>

      <section class="ds-samples" aria-label="选择样例">
        <button
          v-for="s in samples"
          :key="s.id"
          class="ds-sample"
          :class="{ 'is-active': activeId === s.id }"
          type="button"
          :aria-pressed="activeId === s.id ? 'true' : 'false'"
          @click="pick(s.id)"
        >
          <span class="ds-sample-domain">{{ s.domain }} · {{ profileLabel(s.profile) }}</span>
          <b class="ds-sample-title">{{ s.title }}</b>
          <span class="ds-sample-meta">
            {{ s.stats.sentence_count }} 句 · {{ s.stats.entity_count }} 实体 · {{ s.stats.relation_count }} 关系
          </span>
          <span class="ds-sample-hint">{{ s.hint }}</span>
        </button>
      </section>

      <section class="ds-sheet" aria-label="样例抽取结果">
        <div class="ds-sheet-head">
          <div class="ds-sheet-title">
            <h2>{{ current.title }}</h2>
            <p>{{ current.hint }}</p>
          </div>
          <div class="ds-export">
            <button type="button" @click="exportJson">导出 JSON</button>
            <button type="button" @click="exportCsv">导出 CSV</button>
          </div>
        </div>

        <dl class="ds-stats">
          <div><dt>字数</dt><dd>{{ current.stats.char_count }}</dd></div>
          <div><dt>句子</dt><dd>{{ current.stats.sentence_count }}</dd></div>
          <div><dt>实体</dt><dd>{{ current.stats.entity_count }}</dd></div>
          <div><dt>去重实体</dt><dd>{{ current.stats.unique_entity_count }}</dd></div>
          <div><dt>关系</dt><dd>{{ current.stats.relation_count }}</dd></div>
        </dl>

        <div class="ds-columns">
          <div class="ds-source">
            <h3 class="ds-block-title">原文 <span>点句子看这一句抽出了什么</span></h3>
            <div class="ds-sentences">
              <button
                v-for="sent in current.sentences"
                :key="sent.index"
                class="ds-sent"
                :class="{ 'is-active': activeSentence === sent.index }"
                type="button"
                :aria-pressed="activeSentence === sent.index ? 'true' : 'false'"
                :aria-label="`第 ${sent.index + 1} 句，抽出 ${relsFor(sent.index).length} 条关系`"
                @click="activeSentence = sent.index"
              >
                <span class="ds-sent-no">{{ sent.index + 1 }}</span>
                <span class="ds-sent-text">
                  <template v-for="(frag, fi) in fragmentsFor(sent)" :key="fi">
                    <mark v-if="frag.type === 'ent'" class="ds-ent" :title="`${frag.label}：${frag.text}`">{{ frag.text }}</mark>
                    <template v-else>{{ frag.text }}</template>
                  </template>
                </span>
                <span v-if="relsFor(sent.index).length" class="ds-sent-count">{{ relsFor(sent.index).length }} 条</span>
              </button>
            </div>

            <h3 class="ds-block-title ds-entity-head">识别到的实体 <span>{{ current.entities.length }} 处</span></h3>
            <div class="ds-entity-list">
              <span
                v-for="(e, i) in current.entities"
                :key="i"
                class="ds-entity"
                :style="{ background: e.color + '18', borderColor: e.color + '44' }"
                :title="`${e.type_label} · 第 ${e.sentence_index + 1} 句`"
              >
                {{ e.text }}<i>{{ e.type_label }}</i>
              </span>
            </div>
          </div>

          <aside class="ds-result" aria-live="polite">
            <h3 class="ds-block-title">
              第 {{ activeSentence + 1 }} 句 · 抽出 {{ relsFor(activeSentence).length }} 条关系
            </h3>
            <p v-if="!relsFor(activeSentence).length" class="ds-empty">这句没有匹配到关系模板。</p>

            <article v-for="(rel, ri) in relsFor(activeSentence)" :key="ri" class="ds-rel">
              <p class="ds-triple">
                <b>{{ rel.head }}</b>
                <span class="ds-rel-pill" :style="pillStyle(rel)">{{ rel.relation_label }}</span>
                <b>{{ rel.tail }}</b>
              </p>
              <p class="ds-evidence">{{ rel.evidence }}</p>
              <dl class="ds-fields">
                <div><dt>置信度</dt><dd>{{ rel.confidence.toFixed(2) }}</dd></div>
                <div><dt>触发词</dt><dd>{{ rel.trigger || '—' }}</dd></div>
                <div><dt>策略</dt><dd>{{ rel.explanation?.strategy || '—' }}</dd></div>
                <div><dt>所在句</dt><dd>第 {{ (rel.sentence_index ?? 0) + 1 }} 句</dd></div>
              </dl>

              <details v-if="rel.explanation" class="ds-why">
                <summary>为什么抽出来</summary>
                <p class="ds-why-how">{{ rel.explanation.strategy_how }}</p>
                <dl class="ds-why-grid">
                  <div><dt>命中词</dt><dd>{{ rel.explanation.matched }}</dd></div>
                  <div v-if="rel.explanation.template"><dt>模板骨架</dt><dd><code>{{ rel.explanation.template }}</code></dd></div>
                  <div><dt>类型约束</dt><dd>{{ rel.explanation.type_constraint }}</dd></div>
                  <div><dt>置信度构成</dt><dd><code>{{ rel.explanation.confidence_parts?.formula || '—' }}</code></dd></div>
                </dl>
                <p v-if="rel.explanation.rule_description" class="ds-why-rule">{{ rel.explanation.rule_description }}</p>
              </details>
            </article>

            <div class="ds-distribution">
              <h3 class="ds-block-title">这篇的关系分布 <span>{{ distribution.length }} 类</span></h3>
              <div v-for="d in distribution" :key="d.label" class="ds-dist-row">
                <span class="ds-dist-label">{{ d.label }}</span>
                <span class="ds-dist-track" aria-hidden="true">
                  <i :style="{ width: barWidth(d.count), background: d.color || 'var(--brand-red)' }"></i>
                </span>
                <b>{{ d.count }}</b>
              </div>
            </div>
          </aside>
        </div>
      </section>

      <section class="ds-bottom">
        <p>样例看完，下一步是在本机跑你自己的文本。</p>
        <a class="ds-cta" href="/app">
          进入工作台
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M4 12h15M13 6l6 6-6 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </a>
      </section>
    </main>

    <footer class="ds-footer">
      <a href="/">← 返回首页</a>
      <span>样例结果由本机抽取引擎真实运行导出，未经人工改写。</span>
    </footer>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import demoData from '../data/demo-samples.json'

/*
 * 静态试用沙箱：整页不 import api/client，不 import element-plus。
 * 数据来自 pipeline.analyze() 的真实输出（见 demo-samples.json 的 note），
 * 因此断网、后端未启动、静态托管在 CDN 上都能完整工作。
 */
const samples = demoData.samples
const activeId = ref(samples[0].id)
const activeSentence = ref(0)

const PROFILE_LABEL = { general: '通用包', finance: '财经包', legal: '法律包' }
const profileLabel = (key) => PROFILE_LABEL[key] || key

const current = computed(() => samples.find((s) => s.id === activeId.value) || samples[0])

function pick(id) {
  activeId.value = id
  activeSentence.value = 0
}

function relsFor(index) {
  return current.value.relations.filter((r) => r.sentence_index === index)
}

/** 实体的 start/end 是全篇字符偏移；按句子区间切片段，用 <mark> 做红笔标注。 */
function fragmentsFor(sent) {
  const text = current.value.text
  const entities = current.value.entities
    .filter((e) => e.start >= sent.start && e.end <= sent.end)
    .sort((a, b) => a.start - b.start || b.end - a.end)
  const out = []
  let cursor = sent.start
  for (const e of entities) {
    if (e.start < cursor) continue
    if (e.start > cursor) out.push({ type: 'text', text: text.slice(cursor, e.start) })
    out.push({ type: 'ent', text: text.slice(e.start, e.end), label: e.type_label })
    cursor = e.end
  }
  if (cursor < sent.end) out.push({ type: 'text', text: text.slice(cursor, sent.end) })
  return out
}

const distribution = computed(() => {
  const map = new Map()
  for (const r of current.value.relations) {
    const item = map.get(r.relation_label) || {
      label: r.relation_label,
      color: r.relation_color,
      count: 0,
    }
    item.count += 1
    map.set(r.relation_label, item)
  }
  return [...map.values()].sort((a, b) => b.count - a.count)
})

const maxDist = computed(() => Math.max(1, ...distribution.value.map((d) => d.count)))
const barWidth = (count) => `${Math.max(6, Math.round((count / maxDist.value) * 100))}%`

function pillStyle(rel) {
  const color = rel.relation_color || 'var(--brand-red)'
  return { color, background: color + '12', borderColor: color + '33' }
}

function download(filename, content, mime) {
  const url = URL.createObjectURL(new Blob([content], { type: mime }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function exportJson() {
  download(
    `${current.value.id}.json`,
    JSON.stringify(current.value, null, 2),
    'application/json;charset=utf-8',
  )
}

function exportCsv() {
  const header = ['头实体', '头实体类型', '关系', '关系类型', '尾实体', '尾实体类型', '置信度', '触发词', '策略', '证据句']
  const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const lines = current.value.relations.map((r) => [
    r.head, r.head_type, r.relation_label, r.relation,
    r.tail, r.tail_type, r.confidence.toFixed(2), r.trigger || '',
    r.explanation?.strategy || '', r.evidence || '',
  ])
  const csv = [header, ...lines].map((row) => row.map(esc).join(',')).join('\r\n')
  download(`${current.value.id}-relations.csv`, '\ufeff' + csv, 'text/csv;charset=utf-8')
}
</script>

<style scoped>
.ds {
  min-height: 100vh;
  background: var(--brand-paper);
  color: var(--brand-ink);
  font-family: var(--font-sans);
}

.ds-skip {
  position: absolute;
  left: -9999px;
  top: 0;
  z-index: 20;
  padding: 10px 16px;
  background: var(--brand-dark);
  color: #fff;
}
.ds-skip:focus { left: 12px; top: 12px; }

/* ---------- 导航：与首页同一行结构，不做第二套视觉 ---------- */
.ds-nav {
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 14px clamp(16px, 4vw, 56px);
  border-bottom: 1px solid var(--brand-paper-2);
  background: var(--brand-paper);
}
.ds-wordmark {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--brand-ink);
  text-decoration: none;
  font-size: 15px;
  font-weight: 600;
  white-space: nowrap;
}
.ds-wordmark svg { width: 28px; height: 28px; flex: none; }
.ds-nav-links { display: flex; gap: 24px; margin-left: auto; }
.ds-nav-links a {
  font-size: 14px;
  color: var(--brand-ink-2);
  text-decoration: none;
  transition: color var(--dur-color) var(--ease);
}
.ds-nav-links a:hover { color: var(--brand-red); text-decoration: underline; text-underline-offset: 4px; }
.ds-badge {
  flex: none;
  padding: 4px 10px;
  border-radius: var(--r-pill);
  font-size: 11px;
  color: var(--brand-red);
  background: var(--brand-red-soft);
  white-space: nowrap;
}

.ds-main { max-width: 1240px; margin: 0 auto; padding: 0 clamp(16px, 4vw, 56px) 64px; }

/* ---------- 开场 ---------- */
.ds-intro { padding: clamp(40px, 6vw, 72px) 0 36px; max-width: 820px; }
.ds-eyebrow {
  margin: 0 0 14px;
  font-size: 12px;
  letter-spacing: 2px;
  color: var(--brand-red);
}
.ds-intro h1 {
  margin: 0;
  font-size: clamp(28px, 4vw, 44px);
  line-height: 1.25;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.ds-lede {
  margin: 18px 0 0;
  max-width: 42em;
  font-size: 16px;
  line-height: 28px;
  color: var(--brand-ink-2);
}
.ds-boundary {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 22px;
  padding: 12px 16px;
  border-left: 2px solid var(--brand-red);
  background: var(--brand-surface);
  border-radius: 0 var(--r) var(--r) 0;
  font-size: 13px;
  line-height: 22px;
  color: var(--brand-ink-2);
}
.ds-boundary b { flex: none; color: var(--brand-red); }
.ds-boundary a { color: var(--brand-red); font-weight: 600; text-underline-offset: 3px; }

/* ---------- 样例卡 ---------- */
.ds-samples {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
}
.ds-sample {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 16px;
  min-height: 132px;
  text-align: left;
  font-family: inherit;
  color: var(--brand-ink);
  background: var(--brand-surface);
  border: 1px solid var(--brand-paper-2);
  border-radius: var(--r);
  cursor: pointer;
  transition: transform var(--dur-move) var(--ease), border-color var(--dur-color) var(--ease), background var(--dur-color) var(--ease);
}
.ds-sample:hover { transform: translateY(-2px); border-color: var(--brand-paper-3); }
.ds-sample.is-active { border-color: var(--brand-red); background: var(--brand-surface); box-shadow: inset 0 3px 0 var(--brand-red); }
.ds-sample-domain { font-size: 11px; letter-spacing: 0.4px; color: var(--brand-red); }
.ds-sample-title { font-size: 15px; font-weight: 600; line-height: 1.5; }
.ds-sample-meta { font-size: 11.5px; color: var(--brand-muted); font-variant-numeric: tabular-nums; }
.ds-sample-hint { margin-top: auto; font-size: 11.5px; line-height: 1.6; color: var(--brand-muted); }

/* ---------- 结果纸面 ---------- */
.ds-sheet {
  background: var(--brand-surface);
  border: 1px solid var(--brand-paper-2);
  border-radius: var(--r);
  overflow: hidden;
}
.ds-sheet-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 20px 24px;
  border-bottom: 1px solid var(--brand-paper-2);
}
.ds-sheet-title h2 { margin: 0; font-size: 20px; font-weight: 600; line-height: 1.4; }
.ds-sheet-title p { margin: 6px 0 0; font-size: 12.5px; color: var(--brand-muted); }
.ds-export { display: flex; gap: 8px; }
.ds-export button {
  padding: 7px 12px;
  font-family: inherit;
  font-size: 12px;
  color: var(--brand-ink-2);
  background: var(--tone-1);
  border: 1px solid var(--brand-paper-3);
  border-radius: var(--r);
  cursor: pointer;
  transition: background var(--dur-press) var(--ease), color var(--dur-press) var(--ease);
}
.ds-export button:hover { background: var(--brand-red-soft); color: var(--brand-red); }

.ds-stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 1px;
  margin: 0;
  background: var(--brand-paper-2);
  border-bottom: 1px solid var(--brand-paper-2);
}
.ds-stats > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 16px;
  background: var(--tone-1);
}
.ds-stats dt { font-size: 11px; color: var(--brand-muted); }
.ds-stats dd { margin: 0; font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; }

.ds-columns { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr); }
.ds-source { padding: 20px 24px 24px; border-right: 1px solid var(--brand-paper-2); min-width: 0; }
.ds-result { padding: 20px 24px 24px; background: var(--tone-1); min-width: 0; }

.ds-block-title {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 10px;
  margin: 0 0 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-ink);
}
.ds-block-title span { font-size: 11px; font-weight: 400; color: var(--brand-muted); }

/* 原文：句子是按钮，选中态用朱红边注，不用描边盒 */
.ds-sentences { display: flex; flex-direction: column; gap: 2px; }
.ds-sent {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  padding: 10px 10px 10px 8px;
  text-align: left;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.95;
  color: var(--brand-ink-2);
  background: transparent;
  border: 0;
  border-left: 2px solid transparent;
  border-radius: 0 var(--r) var(--r) 0;
  cursor: pointer;
  transition: background var(--dur-color) var(--ease), border-color var(--dur-color) var(--ease);
}
.ds-sent:hover { background: var(--tone-2); }
.ds-sent.is-active { background: var(--tone-2); border-left-color: var(--brand-red); }
.ds-sent-no { flex: none; width: 18px; padding-top: 3px; font-size: 11px; color: var(--brand-muted); font-variant-numeric: tabular-nums; }
.ds-sent-text { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.ds-sent-count { flex: none; margin-top: 4px; font-size: 10.5px; color: var(--brand-red); white-space: nowrap; }
.ds-ent { padding: 0 2px; color: var(--brand-ink); background: var(--brand-red-soft); border-radius: 2px; font-weight: 500; }

.ds-entity-head { margin-top: 24px; }
.ds-entity-list { display: flex; flex-wrap: wrap; gap: 6px; }
.ds-entity {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  padding: 3px 8px;
  border: 1px solid transparent;
  border-radius: var(--r);
  font-size: 11.5px;
  color: var(--brand-ink);
}
.ds-entity i { font-style: normal; font-size: 10px; color: var(--brand-muted); }

/* 右侧：一句抽出的关系 */
.ds-empty { padding: 24px 8px; text-align: center; font-size: 13px; color: var(--brand-muted); }
.ds-rel {
  padding: 14px 16px;
  margin-bottom: 10px;
  background: var(--brand-surface);
  border: 1px solid var(--brand-paper-2);
  border-radius: var(--r);
  animation: ds-in var(--dur-move) var(--ease) both;
}
.ds-triple { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 0; font-size: 14px; }
.ds-triple b { font-weight: 600; color: var(--brand-ink); overflow-wrap: anywhere; }
.ds-rel-pill { padding: 1px 8px; border: 1px solid transparent; border-radius: var(--r); font-size: 11.5px; font-weight: 500; }
.ds-evidence {
  margin: 10px 0 0;
  padding-left: 10px;
  border-left: 2px solid var(--brand-paper-3);
  font-size: 12px;
  line-height: 1.8;
  color: var(--brand-ink-2);
  overflow-wrap: anywhere;
}
.ds-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 5px 12px; margin: 10px 0 0; }
.ds-fields > div { display: flex; align-items: baseline; gap: 6px; min-width: 0; }
.ds-fields dt { flex: none; font-size: 10.5px; color: var(--brand-muted); }
.ds-fields dd { margin: 0; min-width: 0; font-size: 11.5px; color: var(--brand-ink-2); overflow-wrap: anywhere; }

.ds-why { margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--brand-paper-2); }
.ds-why summary { font-size: 12px; font-weight: 600; color: var(--brand-red); cursor: pointer; list-style: none; }
.ds-why summary::-webkit-details-marker { display: none; }
.ds-why summary::before { content: '＋ '; }
.ds-why[open] summary::before { content: '－ '; }
.ds-why summary:focus-visible { outline: 2px solid var(--brand-red); outline-offset: 3px; }
.ds-why-how { margin: 8px 0 0; font-size: 11.5px; line-height: 1.7; color: var(--brand-ink-2); }
.ds-why-grid { display: grid; gap: 5px; margin: 10px 0 0; }
.ds-why-grid > div { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.ds-why-grid dt { flex: 0 0 72px; font-size: 10.5px; color: var(--brand-muted); }
.ds-why-grid dd { margin: 0; min-width: 0; font-size: 11.5px; color: var(--brand-ink-2); overflow-wrap: anywhere; }
.ds-why-grid code, .ds-why-rule { font-family: var(--font-sans); }
.ds-why-grid code { padding: 1px 5px; font-size: 11px; background: var(--tone-2); border-radius: var(--r); }
.ds-why-rule { margin: 8px 0 0; font-size: 11px; color: var(--brand-muted); }

.ds-distribution { margin-top: 24px; }
.ds-dist-row { display: flex; align-items: center; gap: 10px; margin-bottom: 7px; font-size: 11.5px; }
.ds-dist-label { flex: 0 0 72px; color: var(--brand-ink-2); }
.ds-dist-track { flex: 1; height: 6px; min-width: 20px; border-radius: var(--r-pill); background: var(--tone-3); overflow: hidden; }
.ds-dist-track i { display: block; height: 100%; border-radius: var(--r-pill); }
.ds-dist-row b { flex: none; width: 22px; text-align: right; font-weight: 500; color: var(--brand-muted); font-variant-numeric: tabular-nums; }

/* ---------- 收束 ---------- */
.ds-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 20px;
  margin-top: 40px;
  padding: 28px 32px;
  background: var(--brand-dark);
  color: #fffdf6;
  border-radius: var(--r);
}
.ds-bottom p { margin: 0; font-size: 18px; font-weight: 500; }
.ds-cta {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  background: var(--brand-red);
  color: #fff;
  text-decoration: none;
  font-size: 14px;
  font-weight: 600;
  border-radius: var(--r);
  transition: transform var(--dur-press) var(--ease), background var(--dur-color) var(--ease);
}
.ds-cta svg { width: 18px; height: 18px; }
.ds-cta:hover { background: #c03b31; transform: translateY(-1px); }

.ds-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 20px clamp(16px, 4vw, 56px) 32px;
  border-top: 1px solid var(--brand-paper-2);
  font-size: 11.5px;
  color: var(--brand-muted);
}
.ds-footer a { color: var(--brand-ink-2); text-decoration: none; }
.ds-footer a:hover { color: var(--brand-red); text-decoration: underline; text-underline-offset: 3px; }

@keyframes ds-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 960px) {
  .ds-columns { grid-template-columns: 1fr; }
  .ds-source { border-right: 0; border-bottom: 1px solid var(--brand-paper-2); }
}

@media (max-width: 720px) {
  .ds-nav { gap: 12px; flex-wrap: wrap; }
  .ds-nav-links { order: 3; width: 100%; margin-left: 0; }
  .ds-badge { margin-left: auto; }
  .ds-samples { grid-template-columns: 1fr; }
  .ds-sample { min-height: 0; }
  .ds-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .ds-sheet-head, .ds-source, .ds-result { padding: 16px; }
  .ds-fields { grid-template-columns: 1fr; }
  .ds-bottom { padding: 22px 18px; }
  .ds-bottom p { font-size: 16px; }
  .ds-sent { min-height: 44px; }
}

@media (prefers-reduced-motion: reduce) {
  .ds-rel { animation: none; }
  .ds-sample, .ds-cta { transition: none; }
  .ds-sample:hover, .ds-cta:hover { transform: none; }
}
</style>
