import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    // 主动取消不算失败，原样透传，交给调用方按 AbortController 状态判断
    if (err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') {
      return Promise.reject(err)
    }
    const detail = err?.response?.data?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg).join('；')
          : err.message || '请求失败'
    return Promise.reject(new Error(message))
  },
)

export const health = () => http.get('/health')

// options.signal 来自调用方的 AbortController：改了文本又重抽、或清空结果时，
// 在途请求要能取消，不能让旧响应回来覆盖新结果。
export const extractText = (text, title = '', save = true, options = {}) =>
  http.post(
    '/extract',
    { text, title, save, profile: options.profile || 'general' },
    { signal: options.signal },
  )

export const extractFile = (file, save = true, options = {}) => {
  const form = new FormData()
  form.append('file', file)
  return http.post(
    `/extract/file?save=${save}&profile=${encodeURIComponent(options.profile || 'general')}`,
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      signal: options.signal,
    },
  )
}

export const getSamples = () => http.get('/samples')

export const getSchema = () => http.get('/schema')

export const getStats = () => http.get('/stats')

export const getRecords = (params = {}) => http.get('/records', { params })

export const getRecord = (id) => http.get(`/records/${id}`)

export const saveSnapshot = (result, title = '', source = 'text') =>
  http.post('/records', { result, title, source })

export const saveRelations = (id, relations) =>
  http.put(`/records/${id}/relations`, { relations })

export const deleteRecord = (id) => http.delete(`/records/${id}`)

export const clearRecords = () => http.delete('/records')

// 批量抽取：一次提交多篇，服务端逐篇分析并返回跨文档聚合
export const batchExtract = (items, save = true, options = {}) =>
  http.post(
    '/extract/batch',
    { items, save, profile: options.profile || 'general' },
    { signal: options.signal },
  )

export const batchExtractFiles = (files, save = true, options = {}) => {
  const form = new FormData()
  for (const file of files) form.append('files', file)
  return http.post(
    `/extract/batch/files?save=${save}&profile=${encodeURIComponent(options.profile || 'general')}`,
    form,
    {
    headers: { 'Content-Type': 'multipart/form-data' },
    signal: options.signal,
    onUploadProgress: options.onProgress,
  })
}

// 自定义关系触发词
export const getRules = () => http.get('/rules')

export const addRule = (relationKey, trigger) =>
  http.post('/rules', { relation_key: relationKey, trigger })

export const deleteRule = (id) => http.delete(`/rules/${id}`)

export const clearRules = () => http.delete('/rules')

export const getDictionary = () => http.get('/dictionary')

export const addDictionaryTerm = (text, type = 'ORG') =>
  http.post('/dictionary', { text, type })

export const deleteDictionaryTerm = (id) => http.delete(`/dictionary/${id}`)

export const clearDictionary = () => http.delete('/dictionary')

/* ---------- 知识库：跨文档检索、全局图谱、标签、冲突与复核 ---------- */
export const getEntities = (params = {}) => http.get('/entities', { params })
export const getEntityProfile = (name) =>
  http.get('/entities/profile', { params: { name } })
export const getGlobalGraph = (params = {}) => http.get('/graph/global', { params })
export const getTags = () => http.get('/tags')
export const setRecordTags = (id, tags) => http.put(`/records/${id}/tags`, { tags })
export const getConflicts = (params = {}) => http.get('/conflicts', { params })
export const getReviewQueue = (params = {}) => http.get('/review', { params })

/* ---------- 质量闭环：评测台、规则实验室、实体校正 ---------- */
export const getEvalGold = () => http.get('/eval/gold')
export const runEval = (payload = {}) => http.post('/eval', payload)
export const getEvalRuns = () => http.get('/eval/runs')
export const getEvalRun = (id) => http.get(`/eval/runs/${id}`)

// 标注：把「规则准不准」变成能在自己材料上复现的结论
export const getAnnotationSets = () => http.get('/annotation/sets')
export const createAnnotationSet = (payload) => http.post('/annotation/sets', payload)
export const getAnnotationSet = (id) => http.get(`/annotation/sets/${id}`)
export const deleteAnnotationSet = (id) => http.delete(`/annotation/sets/${id}`)
export const addAnnotationRecords = (id, recordIds) =>
  http.post(`/annotation/sets/${id}/records`, { record_ids: recordIds })
export const removeAnnotationRecords = (id, recordIds) =>
  http.delete(`/annotation/sets/${id}/records`, { data: { record_ids: recordIds } })
export const getAnnotationCoverage = (id) => http.get(`/annotation/sets/${id}/coverage`)
export const getRecordAnnotation = (recordId) => http.get(`/annotation/records/${recordId}`)
export const saveRecordAnnotation = (recordId, items) =>
  http.put(`/annotation/records/${recordId}`, { items })
export const clearRecordAnnotation = (recordId) => http.delete(`/annotation/records/${recordId}`)
export const trialRules = (payload) => http.post('/rules/trial', payload)
export const getInsights = () => http.get('/insights')
export const getProfiles = () => http.get('/profiles')
export const getRuleVersions = () => http.get('/rules/versions')
export const saveRuleVersion = (name) => http.post('/rules/versions', { name })
export const restoreRuleVersion = (id) => http.post(`/rules/versions/${id}/restore`)
export const saveEntities = (id, entities, corrections = []) =>
  http.put(`/records/${id}/entities`, { entities, corrections })

/* ---------- 交付：离线报告、项目包、后台任务 ---------- */
export const buildReport = (payload) => http.post('/report', payload)
export const exportProject = () => http.get('/project/export')
export const importProject = (payload, mode = 'merge') =>
  http.post('/project/import', { payload, mode })
export const submitBatchTask = (items, save = true, profile = 'general') =>
  http.post('/tasks/batch', { items, save, profile })
export const getTask = (id) => http.get(`/tasks/${id}`)
export const getTasks = () => http.get('/tasks')

/* ---------- 复核闭环：逐条结论、状态流转、定稿快照 ---------- */
export const getReviewState = (id) => http.get(`/records/${id}/review`)
export const saveReviewDecisions = (id, decisions, reviewer = '') =>
  http.put(`/records/${id}/review/decisions`, { decisions, reviewer })
export const setReviewStatus = (id, status) =>
  http.put(`/records/${id}/review/status`, { status })
export const finalizeReview = (id, title = '') =>
  http.post(`/records/${id}/review/finalize`, { title })
export const getReviewSnapshots = (id) => http.get(`/records/${id}/review/snapshots`)

/* ---------- 只读报告分享链接（带签名与有效期） ---------- */
export const createShareLink = (recordId, ttlSeconds = 7 * 24 * 3600) =>
  http.post('/report/share', { record_id: recordId, ttl_seconds: ttlSeconds })

export default http
