import React from 'react'

const STATUS_STYLE = {
  healthy: { label: 'HEALTHY', tone: 'bg-success/20 text-success border-success/40' },
  ok: { label: 'HEALTHY', tone: 'bg-success/20 text-success border-success/40' },
  degraded: { label: 'DEGRADED', tone: 'bg-warning/20 text-warning border-warning/40' },
  warning: { label: 'DEGRADED', tone: 'bg-warning/20 text-warning border-warning/40' },
  critical: { label: 'CRITICAL', tone: 'bg-danger/20 text-danger border-danger/40' },
}

function normalizeStatus(status) {
  const key = String(status || 'critical').toLowerCase()
  return STATUS_STYLE[key] || STATUS_STYLE.critical
}

function metricValue(value, fallback = 'n/a') {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return fallback
  }
  return value
}

export default function HealthCard({ health, llmLatency, cacheGain, queueStatus }) {
  const statusMeta = normalizeStatus(health?.status)

  return (
    <section className="rounded-2xl border border-surface-border bg-surface-card/90 p-5 shadow-xl shadow-black/30">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-100">System Health</h2>
          <p className="text-sm text-slate-400">Snapshot live de /health/full</p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${statusMeta.tone}`}>
          {statusMeta.label}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Metric title="Score" value={metricValue(health?.score, 0)} accent="text-accent" />
        <Metric
          title="Status"
          value={String(health?.status || 'critical').toUpperCase()}
          accent={statusMeta.label === 'HEALTHY' ? 'text-success' : statusMeta.label === 'DEGRADED' ? 'text-warning' : 'text-danger'}
        />
        <Metric title="LLM Latency" value={typeof llmLatency === 'number' ? `${llmLatency.toFixed(2)}s` : 'n/a'} accent="text-slate-100" />
        <Metric title="Cache Gain" value={typeof cacheGain === 'number' ? `x${cacheGain.toFixed(2)}` : 'n/a'} accent="text-slate-100" />
        <Metric title="Queue" value={queueStatus ? 'UP' : 'DOWN'} accent={queueStatus ? 'text-success' : 'text-danger'} />
      </div>
    </section>
  )
}

function Metric({ title, value, accent = 'text-slate-100' }) {
  return (
    <div className="rounded-xl border border-surface-border bg-surface-alt/70 p-3">
      <div className="text-xs uppercase tracking-wide text-slate-400">{title}</div>
      <div className={`mt-1 text-lg font-semibold ${accent}`}>{value}</div>
    </div>
  )
}
