import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8090'
const LOG_WS = import.meta.env.VITE_WS_LOGS || 'ws://localhost:8090/ws/logs'
const METRICS_WS = import.meta.env.VITE_WS_METRICS || 'ws://localhost:8090/ws/metrics'

const client = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 5000,
})

export const getHealth = () => client.get('/health').then((r) => r.data)
export const getReadiness = () => client.get('/readiness').then((r) => r.data)

export const fetchMetricsRaw = async () => {
  const res = await client.get('/metrics', { responseType: 'text' })
  return res.data
}

export const parsePrometheus = (text) => {
  const lines = (text || '').split('\n')
  const data = {}
  for (const line of lines) {
    if (!line || line.startsWith('#')) continue
    const [key, value] = line.split(/\s+/)
    if (key && value !== undefined) {
      const num = Number(value)
      data[key] = Number.isNaN(num) ? value : num
    }
  }
  return data
}

export const getMetrics = async () => parsePrometheus(await fetchMetricsRaw())

export const sendMessage = async ({ text, chat_id = 'web', mode = 'auto' }) => {
  const res = await client.post(
    '/message',
    { text, chat_id, mode },
    {
      headers: { 'X-LLM-Mode': mode },
      timeout: 8000,
    },
  )
  return res.data
}

export const getLogWebSocketUrl = () => LOG_WS
export const getMetricsWebSocketUrl = () => METRICS_WS

export default client
