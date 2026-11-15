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
  http.post('/extract', { text, title, save }, { signal: options.signal })

export const extractFile = (file, save = true, options = {}) => {
  const form = new FormData()
  form.append('file', file)
  return http.post(`/extract/file?save=${save}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    signal: options.signal,
  })
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
  http.post('/extract/batch', { items, save }, { signal: options.signal })

export const batchExtractFiles = (files, save = true, options = {}) => {
  const form = new FormData()
  for (const file of files) form.append('files', file)
  return http.post(`/extract/batch/files?save=${save}`, form, {
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

export default http
