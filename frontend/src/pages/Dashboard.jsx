import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchDashboardSummary, runRepair, runRepairDryRun } from '../api'
import HealthCard from '../components/HealthCard'
import HistoryTable from '../components/HistoryTable'
import MetricsGraph from '../components/MetricsGraph'
import PolicyCard from '../components/PolicyCard'
import RepairCard from '../components/RepairCard'

const POLL_INTERVAL_MS = 5000
const HISTORY_LIMIT = 30
const GRAPH_WINDOW = 36

function safeNumber(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function extractDetails(health) {
  if (!health || typeof health !== 'object') return {}
  const details = health.details
  if (!details || typeof details !== 'object') return {}
  if (details.details && typeof details.details === 'object') {
    return details.details
  }
  return details
}

function getLlmLatency(health) {
  const details = extractDetails(health)
  const cache = details.cache && typeof details.cache === 'object' ? details.cache : {}
  const firstDuration = safeNumber(cache.first?.duration_s)
  if (firstDuration !== null) return firstDuration
  return safeNumber(details.llm_latency_seconds)
}

function getCacheGain(health) {
  const details = extractDetails(health)
  const cache = details.cache && typeof details.cache === 'object' ? details.cache : {}
  const latencyRatio = safeNumber(cache.latency_ratio)
  if (latencyRatio && latencyRatio > 0) return 1 / latencyRatio
  const firstDuration = safeNumber(cache.first?.duration_s)
  const secondDuration = safeNumber(cache.second?.duration_s)
  if (firstDuration !== null && secondDuration && secondDuration > 0) {
    return firstDuration / secondDuration
  }
  return null
}

function getQueueStatus(health) {
  const details = extractDetails(health)
  if (health?.components && typeof health.components === 'object' && 'queue' in health.components) {
    return Boolean(health.components.queue)
  }
  if (health?.details?.components && typeof health.details.components === 'object' && 'queue' in health.details.components) {
    return Boolean(health.details.components.queue)
  }
  if (details.queue && typeof details.queue === 'object' && 'ok' in details.queue) {
    return Boolean(details.queue.ok)
  }
  return false
}

function formatTimeLabel(ts) {
  if (!ts) return '--:--:--'
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return date.toLocaleTimeString('fr-FR', { hour12: false })
}

export default function Dashboard() {
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionStatus, setActionStatus] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [series, setSeries] = useState([])

  const refresh = useCallback(async () => {
    try {
      const payload = await fetchDashboardSummary(HISTORY_LIMIT)
      setSummary(payload)
      setError('')

      const health = payload?.health || {}
      const repair = payload?.repair || {}
      const repairsCount = Array.isArray(repair?.recent_history) ? repair.recent_history.length : 0
      const point = {
        time: formatTimeLabel(health?.timestamp || new Date().toISOString()),
        score: safeNumber(health?.score) ?? 0,
        llmLatency: safeNumber(getLlmLatency(health)) ?? 0,
        repairsCount,
      }
      setSeries((prev) => [...prev, point].slice(-GRAPH_WINDOW))
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Erreur de chargement dashboard')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let active = true

    const boot = async () => {
      if (!active) return
      await refresh()
    }

    boot()
    const intervalId = setInterval(() => {
      if (active) {
        refresh()
      }
    }, POLL_INTERVAL_MS)

    return () => {
      active = false
      clearInterval(intervalId)
    }
  }, [refresh])

  const health = summary?.health || {}
  const policy = summary?.policy || {}
  const repair = summary?.repair || {}
  const history = summary?.history || {}

  const llmLatency = useMemo(() => getLlmLatency(health), [health])
  const cacheGain = useMemo(() => getCacheGain(health), [health])
  const queueStatus = useMemo(() => getQueueStatus(health), [health])

  const handleAction = async (mode) => {
    setActionLoading(true)
    setActionStatus('')
    try {
      const payload = mode === 'dry-run' ? await runRepairDryRun() : await runRepair()
      const correlationId = payload?.correlation_id || payload?.last_result?.correlation_id || 'n/a'
      setActionStatus(`${mode === 'dry-run' ? 'Dry-run' : 'Repair'} lancé (correlation_id=${correlationId})`)
      await refresh()
    } catch (err) {
      setActionStatus(`Action échouée: ${err?.response?.data?.detail || err?.message || 'unknown error'}`)
    } finally {
      setActionLoading(false)
    }
  }

  if (loading) {
    return <div className="text-sm text-slate-300">Chargement du cockpit observabilité...</div>
  }

  return (
    <div className="space-y-6">
      <header className="rounded-2xl border border-surface-border bg-surface-card/90 p-5 shadow-xl shadow-black/30">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-100">SEGYR Observability Cockpit</h1>
            <p className="text-sm text-slate-400">Health, policy engine, auto-repair et audit en temps réel (refresh 5s).</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => handleAction('run')}
              disabled={actionLoading}
              className="rounded-xl border border-success/50 bg-success/15 px-4 py-2 text-sm font-semibold text-success transition hover:bg-success/25 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Lancer repair
            </button>
            <button
              type="button"
              onClick={() => handleAction('dry-run')}
              disabled={actionLoading}
              className="rounded-xl border border-accent/50 bg-accent/15 px-4 py-2 text-sm font-semibold text-accent transition hover:bg-accent/25 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Dry-run
            </button>
          </div>
        </div>
        {actionStatus && <p className="mt-3 text-xs text-slate-300">{actionStatus}</p>}
        {error && <p className="mt-2 text-xs text-danger">{error}</p>}
      </header>

      <HealthCard health={health} llmLatency={llmLatency} cacheGain={cacheGain} queueStatus={queueStatus} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <PolicyCard policy={policy} />
        <RepairCard repair={repair} />
      </div>

      <MetricsGraph points={series} />

      <HistoryTable
        repairs={history.repairs || repair.recent_history || []}
        policies={history.policy || []}
        audit={history.audit || repair.recent_audit || []}
      />
    </div>
  )
}
