<script setup>
/**
 * 抽取过程演绎：把一次已完成的抽取拆成「原文 → 实体 → 关系 → 回到原文」四步，
 * 让用户看见结果是怎么一步步得出来的——这是项目「每条关系都能回到原文」主张的
 * 动态表达，不是装饰动画。数据全部来自当次 result，不编造。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  result: { type: Object, default: null },
  schema: { type: Object, default: () => ({}) },
})

const STAGES = [
  { key: 'source', label: '原文', hint: '先分句' },
  { key: 'entities', label: '实体', hint: '识别六类实体' },
  { key: 'relations', label: '关系', hint: '触发词 + 句式模板' },
  { key: 'evidence', label: '回到原文', hint: '每条三元组附证据句' },
]

const activeStage = ref(-1)
const playing = ref(false)
const reduced = ref(false)
let timer = null
let seq = 0

const entityTypes = computed(() => {
  const map = {}
  for (const t of props.schema?.entity_types || []) map[t.key] = t.label || t.key
  return map
})
const relationTypes = computed(() => {
  const map = {}
  for (const t of props.schema?.relation_types || []) map[t.key] = t.label || t.key
  return map
})
const firstSentence = computed(() => props.result?.sentences?.[0]?.text || props.result?.text || '')
const topEntities = computed(() => (props.result?.entities || []).slice(0, 6))
const topRelations = computed(() => (props.result?.relations || []).slice(0, 4))
const firstRelation = computed(() => props.result?.relations?.[0] || null)
const evidenceSentence = computed(() => {
  const rel = firstRelation.value
  if (!rel) return ''
  const s = props.result?.sentences?.[rel.sentence_index]
  return s?.text || rel.evidence || ''
})

function stop() {
  if (timer) clearTimeout(timer)
  timer = null
  playing.value = false
}

function play() {
  stop()
  const token = ++seq
  if (reduced.value) {
    activeStage.value = STAGES.length - 1
    return
  }
  playing.value = true
  activeStage.value = 0
  const step = () => {
    if (token !== seq) return
    if (activeStage.value >= STAGES.length - 1) {
      playing.value = false
      timer = null
      return
    }
    // 220ms 一步，错开 60ms 由 CSS 延迟承担，总时长受控
    timer = setTimeout(() => {
      if (token !== seq) return
      activeStage.value += 1
      step()
    }, 220)
  }
  step()
}

watch(
  () => props.result,
  () => {
    stop()
    activeStage.value = -1
  },
)

onMounted(() => {
  reduced.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches
})

onBeforeUnmount(() => {
  seq += 1
  stop()
})
</script>

<template>
  <div v-if="result" class="replay-strip" :class="{ 'is-playing': playing }">
    <div class="replay-head">
      <div class="replay-title">
        <span class="replay-label">抽取过程</span>
        <small>看这 {{ result.stats?.relation_count || 0 }} 条关系是怎么从原文来的</small>
      </div>
      <button
        class="replay-play"
        type="button"
        :disabled="playing"
        :aria-label="playing ? '正在播放抽取过程' : '播放抽取过程'"
        @click="play"
      >
        {{ playing ? '播放中…' : activeStage >= 0 ? '重新播放' : '播放过程' }}
      </button>
    </div>

    <div class="replay-steps" role="group" aria-label="抽取的四个阶段">
      <button
        v-for="(s, i) in STAGES"
        :key="s.key"
        class="replay-step"
        :class="{ 'is-active': activeStage === i, 'is-done': activeStage > i }"
        type="button"
        :aria-current="activeStage === i ? 'step' : undefined"
        :title="s.hint"
        @click="stop(); activeStage = i"
      >
        <span class="replay-step-no">{{ i + 1 }}</span>
        <span>{{ s.label }}</span>
      </button>
    </div>

    <p class="replay-sr" aria-live="polite">
      {{ activeStage >= 0 ? `第 ${activeStage + 1} 步：${STAGES[activeStage].label}。${STAGES[activeStage].hint}` : '' }}
    </p>

    <Transition name="replay-fade" mode="out-in">
      <div v-if="activeStage >= 0" :key="activeStage" class="replay-detail">
        <!-- 1. 原文：这一句先被读进来 -->
        <div v-if="activeStage === 0" class="replay-source">
          <span class="replay-detail-cap">第 1 句 · 原文</span>
          <p>{{ firstSentence }}</p>
        </div>

        <!-- 2. 实体：按出现顺序列出，类型标注来自 schema -->
        <div v-else-if="activeStage === 1" class="replay-entities">
          <span class="replay-detail-cap">识别到 {{ result.stats?.entity_count || 0 }} 个实体，先看前 {{ topEntities.length }} 个</span>
          <div class="replay-chips">
            <span
              v-for="(ent, i) in topEntities"
              :key="i"
              class="replay-chip"
              :style="{ '--i': Math.min(i, 3) }"
            >
              <b>{{ ent.text }}</b>
              <small>{{ ent.type_label || entityTypes[ent.type] || ent.type }}</small>
            </span>
            <span v-if="!topEntities.length" class="replay-empty">这一段没有命中实体词典</span>
          </div>
        </div>

        <!-- 3. 关系：触发词锚定句式，输出三元组 -->
        <div v-else-if="activeStage === 2" class="replay-triples">
          <span class="replay-detail-cap">触发词命中 {{ result.stats?.relation_count || 0 }} 条关系，先看前 {{ topRelations.length }} 条</span>
          <ul class="replay-triple-list">
            <li
              v-for="(rel, i) in topRelations"
              :key="i"
              :style="{ '--i': Math.min(i, 3) }"
            >
              <b>{{ rel.head }}</b>
              <span class="replay-arrow">{{ rel.relation_label || relationTypes[rel.relation] || rel.relation }} →</span>
              <b>{{ rel.tail }}</b>
            </li>
            <li v-if="!topRelations.length" class="replay-empty">这一段没有命中关系模板</li>
          </ul>
        </div>

        <!-- 4. 回到原文：把第一条关系指回证据句 -->
        <div v-else class="replay-evidence">
          <span class="replay-detail-cap">第一条关系的证据句 · 第 {{ (firstRelation?.sentence_index ?? 0) + 1 }} 句</span>
          <p>{{ evidenceSentence }}</p>
          <small v-if="firstRelation">
            触发词「{{ firstRelation.trigger }}」 ·
            {{ firstRelation.relation_label || relationTypes[firstRelation.relation] || firstRelation.relation }}
          </small>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.replay-strip {
  margin: 0 var(--sp-5) var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  background: var(--tone-1);
  border-radius: var(--r);
}
.replay-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
}
.replay-title {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.replay-label {
  font-weight: 600;
  color: var(--ink);
}
.replay-title small {
  color: var(--muted);
  font-size: var(--text-caption);
}
.replay-play {
  flex: none;
  border: 0;
  background: var(--brand-dark);
  color: var(--brand-paper);
  border-radius: var(--r);
  padding: var(--sp-1) var(--sp-3);
  font-size: var(--text-caption);
  cursor: pointer;
  transition: opacity var(--dur-swap) var(--ease);
}
.replay-play:hover:not(:disabled) { opacity: 0.82; }
.replay-play:disabled { cursor: default; opacity: 0.6; }
.replay-steps {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
  flex-wrap: wrap;
}
.replay-step {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 0;
  background: transparent;
  color: var(--muted);
  font-size: var(--text-caption);
  padding: 2px 0;
  cursor: pointer;
  transition: color var(--dur-swap) var(--ease);
}
.replay-step:hover { color: var(--ink); }
.replay-step.is-active { color: var(--accent); font-weight: 600; }
.replay-step.is-done { color: var(--ink-2); }
.replay-step-no {
  display: inline-grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border-radius: var(--r);
  background: var(--tone-3);
  color: var(--ink-2);
  font-size: 11px;
}
.replay-step.is-active .replay-step-no { background: var(--accent); color: #fff; }
.replay-sr {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
.replay-detail {
  margin-top: var(--sp-3);
  padding-top: var(--sp-3);
  border-top: 1px solid var(--line);
  min-height: 76px;
}
.replay-detail-cap {
  display: block;
  color: var(--muted);
  font-size: var(--text-caption);
  margin-bottom: var(--sp-2);
}
.replay-source p,
.replay-evidence p {
  margin: 0;
  line-height: 22px;
  color: var(--ink-2);
}
.replay-evidence small {
  display: block;
  margin-top: var(--sp-2);
  color: var(--accent);
  font-size: var(--text-caption);
}
.replay-chips {
  display: flex;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.replay-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  padding: 3px var(--sp-2);
  background: var(--tone-0);
  border-radius: var(--r);
  font-size: var(--text-caption);
  animation: replayRise 220ms var(--ease) both;
  animation-delay: calc(var(--i) * 60ms);
}
.replay-chip small { color: var(--muted); }
.replay-triple-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--sp-1);
}
.replay-triple-list li {
  font-size: var(--text-caption);
  color: var(--ink-2);
  animation: replayRise 220ms var(--ease) both;
  animation-delay: calc(var(--i) * 60ms);
}
.replay-arrow { color: var(--accent); margin: 0 6px; }
.replay-empty { color: var(--muted); font-size: var(--text-caption); }
@keyframes replayRise {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}
.replay-fade-enter-active,
.replay-fade-leave-active {
  transition: opacity var(--dur-swap) var(--ease), transform var(--dur-swap) var(--ease);
}
.replay-fade-enter-from { opacity: 0; transform: translateY(8px); }
.replay-fade-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .replay-chip,
  .replay-triple-list li { animation: none; }
  .replay-fade-enter-active,
  .replay-fade-leave-active { transition: opacity var(--dur-swap) linear; }
  .replay-fade-enter-from { transform: none; }
}
@media (max-width: 720px) {
  .replay-strip { margin: 0 var(--sp-3) var(--sp-3); }
  .replay-head { align-items: flex-start; }
}
</style>
