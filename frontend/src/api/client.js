import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
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

export const extractText = (text, title = '', save = true) =>
  http.post('/extract', { text, title, save })

export const extractFile = (file, save = true) => {
  const form = new FormData()
  form.append('file', file)
  return http.post(`/extract/file?save=${save}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
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

export const getDictionary = () => http.get('/dictionary')

export const addDictionaryTerm = (text, type = 'ORG') =>
  http.post('/dictionary', { text, type })

export const deleteDictionaryTerm = (id) => http.delete(`/dictionary/${id}`)

export const clearDictionary = () => http.delete('/dictionary')

export default http
