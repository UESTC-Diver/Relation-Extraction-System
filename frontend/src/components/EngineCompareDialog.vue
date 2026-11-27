<template>
  <el-dialog
    :model-value="modelValue"
    width="min(1040px, calc(100vw - 24px))"
    append-to-body
    class="ec-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="onOpen"
  >
    <template #header>
      <div class="ec-head">
        <span class="ec-title">双引擎对比</span>
        <span class="ec-sub">同一件事的中英两种说法，走两套引擎，输出同一套三元组结构</span>
      </div>
    </template>

    <div class="ec-intro">
      <p>
        中文用自研的「词典 + 触发词规则」，零模型依赖、每条关系都能指回原文；
        英文用 spaCy 的 NER + 依存句法，借成熟工具省掉重复造轮子。
        这里把两句话并排跑一遍，看它们如何落到同一套 schema 上。
      </p>
    </div>

    <div class="ec-samples" role="group" aria-label="选择对比样例">
      <button
        v-for="(s, i) in samples"
        :key="s.id"
        class="ec-sample-btn"
        :class="{ 'is-active': activeSample === i }"
        type="button"
        :aria-pressed="activeSample === i ? 'true' : 'false'"
        @click="activeSample = i"
      >{{ s.label }}</button>
    </div>

    <div class="ec-grid">
      <section class="ec-col" aria-labelledby="ec-zh-title">
        <div class="ec-col-head">
          <h4 id="ec-zh-title">中文 · 自研规则引擎</h4>
          <span class="ec-tag">jieba + 词典 + 触发词</span>
        </div>
        <p class="ec-source">{{ current.zh }}</p>
        <div v-if="zhResult" class="ec-result">
          <div class="ec-metrics">
            <span><b>{{ zhResult.stats?.entity_count ?? 0 }}</b> 实体</span>
            <span><b>{{ zhResult.stats?.relation_count ?? 0 }}</b> 关系</span>
            <span class="ec-engine-note">{{ engineLabel(zhResult) }}</span>
          </div>
          <ul class="ec-rels">
            <li v-for="r in zhResult.relations" :key="r.id">
              <b>{{ r.head }}</b>
              <span class="ec-rel">{{ r.relation_label }}</span>
              <b>{{ r.tail }}</b>
            </li>
            <li v-if="!zhResult.relations?.length" class="ec-empty">该句未命中关系</li>
          </ul>
        </div>
      </section>

      <section class="ec-col" aria-labelledby="ec-en-title">
        <div class="ec-col-head">
          <h4 id="ec-en-title">English · spaCy 引擎</h4>
          <span class="ec-tag">NER + 依存句法</span>
        </div>
        <p class="ec-source">{{ current.en }}</p>
        <div v-if="enResult" class="ec-result">
          <div class="ec-metrics">
            <span><b>{{ enResult.stats?.entity_count ?? 0 }}</b> 实体</span>
            <span><b>{{ enResult.stats?.relation_count ?? 0 }}</b> 关系</span>
            <span class="ec-engine-note">{{ engineLabel(enResult) }}</span>
          </div>
          <ul class="ec-rels">
            <li v-for="r in enResult.relations" :key="r.id">
              <b>{{ r.head }}</b>
              <span class="ec-rel">{{ r.relation_label }}</span>
              <b>{{ r.tail }}</b>
            </li>
            <li v-if="!enResult.relations?.length" class="ec-empty">该句未命中关系</li>
          </ul>
        </div>
        <p v-else-if="enError" class="ec-error">{{ enError }}</p>
      </section>
    </div>

    <div class="ec-schema">
      <span class="ec-schema-label">同一套 schema</span>
      <code>head · relation · tail · confidence · evidence · explanation</code>
      <span class="ec-schema-note">前端、报告与评测层不区分语言；英文结果只多 language / engine 两个元信息字段</span>
    </div>

    <div class="ec-tradeoff">
      <h4>为什么这么选</h4>
      <div class="ec-tradeoff-grid">
        <div>
          <b>中文自研</b>
          <p>中文分词与句式贴合项目自己的规则体系，确定性、可解释、可现场改词典和触发词；不依赖外部模型，断网可用。</p>
        </div>
        <div>
          <b>英文现成工具</b>
          <p>英文 NER 与依存句法用 spaCy 更省事：它的词形归一和句法锚点能处理 acquired / became 等变化，避免重复造轮子。</p>
        </div>
      </div>
    </div>

    <template #footer>
      <button class="ec-run" type="button" :disabled="loading" @click="runCompare">
        {{ loading ? '正在对比…' : '重新跑一遍' }}
      </button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { extractText } from '../api/client'

defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue'])

const samples = [
  {
    id: 'acquire', label: '收购',
    zh: '苹果公司宣布正式收购了搜狗公司， Alphabet 收购了 Fitbit。',
    en: 'Apple acquired Sogou Inc. in 2021. Alphabet acquired Fitbit in 2020.',
  },
  {
    id: 'people', label: '人物与任职',
    zh: '王小川创立了搜狗公司，并担任搜狗 CEO。',
    en: 'Jack Ma founded Alibaba in 1999. Sundar Pichai is the CEO of Google.',
  },
  {
    id: 'invest', label: '投资',
    zh: '谷歌投资了 Anthropic，双方将展开合作。',
    en: 'Google invested in Anthropic in 2023. Tencent invested in Epic Games.',
  },
]

const activeSample = ref(0)
const current = computed(() => samples[activeSample.value])
const zhResult = ref(null)
const enResult = ref(null)
const enError = ref('')
const loading = ref(false)

function engineLabel(result) {
  if (result.engine === 'spacy') return 'spaCy'
  return '规则'
}

async function runCompare() {
  loading.value = true
  enError.value = ''
  const s = current.value
  // 两边分别调用、各自兜底：英文模型未装时接口返回 503，中文侧不受影响。
  try {
    const zh = await extractText(s.zh, '', false, { language: 'zh' })
    zhResult.value = zh.result
  } catch {
    zhResult.value = null
  }
  try {
    const en = await extractText(s.en, '', false, { language: 'en' })
    enResult.value = en.result
  } catch (err) {
    enResult.value = null
    enError.value = err.message || '英文引擎不可用，可能未安装 spaCy 模型'
  }
  loading.value = false
}

function onOpen() {
  runCompare()
}

watch(activeSample, () => runCompare())
</script>

<style scoped>
.ec-head { display: flex; align-items: baseline; gap: 12px; }
.ec-title { font-size: var(--brand-scale-3); font-weight: 600; color: var(--ink); }
.ec-sub { font-size: var(--text-caption); color: var(--muted); }
.ec-intro { padding: 12px 16px; background: var(--tone-1); border-radius: var(--r); }
.ec-intro p { margin: 0; font-size: var(--text-body-sm); line-height: 20px; color: var(--ink-2); }
.ec-samples { display: flex; gap: var(--sp-3); margin-top: var(--sp-5); }
.ec-sample-btn {
  min-height: 32px; padding: 0 12px; border: 0; border-radius: var(--r);
  background: var(--tone-2); color: var(--ink-2); cursor: pointer;
  font-family: inherit; font-size: var(--text-body-sm);
  transition: color var(--dur-color) var(--ease), background var(--dur-color) var(--ease);
}
.ec-sample-btn:hover { color: var(--ink); }
.ec-sample-btn.is-active { background: var(--accent); color: #fff; }
.ec-sample-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.ec-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--sp-5); margin-top: var(--sp-5); }
.ec-col { min-width: 0; padding: 16px; background: var(--tone-0); border-radius: var(--r); }
.ec-col-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.ec-col-head h4 { margin: 0; font-size: var(--text-body); font-weight: 600; color: var(--ink); }
.ec-tag { font-size: var(--text-caption); color: var(--muted); }
.ec-source { margin: 12px 0; font-size: var(--text-body-sm); line-height: 20px; color: var(--ink-2); overflow-wrap: anywhere; }
.ec-metrics { display: flex; gap: 16px; align-items: baseline; font-size: var(--text-caption); color: var(--muted); }
.ec-metrics b { font-size: var(--text-body); color: var(--ink); font-variant-numeric: tabular-nums; }
.ec-engine-note { margin-left: auto; }
.ec-rels { list-style: none; margin: 12px 0 0; padding: 0; }
.ec-rels li { display: flex; align-items: baseline; gap: 8px; padding: 4px 0; font-size: var(--text-body-sm); color: var(--ink); }
.ec-rels b { font-weight: 600; }
.ec-rel { color: var(--accent); }
.ec-empty, .ec-error { color: var(--muted); font-size: var(--text-body-sm); }
.ec-error { margin-top: 12px; }
.ec-schema { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-top: var(--sp-5); padding: 12px 16px; background: var(--tone-2); border-radius: var(--r); }
.ec-schema-label { font-size: var(--text-body-sm); font-weight: 600; color: var(--ink); }
.ec-schema code { font-size: var(--text-caption); color: var(--ink-2); overflow-wrap: anywhere; }
.ec-schema-note { font-size: var(--text-caption); color: var(--muted); }
.ec-tradeoff { margin-top: var(--sp-5); }
.ec-tradeoff h4 { margin: 0 0 8px; font-size: var(--text-body); font-weight: 600; color: var(--ink); }
.ec-tradeoff-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--sp-5); }
.ec-tradeoff-grid b { font-size: var(--text-body-sm); color: var(--ink); }
.ec-tradeoff-grid p { margin: 4px 0 0; font-size: var(--text-body-sm); line-height: 20px; color: var(--muted); }
.ec-run { min-height: 40px; padding: 0 20px; border: 0; border-radius: var(--r); background: var(--accent); color: #fff; font-family: inherit; font-size: var(--text-body-sm); cursor: pointer; }
.ec-run:disabled { opacity: 0.6; cursor: default; }
.ec-run:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 720px) {
  .ec-grid, .ec-tradeoff-grid { grid-template-columns: minmax(0, 1fr); }
  .ec-sample-btn { min-height: 32px; padding: 0 10px; }
  .ec-head { flex-direction: column; gap: 4px; align-items: flex-start; }
}
</style>
