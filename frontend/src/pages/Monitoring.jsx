import React, { useEffect, useState } from 'react'
import { AreaChart, Area, BarChart, Bar, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getMetricsWebSocketUrl } from '../lib/api'
import ChartCard from '../components/ChartCard'
import Card from '../components/Card'
import useWebSocket from '../hooks/useWebSocket'

const MAX_POINTS = 80

export default function Monitoring() {
  const [metrics, setMetrics] = useState([])
  const [error, setError] = useState('')
  const wsUrl = getMetricsWebSocketUrl()
  const { status: wsStatus, lastMessage, latencyMs: wsLatency } = useWebSocket(wsUrl)

  useEffect(() => {
    if (!lastMessage) return
    const ts = lastMessage.timestamp ? new Date(lastMessage.timestamp * 1000).toLocaleTimeString('fr-FR', { hour12: false }) : new Date().toLocaleTimeString('fr-FR', { hour12: false })
    setMetrics((prev) =>
      [
        ...prev,
        {
          ts,
          latency: Number(lastMessage.llm_avg_latency_ms || lastMessage.request_latency_ms) || 0,
          fallback: Number(lastMessage.llm_fallbacks || lastMessage.fallback || 0) || 0,
          queue: Number(lastMessage.queue_inbound_depth) || 0,
          queueMax: Number(lastMessage.queue_inbound_max) || 0,
          rejected: Number(lastMessage.rejected_busy) || 0,
        },
      ].slice(-MAX_POINTS),
    )
    setError('')
  }, [lastMessage])

  useEffect(() => {
    if (wsStatus === 'error') setError('WebSocket métriques en erreur')
  }, [wsStatus])

  return (
    <div className="space-y-6">
      <Card className="p-5 shadow-black/20">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-[#E5E7EB]">Monitoring</h1>
            <p className="text-sm text-slate-400">Latence, fallback, saturation queue · WebSocket live.</p>
          </div>
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <span className={`h-2 w-2 rounded-full ${wsStatus === 'open' ? 'bg-[#10B981]' : 'bg-[#F59E0B]'} animate-pulse`} aria-hidden />
            {wsLatency != null && <span>WS {wsLatency.toFixed(0)} ms</span>}
          </div>
          {error && <p className="text-sm text-danger">{error}</p>}
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartCard title="Latence LLM (ms)">
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={metrics} margin={{ left: -10, right: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="ts" stroke="#94a3b8" tick={{ fontSize: 11 }} />
              <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1f2937' }} />
              <Area type="monotone" dataKey="latency" stroke="#3B82F6" fill="#3B82F622" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Fallback cumulative">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={metrics} margin={{ left: -10, right: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="ts" stroke="#94a3b8" tick={{ fontSize: 11 }} />
              <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1f2937' }} />
              <Bar dataKey="fallback" fill="#F59E0B" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartCard title="Queue inbound">
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={metrics} margin={{ left: -10, right: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="ts" stroke="#94a3b8" tick={{ fontSize: 11 }} />
              <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1f2937' }} />
              <Area type="monotone" dataKey="queue" stroke="#10B981" fill="#10B98122" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Rejets (busy)">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={metrics} margin={{ left: -10, right: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="ts" stroke="#94a3b8" tick={{ fontSize: 11 }} />
              <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1f2937' }} />
              <Bar dataKey="rejected" fill="#EF4444" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  )
}
