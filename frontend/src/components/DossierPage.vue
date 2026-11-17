<template>
  <div class="cases">
    <a class="skip-link" href="#case-main">跳到案卷内容</a>

    <header class="cbar">
      <a class="cbar-brand" href="/" aria-label="返回首页">
        <svg class="cbar-logo" viewBox="0 0 26 26" fill="none" aria-hidden="true">
          <path d="M8.1 8.4 L18.1 11 M8.5 10 L11.2 17.2 M18.4 12.6 L14.6 18.2" stroke="#ddd5c2" stroke-width="1.3" stroke-linecap="round" />
          <circle cx="6.6" cy="7.8" r="3.1" fill="#201e19" />
          <circle cx="20.2" cy="10.6" r="3.1" fill="#201e19" />
          <circle cx="13" cy="20" r="3.1" fill="#a8322a" />
        </svg>
        <span class="cbar-name">中文关系抽取系统</span>
      </a>
      <span class="cbar-sep" aria-hidden="true"></span>
      <span class="cbar-current">尽调案卷</span>
      <span class="cbar-spacer"></span>
      <a class="cbar-link" href="/app">工作台</a>
      <a class="cbar-link" href="/demo">静态样例</a>
      <button class="cbtn" type="button" :disabled="seeding" @click="onSeed">
        {{ seeding ? '正在载入…' : '载入示例案卷' }}
      </button>
      <button class="cbtn cbtn-solid" type="button" @click="newOpen = !newOpen">新建案卷</button>
    </header>

    <div class="cbody">
      <aside class="clist" aria-label="案卷列表">
        <label class="clist-search">
          <span class="sr-only">搜索案卷</span>
          <input v-model="keyword" type="search" placeholder="搜索案卷或标的" />
        </label>
        <p v-if="!filtered.length" class="clist-empty">
          {{ dossiers.length ? '没有匹配的案卷' : '还没有案卷' }}
        </p>
        <button
          v-for="d in filtered"
          :key="d.id"
          class="clist-item"
          :class="{ 'is-active': d.id === currentId }"
          type="button"
          @click="select(d.id)"
        >
          <b>{{ d.name }}</b>
          <span>{{ d.subject || '未填标的' }} · {{ d.material_count }} 份材料</span>
        </button>
      </aside>

      <main id="case-main" class="cmain" tabindex="-1">
        <form v-if="newOpen" class="newform" @submit.prevent="onCreate">
          <h2 class="newform-title">新建案卷</h2>
          <div class="newform-grid">
            <label>
              <span>案卷名</span>
              <input v-model="form.name" required maxlength="80" placeholder="例如：某某公司 · 关联方核查" />
            </label>
            <label>
              <span>标的公司 / 主体</span>
              <input v-model="form.subject" maxlength="64" placeholder="留空则按材料中出现最多的机构推断" />
            </label>
          </div>
          <label class="newform-note">
            <span>备注（可选）</span>
            <input v-model="form.note" maxlength="400" placeholder="委托方、核查范围、口径说明…" />
          </label>
          <div class="newform-actions">
            <button class="cbtn cbtn-solid" type="submit" :disabled="creating">创建</button>
            <button class="cbtn" type="button" @click="newOpen = false">取消</button>
          </div>
        </form>

        <p v-if="error" class="cerr" role="alert">{{ error }}</p>

        <div v-if="loading" class="cloading" role="status">正在读取案卷…</div>

        <section v-else-if="!view" class="cempty">
          <svg viewBox="0 0 200 120" fill="none" aria-hidden="true" class="cempty-art">
            <rect x="34" y="18" width="76" height="92" rx="4" fill="#fffdf6" stroke="#ddd5c2" />
            <rect x="46" y="32" width="52" height="4" rx="2" fill="#ebe5d6" />
            <rect x="46" y="44" width="40" height="4" rx="2" fill="#ebe5d6" />
            <rect x="46" y="56" width="48" height="4" rx="2" fill="#ebe5d6" />
            <rect x="96" y="30" width="70" height="84" rx="4" fill="#fffdf6" stroke="#ddd5c2" />
            <circle cx="131" cy="58" r="9" fill="#fffdf6" stroke="#a8322a" stroke-width="1.4" />
            <circle cx="112" cy="86" r="6" fill="#fffdf6" stroke="#c4bba6" stroke-width="1.4" />
            <circle cx="150" cy="86" r="6" fill="#fffdf6" stroke="#c4bba6" stroke-width="1.4" />
            <path d="M124 64 L116 80" stroke="#c4bba6" stroke-width="1.2" />
            <path d="M138 64 L146 80" stroke="#c4bba6" stroke-width="1.2" />
            <path d="M118 86 L144 86" stroke="#a8322a" stroke-width="1.2" stroke-dasharray="4 4" />
          </svg>
          <h2>还没有打开任何案卷</h2>
          <p>
            一个案卷 = 一个标的 + 一批材料。系统会把材料里的关系按「直接结论 / 推断关联 / 疑点」三层摆开，
            每条都指回原文的某一句话。
          </p>
          <div class="cempty-actions">
            <button class="cbtn cbtn-solid" type="button" :disabled="seeding" @click="onSeed">
              {{ seeding ? '正在载入…' : '载入示例案卷，先看效果' }}
            </button>
            <button class="cbtn" type="button" @click="newOpen = true">自己新建一个</button>
          </div>
        </section>

        <template v-else>
          <section class="chead">
            <p class="eyebrow">尽调案卷</p>
            <h1 class="chead-title">{{ view.name }}</h1>
            <p class="chead-subj">
              标的：<b>{{ view.subject_effective || '未指定' }}</b>
              <span v-if="view.subject_auto" class="chead-auto">未填写标的，按材料中出现最多的机构推断</span>
            </p>
            <p v-if="view.note" class="chead-note">{{ view.note }}</p>
            <div class="chead-actions">
              <a class="cbtn" :href="reportUrl" target="_blank" rel="noopener">导出案卷报告</a>
              <button class="cbtn" type="button" @click="editOpen = !editOpen">
                {{ editOpen ? '收起编辑' : '编辑信息' }}
              </button>
              <button class="cbtn cbtn-quiet" type="button" @click="onDelete">删除案卷</button>
            </div>
            <form v-if="editOpen" class="editform" @submit.prevent="onSaveInfo">
              <label>
                <span>案卷名</span>
                <input v-model="edit.name" maxlength="80" />
              </label>
              <label>
                <span>标的</span>
                <input v-model="edit.subject" maxlength="64" />
              </label>
              <label class="editform-wide">
                <span>备注</span>
                <input v-model="edit.note" maxlength="400" />
              </label>
              <button class="cbtn cbtn-solid" type="submit" :disabled="saving">保存</button>
            </form>
          </section>

          <div class="cmetrics">
            <div class="cmetric">
              <b>{{ view.summary.materials }}</b><span>材料</span>
            </div>
            <div class="cmetric">
              <b>{{ view.summary.relations_merged }}</b>
              <span>直接结论<i v-if="view.summary.relations_raw > view.summary.relations_merged">（由 {{ view.summary.relations_raw }} 条归并）</i></span>
            </div>
            <div class="cmetric">
              <b>{{ view.summary.inferred }}</b>
              <span>推断关联<i v-if="view.summary.inferred_strong">（{{ view.summary.inferred_strong }} 条较强）</i></span>
            </div>
            <div class="cmetric">
              <b>{{ view.summary.entities }}</b><span>涉及实体</span>
            </div>
            <div class="cmetric" :class="{ 'is-warn': view.summary.ambiguities > 0 }">
              <b>{{ view.summary.ambiguities }}</b>
              <span>待补强疑点<i v-if="view.summary.tensions">（{{ view.summary.tensions }} 条对抗并行）</i></span>
            </div>
          </div>

          <div class="ctabs" role="tablist" aria-label="案卷视图切换" @keydown="onTabKeydown">
            <button
              v-for="t in TABS"
              :key="t.key"
              :id="'ctab-' + t.key"
              class="ctab"
              :class="{ 'is-active': tab === t.key }"
              role="tab"
              type="button"
              :aria-selected="tab === t.key ? 'true' : 'false'"
              :tabindex="tab === t.key ? 0 : -1"
              aria-controls="case-panel"
              @click="tab = t.key"
            >
              {{ t.label }}
              <span class="ctab-count">{{ countOf(t.key) }}</span>
            </button>
          </div>

          <div id="case-panel" class="cpanel" role="tabpanel" :aria-labelledby="'ctab-' + tab">
            <!-- 直接结论 -->
            <template v-if="tab === 'direct'">
              <p class="chint">
                同一组头尾关系在多份材料里出现时合成一条，<b>「支撑」</b>就是有几份材料独立这么说。
                点任意一行看全部出处。
              </p>
              <p v-if="!view.direct.length" class="cempty-line">这批材料里还没有抽出关系。</p>
              <div v-else class="dtable" role="table" aria-label="直接结论">
                <div class="drow drow-head" role="row">
                  <span role="columnheader">头实体</span>
                  <span role="columnheader">关系</span>
                  <span role="columnheader">尾实体</span>
                  <span role="columnheader">支撑</span>
                  <span role="columnheader">置信度</span>
                </div>
                <div v-for="(d, i) in view.direct" :key="i" class="dgroup">
                  <button
                    class="drow drow-body"
                    type="button"
                    :aria-expanded="expanded.has(i) ? 'true' : 'false'"
                    @click="toggleRow(i)"
                  >
                    <span class="dcell-entity">{{ d.head }}</span>
                    <span><i class="drel">{{ d.relation_label }}</i></span>
                    <span class="dcell-entity">{{ d.tail }}</span>
                    <span class="dcell-num">{{ d.support_count }}</span>
                    <span class="dcell-num">{{ d.confidence.toFixed(2) }}</span>
                  </button>
                  <div v-if="expanded.has(i)" class="dsources">
                    <p class="dsources-title">这条结论的 {{ d.evidence_count }} 处原文出处</p>
                    <ul>
                      <li v-for="(s, j) in d.sources" :key="j">
                        <b>《{{ s.doc_title }}》</b>
                        <i>{{ s.role }} · 第 {{ s.sentence_index + 1 }} 句</i>
                        <q>{{ s.evidence }}</q>
                      </li>
                    </ul>
                  </div>
                </div>
              </div>
            </template>

            <!-- 推断关联 -->
            <template v-else-if="tab === 'inferred'">
              <div class="cnotice">
                <b>先读这段。</b>下面每一条都是把已有结论做图运算得出的，原文里没有任何一句话这么说。
                它们的作用是提示下一步该查什么，不能当作认定事实的依据，也不计入任何评测指标。
              </div>
              <p v-if="!view.inferred.length" class="cempty-line">
                这批材料里没有可推出的间接关联。推断只在控制链两跳、同一人任职、同一创始人、
                同一具体地址四类规则成立时才生成，推不出来就不写。
              </p>
              <article v-for="inf in view.inferred" :key="inf.id" class="infcard">
                <div class="infcard-head">
                  <span class="infbadge" :class="inf.strength === 'strong' ? 'is-strong' : 'is-weak'">
                    推断 · {{ inf.strength === 'strong' ? '较强' : '较弱' }}
                  </span>
                  <span class="infcard-line">
                    <b>{{ inf.head }}</b>
                    <em>{{ inf.label }}</em>
                    <b>{{ inf.tail }}</b>
                  </span>
                  <span class="infcard-conf">{{ inf.confidence.toFixed(2) }}</span>
                </div>
                <p class="infcard-basis"><i>依据</i>{{ inf.basis }}（{{ inf.kind_label }}）</p>
                <ol class="infpath">
                  <li v-for="(step, k) in inf.path" :key="k">
                    <span class="infpath-eq">{{ step.head }} <em>{{ step.relation_label }}</em> {{ step.tail }}</span>
                    <span class="infpath-src">
                      《{{ step.doc_title }}》{{ step.role }} · 第 {{ step.sentence_index + 1 }} 句
                    </span>
                    <q class="infpath-q">{{ step.evidence }}</q>
                  </li>
                </ol>
                <p class="infcard-caveat">{{ inf.caveat }}</p>
              </article>
            </template>

            <!-- 疑点 -->
            <template v-else-if="tab === 'ambiguities'">
              <p class="chint">
                这一节列的是「这份案卷还不扎实的地方」，不是结论。把它当下一轮要补的材料清单。
              </p>
              <p v-if="!view.ambiguities.length" class="cempty-line">
                没有发现待补强的疑点：没有权益关系互相矛盾，没有只靠一份材料撑着的弱结论，
                也没有哪份材料完全没连到标的。
              </p>
              <ul v-else class="amblist">
                <li v-for="(a, i) in view.ambiguities" :key="i" :class="'lv-' + a.level">
                  <span class="ambtag">{{ levelLabel(a) }}</span>
                  <div>
                    <p class="ambtitle">{{ a.title }}</p>
                    <p class="ambdetail">{{ a.detail }}</p>
                  </div>
                </li>
              </ul>
            </template>

            <!-- 材料 -->
            <template v-else>
              <div class="matbar">
                <span>共 {{ view.materials.length }} 份材料，按归档顺序排列。</span>
                <button class="cbtn" type="button" @click="openAdd">添加材料</button>
              </div>
              <p v-if="!view.materials.length" class="cempty-line">
                案卷里还没有材料。从历史记录里挑几份归档进来，关系是现成的，不需要重新抽。
              </p>
              <ul v-else class="matlist">
                <li v-for="m in view.materials" :key="m.record_id">
                  <div class="mat-main">
                    <b>{{ m.title }}</b>
                    <span class="mat-meta">
                      {{ m.char_count }} 字 · {{ m.relation_count }} 条关系 · 归档于 {{ m.added_at }}
                    </span>
                  </div>
                  <span class="mat-role">{{ m.role }}</span>
                  <a class="mat-open" :href="'/app?record=' + m.record_id" target="_blank" rel="noopener">在工作台打开</a>
                  <button class="mat-remove" type="button" @click="onRemoveMaterial(m)">移出</button>
                </li>
              </ul>
            </template>
          </div>
        </template>
      </main>
    </div>

    <!-- 添加材料 -->
    <div v-if="addOpen" class="drawer-mask" @click.self="addOpen = false">
      <div class="drawer" role="dialog" aria-modal="true" aria-labelledby="add-title">
        <header class="drawer-head">
          <h2 id="add-title">添加材料</h2>
          <button class="drawer-close" type="button" aria-label="关闭" @click="addOpen = false">×</button>
        </header>
        <p class="drawer-hint">
          选已有记录归档。材料本身不复制，抽取结果和人工校正始终只有一份。
        </p>
        <label class="drawer-role">
          <span>材料角色</span>
          <select v-model="addRole">
            <option v-for="r in roles" :key="r" :value="r">{{ r }}</option>
          </select>
        </label>
        <p v-if="historyLoading" class="drawer-hint">正在读取历史记录…</p>
        <p v-else-if="!candidates.length" class="drawer-hint">历史里还没有可归档的记录，先去工作台抽一篇。</p>
        <ul v-else class="picklist">
          <li v-for="r in candidates" :key="r.id">
            <label>
              <input v-model="picked" type="checkbox" :value="r.id" />
              <span class="pick-title">{{ r.title }}</span>
              <span class="pick-meta">{{ r.relation_count }} 条关系 · {{ r.char_count }} 字</span>
            </label>
          </li>
        </ul>
        <footer class="drawer-foot">
          <button class="cbtn cbtn-solid" type="button" :disabled="!picked.length || adding" @click="onAddMaterials">
            {{ adding ? '归档中…' : `归档 ${picked.length} 份` }}
          </button>
          <button class="cbtn" type="button" @click="addOpen = false">取消</button>
        </footer>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import {
  addDossierMaterials,
  createDossier,
  deleteDossier,
  dossierReportUrl,
  getDossier,
  getDossiers,
  getRecords,
  removeDossierMaterial,
  seedDossier,
  updateDossier,
} from '../api/client'

const TABS = [
  { key: 'direct', label: '直接结论' },
  { key: 'inferred', label: '推断关联' },
  { key: 'ambiguities', label: '疑点' },
  { key: 'materials', label: '材料' },
]

const dossiers = ref([])
const currentId = ref(null)
const view = ref(null)
const roles = ref([])
const tab = ref('direct')
const keyword = ref('')
const loading = ref(false)
const seeding = ref(false)
const creating = ref(false)
const saving = ref(false)
const error = ref('')
const newOpen = ref(false)
const editOpen = ref(false)
const expanded = ref(new Set())
const reportUrl = computed(() => (currentId.value ? dossierReportUrl(currentId.value) : '#'))

const form = reactive({ name: '', subject: '', note: '' })
const edit = reactive({ name: '', subject: '', note: '' })

const addOpen = ref(false)
const candidates = ref([])
const historyLoading = ref(false)
const picked = ref([])
const addRole = ref('其他材料')
const adding = ref(false)

const filtered = computed(() => {
  const q = keyword.value.trim()
  if (!q) return dossiers.value
  return dossiers.value.filter((d) => (d.name + d.subject).includes(q))
})

function countOf(key) {
  if (!view.value) return 0
  if (key === 'direct') return view.value.direct.length
  if (key === 'inferred') return view.value.inferred.length
  if (key === 'ambiguities') return view.value.ambiguities.length
  return view.value.materials.length
}

function levelLabel(a) {
  if (a.type === 'conflict') return '需裁决'
  if (a.type === 'tension') return '对抗信号'
  if (a.type === 'orphan_material') return '材料脱节'
  return '待补强'
}

function toggleRow(i) {
  const next = new Set(expanded.value)
  if (next.has(i)) next.delete(i)
  else next.add(i)
  expanded.value = next
}

function onTabKeydown(event) {
  const keys = ['ArrowRight', 'ArrowLeft', 'Home', 'End']
  if (!keys.includes(event.key)) return
  event.preventDefault()
  const index = TABS.findIndex((t) => t.key === tab.value)
  let next = index
  if (event.key === 'ArrowRight') next = (index + 1) % TABS.length
  if (event.key === 'ArrowLeft') next = (index - 1 + TABS.length) % TABS.length
  if (event.key === 'Home') next = 0
  if (event.key === 'End') next = TABS.length - 1
  tab.value = TABS[next].key
  document.getElementById('ctab-' + TABS[next].key)?.focus()
}

async function loadList() {
  const data = await getDossiers()
  dossiers.value = data.items || []
  roles.value = data.roles || []
}

async function select(id) {
  currentId.value = id
  loading.value = true
  error.value = ''
  tab.value = 'direct'
  expanded.value = new Set()
  try {
    view.value = await getDossier(id)
    Object.assign(edit, {
      name: view.value.name,
      subject: view.value.subject,
      note: view.value.note,
    })
    const url = new URL(location.href)
    url.searchParams.set('id', String(id))
    window.history.replaceState(null, '', url)
  } catch (err) {
    error.value = err.message || '案卷读取失败'
    view.value = null
  } finally {
    loading.value = false
  }
}

async function onSeed() {
  seeding.value = true
  error.value = ''
  try {
    const data = await seedDossier()
    await loadList()
    currentId.value = data.id
    view.value = data
    Object.assign(edit, { name: data.name, subject: data.subject, note: data.note })
  } catch (err) {
    error.value = err.message || '示例案卷载入失败'
  } finally {
    seeding.value = false
  }
}

async function onCreate() {
  creating.value = true
  error.value = ''
  try {
    const row = await createDossier({ ...form, subject_type: 'ORG' })
    newOpen.value = false
    form.name = ''
    form.subject = ''
    form.note = ''
    await loadList()
    await select(row.id)
    tab.value = 'materials'
    openAdd()
  } catch (err) {
    error.value = err.message || '新建失败'
  } finally {
    creating.value = false
  }
}

async function onSaveInfo() {
  saving.value = true
  try {
    await updateDossier(currentId.value, { ...edit })
    await loadList()
    await select(currentId.value)
    editOpen.value = false
  } catch (err) {
    error.value = err.message || '保存失败'
  } finally {
    saving.value = false
  }
}

async function onDelete() {
  if (!window.confirm('删除这个案卷？材料本身、标注和复核结论都不受影响，只是不再归档在这个案卷里。')) {
    return
  }
  try {
    await deleteDossier(currentId.value)
    view.value = null
    currentId.value = null
    await loadList()
    if (dossiers.value.length) await select(dossiers.value[0].id)
  } catch (err) {
    error.value = err.message || '删除失败'
  }
}

async function openAdd() {
  addOpen.value = true
  picked.value = []
  historyLoading.value = true
  try {
    const data = await getRecords({ limit: 100, offset: 0 })
    const archived = new Set((view.value?.materials || []).map((m) => m.record_id))
    candidates.value = (data.items || []).filter((r) => !archived.has(r.id))
  } catch (err) {
    error.value = err.message || '历史记录读取失败'
  } finally {
    historyLoading.value = false
  }
}

async function onAddMaterials() {
  adding.value = true
  try {
    await addDossierMaterials(currentId.value, picked.value, addRole.value)
    addOpen.value = false
    await loadList()
    await select(currentId.value)
    tab.value = 'materials'
  } catch (err) {
    error.value = err.message || '归档失败'
  } finally {
    adding.value = false
  }
}

async function onRemoveMaterial(m) {
  if (!window.confirm(`把《${m.title}》移出这个案卷？记录本身会保留。`)) return
  try {
    await removeDossierMaterial(currentId.value, m.record_id)
    await loadList()
    await select(currentId.value)
    tab.value = 'materials'
  } catch (err) {
    error.value = err.message || '移出失败'
  }
}

onMounted(async () => {
  try {
    await loadList()
  } catch (err) {
    error.value = err.message || '案卷列表读取失败'
    return
  }
  const wanted = Number(new URLSearchParams(location.search).get('id'))
  const target = dossiers.value.find((d) => d.id === wanted) || dossiers.value[0]
  if (target) await select(target.id)
})
</script>

<style scoped>
.cases {
  min-height: 100vh;
  background: var(--bg);
  color: var(--ink);
}

/* ---------- 顶栏 ---------- */
.cbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--line);
  background: var(--surface);
  position: sticky;
  top: 0;
  z-index: 20;
}
.cbar-brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
  color: var(--ink);
}
.cbar-logo {
  width: 22px;
  height: 22px;
}
.cbar-name {
  font-size: 13px;
  letter-spacing: 0.02em;
}
.cbar-sep {
  width: 1px;
  height: 16px;
  background: var(--line);
}
.cbar-current {
  font-size: 13px;
  color: var(--accent);
}
.cbar-spacer {
  flex: 1;
}
.cbar-link {
  font-size: 12.5px;
  color: var(--muted);
  text-decoration: none;
  padding: 4px 6px;
  border-radius: 4px;
}
.cbar-link:hover {
  color: var(--ink);
  background: var(--tone-2);
}

.cbtn {
  font: inherit;
  font-size: 12.5px;
  padding: 6px 12px;
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  background: var(--surface);
  color: var(--ink-2);
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.cbtn:hover {
  background: var(--tone-2);
}
.cbtn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.cbtn-solid {
  background: var(--brand);
  border-color: var(--brand);
  color: #fbf8ee;
}
.cbtn-solid:hover {
  background: var(--brand-hover);
}
.cbtn-quiet {
  border-color: transparent;
  color: var(--muted);
}
.cbtn-quiet:hover {
  color: var(--accent);
  background: var(--red-soft);
}

/* ---------- 主体两栏 ---------- */
.cbody {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr);
  min-height: calc(100vh - 45px);
}

.clist {
  border-right: 1px solid var(--line);
  padding: 14px 10px 40px;
  background: var(--tone-1);
}
.clist-search input {
  width: 100%;
  font: inherit;
  font-size: 12.5px;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--surface);
  color: var(--ink);
}
.clist-search input:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
.clist-empty {
  font-size: 12px;
  color: var(--muted);
  padding: 14px 6px;
}
.clist-item {
  display: block;
  width: 100%;
  text-align: left;
  font: inherit;
  padding: 10px 10px;
  margin-top: 6px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
}
.clist-item:hover {
  background: var(--tone-2);
}
.clist-item.is-active {
  background: var(--surface);
  border-color: var(--line-strong);
}
.clist-item b {
  display: block;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.45;
}
.clist-item span {
  display: block;
  font-size: 11.5px;
  color: var(--muted);
  margin-top: 3px;
}

.cmain {
  padding: 26px 32px 64px;
  max-width: 1080px;
}

/* ---------- 头部 ---------- */
.chead {
  border-bottom: 1px solid var(--line);
  padding-bottom: 18px;
}
.eyebrow {
  font-size: 11.5px;
  letter-spacing: 0.16em;
  color: var(--accent);
  margin: 0 0 8px;
}
.chead-title {
  font-size: 26px;
  font-weight: 500;
  line-height: 1.3;
  margin: 0 0 8px;
}
.chead-subj {
  font-size: 14px;
  margin: 0 0 6px;
}
.chead-subj b {
  font-weight: 500;
}
.chead-auto {
  font-size: 11.5px;
  color: var(--muted);
  margin-left: 8px;
  padding: 1px 6px;
  border: 1px dashed var(--line-strong);
  border-radius: 3px;
}
.chead-note {
  font-size: 12.5px;
  color: var(--muted);
  margin: 6px 0 0;
  max-width: 72ch;
  line-height: 1.65;
}
.chead-actions {
  display: flex;
  gap: 8px;
  margin-top: 14px;
  flex-wrap: wrap;
}

.editform {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 14px;
  margin-top: 14px;
  padding: 14px 16px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 4px;
}
.editform label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
  color: var(--muted);
}
.editform-wide {
  grid-column: 1 / -1;
}
.editform input {
  font: inherit;
  font-size: 13px;
  padding: 6px 9px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--tone-1);
  color: var(--ink);
}

/* ---------- 新建表单 ---------- */
.newform {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 18px 20px;
  margin-bottom: 22px;
}
.newform-title {
  font-size: 15px;
  font-weight: 500;
  margin: 0 0 12px;
}
.newform-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 12px;
}
.newform label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
  color: var(--muted);
}
.newform-note {
  margin-top: 12px;
}
.newform input {
  font: inherit;
  font-size: 13px;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--tone-1);
  color: var(--ink);
}
.newform-actions {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}

/* ---------- 指标 ---------- */
.cmetrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 1px;
  background: var(--line);
  border: 1px solid var(--line);
  border-radius: 4px;
  overflow: hidden;
  margin: 20px 0 24px;
}
.cmetric {
  background: var(--surface);
  padding: 14px 16px;
}
.cmetric b {
  display: block;
  font-size: 24px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.cmetric span {
  font-size: 11.5px;
  color: var(--muted);
}
.cmetric span i {
  font-style: normal;
  color: var(--faint);
}
.cmetric.is-warn b {
  color: var(--accent);
}

/* ---------- 页签 ---------- */
.ctabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--line);
}
.ctab {
  font: inherit;
  font-size: 13px;
  padding: 8px 14px;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  margin-bottom: -1px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ctab:hover {
  color: var(--ink);
}
.ctab.is-active {
  color: var(--ink);
  border-bottom-color: var(--accent);
}
.ctab:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.ctab-count {
  font-size: 11px;
  color: var(--faint);
  font-variant-numeric: tabular-nums;
}

.cpanel {
  padding-top: 18px;
}
.chint {
  font-size: 12.5px;
  color: var(--muted);
  line-height: 1.7;
  margin: 0 0 14px;
}
.chint b {
  color: var(--ink-2);
  font-weight: 500;
}
.cempty-line {
  font-size: 13px;
  color: var(--muted);
  padding: 22px 0;
  line-height: 1.75;
  max-width: 70ch;
}

/* ---------- 直接结论表 ---------- */
.dtable {
  border: 1px solid var(--line);
  border-radius: 4px;
  overflow: hidden;
  background: var(--surface);
}
.drow {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(0, 0.8fr) minmax(0, 1.3fr) 96px 76px;
  gap: 10px;
  align-items: baseline;
  width: 100%;
  padding: 9px 14px;
  font: inherit;
  font-size: 12.5px;
  text-align: left;
}
.drow-head {
  background: var(--tone-3);
  color: var(--muted);
  font-size: 11.5px;
  letter-spacing: 0.02em;
}
.drow-body {
  border: none;
  border-top: 1px solid var(--line);
  background: transparent;
  cursor: pointer;
  color: var(--ink);
}
.drow-body:hover {
  background: var(--tone-2);
}
.drow-body:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.dcell-entity {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.drel {
  font-style: normal;
  font-size: 11.5px;
  padding: 1px 7px;
  border-radius: 3px;
  background: var(--tone-3);
  color: var(--ink-2);
  white-space: nowrap;
}
.dcell-num {
  font-variant-numeric: tabular-nums;
  color: var(--ink-2);
}
.dweak {
  display: inline-block;
  font-style: normal;
  font-size: 10px;
  color: var(--warn);
  margin-left: 4px;
  border: 1px solid #e8d5b8;
  border-radius: 2px;
  padding: 0 3px;
}
.dsources {
  border-top: 1px dashed var(--line-strong);
  background: var(--tone-1);
  padding: 12px 16px 14px;
}
.dsources-title {
  font-size: 11.5px;
  color: var(--muted);
  margin: 0 0 8px;
}
.dsources ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.dsources li {
  font-size: 12px;
  line-height: 1.7;
  padding: 5px 0 5px 12px;
  position: relative;
  border-top: 1px solid var(--line);
}
.dsources li:first-child {
  border-top: none;
}
.dsources li:before {
  content: '·';
  position: absolute;
  left: 0;
  color: var(--accent);
}
.dsources b {
  font-weight: 500;
}
.dsources i {
  font-style: normal;
  color: var(--muted);
  margin-left: 6px;
  font-size: 11.5px;
}
.dsources q {
  display: block;
  color: var(--ink-2);
  quotes: '「' '」';
  margin-top: 2px;
}

/* ---------- 推断卡片 ---------- */
.cnotice {
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--ink-2);
  background: #fdf3f1;
  border: 1px solid #e8cfc9;
  border-radius: 4px;
  padding: 12px 16px;
  margin-bottom: 16px;
  max-width: 80ch;
}
.cnotice b {
  color: var(--accent);
  font-weight: 500;
}
.infcard {
  border: 1px dashed #b9ae95;
  background: #fbf8ef;
  border-radius: 4px;
  padding: 14px 18px;
  margin-bottom: 12px;
}
.infcard-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}
.infbadge {
  font-size: 10.5px;
  padding: 1px 7px;
  border-radius: 3px;
  border: 1px dashed var(--accent);
  color: var(--accent);
  white-space: nowrap;
}
.infbadge.is-weak {
  border-style: solid;
  border-color: var(--line-strong);
  color: var(--muted);
}
.infcard-line {
  font-size: 13.5px;
  display: inline-flex;
  align-items: baseline;
  gap: 7px;
  flex-wrap: wrap;
}
.infcard-line b {
  font-weight: 500;
}
.infcard-line em {
  font-style: normal;
  color: var(--accent);
  font-size: 12.5px;
}
.infcard-conf {
  margin-left: auto;
  font-size: 12px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.infcard-basis {
  font-size: 12.5px;
  color: var(--ink-2);
  margin: 8px 0 0;
}
.infcard-basis i {
  font-style: normal;
  color: var(--muted);
  margin-right: 8px;
}
.infpath {
  list-style: none;
  margin: 10px 0 0;
  padding: 0 0 0 14px;
  border-left: 1px solid var(--line-strong);
}
.infpath li {
  font-size: 12px;
  line-height: 1.65;
  padding: 6px 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.infpath-eq {
  color: var(--ink);
}
.infpath-eq em {
  font-style: normal;
  color: var(--accent);
  padding: 0 3px;
}
.infpath-src {
  color: var(--muted);
  font-size: 11.5px;
}
.infpath-q {
  color: var(--faint);
  quotes: '「' '」';
  font-size: 11.5px;
}
.infcard-caveat {
  font-size: 11.5px;
  color: var(--muted);
  line-height: 1.7;
  margin: 10px 0 0;
}

/* ---------- 疑点 ---------- */
.amblist {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 4px;
  overflow: hidden;
  background: var(--surface);
}
.amblist li {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  border-top: 1px solid var(--line);
}
.amblist li:first-child {
  border-top: none;
}
.ambtag {
  flex: none;
  font-size: 10.5px;
  padding: 1px 7px;
  border-radius: 3px;
  align-self: flex-start;
  margin-top: 2px;
  background: var(--tone-3);
  color: var(--muted);
}
.lv-high .ambtag {
  background: var(--red-soft);
  color: var(--accent);
}
.lv-medium .ambtag {
  background: #fdf0d5;
  color: #8a5a10;
}
.ambtitle {
  font-size: 13px;
  margin: 0;
  line-height: 1.6;
}
.ambdetail {
  font-size: 12px;
  color: var(--muted);
  margin: 3px 0 0;
  line-height: 1.65;
}

/* ---------- 材料 ---------- */
.matbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 12.5px;
  color: var(--muted);
  margin-bottom: 12px;
}
.matlist {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 4px;
  overflow: hidden;
  background: var(--surface);
}
.matlist li {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-top: 1px solid var(--line);
}
.matlist li:first-child {
  border-top: none;
}
.mat-main {
  flex: 1;
  min-width: 0;
}
.mat-main b {
  display: block;
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mat-meta {
  font-size: 11.5px;
  color: var(--muted);
}
.mat-role {
  flex: none;
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 3px;
  background: var(--tone-3);
  color: var(--ink-2);
}
.mat-open,
.mat-remove {
  flex: none;
  font-size: 11.5px;
  color: var(--muted);
  text-decoration: none;
  background: none;
  border: none;
  font-family: inherit;
  cursor: pointer;
  padding: 2px 4px;
}
.mat-open:hover {
  color: var(--ink);
}
.mat-remove:hover {
  color: var(--accent);
}

/* ---------- 空态 / 加载 / 错误 ---------- */
.cempty {
  padding: 60px 0 0;
  max-width: 520px;
}
.cempty-art {
  width: 200px;
  height: 120px;
  display: block;
  margin-bottom: 20px;
}
.cempty h2 {
  font-size: 19px;
  font-weight: 500;
  margin: 0 0 8px;
}
.cempty p {
  font-size: 13px;
  color: var(--muted);
  line-height: 1.8;
  margin: 0 0 18px;
}
.cempty-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.cloading {
  font-size: 13px;
  color: var(--muted);
  padding: 40px 0;
}
.cerr {
  font-size: 12.5px;
  color: var(--accent);
  background: var(--red-soft);
  border: 1px solid #e8cfc9;
  border-radius: 4px;
  padding: 10px 14px;
  margin: 14px 0;
}

/* ---------- 抽屉 ---------- */
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(32, 30, 25, 0.32);
  display: flex;
  justify-content: flex-end;
  z-index: 60;
}
.drawer {
  width: min(460px, 100vw);
  background: var(--surface);
  border-left: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  padding: 18px 20px;
  overflow: hidden;
}
.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.drawer-head h2 {
  font-size: 15px;
  font-weight: 500;
  margin: 0;
}
.drawer-close {
  border: none;
  background: none;
  font-size: 22px;
  line-height: 1;
  color: var(--muted);
  cursor: pointer;
}
.drawer-close:hover {
  color: var(--ink);
}
.drawer-hint {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.7;
  margin: 10px 0 0;
}
.drawer-role {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--muted);
  margin: 14px 0 4px;
}
.drawer-role select {
  font: inherit;
  font-size: 12.5px;
  padding: 5px 8px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--tone-1);
  color: var(--ink);
}
.picklist {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  overflow-y: auto;
  flex: 1;
  border-top: 1px solid var(--line);
}
.picklist li {
  border-bottom: 1px solid var(--line);
}
.picklist label {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 10px;
  align-items: center;
  padding: 9px 2px;
  cursor: pointer;
  font-size: 12.5px;
}
.picklist label:hover {
  background: var(--tone-1);
}
.pick-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pick-meta {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
}
.drawer-foot {
  display: flex;
  gap: 8px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
  margin-top: 10px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
.skip-link {
  position: absolute;
  left: -9999px;
  top: 0;
}
.skip-link:focus {
  left: 8px;
  top: 8px;
  z-index: 99;
  background: var(--surface);
  padding: 6px 10px;
  border: 1px solid var(--accent);
}

@media (max-width: 980px) {
  .cbody {
    grid-template-columns: 1fr;
  }
  .clist {
    border-right: none;
    border-bottom: 1px solid var(--line);
    display: flex;
    gap: 6px;
    overflow-x: auto;
    padding: 10px 12px;
  }
  .clist-search {
    flex: none;
    width: 160px;
  }
  .clist-item {
    flex: none;
    width: 180px;
    margin-top: 0;
  }
  .cmain {
    padding: 20px 18px 56px;
  }
  .drow {
    grid-template-columns: minmax(0, 1fr) minmax(0, 0.7fr) minmax(0, 1fr) 64px;
    grid-template-areas:
      'h r t c'
      's s s s';
  }
  .drow > :nth-child(4) {
    display: none;
  }
  .editform,
  .newform-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 560px) {
  .cbar-name,
  .cbar-sep,
  .cbar-current {
    display: none;
  }
  .cbar {
    padding: 8px 12px;
    gap: 6px;
  }
  .chead-title {
    font-size: 21px;
  }
  /* 窄屏改成卡片式：头一行、尾一行、关系与置信度并排，比四行堆叠省一半高度 */
  .drow {
    grid-template-columns: 1fr auto;
    grid-template-areas:
      'h h'
      't t'
      'r c';
    gap: 2px 8px;
  }
  .drow-head {
    display: none;
  }
  .drow-body {
    padding: 10px 14px;
  }
  .drow-body > :nth-child(1) {
    grid-area: h;
  }
  .drow-body > :nth-child(2) {
    grid-area: r;
    justify-self: start;
  }
  .drow-body > :nth-child(3) {
    grid-area: t;
  }
  .drow-body > :nth-child(5) {
    grid-area: c;
  }
  .cmetric:last-child:nth-child(odd) {
    grid-column: 1 / -1;
  }
  .matlist li {
    flex-wrap: wrap;
  }
}

@media (prefers-reduced-motion: reduce) {
  .cbtn,
  .clist-item,
  .drow-body {
    transition: none;
  }
}
</style>
