import React, { useEffect, useMemo, useState } from 'react'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import Spinner from '../components/Spinner'
import { getHealth, getReadiness, getMetricsWebSocketUrl } from '../lib/api'
import useWebSocket from '../hooks/useWebSocket'

function normalizeStatus(val) {
  const v = (val || '').toLowerCase()
  if (v === 'ok') return 'ok'
  if (v === 'degraded' || v === 'fallback') return 'degraded'
  return 'error'
}

export default function System() {
  const [health, setHealth] = useState(null)
  const [ready, setReady] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const metricsWs = getMetricsWebSocketUrl()
  const { status: wsStatus, lastMessage, latencyMs: wsLatency } = useWebSocket(metricsWs)

  useEffect(() => {
    let active = true
    const tick = async () => {
      try {
        const [h, r] = await Promise.all([getHealth(), getReadiness()])
        if (!active) return
        setHealth(h)
        setReady(r)
      } catch (e) {
        if (!active) return
        setError(e?.message || 'Erreur chargement statuts')
      } finally {
        setLoading(false)
      }
    }
    tick()
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!lastMessage) return
    setMetrics(lastMessage)
    setLoading(false)
    setError('')
  }, [lastMessage])

  useEffect(() => {
    if (wsStatus === 'error') {
      setError('WebSocket metrics en erreur')
      setLoading(false)
    }
  }, [wsStatus])

  const fallbackActive = useMemo(() => (metrics?.segyr_llm_fallback_total || 0) > 0, [metrics])

  const gatewayStatus = normalizeStatus(health?.status || health?.state || 'error')
  const redisStatus = normalizeStatus(ready?.redis || ready?.details?.redis || ready?.components?.redis)
  const llmStatus = fallbackActive ? 'degraded' : normalizeStatus(ready?.llm || ready?.details?.llm || ready?.components?.llm)
  const globalStatus = gatewayStatus === 'error' || redisStatus === 'error' ? 'error' : llmStatus === 'degraded' ? 'degraded' : 'ok'

  return (
    <div className="space-y-6">
      <Card className="p-5 shadow-black/20">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-[#E5E7EB]">Système</h1>
            <p className="text-sm text-slate-400">Health + Readiness · WebSocket métriques · badges Redis / LLM / Gateway.</p>
          </div>
          {fallbackActive && <span className="text-xs text-[#F59E0B]">⚠ fallback actif</span>}
        </div>
      </Card>

      {loading ? (
        <Spinner label="Chargement des statuts..." />
      ) : error ? (
        <p className="text-sm text-[#EF4444]">{error}</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatusCard title="Gateway" status={gatewayStatus} detail={health} />
          <StatusCard title="Redis" status={redisStatus} detail={ready?.redis || ready?.details?.redis} />
          <StatusCard title="LLM" status={llmStatus} detail={ready?.llm || ready?.details?.llm} fallbackActive={fallbackActive} />
          <StatusCard title="Global" status={globalStatus} detail={{ health: health?.status, readiness: ready?.status }} />
          <StatusCard
            title="WebSocket"
            status={wsStatus === 'open' ? 'ok' : wsStatus === 'paused' ? 'degraded' : 'degraded'}
            detail={wsLatency != null ? `${wsLatency.toFixed(0)} ms` : wsStatus}
          />
        </div>
      )}
    </div>
  )
}

function StatusCard({ title, status, detail, fallbackActive = false }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-[#E5E7EB]">{title}</h3>
        <StatusBadge status={status} />
      </div>
      {fallbackActive && <p className="mt-1 text-xs text-[#F59E0B]">⚠ fallback actif</p>}
      <p className="mt-2 text-sm text-slate-400">{renderDetail(detail)}</p>
    </Card>
  )
}

function renderDetail(detail) {
  if (!detail) return '—'
  if (typeof detail === 'string') return detail
  try {
    return JSON.stringify(detail)
  } catch (e) {
    return '—'
  }
}
