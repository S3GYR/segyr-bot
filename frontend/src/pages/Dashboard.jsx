import React, { useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Bar, BarChart } from 'recharts'
import Spinner from '../components/Spinner'
import Card from '../components/Card'
import { getMetricsWebSocketUrl } from '../lib/api'
import useWebSocket from '../hooks/useWebSocket'

const POLL_INTERVAL_MS = 4000
const MAX_POINTS = 50

const fmt = (v, digits = 2) => (Number.isFinite(v) ? Number(v).toFixed(digits) : '0')

function statusColor(status) {
  if (status === 'ok') return 'text-[#10B981]'
  if (status === 'degraded') return 'text-[#F59E0B]'
  return 'text-[#EF4444]'
}

export default function Dashboard() {
  const [metrics, setMetrics] = useState({})
  const [seriesLatency, setSeriesLatency] = useState([])
  const [seriesRequests, setSeriesRequests] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const wsUrl = getMetricsWebSocketUrl()
  const { status: wsStatus, lastMessage, latencyMs: wsLatency } = useWebSocket(wsUrl)

  useEffect(() => {
    if (!lastMessage) return
    const data = lastMessage || {}
    setMetrics(data)
    const ts = data.timestamp ? new Date(data.timestamp * 1000).toLocaleTimeString('fr-FR', { hour12: false }) : new Date().toLocaleTimeString('fr-FR', { hour12: false })
    const latency = Number(data.llm_avg_latency_ms || data.request_latency_ms) || 0
    const req = Number(data.requests_total) || 0
    const fallback = Number(data.llm_fallbacks || data.fallback || 0) || 0
    setSeriesLatency((prev) => [...prev, { ts, latency }].slice(-MAX_POINTS))
    setSeriesRequests((prev) => [...prev, { ts, req, fallback }].slice(-MAX_POINTS))
    setError('')
    setLoading(false)
  }, [lastMessage])

  useEffect(() => {
    if (wsStatus === 'error') {
      setError('WebSocket métriques en erreur')
      setLoading(false)
    }
    if (wsStatus === 'open') {
      setError('')
    }
  }, [wsStatus])

  const cards = useMemo(() => {
    const req = metrics.segyr_requests_total ?? metrics.requests_total ?? 0
    const llmReq = metrics.segyr_llm_requests_total ?? metrics.llm_requests_total ?? 0
    const fallback = metrics.segyr_llm_fallback_total ?? metrics.llm_fallbacks ?? 0
    const queue = metrics.segyr_queue_inbound_depth ?? metrics.queue_inbound_depth ?? 0
    const queueMax = metrics.segyr_queue_inbound_max ?? metrics.queue_inbound_max ?? 0
    const rejected = metrics.segyr_requests_rejected_busy ?? metrics.rejected_busy ?? 0
    return [
      { title: 'Requêtes HTTP', value: req, accent: 'text-[#3B82F6]' },
      { title: 'LLM requêtes', value: llmReq, accent: 'text-[#10B981]' },
      { title: 'Fallbacks', value: fallback, accent: 'text-[#F59E0B]' },
      { title: 'Queue inbound', value: `${queue}/${queueMax || '?'} (rej:${rejected})`, accent: 'text-[#22d3ee]' },
    ]
  }, [metrics])

  const latencyCards = useMemo(() => {
    return [
      { label: 'Latence moy. (ms)', value: fmt(metrics.segyr_llm_avg_latency_ms ?? metrics.llm_avg_latency_ms) },
      { label: 'Latence primary (ms)', value: fmt(metrics.segyr_llm_avg_latency_primary_ms ?? metrics.llm_avg_latency_primary_ms) },
      { label: 'Latence secondary (ms)', value: fmt(metrics.segyr_llm_avg_latency_secondary_ms ?? metrics.llm_avg_latency_secondary_ms) },
      { label: 'Latence fast (ms)', value: fmt(metrics.segyr_llm_avg_latency_fast_ms ?? metrics.llm_avg_latency_fast_ms) },
    ]
  }, [metrics])

  return (
    <div className="space-y-6">
      <Card className="p-5 shadow-xl shadow-black/30" hover={false}>
        <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-100">SEGYR BOT · Dashboard</h1>
            <p className="text-sm text-slate-400">Observabilité temps réel · WebSocket métriques.</p>
          </div>
          <div className="flex items-center gap-3 text-sm text-slate-400">
            <span className={`h-2 w-2 rounded-full ${wsStatus === 'open' ? 'bg-[#10B981]' : 'bg-[#F59E0B]'} animate-pulse`} aria-hidden />
            {wsLatency != null && <span>WS {wsLatency.toFixed(0)} ms</span>}
            {error && <span className="text-danger">{error}</span>}
          </div>
        </div>
      </Card>

      {loading ? (
        <Spinner label="Chargement des métriques..." />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {cards.map((c) => (
              <Card key={c.title} className="p-4 shadow-lg shadow-black/20" hover>
                <p className="text-xs uppercase tracking-wide text-slate-400">{c.title}</p>
                <p className={`mt-2 text-2xl font-semibold ${c.accent}`}>{c.value}</p>
              </Card>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <ChartCard title="Latence LLM (ms)">
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={seriesLatency} margin={{ left: -20, right: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="ts" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1f2937' }} />
                  <Area type="monotone" dataKey="latency" stroke="#22d3ee" fill="#22d3ee22" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Requêtes & Fallbacks">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={seriesRequests} margin={{ left: -10, right: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="ts" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1f2937' }} />
                  <Bar dataKey="req" stackId="a" fill="#22d3ee" radius={[6, 6, 0, 0]} />
                  <Bar dataKey="fallback" stackId="a" fill="#f59e0b" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Latences par provider">
              <div className="flex flex-col gap-3">
                {latencyCards.map((c) => (
                  <div key={c.label} className="flex items-center justify-between rounded-xl border border-[#1F2937] bg-[#121826]/90 px-4 py-3">
                    <span className="text-sm text-slate-300">{c.label}</span>
                    <span className="text-lg font-semibold text-[#3B82F6]">{c.value}</span>
                  </div>
                ))}
              </div>
            </ChartCard>
          </div>

          <StatusGrid metrics={metrics} />
        </>
      )}
    </div>
  )
}

function ChartCard({ title, children }) {
  return (
    <div className="rounded-2xl border border-surface-border bg-surface-card/90 p-4 shadow-lg shadow-black/20">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-100">{title}</h3>
      </div>
      {children}
    </div>
  )
}

function StatusGrid({ metrics }) {
  const items = [
    {
      label: 'Gateway readiness',
      status: (metrics.segyr_requests_total || 0) >= 0 ? 'ok' : 'unknown',
      value: metrics.segyr_requests_total ?? 0,
    },
    {
      label: 'LLM fallback count',
      status: (metrics.segyr_llm_fallback_total || 0) > 0 ? 'degraded' : 'ok',
      value: metrics.segyr_llm_fallback_total ?? 0,
    },
    {
      label: 'Inbound queue depth',
      status:
        metrics.segyr_queue_inbound_max && metrics.segyr_queue_inbound_depth >= metrics.segyr_queue_inbound_max * 0.9
          ? 'degraded'
          : 'ok',
      value: `${metrics.segyr_queue_inbound_depth || 0}/${metrics.segyr_queue_inbound_max || '?'}`,
    },
    {
      label: 'Rejected (busy)',
      status: metrics.segyr_requests_rejected_busy > 0 ? 'degraded' : 'ok',
      value: metrics.segyr_requests_rejected_busy ?? 0,
    },
  ]

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <Card key={item.label} className="p-4 shadow-lg shadow-black/20" hover>
          <p className="text-sm text-slate-400">{item.label}</p>
          <div className="mt-2 flex items-center justify-between">
            <span className={`text-sm font-medium ${statusColor(item.status)}`}>{item.status.toUpperCase()}</span>
            <span className="text-lg font-semibold text-slate-100">{item.value}</span>
          </div>
        </Card>
      ))}
    </div>
  )
}
