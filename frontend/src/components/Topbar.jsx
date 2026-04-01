import React, { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { getMetricsWebSocketUrl } from '../lib/api'
import useWebSocket from '../hooks/useWebSocket'
import StatusBadge from './StatusBadge'
import Card from './Card'

export default function Topbar() {
  const [status, setStatus] = useState('ok')
  const [latency, setLatency] = useState(0)
  const [fallbacks, setFallbacks] = useState(0)
  const [global, setGlobal] = useState('stable')
  const wsUrl = getMetricsWebSocketUrl()
  const { status: wsStatus, lastMessage, latencyMs: wsLatency, lastActivity } = useWebSocket(wsUrl)
  const [lastAge, setLastAge] = useState(0)

  useEffect(() => {
    if (!lastMessage) return
    const data = lastMessage
    const reqs = Number(data.segyr_requests_total || data.requests_total || 0)
    const fall = Number(data.segyr_llm_fallback_total || data.llm_fallbacks || data.fallback || 0)
    const lat = Number(data.segyr_llm_avg_latency_ms || data.llm_avg_latency_ms || 0)
    setFallbacks(fall)
    setLatency(lat)
    const queueBusy = data.segyr_queue_inbound_max && data.segyr_queue_inbound_depth >= data.segyr_queue_inbound_max * 0.9
    const degraded = queueBusy || fall > 0
    setStatus(degraded ? 'degraded' : 'ok')
    if (!Number.isFinite(reqs)) setStatus('unknown')
    setGlobal(queueBusy ? 'critique' : fall > 0 ? 'degradé' : 'stable')
  }, [lastMessage])

  useEffect(() => {
    if (!lastActivity) return
    const id = setInterval(() => {
      setLastAge(Math.max(0, Date.now() - lastActivity))
    }, 1000)
    return () => clearInterval(id)
  }, [lastActivity])

  const wsTone =
    wsStatus === 'open'
      ? 'bg-[#10B981]'
      : wsStatus === 'reconnecting'
      ? 'bg-[#F59E0B]'
      : wsStatus === 'stale'
      ? 'bg-[#F59E0B]'
      : wsStatus === 'paused' || wsStatus === 'connecting'
      ? 'bg-[#94a3b8]'
      : 'bg-[#EF4444]'
  const wsPulse = wsStatus === 'stale' ? 'animate-pulse' : 'animate-ping'
  const latencyDisplay = wsLatency != null ? `${wsLatency.toFixed(0)} ms` : '--'
  const ageDisplay = lastAge ? `${Math.floor(lastAge / 1000)}s` : '0s'

  return (
    <div className="px-4 md:px-6 lg:px-8 pt-4">
      <Card className="p-3 flex items-center justify-between bg-[#121826]/90">
        <div className="flex items-center gap-3">
          <StatusBadge status={status}>Status {status.toUpperCase()}</StatusBadge>
          <span className="text-sm text-slate-400">Latency: <span className="text-[#3B82F6] font-semibold">{latency.toFixed(0)} ms</span></span>
          <span className="text-sm text-slate-400">Fallbacks: <span className="text-[#F59E0B] font-semibold">{fallbacks}</span></span>
          {fallbacks > 0 && <span className="text-xs text-[#F59E0B]">⚠ fallback actif</span>}
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <motion.span
              className={`h-2 w-2 rounded-full ${wsTone} ${wsPulse}`}
              aria-hidden
              animate={{ scale: wsStatus === 'open' ? 1 : 1.05 }}
              transition={{ duration: 0.4, repeat: Infinity, repeatType: 'reverse' }}
            />
            <span>WS {latencyDisplay}</span>
            <span>{ageDisplay}</span>
          </div>
        </div>
        <div className="text-sm text-slate-500 flex items-center gap-2">
          <span>
            {global === 'critique' ? '🔴 Critique' : global === 'degradé' ? '🟠 Dégradé' : '🟢 Stable'}
          </span>
          <span className="hidden sm:inline">Console IA SEGYR</span>
        </div>
      </Card>
    </div>
  )
}
