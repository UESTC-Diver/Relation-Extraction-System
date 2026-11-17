<template>
  <el-dialog
    :model-value="modelValue"
    width="960px"
    append-to-body
    class="kb-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="loadAll"
  >
    <template #header>
      <div class="kb-head">
        <span class="kb-title">知识库</span>
        <span class="kb-sub">跨全部历史记录检索实体、关系与证据</span>
      </div>
    </template>

    <div class="kb-tabs" role="tablist" aria-label="知识库视图">
      <button
        v-for="t in TABS"
        :key="t.key"
        type="button"
        role="tab"
        :aria-selected="tab === t.key ? 'true' : 'false'"
        :class="{ 'is-active': tab === t.key }"
        @click="tab = t.key"
      >{{ t.label }}</button>
    </div>

    <!-- 全局实体检索 + 画像 -->
    <div v-if="tab === 'entities'" class="kb-pane">
      <div class="kb-search">
        <el-input
          v-model="q"
          placeholder="输入实体名，如「腾讯」"
          clearable
          aria-label="检索实体"
          @keyup.enter="searchEntities"
        />
        <el-select v-model="typeFilter" placeholder="全部类型" clearable style="width: 148px" aria-label="实体类型">
          <el-option v-for="t in entityTypes" :key="t.key" :label="t.label" :value="t.key" />
        </el-select>
        <el-button type="primary" @click="searchEntities">检索</el-button>
        <span class="kb-count">共 {{ entityTotal }} 个实体</span>
      </div>
      <div class="kb-split">
        <el-table :data="entities" height="330" size="small" class="kb-table" @row-click="openEntity">
          <el-table-column prop="name" label="实体" min-width="130" />
          <el-table-column label="类型" width="90">
            <template #default="{ row }"><span class="kb-tag">{{ typeLabel(row.type) }}</span></template>
          </el-table-column>
          <el-table-column prop="count" label="出现" width="72" align="center" />
          <el-table-column prop="documents" label="文档" width="72" align="center" />
          <el-table-column label="别名" min-width="130">
            <template #default="{ row }">
              <span class="kb-muted">{{ row.aliases.length ? row.aliases.join('、') : '—' }}</span>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="profile" class="kb-profile">
          <h3>{{ profile.name }} <span class="kb-tag">{{ typeLabel(profile.type) }}</span></h3>
          <p class="kb-muted">出现 {{ profile.appearances }} 次 · {{ profile.documents.length }} 篇文档</p>
          <p v-if="profile.aliases.length" class="kb-muted">其他写法：{{ profile.aliases.join('、') }}</p>
          <h4>来源文档</h4>
          <div class="kb-chips">
            <button v-for="d in profile.documents" :key="d.id" class="kb-chip" type="button" @click="loadRecord(d.id)">
              #{{ d.id }} {{ d.title }}
            </button>
          </div>
          <h4>参与关系（{{ profile.relation_total }}）</h4>
          <div class="kb-rel-list">
            <p v-for="(r, i) in profile.relations.slice(0, 24)" :key="i" :title="r.evidence">
              <span :class="r.direction === 'out' ? 'kb-out' : 'kb-in'">{{ r.direction === 'out' ? '→' : '←' }}</span>
              {{ r.other }} <i>{{ r.relation_label }}</i>
              <button type="button" @click="loadRecord(r.record_id)">#{{ r.record_id }}</button>
            </p>
          </div>
          <button class="kb-link" type="button" @click="focusEntity(profile.name)">在工作台筛选这个实体 →</button>
        </div>
        <div v-else class="kb-profile kb-empty">点左侧任一行，查看它的别名、来源文档与全部关系。</div>
      </div>
    </div>

    <!-- 跨文档关系网络 -->
    <div v-else-if="tab === 'graph'" class="kb-pane">
      <div class="kb-search">
        <el-select v-model="graphRelation" placeholder="全部关系类型" clearable style="width: 190px" aria-label="关系类型">
          <el-option v-for="r in relationTypes" :key="r.key" :label="r.label" :value="r.key" />
        </el-select>
        <el-button @click="loadGraph">刷新网络</el-button>
        <span class="kb-count">{{ graph.node_count }} 个节点 · {{ graph.link_count }} 组关系</span>
      </div>
      <p class="kb-hint">按归一化写法合并同一实体，统计跨全部历史记录的出现次数。点节点名可直接下钻到工作台。</p>
      <div class="kb-split">
        <div class="kb-list">
          <h4>节点</h4>
          <button v-for="n in graph.nodes.slice(0, 40)" :key="n.id" class="kb-line" type="button" @click="focusEntity(n.name)">
            <b>{{ n.name }}</b><span>{{ typeLabel(n.type) }} · {{ n.count }} 次</span>
          </button>
        </div>
        <div class="kb-list">
          <h4>关系（按频次）</h4>
          <p v-for="(l, i) in graph.links.slice(0, 40)" :key="i" class="kb-line-static">
            {{ l.source }} <i>— {{ l.label }} →</i> {{ l.target }} <b>×{{ l.count }}</b>
            <span class="kb-muted">{{ l.documents }} 篇</span>
          </p>
        </div>
      </div>
    </div>

    <!-- 标签、冲突与低置信度复核 -->
    <div v-else class="kb-pane">
      <div class="kb-columns">
        <div class="kb-list">
          <h4>标签</h4>
          <div class="kb-chips">
            <button v-for="t in tags" :key="t.tag" class="kb-chip" type="button" @click="tagFilter = t.tag">
              {{ t.tag }} <b>{{ t.count }}</b>
            </button>
            <span v-if="!tags.length" class="kb-muted">还没有标签</span>
          </div>
          <div v-if="activeRecordId" class="kb-tagform">
            <p class="kb-muted">给当前记录 #{{ activeRecordId }} 设置标签（逗号分隔）</p>
            <el-input v-model="tagInput" placeholder="并购, 互联网" aria-label="当前记录标签" />
            <el-button size="small" @click="saveTags">保存标签</el-button>
          </div>
          <p v-if="tagFilter" class="kb-muted">已选「{{ tagFilter }}」，可在历史记录里按标签筛选。</p>
        </div>
        <div class="kb-list">
          <h4>关系冲突（{{ conflicts.length }}）</h4>
          <p class="kb-hint">同一对实体在不同文档里被判成不同关系，值得人工复核。</p>
          <div v-for="(c, i) in conflicts.slice(0, 12)" :key="i" class="kb-conflict">
            <b>{{ c.head }} ↔ {{ c.tail }}</b>
            <span v-for="(item, j) in c.items.slice(0, 4)" :key="j" class="kb-tag">{{ item.relation_label }}</span>
            <button type="button" @click="loadRecord(c.items[0].record_id)">查看 #{{ c.items[0].record_id }}</button>
          </div>
          <p v-if="!conflicts.length" class="kb-muted">未发现冲突</p>
        </div>
      </div>
      <h4 class="kb-review-title">低置信度复核队列（{{ reviewTotal }} 条）</h4>
      <el-table :data="review" height="190" size="small" class="kb-table">
        <el-table-column prop="head" label="头实体" min-width="110" />
        <el-table-column prop="relation_label" label="关系" width="100" />
        <el-table-column prop="tail" label="尾实体" min-width="110" />
        <el-table-column prop="confidence" label="置信度" width="86" align="center" />
        <el-table-column label="证据" min-width="190">
          <template #default="{ row }"><span class="kb-muted">{{ row.evidence }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="94" align="center">
          <template #default="{ row }">
            <el-button link size="small" @click="loadRecord(row.record_id)">载入</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '../api/client'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  activeRecordId: { type: Number, default: null },
  schema: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue', 'load', 'focus'])

const TABS = [
  { key: 'entities', label: '全局实体' },
  { key: 'graph', label: '跨文档图谱' },
  { key: 'review', label: '标签与复核' },
]
const tab = ref('entities')
const q = ref('')
const typeFilter = ref('')
const graphRelation = ref('')
const entityTypes = ref([])
const relationTypes = ref([])
const entities = ref([])
const entityTotal = ref(0)
const profile = ref(null)
const graph = ref({ nodes: [], links: [], node_count: 0, link_count: 0 })
const tags = ref([])
const tagInput = ref('')
const tagFilter = ref('')
const conflicts = ref([])
const review = ref([])
const reviewTotal = ref(0)

const typeLabel = (key) => entityTypes.value.find((t) => t.key === key)?.label || key

async function searchEntities() {
  try {
    const res = await api.getEntities({ q: q.value.trim(), type: typeFilter.value || '', limit: 60 })
    entities.value = res.items
    entityTotal.value = res.total
  } catch (err) {
    ElMessage.error(`检索失败：${err.message}`)
  }
}

async function openEntity(row) {
  try {
    profile.value = await api.getEntityProfile(row.name)
  } catch (err) {
    ElMessage.error(`画像加载失败：${err.message}`)
  }
}

async function loadGraph() {
  try {
    graph.value = await api.getGlobalGraph({ relation: graphRelation.value || '', limit: 120 })
  } catch (err) {
    ElMessage.error(`图谱加载失败：${err.message}`)
  }
}

async function loadAll() {
  entityTypes.value = props.schema.entity_types || []
  relationTypes.value = props.schema.relation_types || []
  await Promise.all([
    searchEntities(), loadGraph(),
    api.getTags().then((r) => { tags.value = r.items }).catch(() => {}),
    api.getConflicts().then((r) => { conflicts.value = r.items }).catch(() => {}),
    api.getReviewQueue({ threshold: 0.8, limit: 50 })
      .then((r) => { review.value = r.items; reviewTotal.value = r.total }).catch(() => {}),
  ])
  if (props.activeRecordId) {
    try {
      const rec = await api.getRecord(props.activeRecordId)
      tagInput.value = (rec.tags || []).join(', ')
    } catch { /* 记录不存在时留空即可 */ }
  }
}

async function saveTags() {
  if (!props.activeRecordId) return
  const list = tagInput.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
  try {
    await api.setRecordTags(props.activeRecordId, list)
    tags.value = (await api.getTags()).items
    ElMessage.success(`已给 #${props.activeRecordId} 设置 ${list.length} 个标签`)
  } catch (err) {
    ElMessage.error(`保存失败：${err.message}`)
  }
}

function loadRecord(id) {
  if (!id) return
  emit('load', id)
  emit('update:modelValue', false)
}

function focusEntity(name) {
  emit('focus', name)
  emit('update:modelValue', false)
}

watch(graphRelation, () => loadGraph())
watch(typeFilter, () => searchEntities())
</script>

<style scoped>
.kb-head { display: flex; align-items: baseline; gap: 10px; }
.kb-title { font-size: 13.5px; font-weight: 600; color: var(--ink); }
.kb-sub { font-size: 11.5px; color: var(--muted); }
.kb-tabs { display: flex; gap: 6px; margin-bottom: 14px; border-bottom: 1px solid var(--line); }
.kb-tabs button {
  min-height: 34px; padding: 0 14px; font-size: 12.5px; font-family: inherit;
  color: var(--muted); background: transparent; border: none;
  border-bottom: 2px solid transparent; cursor: pointer;
  transition: color var(--dur-color) var(--ease), border-color var(--dur-color) var(--ease);
}
.kb-tabs button:hover { color: var(--ink); }
.kb-tabs button.is-active { color: var(--brand-red); border-bottom-color: var(--brand-red); }
.kb-search { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
.kb-count, .kb-muted { font-size: 11.5px; color: var(--muted); }
.kb-count { margin-left: auto; font-variant-numeric: tabular-nums; }
.kb-hint { margin: 0 0 10px; font-size: 11.5px; line-height: 1.6; color: var(--muted); }
.kb-split { display: grid; grid-template-columns: 1.25fr 1fr; gap: 14px; min-height: 330px; }
.kb-table { border: 1px solid var(--line); border-radius: var(--r-sm); font-size: 12px; }
.kb-tag {
  display: inline-block; padding: 1px 6px; margin-right: 4px; font-size: 11px;
  color: var(--ink-2); background: var(--surface-3); border-radius: var(--r-xs);
}
.kb-profile, .kb-list {
  padding: 12px 14px; border: 1px solid var(--line); border-radius: var(--r-sm);
  background: var(--surface-2); overflow: auto; max-height: 330px;
}
.kb-empty { display: grid; place-items: center; text-align: center; color: var(--muted); font-size: 12px; }
.kb-profile h3 { margin: 0 0 6px; font-size: 16px; font-weight: 500; color: var(--ink); }
.kb-profile h4, .kb-list h4 { margin: 14px 0 6px; font-size: 11.5px; font-weight: 600; color: var(--ink-2); }
.kb-profile p { margin: 2px 0; }
.kb-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.kb-chip {
  padding: 3px 8px; font-size: 11px; font-family: inherit; color: var(--ink-2);
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-xs); cursor: pointer;
}
.kb-chip:hover { border-color: var(--brand-red); color: var(--brand-red); }
.kb-chip b { color: var(--brand-red); font-variant-numeric: tabular-nums; }
.kb-rel-list p, .kb-line-static { margin: 0 0 4px; font-size: 11.5px; color: var(--ink-2); }
.kb-rel-list i, .kb-line-static i { font-style: normal; color: var(--brand-red); }
.kb-rel-list button, .kb-conflict button {
  border: none; background: transparent; color: var(--brand-red); cursor: pointer;
  font-size: 11px; font-family: inherit; padding: 0 2px;
}
.kb-out { color: var(--brand-red); }
.kb-in { color: var(--muted); }
.kb-link {
  margin-top: 12px; padding: 0; border: none; background: transparent;
  color: var(--brand-red); font-size: 11.5px; font-family: inherit; cursor: pointer;
}
.kb-line {
  display: flex; justify-content: space-between; gap: 10px; width: 100%; min-height: 30px;
  padding: 4px 6px; font-family: inherit; text-align: left; background: transparent;
  border: none; border-radius: var(--r-xs); cursor: pointer; color: var(--ink-2);
}
.kb-line:hover { background: var(--surface-3); }
.kb-line b, .kb-line-static b { font-size: 11.5px; font-weight: 500; }
.kb-line span { font-size: 11px; color: var(--muted); }
.kb-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.kb-tagform { margin-top: 12px; display: grid; gap: 8px; justify-items: start; }
.kb-conflict { margin-bottom: 8px; font-size: 11.5px; color: var(--ink-2); }
.kb-conflict b { display: block; font-weight: 500; }
.kb-review-title { margin: 16px 0 8px; font-size: 11.5px; font-weight: 600; color: var(--ink-2); }
@media (max-width: 720px) {
  .kb-split, .kb-columns { grid-template-columns: 1fr; }
  .kb-count { margin-left: 0; }
}
</style>
