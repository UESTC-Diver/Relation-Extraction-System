<template>
  <div class="graph">
    <div class="graph-toolbar">
      <div class="gt-left">
        <el-radio-group v-model="layout" size="small" aria-label="图谱布局">
          <el-radio-button value="force">力导向</el-radio-button>
          <el-radio-button value="circular">环形</el-radio-button>
        </el-radio-group>
        <el-checkbox v-model="showEdgeLabel" size="small">关系标签</el-checkbox>
        <el-checkbox v-model="mergeNodes" size="small">合并同义实体</el-checkbox>
      </div>
      <div class="gt-right">
        <span class="gt-hint">点节点可下钻到三元组</span>
        <span class="gt-count">{{ nodes.length }} 节点 · {{ edges.length }} 边</span>
        <el-button :icon="Refresh" @click="relayout">重新布局</el-button>
        <el-button :icon="Picture" @click="savePng">导出图片</el-button>
      </div>
    </div>

    <div class="graph-canvas-wrap">
      <div
        ref="canvasRef"
        class="graph-canvas"
        tabindex="0"
        role="application"
        aria-label="关系图谱。左右方向键逐个选中节点，回车查看该实体的三元组"
        @keydown="onCanvasKeydown"
      ></div>

      <p class="sr-only" aria-live="polite">{{ kbdStatus }}</p>

      <div v-if="!edges.length" class="graph-empty">
        <el-empty description="没有可绘制的关系，换一段文本试试" :image-size="80" />
      </div>

      <div v-if="kbdLabel" class="kbd-chip" aria-hidden="true">{{ kbdLabel }}</div>

      <div v-if="categories.length" class="graph-legend">
        <span v-for="c in categories" :key="c.name" class="gl-item">
          <i :style="{ background: c.itemStyle.color }"></i>{{ c.name }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { Picture, Refresh } from '@element-plus/icons-vue'

const props = defineProps({
  relations: { type: Array, default: () => [] },
  schema: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['focus-entity'])

const canvasRef = ref(null)
const layout = ref('force')
// 默认不显示连线标签：多条关系指向同一对节点时标签必然互相压字，
// 关系名交给悬停提示和三元组表格，勾选可随时打开
const showEdgeLabel = ref(false)
const mergeNodes = ref(true)
const kbdIndex = ref(-1)
const kbdStatus = ref('')

let chart = null
let observer = null
let pointerStart = null

const entityMap = computed(() => {
  const map = {}
  for (const t of props.schema.entity_types || []) map[t.key] = t
  return map
})

const relMap = computed(() => {
  const map = {}
  for (const r of props.schema.relation_types || []) map[r.key] = r
  return map
})

function typeLabel(type) {
  return entityMap.value[type]?.label || type
}

function typeColor(type) {
  return entityMap.value[type]?.color || '#94a3b8'
}

const graphData = computed(() => {
  const nodeMap = new Map()
  const edges = []

  const addNode = (rawName, type, canonical) => {
    const display = mergeNodes.value && canonical ? canonical : rawName
    const key = `${type}::${display}`
    if (!nodeMap.has(key)) {
      nodeMap.set(key, { key, name: display, type, degree: 0, raw: [rawName] })
    } else if (!nodeMap.get(key).raw.includes(rawName)) {
      nodeMap.get(key).raw.push(rawName)
    }
    return key
  }

  for (const r of props.relations) {
    const source = addNode(r.head, r.head_type, r.head_canonical)
    const target = addNode(r.tail, r.tail_type, r.tail_canonical)
    if (source === target) continue
    nodeMap.get(source).degree += 1
    nodeMap.get(target).degree += 1
    edges.push({
      source,
      target,
      relation: r.relation,
      label: r.relation_label,
      confidence: r.confidence,
      evidence: r.evidence,
      color: relMap.value[r.relation]?.color || '#6366f1',
    })
  }
  return { nodes: [...nodeMap.values()], edges }
})

const nodes = computed(() => graphData.value.nodes)
const edges = computed(() => graphData.value.edges)

const kbdLabel = computed(() => {
  const n = nodes.value[kbdIndex.value]
  if (!n) return ''
  return `${n.name} · ${typeLabel(n.type)} · ${n.degree} 条关系（回车下钻）`
})

const categories = computed(() => {
  const seen = []
  for (const n of nodes.value) {
    if (seen.some((c) => c.name === typeLabel(n.type))) continue
    seen.push({ name: typeLabel(n.type), itemStyle: { color: typeColor(n.type) } })
  }
  return seen
})

function buildOption() {
  const categoryIndex = new Map(categories.value.map((c, i) => [c.name, i]))
  const nodeData = nodes.value.map((n) => ({
    id: n.key,
    name: n.name,
    category: categoryIndex.get(typeLabel(n.type)) ?? 0,
    symbolSize: 16 + Math.min(16, n.degree * 4),
    value: n.degree,
    itemStyle: {
      color: typeColor(n.type),
      borderColor: '#fffdf6',
      borderWidth: 2,
      shadowBlur: 10,
      shadowColor: 'rgba(16,18,22,0.10)',
    },
    tooltip: { formatter: `${n.name}<br/>类型：${typeLabel(n.type)}<br/>关联关系：${n.degree} 条` },
    label: {
      show: true,
      position: 'bottom',
      distance: 7,
      fontSize: 11.5,
      color: '#1e1c18',
      fontWeight: 500,
      textBorderColor: 'rgba(255,253,246,0.95)',
      textBorderWidth: 3,
    },
  }))

  const edgeData = edges.value.map((e) => ({
    source: e.source,
    target: e.target,
    value: e.label,
    lineStyle: {
      color: e.color,
      width: 1 + Math.min(1.2, e.confidence),
      opacity: 0.55,
      curveness: 0.1,
    },
    label: {
      show: showEdgeLabel.value,
      formatter: e.label,
      position: 'middle',
      rotate: 0,
      fontSize: 10,
      color: '#615d52',
      backgroundColor: 'rgba(255,253,246,0.94)',
      borderColor: 'rgba(16,18,22,0.06)',
      borderWidth: 1,
      padding: [1.5, 4],
      borderRadius: 3,
    },
    tooltip: {
      formatter: `<b>${e.label}</b><br/>${truncate(e.evidence, 46)}<br/>置信度 ${(e.confidence * 100).toFixed(0)}%`,
    },
  }))

  return {
    backgroundColor: 'transparent',
    animationDuration: 480,
    tooltip: {
      confine: true,
      backgroundColor: 'rgba(32,30,25,0.94)',
      borderWidth: 0,
      textStyle: { color: '#f6f3ea', fontSize: 12 },
      extraCssText: 'border-radius:8px;padding:8px 11px;box-shadow:0 10px 28px -12px rgba(0,0,0,.5);',
    },
    series: [
      {
        type: 'graph',
        layout: layout.value,
        data: nodeData,
        links: edgeData,
        categories: categories.value,
        roam: true,
        draggable: true,
        scaleLimit: { min: 0.4, max: 3 },
        emphasis: {
          focus: 'adjacency',
          scale: 1.06,
          lineStyle: { width: 2.2, opacity: 0.95 },
          label: { fontWeight: 600 },
        },
        blur: {
          itemStyle: { opacity: 0.28 },
          lineStyle: { opacity: 0.12 },
          label: { opacity: 0.35 },
        },
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: [0, 6],
        // 节点名互相挤开而不是直接隐藏 —— 藏掉名字比挤开更糟
        labelLayout: { hideOverlap: false, moveOverlap: 'shiftY' },
        force:
          layout.value === 'force'
            ? {
                repulsion: 900,
                edgeLength: [110, 175],
                gravity: 0.12,
                friction: 0.2,
                layoutAnimation: true,
              }
            : undefined,
        circular: layout.value === 'circular' ? { rotateLabel: true } : undefined,
        lineStyle: { opacity: 0.55 },
      },
    ],
  }
}

function truncate(str, n) {
  if (!str) return ''
  return str.length > n ? `${str.slice(0, n)}…` : str
}

function render() {
  if (!chart) return
  if (!nodes.value.length) {
    chart.clear()
    return
  }
  chart.setOption(buildOption(), true)
  kbdIndex.value = -1
  kbdStatus.value = ''
}

function relayout() {
  if (chart && nodes.value.length) {
    render()
    chart.resize()
  }
}

/** 返回当前图谱的 PNG dataURL，无图时返回 null。供结果面板的导出菜单调用。 */
function snapshot() {
  if (!chart || !edges.value.length) return null
  return chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fffdf6' })
}

function savePng() {
  const url = snapshot()
  if (!url) {
    ElMessage.warning('当前没有可导出的关系图')
    return
  }
  const a = document.createElement('a')
  a.href = url
  a.download = `关系图谱_${new Date().toISOString().slice(0, 10)}.png`
  a.click()
  ElMessage.success('关系图已导出')
}

/* ---------- 点节点下钻 ---------- */
function drill(node) {
  if (!node) return
  emit('focus-entity', { name: node.name, type: node.type, key: node.key })
}

/* ---------- 键盘浏览：方向键选节点，回车下钻 ---------- */
function onCanvasKeydown(event) {
  const list = nodes.value
  if (!list.length) return
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
    event.preventDefault()
    kbdIndex.value = (kbdIndex.value + 1) % list.length
    applyKbdHighlight()
  } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
    event.preventDefault()
    kbdIndex.value = kbdIndex.value <= 0 ? list.length - 1 : kbdIndex.value - 1
    applyKbdHighlight()
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    drill(list[kbdIndex.value])
  }
}

function applyKbdHighlight() {
  const n = nodes.value[kbdIndex.value]
  if (!chart || !n) return
  chart.dispatchAction({ type: 'downplay', seriesIndex: 0 })
  chart.dispatchAction({ type: 'highlight', seriesIndex: 0, name: n.name })
  kbdStatus.value = `${n.name}，${typeLabel(n.type)}，${n.degree} 条关系，回车查看三元组`
}

defineExpose({ snapshot })

onMounted(async () => {
  await nextTick()
  if (canvasRef.value) {
    chart = echarts.init(canvasRef.value)
    render()
    observer = new ResizeObserver(() => chart && chart.resize())
    observer.observe(canvasRef.value)

    // 拖拽节点后松手也会触发 click —— 用位移阈值挡掉，避免误下钻
    chart.getZr().on('mousedown', (e) => {
      pointerStart = { x: e.offsetX, y: e.offsetY }
    })
    chart.on('click', (params) => {
      if (params.dataType !== 'node') return
      if (pointerStart) {
        const dx = Math.abs(params.event?.offsetX - pointerStart.x || 0)
        const dy = Math.abs(params.event?.offsetY - pointerStart.y || 0)
        if (dx + dy > 6) return
      }
      drill(nodes.value.find((n) => n.name === params.name))
    })
  }
})

onBeforeUnmount(() => {
  if (observer) observer.disconnect()
  if (chart) {
    chart.dispose()
    chart = null
  }
})

watch(() => props.relations, render, { deep: true })
watch([layout, showEdgeLabel, mergeNodes], render)
</script>

<style scoped>
.graph {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-height: 0;
}

.graph-toolbar {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.gt-left,
.gt-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.gt-hint {
  font-size: 11px;
  color: var(--muted);
}

.gt-count {
  font-size: 11.5px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.graph-toolbar :deep(.el-button) {
  height: 28px;
  padding: 0 10px;
  font-size: 12px;
  border-radius: var(--r-sm);
}

.graph-toolbar :deep(.el-radio-button__inner) {
  height: 28px;
  padding: 0 11px;
  font-size: 12px;
  line-height: 1;
  border-radius: var(--r-sm);
  box-shadow: none;
}

.graph-toolbar :deep(.el-radio-button:first-child .el-radio-button__inner) {
  border-radius: var(--r-sm) 0 0 var(--r-sm);
}

.graph-toolbar :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
}

.graph-toolbar :deep(.el-checkbox__label) {
  font-size: 12px;
  color: var(--ink-2);
}

.graph-canvas-wrap {
  position: relative;
  flex: 1;
  min-height: 320px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background-color: var(--surface);
  background-image: radial-gradient(circle at 1px 1px, #eef0f2 1px, transparent 0);
  background-size: 18px 18px;
  overflow: hidden;
}

.graph-canvas {
  width: 100%;
  height: 100%;
  outline-offset: -2px;
}

.graph-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgba(255, 253, 246, 0.86);
}

/* 键盘选中的节点说明 */
.kbd-chip {
  position: absolute;
  top: 10px;
  left: 10px;
  max-width: calc(100% - 20px);
  padding: 4px 9px;
  font-size: 11.5px;
  color: var(--ink);
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  box-shadow: 0 2px 8px rgba(16, 18, 22, 0.06);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.graph-legend {
  position: absolute;
  left: 10px;
  bottom: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 5px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(4px);
  font-size: 11px;
  color: var(--ink-2);
}

.gl-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.gl-item i {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 2px;
}
</style>
