import React from 'react'

function normalizeRepairStatus(repair) {
  const last = repair?.last_result || {}
  const statusFinal = String(last?.status_final || last?.status || '').toLowerCase()
  if (statusFinal === 'skipped') return { label: 'SKIPPED', tone: 'text-warning border-warning/40 bg-warning/20' }
  if (statusFinal === 'success' || last?.repaired) return { label: 'SUCCESS', tone: 'text-success border-success/40 bg-success/20' }
  if (repair?.status === 'running') return { label: 'RUNNING', tone: 'text-accent border-accent/40 bg-accent/20' }
  return { label: 'FAILED', tone: 'text-danger border-danger/40 bg-danger/20' }
}

function numberOrDefault(value, fallback = 0) {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export default function RepairCard({ repair }) {
  const last = repair?.last_result || {}
  const statusMeta = normalizeRepairStatus(repair)
  const scoreBefore = numberOrDefault(last?.score_before)
  const scoreAfter = numberOrDefault(last?.score_after)
  const deltaExpected = numberOrDefault(last?.score_delta_expected)
  const deltaActual = numberOrDefault(last?.score_delta_actual)
  const actions = Array.isArray(last?.actions) ? last.actions : []

  return (
    <section className="rounded-2xl border border-surface-border bg-surface-card/90 p-5 shadow-xl shadow-black/30">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-slate-100">Auto-Repair</h2>
          <p className="text-sm text-slate-400">État et dernier résultat de /repair/status</p>
        </div>
        <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${statusMeta.tone}`}>{statusMeta.label}</span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric title="Score before" value={scoreBefore} />
        <Metric title="Score after" value={scoreAfter} />
        <Metric title="Delta expected" value={deltaExpected} />
        <Metric title="Delta actual" value={deltaActual} />
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <Field label="Correlation ID" value={last?.correlation_id || 'n/a'} mono />
        <Field label="Source" value={last?.source || 'n/a'} />
      </div>

      <div className="mt-4">
        <div className="mb-2 text-xs uppercase tracking-wide text-slate-400">Actions exécutées</div>
        <div className="flex flex-wrap gap-2">
          {actions.length > 0 ? (
            actions.map((action, idx) => {
              const value = typeof action === 'string' ? action : action?.action || JSON.stringify(action)
              return (
                <span key={`${value}-${idx}`} className="rounded-full border border-slate-600 bg-surface-alt px-3 py-1 text-xs text-slate-200">
                  {value}
                </span>
              )
            })
          ) : (
            <span className="rounded-full border border-slate-600 px-3 py-1 text-xs text-slate-400">Aucune</span>
          )}
        </div>
      </div>
    </section>
  )
}

function Metric({ title, value }) {
  return (
    <div className="rounded-xl border border-surface-border bg-surface-alt/70 p-3">
      <div className="text-xs uppercase tracking-wide text-slate-400">{title}</div>
      <div className="mt-1 text-lg font-semibold text-slate-100">{value}</div>
    </div>
  )
}

function Field({ label, value, mono = false }) {
  return (
    <div className="rounded-xl border border-surface-border bg-surface-alt/70 p-3">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-sm text-slate-100 ${mono ? 'font-mono break-all' : ''}`}>{value}</div>
    </div>
  )
}
