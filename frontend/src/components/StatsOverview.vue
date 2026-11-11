<template>
  <div class="stats">
    <div class="metrics">
      <div v-for="c in cards" :key="c.label" class="metric">
        <span class="metric-label">{{ c.label }}</span>
        <span class="metric-value">
          {{ c.value }}<i v-if="c.unit">{{ c.unit }}</i>
        </span>
      </div>
    </div>

    <div class="grids">
      <section class="stat-card">
        <div class="stat-head">
          <span>实体类型分布</span>
          <span class="stat-sub">{{ result?.stats?.entity_count || 0 }} 个</span>
        </div>
        <div class="bars">
          <div v-for="e in entityBars" :key="e.key" class="bar-row">
            <span class="bar-name">{{ e.label }}</span>
            <div class="bar-track">
              <div class="bar-fill" :style="{ width: e.pct + '%', background: e.color }"></div>
            </div>
            <span class="bar-num">{{ e.count }}</span>
          </div>
        </div>
      </section>

      <section class="stat-card">
        <div class="stat-head">
          <span>关系类型分布</span>
          <span class="stat-sub">{{ result?.stats?.relation_count || 0 }} 条</span>
        </div>
        <div class="bars" v-if="relationBars.length">
          <div v-for="r in relationBars" :key="r.key" class="bar-row">
            <span class="bar-name">{{ r.label }}</span>
            <div class="bar-track">
              <div class="bar-fill" :style="{ width: r.pct + '%', background: r.color }"></div>
            </div>
            <span class="bar-num">{{ r.count }}</span>
          </div>
        </div>
        <el-empty v-else description="本文未抽出关系" :image-size="60" />
      </section>

      <section class="stat-card">
        <div class="stat-head">
          <span>全库累计</span>
          <span class="stat-sub">历史记录</span>
        </div>
        <div class="global-grid">
          <div class="global-item">
            <b>{{ global.records ?? 0 }}</b>
            <span>抽取次数</span>
          </div>
          <div class="global-item">
            <b>{{ global.entities ?? 0 }}</b>
            <span>累计实体</span>
          </div>
          <div class="global-item">
            <b>{{ global.relations ?? 0 }}</b>
            <span>累计三元组</span>
          </div>
          <div class="global-item">
            <b>{{ global.avg_ms ?? 0 }}<i>ms</i></b>
            <span>平均耗时</span>
          </div>
        </div>
        <div class="hot" v-if="(global.top_relations || []).length">
          <span class="hot-label">热点关系</span>
          <span v-for="r in global.top_relations.slice(0, 6)" :key="r.relation" class="hot-tag">
            {{ r.relation_label }}<b>{{ r.cnt }}</b>
          </span>
        </div>
      </section>

      <section class="stat-card sentence-card">
        <div class="stat-head">
          <span>句子明细</span>
          <span class="stat-sub">{{ result?.sentences?.length || 0 }} 句 · 点任一句定位原文</span>
        </div>
        <el-scrollbar class="sentences">
          <button
            v-for="s in result?.sentences || []"
            :key="s.index"
            class="sentence-row"
            :class="{ 'has-rel': countBySentence(s.index) }"
            type="button"
            :aria-label="`第 ${s.index + 1} 句，${countBySentence(s.index)} 条关系，点击定位原文`"
            @click="emit('locate', s.index)"
          >
            <span class="sentence-idx">{{ s.index + 1 }}</span>
            <span class="sentence-text">{{ s.text }}</span>
            <span class="sentence-rel" v-if="countBySentence(s.index)">
              {{ countBySentence(s.index) }} 条
            </span>
          </button>
          <el-empty v-if="!(result?.sentences || []).length" description="没有分句结果" :image-size="60" />
        </el-scrollbar>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  result: { type: Object, default: null },
  stats: { type: Object, default: () => ({}) },
  schema: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['locate'])

const global = computed(() => props.stats || {})

const relMap = computed(() => {
  const map = {}
  for (const r of props.schema.relation_types || []) map[r.key] = r
  return map
})

const cards = computed(() => {
  const s = props.result?.stats || {}
  return [
    { label: '字符数', value: s.char_count ?? 0 },
    { label: '句子数', value: s.sentence_count ?? 0 },
    { label: '实体数', value: s.entity_count ?? 0 },
    { label: '三元组', value: s.relation_count ?? 0 },
    { label: '耗时', value: s.elapsed_ms ?? 0, unit: 'ms' },
  ]
})

const entityBars = computed(() => {
  const counts = props.result?.entity_type_counts || {}
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1
  return (props.schema.entity_types || [])
    .map((t) => ({
      key: t.key,
      label: t.label,
      color: t.color,
      count: counts[t.key] || 0,
      pct: Math.round(((counts[t.key] || 0) / total) * 100),
    }))
    .filter((x) => x.count > 0)
    .sort((a, b) => b.count - a.count)
})

const relationBars = computed(() => {
  const counts = props.result?.relation_type_counts || {}
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1
  return Object.entries(counts)
    .map(([key, count]) => ({
      key,
      label: relMap.value[key]?.label || key,
      color: relMap.value[key]?.color || '#6366f1',
      count,
      pct: Math.max(5, Math.round((count / total) * 100)),
    }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 8)
})

const sentenceCounter = computed(() => {
  const map = {}
  for (const r of props.result?.relations || []) {
    map[r.sentence_index] = (map[r.sentence_index] || 0) + 1
  }
  return map
})

function countBySentence(idx) {
  return sentenceCounter.value[idx] || 0
}
</script>

<style scoped>
.stats {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
  overflow: auto;
}

/* ---------- 指标条：一格一指标，共享边框 ---------- */
.metrics {
  flex: none;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
  overflow: hidden;
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 11px 14px;
  border-right: 1px solid var(--line);
}

.metric:last-child {
  border-right: none;
}

.metric-label {
  font-size: 11px;
  color: var(--muted);
  letter-spacing: 0.2px;
}

.metric-value {
  font-size: 20px;
  font-weight: 600;
  line-height: 1.15;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.2px;
}

.metric-value i {
  margin-left: 2px;
  font-style: normal;
  font-size: 11px;
  font-weight: 400;
  color: var(--muted);
}

/* ---------- 分布式卡片 ---------- */
.grids {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(272px, 1fr));
  gap: 12px;
  /* 同排卡片等高，避免底边参差 */
  align-items: stretch;
}

.stat-card {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
  padding: 12px 14px 14px;
}

.sentence-card {
  grid-column: 1 / -1;
}

.stat-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 11px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
}

.stat-sub {
  font-size: 11px;
  font-weight: 400;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

/* ---------- 条形 ---------- */
.bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bar-row {
  display: grid;
  grid-template-columns: 58px 1fr 26px;
  align-items: center;
  gap: 9px;
}

.bar-name {
  font-size: 11.5px;
  color: var(--ink-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bar-track {
  height: 5px;
  border-radius: 999px;
  background: var(--surface-3);
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 999px;
  transition: width var(--dur-move) var(--ease);
}

.bar-num {
  font-size: 11.5px;
  color: var(--ink-2);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

/* ---------- 全库累计 ---------- */
.global-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  background: var(--line);
  border-radius: var(--r-sm);
  overflow: hidden;
}

.global-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 9px 11px;
  background: var(--surface);
}

.global-item b {
  font-size: 16px;
  font-weight: 600;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.global-item b i {
  margin-left: 1px;
  font-style: normal;
  font-size: 10.5px;
  font-weight: 400;
  color: var(--muted);
}

.global-item span {
  font-size: 11px;
  color: var(--muted);
}

.hot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  margin-top: 11px;
}

.hot-label {
  font-size: 11px;
  color: var(--muted);
  margin-right: 2px;
}

.hot-tag {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  padding: 1px 7px;
  border-radius: var(--r-xs);
  font-size: 11px;
  color: var(--ink-2);
  background: var(--surface-3);
}

.hot-tag b {
  font-weight: 600;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

/* ---------- 句子明细 ---------- */
.sentences {
  max-height: 220px;
}

.sentence-row {
  width: 100%;
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 6px 4px;
  border: none;
  border-bottom: 1px solid var(--line);
  border-radius: var(--r-xs);
  background: transparent;
  font-family: inherit;
  font-size: 12px;
  line-height: 1.75;
  color: var(--ink-2);
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-press) var(--ease), color var(--dur-press) var(--ease);
}

.sentence-row:hover {
  background: var(--surface-3);
  color: var(--ink);
}

.sentence-row:last-child {
  border-bottom: none;
}

.sentence-idx {
  flex: none;
  width: 17px;
  height: 17px;
  border-radius: var(--r-xs);
  background: var(--surface-3);
  color: var(--muted);
  font-size: 10px;
  font-weight: 500;
  display: grid;
  place-items: center;
  font-variant-numeric: tabular-nums;
}

.sentence-text {
  flex: 1;
  min-width: 0;
}

.sentence-rel {
  flex: none;
  padding: 0 5px;
  font-size: 10.5px;
  line-height: 16px;
  color: #8f2a23;
  background: #f7e9e7;
  border-radius: var(--r-xs);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 900px) {
  .metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .metric:nth-child(3n) {
    border-right: none;
  }
  .metric:nth-child(-n + 3) {
    border-bottom: 1px solid var(--line);
  }
}
</style>
