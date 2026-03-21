import React from 'react'

export default function PolicyCard({ policy }) {
  const decision = String(policy?.decision || 'skip').toLowerCase()
  const isExecute = decision === 'execute'
  const recommended = Array.isArray(policy?.recommended_actions) ? policy.recommended_actions : []
  const reason = policy?.reason || 'n/a'

  return (
    <section className="rounded-2xl border border-surface-border bg-surface-card/90 p-5 shadow-xl shadow-black/30">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-100">Policy Engine</h2>
          <p className="text-sm text-slate-400">Décision d’exécution auto-repair</p>
        </div>
        <span
          className={`rounded-full border px-3 py-1 text-xs font-semibold ${
            isExecute ? 'border-success/40 bg-success/20 text-success' : 'border-warning/40 bg-warning/20 text-warning'
          }`}
        >
          {isExecute ? 'EXECUTE' : 'SKIP'}
        </span>
      </div>

      <div className="space-y-3">
        <Row label="Reason" value={reason} />
        <div>
          <div className="mb-2 text-xs uppercase tracking-wide text-slate-400">Recommended actions</div>
          <div className="flex flex-wrap gap-2">
            {recommended.length > 0 ? (
              recommended.map((action) => (
                <span key={action} className="rounded-full border border-accent/40 bg-accent/10 px-3 py-1 text-xs text-accent">
                  {action}
                </span>
              ))
            ) : (
              <span className="rounded-full border border-slate-600 px-3 py-1 text-xs text-slate-400">[]</span>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}

function Row({ label, value }) {
  return (
    <div className="rounded-xl border border-surface-border bg-surface-alt/70 px-3 py-2">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-sm font-semibold text-slate-100">{value}</div>
    </div>
  )
}
