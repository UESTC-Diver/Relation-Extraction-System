<template>
  <div class="verify">
    <a class="skip-link" href="#verify-main">跳到甄别结果</a>

    <header class="vbar">
      <a class="vbar-brand" href="/" aria-label="返回首页">
        <svg class="vbar-logo" viewBox="0 0 26 26" fill="none" aria-hidden="true">
          <path d="M8.1 8.4 L18.1 11 M8.5 10 L11.2 17.2 M18.4 12.6 L14.6 18.2" stroke="#ddd5c2" stroke-width="1.3" stroke-linecap="round" />
          <circle cx="6.6" cy="7.8" r="3.1" fill="#201e19" />
          <circle cx="20.2" cy="10.6" r="3.1" fill="#201e19" />
          <circle cx="13" cy="20" r="3.1" fill="#a8322a" />
        </svg>
        <span class="vbar-name">文本关系抽取与信息甄别系统</span>
      </a>
      <span class="vbar-sep" aria-hidden="true"></span>
      <span class="vbar-current">信息甄别</span>
      <span class="vbar-spacer"></span>
      <a class="vbar-link" href="/app">工作台</a>
      <a class="vbar-link" href="/cases">尽调案卷</a>
      <span class="vbar-mode" :class="{ 'is-on': capability.enabled }" :title="capability.reason">
        <i class="vbar-dot" aria-hidden="true"></i>
        {{ capability.enabled ? '联网已就绪' : '离线模式' }}
      </span>
    </header>

    <main id="verify-main" class="vbody" tabindex="-1">
      <section class="vintro">
        <p class="eyebrow">信息甄别 · 日常场景</p>
        <h1 class="vintro-title">一段网传消息，到底值不值得信？</h1>
        <p class="vintro-sub">
          粘贴你看到的说法，系统会把它拆成一条条可核查的断言，按
          <b>有据可查 / 存疑待核 / 无从核实</b> 分层摆开，并标出煽动、模糊信源等可疑措辞。
          每条结论都能点回原文。判断由确定性规则生成，<b>不盖「真 / 假」的章</b>。
        </p>
      </section>

      <div class="vwork">
        <section class="vinput" aria-label="输入待甄别的文字">
          <div class="vpane-head">
            <span class="vpane-label">待甄别的文字</span>
            <span class="vpane-count">{{ text.length }} / {{ MAX_CHARS }}</span>
          </div>
          <textarea
            v-model="text"
            class="vtextarea"
            :maxlength="MAX_CHARS"
            placeholder="把群聊、朋友圈或网页上看到的一段说法粘进来…"
            aria-label="待甄别文字输入框"
          ></textarea>

          <div v-if="examples.length" class="vexamples">
            <span class="vexamples-label">试试这些例子：</span>
            <button
              v-for="ex in examples"
              :key="ex.id"
              class="vexample"
              type="button"
              :title="ex.hint"
              @click="text = ex.text"
            >{{ ex.title }}</button>
          </div>

          <label class="vswitch">
            <input v-model="useExternal" type="checkbox" :disabled="!capability.enabled" />
            <span class="vswitch-track" aria-hidden="true"><i></i></span>
            <span class="vswitch-text">
              联网核验
              <small>{{ capability.enabled ? capability.privacy_note : `当前离线${capability.reason ? '：' + capability.reason : ''}` }}</small>
            </span>
          </label>

          <div class="vinput-actions">
            <button class="cbtn cbtn-solid vrun" type="button" :disabled="loading || !text.trim()" @click="run">
              {{ loading ? '正在甄别…' : '开始甄别' }}
            </button>
            <button class="cbtn" type="button" :disabled="!text || loading" @click="text = ''">清空</button>
          </div>
          <p v-if="error" class="verr" role="alert">{{ error }}</p>
        </section>

        <section class="vresult" aria-label="甄别结果" :aria-busy="loading ? 'true' : 'false'">
          <div v-if="loading" class="vloading" role="status">
            <div class="vload-bar"></div>
            <p>正在拆句、抽取关系、核对可疑措辞…</p>
          </div>

          <div v-else-if="!report" class="vempty">
            <svg viewBox="0 0 220 130" fill="none" aria-hidden="true" class="vempty-art">
              <rect x="30" y="16" width="160" height="98" rx="6" fill="#fffdf6" stroke="#ddd5c2" />
              <rect x="46" y="34" width="96" height="6" rx="3" fill="#ebe5d6" />
              <rect x="46" y="50" width="128" height="5" rx="2.5" fill="#efeadd" />
              <rect x="46" y="62" width="112" height="5" rx="2.5" fill="#efeadd" />
              <circle cx="150" cy="92" r="18" fill="#fffdf6" stroke="#a8322a" stroke-width="1.6" />
              <path d="M143 92 L148 97 L158 87" stroke="#a8322a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <h2>贴上一段文字，看看它经不经得起推敲</h2>
            <p>左侧有现成的例子，点一个就能看到完整的甄别过程。</p>
          </div>

          <template v-else>
            <!-- 总体结论 -->
            <div class="voverall" :class="'is-' + report.overall.verdict">
              <div class="voverall-head">
                <span class="voverall-badge">{{ report.overall.verdict_label }}</span>
                <span class="voverall-meta">
                  {{ report.overall.claim_count }} 条可核查断言 · {{ report.text.length }} 字
                </span>
              </div>
              <p class="voverall-summary">{{ report.overall.summary }}</p>
              <div v-if="report.subjects && report.subjects.length" class="vsubjects">
                <span class="vsubjects-label">识别到的主体</span>
                <span v-for="s in report.subjects" :key="s" class="vsubject">{{ s }}</span>
                <span class="vsubjects-note">外部检索将围绕这些主体展开</span>
              </div>
              <p class="vdisclaimer">
                <svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><circle cx="8" cy="8" r="7" stroke="currentColor" /><path d="M8 7v4M8 5h.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" /></svg>
                {{ report.disclaimer }}
              </p>
            </div>

            <!-- 可疑措辞 -->
            <section v-if="report.signals.length" class="vblock">
              <h2 class="vblock-title">
                可疑措辞
                <span class="vblock-count">{{ report.signals.length }}</span>
              </h2>
              <p class="vblock-note">这些写法本身不等于错误，但值得多问一句「来源是谁、依据是什么」。</p>
              <ul class="vsignals">
                <li v-for="(s, i) in report.signals" :key="s.key + '-' + i" class="vsignal" :class="'is-' + s.level">
                  <div class="vsignal-top">
                    <span class="vsignal-tag">{{ s.label }}</span>
                    <mark class="vsignal-match">{{ s.matched }}</mark>
                  </div>
                  <p class="vsignal-hint">{{ s.hint }}</p>
                </li>
              </ul>
            </section>

            <!-- 逐条断言 -->
            <section class="vblock">
              <h2 class="vblock-title">
                逐条断言
                <span class="vblock-count">{{ report.claims.length }}</span>
              </h2>
              <p v-if="!report.claims.length" class="vblock-note">
                这段文字没有抽出具体的关系断言，属于陈述或情绪表达，无法在事实层面逐条核实。
              </p>
              <div v-else class="vclaims">
                <article v-for="(c, i) in report.claims" :key="i" class="vclaim" :class="'is-' + c.verdict">
                  <div class="vclaim-head">
                    <span class="vclaim-index">{{ String(i + 1).padStart(2, '0') }}</span>
                    <div class="vclaim-triple">
                      <b>{{ c.head }}</b>
                      <span class="vclaim-rel">{{ c.relation_label }}</span>
                      <b>{{ c.tail }}</b>
                    </div>
                    <span class="vclaim-badge">{{ c.verdict_label }}</span>
                  </div>

                  <blockquote class="vclaim-evidence">
                    <span class="vclaim-q">原句 · 第 {{ c.sentence_index + 1 }} 句</span>
                    {{ c.evidence_sentence || c.evidence }}
                  </blockquote>

                  <ul class="vclaim-reasons">
                    <li v-for="(r, ri) in c.reasons" :key="ri">{{ r }}</li>
                  </ul>

                  <!-- 外部证据 -->
                  <div v-if="c.external && c.external.evidence && c.external.evidence.length" class="vexternal">
                    <p class="vexternal-head">
                      外部检索线索
                      <span v-if="c.external.refuted" class="vexternal-refute">含疑似辟谣 / 否认信息</span>
                    </p>
                    <ul>
                      <li v-for="(e, ei) in c.external.evidence" :key="ei" class="vev">
                        <div class="vev-top">
                          <a :href="e.url" target="_blank" rel="noopener noreferrer">{{ e.title }}</a>
                          <span class="vev-tier" :class="'is-' + e.source_tier">{{ e.source_label }}</span>
                        </div>
                        <p v-if="e.snippet" class="vev-snippet">{{ e.snippet }}</p>
                      </li>
                    </ul>
                  </div>
                </article>
              </div>
            </section>

            <p class="vfoot">
              指纹 {{ report.fingerprint }} · 生成于 {{ report.generated_at }}
              <span v-if="report.external && report.external.queries_used">
                · 外部检索 {{ report.external.queries_used }} 次
              </span>
            </p>
          </template>
        </section>
      </div>
    </main>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '../api/client'

const MAX_CHARS = 8000
const text = ref('')
const useExternal = ref(false)
const loading = ref(false)
const error = ref('')
const report = ref(null)
const examples = ref([])
const capability = ref({
  enabled: false,
  provider: 'none',
  reason: '',
  privacy_note: '联网时只发送实体名与关系短语，不会上传原文全文。',
})

onMounted(async () => {
  try {
    const [caps, exs] = await Promise.all([
      api.getVerifyCapability(),
      api.getVerifyExamples(),
    ])
    capability.value = caps
    examples.value = exs || []
    // 有联网能力时默认打开；离线保持关闭，避免用户误以为已核实
    useExternal.value = caps.enabled
  } catch {
    // 能力探测失败不影响离线甄别：按离线处理
    error.value = ''
  }
})

async function run() {
  if (!text.value.trim() || loading.value) return
  loading.value = true
  error.value = ''
  report.value = null
  try {
    report.value = await api.verifyText(text.value, useExternal.value && capability.value.enabled)
  } catch (err) {
    error.value = err.message || '甄别失败'
    ElMessage.error(error.value)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.verify { min-height: 100vh; background: var(--bg); color: var(--ink); }

/* ---------- 顶栏 ---------- */
.vbar {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 20px; border-bottom: 1px solid var(--line);
  background: var(--surface); position: sticky; top: 0; z-index: 20;
}
.vbar-brand { display: inline-flex; align-items: center; gap: 8px; text-decoration: none; color: var(--ink); }
.vbar-logo { width: 22px; height: 22px; }
.vbar-name { font-size: 13px; letter-spacing: 0.02em; }
.vbar-sep { width: 1px; height: 16px; background: var(--line); }
.vbar-current { font-size: 13px; color: var(--accent); }
.vbar-spacer { flex: 1; }
.vbar-link { font-size: 12.5px; color: var(--muted); text-decoration: none; padding: 4px 6px; border-radius: 4px; }
.vbar-link:hover { color: var(--ink); background: var(--tone-2); }
.vbar-mode {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--muted); padding: 4px 10px;
  border: 1px solid var(--line-strong); border-radius: 999px;
}
.vbar-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--tone-4); }
.vbar-mode.is-on { color: var(--accent); }
.vbar-mode.is-on .vbar-dot { background: var(--accent); }

/* ---------- 正文 ---------- */
.vbody { max-width: 1240px; margin: 0 auto; padding: 32px 24px 64px; }
.vintro { max-width: 760px; margin-bottom: 28px; }
.eyebrow { font-size: 12px; letter-spacing: 1.4px; color: var(--accent); text-transform: uppercase; margin: 0 0 8px; }
.vintro-title { font-size: 30px; line-height: 1.3; font-weight: 600; letter-spacing: 0.01em; margin: 0; }
.vintro-sub { font-size: 15px; line-height: 1.75; color: var(--muted); margin: 12px 0 0; }
.vintro-sub b { color: var(--ink-2); font-weight: 600; }

.vwork { display: grid; grid-template-columns: minmax(300px, 400px) minmax(0, 1fr); gap: 20px; align-items: start; }

/* ---------- 输入面板 ---------- */
.vinput {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--r);
  padding: 16px; position: sticky; top: 70px;
}
.vpane-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }
.vpane-label { font-size: 13px; font-weight: 600; }
.vpane-count { font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }
.vtextarea {
  width: 100%; min-height: 230px; resize: vertical;
  font: inherit; font-size: 14px; line-height: 1.7; color: var(--ink);
  background: var(--brand-paper); border: 1px solid var(--line-strong);
  border-radius: var(--r); padding: 12px;
}
.vtextarea:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
.vexamples { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 12px; }
.vexamples-label { font-size: 11.5px; color: var(--muted); }
.vexample {
  font: inherit; font-size: 11.5px; padding: 4px 9px; cursor: pointer;
  border: 1px solid var(--line-strong); border-radius: 999px;
  background: var(--surface); color: var(--ink-2);
}
.vexample:hover { background: var(--tone-2); color: var(--accent); }

.vswitch { display: flex; align-items: flex-start; gap: 10px; margin-top: 18px; cursor: pointer; }
.vswitch input { position: absolute; opacity: 0; width: 0; height: 0; }
.vswitch-track {
  flex: none; width: 34px; height: 19px; border-radius: 999px;
  background: var(--tone-4); position: relative; transition: background 0.18s ease;
}
.vswitch-track i {
  position: absolute; top: 2px; left: 2px; width: 15px; height: 15px;
  border-radius: 50%; background: #fffdf6; transition: transform 0.18s ease;
}
.vswitch input:checked + .vswitch-track { background: var(--accent); }
.vswitch input:checked + .vswitch-track i { transform: translateX(15px); }
.vswitch input:focus-visible + .vswitch-track { outline: 2px solid var(--accent); outline-offset: 2px; }
.vswitch input:disabled + .vswitch-track { opacity: 0.5; }
.vswitch-text { font-size: 13px; font-weight: 600; line-height: 19px; }
.vswitch-text small { display: block; font-size: 11px; font-weight: 400; line-height: 1.5; color: var(--muted); margin-top: 2px; }

.vinput-actions { display: flex; gap: 8px; margin-top: 20px; }
.vrun { flex: 1; justify-content: center; }
.verr { font-size: 12px; color: var(--danger); margin: 10px 0 0; }

/* ---------- 结果面板 ---------- */
.vresult { min-height: 420px; }
.vloading { padding: 60px 20px; text-align: center; color: var(--muted); }
.vload-bar { height: 3px; width: 160px; margin: 0 auto 16px; background: var(--tone-3); border-radius: 2px; overflow: hidden; position: relative; }
.vload-bar::after { content: ''; position: absolute; inset: 0; width: 40%; background: var(--accent); animation: vslide 1.1s ease-in-out infinite; }
@keyframes vslide { 0% { transform: translateX(-100%); } 100% { transform: translateX(350%); } }

.vempty { padding: 56px 24px; text-align: center; background: var(--surface); border: 1px dashed var(--line-strong); border-radius: var(--r); }
.vempty-art { width: 200px; height: 118px; margin-bottom: 8px; }
.vempty h2 { font-size: 17px; font-weight: 600; margin: 0; }
.vempty p { font-size: 13px; color: var(--muted); margin: 8px 0 0; }

/* 总体结论卡 */
.voverall { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--tone-4); border-radius: var(--r); padding: 18px 20px; margin-bottom: 22px; }
.voverall.is-grounded { border-left-color: #4a7c59; }
.voverall.is-question { border-left-color: #b8862f; }
.voverall.is-uncheckable { border-left-color: var(--accent); }
.voverall-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.voverall-badge { font-size: 15px; font-weight: 700; letter-spacing: 0.02em; }
.voverall.is-grounded .voverall-badge { color: #3c6849; }
.voverall.is-question .voverall-badge { color: #92681f; }
.voverall.is-uncheckable .voverall-badge { color: var(--accent); }
.voverall-meta { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.voverall-summary { font-size: 14px; line-height: 1.7; margin: 10px 0 0; }
.vsubjects { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 12px 0 0; }
.vsubjects-label { font-size: 11.5px; color: var(--muted); margin-right: 2px; }
.vsubject { display: inline-block; font-size: 12px; font-weight: 600; color: #7a2f28; background: #f6e8e2; border: 1px solid #e6cdc3; border-radius: 999px; padding: 3px 10px; }
.vsubjects-note { font-size: 11px; color: var(--muted); margin-left: 2px; }
.vdisclaimer { display: flex; align-items: flex-start; gap: 6px; font-size: 11.5px; line-height: 1.6; color: var(--muted); margin: 14px 0 0; padding-top: 12px; border-top: 1px solid var(--line); }
.vdisclaimer svg { width: 14px; height: 14px; flex: none; margin-top: 1px; }

/* 区块 */
.vblock { margin-bottom: 28px; }
.vblock-title { font-size: 16px; font-weight: 600; margin: 0 0 4px; display: flex; align-items: center; gap: 8px; }
.vblock-count { font-size: 11px; font-weight: 600; color: var(--accent); background: var(--red-soft); border-radius: 999px; padding: 1px 8px; font-variant-numeric: tabular-nums; }
.vblock-note { font-size: 12.5px; color: var(--muted); line-height: 1.6; margin: 0 0 12px; }

/* 可疑措辞 */
.vsignals { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
.vsignal { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r); padding: 12px 14px; }
.vsignal.is-high { border-top: 2px solid var(--accent); }
.vsignal.is-medium { border-top: 2px solid #b8862f; }
.vsignal-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.vsignal-tag { font-size: 12px; font-weight: 600; }
.vsignal-match { font-size: 12px; color: var(--accent); background: var(--red-soft); padding: 1px 6px; border-radius: 3px; }
.vsignal-hint { font-size: 11.5px; line-height: 1.6; color: var(--muted); margin: 8px 0 0; }

/* 断言卡 */
.vclaims { display: flex; flex-direction: column; gap: 14px; }
.vclaim { background: var(--surface); border: 1px solid var(--line); border-radius: var(--r); padding: 16px 18px; }
.vclaim.is-grounded { border-left: 3px solid #4a7c59; }
.vclaim.is-question { border-left: 3px solid #b8862f; }
.vclaim.is-uncheckable { border-left: 3px solid var(--accent); }
.vclaim-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.vclaim-index { font-size: 11px; font-weight: 700; color: var(--muted); font-variant-numeric: tabular-nums; }
.vclaim-triple { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; flex: 1; font-size: 14px; }
.vclaim-triple b { font-weight: 600; }
.vclaim-rel { font-size: 11.5px; color: var(--accent); background: var(--red-soft); border-radius: 3px; padding: 2px 8px; }
.vclaim-badge { font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 999px; background: var(--tone-2); color: var(--ink-2); }
.vclaim.is-grounded .vclaim-badge { background: #e4efe6; color: #3c6849; }
.vclaim.is-question .vclaim-badge { background: #f5ecd8; color: #92681f; }
.vclaim.is-uncheckable .vclaim-badge { background: var(--red-soft); color: var(--accent); }
.vclaim-evidence { margin: 12px 0 0; padding: 10px 12px; background: var(--brand-paper); border-radius: var(--r); font-size: 13px; line-height: 1.7; color: var(--ink-2); }
.vclaim-q { display: block; font-size: 10.5px; letter-spacing: 0.4px; color: var(--muted); margin-bottom: 4px; }
.vclaim-reasons { list-style: none; padding: 0; margin: 12px 0 0; }
.vclaim-reasons li { font-size: 12px; line-height: 1.6; color: var(--muted); padding-left: 16px; position: relative; }
.vclaim-reasons li::before { content: '·'; position: absolute; left: 4px; font-weight: 700; color: var(--accent); }

/* 外部证据 */
.vexternal { margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--line-strong); }
.vexternal-head { font-size: 12px; font-weight: 600; margin: 0 0 8px; }
.vexternal-refute { font-size: 11px; font-weight: 500; color: var(--accent); margin-left: 8px; }
.vexternal ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
.vev { padding: 8px 10px; background: var(--tone-1); border-radius: var(--r); }
.vev-top { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.vev-top a { font-size: 12.5px; color: var(--accent); text-decoration: none; line-height: 1.4; }
.vev-top a:hover { text-decoration: underline; text-underline-offset: 2px; }
.vev-tier { font-size: 10px; padding: 1px 7px; border-radius: 999px; background: var(--surface); color: var(--muted); white-space: nowrap; }
.vev-tier.is-official { background: #e4efe6; color: #3c6849; }
.vev-tier.is-major { background: #e6eef4; color: #2f5f7c; }
.vev-tier.is-community { background: #f5ecd8; color: #92681f; }
.vev-snippet { font-size: 11.5px; line-height: 1.6; color: var(--muted); margin: 5px 0 0; }
.vfoot { font-size: 11px; color: var(--muted); text-align: right; margin-top: 20px; font-variant-numeric: tabular-nums; }

@media (max-width: 900px) {
  .vwork { grid-template-columns: 1fr; }
  .vinput { position: static; }
  .vintro-title { font-size: 25px; }
}
@media (max-width: 560px) {
  .vbody { padding: 22px 14px 48px; }
  .vbar { padding: 10px 14px; }
  .vbar-name, .vbar-link { display: none; }
  .vclaim-triple { font-size: 13px; }
}
@media (prefers-reduced-motion: reduce) {
  .vload-bar::after { animation: none; }
}
</style>
