import React from 'react'

function tableCellClass(emphasis = false) {
  return `border-b border-surface-border px-3 py-2 text-xs ${emphasis ? 'font-semibold text-slate-100' : 'text-slate-300'}`
}

function formatTs(value) {
  if (!value) return 'n/a'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('fr-FR')
}

function formatActions(actions) {
  if (!Array.isArray(actions) || actions.length === 0) return '[]'
  return actions
    .map((a) => {
      if (typeof a === 'string') return a
      if (a && typeof a === 'object') return a.action || JSON.stringify(a)
      return String(a)
    })
    .join(', ')
}

export default function HistoryTable({ repairs, policies, audit }) {
  const repairRows = Array.isArray(repairs) ? repairs.slice().reverse().slice(0, 8) : []
  const policyRows = Array.isArray(policies) ? policies.slice().reverse().slice(0, 8) : []
  const auditRows = Array.isArray(audit) ? audit.slice().reverse().slice(0, 8) : []

  return (
    <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
      <TableCard
        title="Dernières réparations"
        headers={['Date', 'Status', 'Delta', 'Correlation']}
        rows={repairRows.map((row) => [
          formatTs(row.ended_at || row.started_at),
          row.status_final || row.status || (row.repaired ? 'success' : 'failed'),
          `${row.score_delta_actual ?? 0} / ${row.score_delta_expected ?? 0}`,
          row.correlation_id || 'n/a',
        ])}
      />

      <TableCard
        title="Décisions policy"
        headers={['Date', 'Decision', 'Reason', 'Actions']}
        rows={policyRows.map((row) => [
          formatTs(row.timestamp),
          row.decision || 'skip',
          row.reason || 'n/a',
          formatActions(row.recommended_actions),
        ])}
      />

      <TableCard
        title="Audit JSONL"
        headers={['Date', 'Endpoint', 'Status', 'Correlation']}
        rows={auditRows.map((row) => [
          formatTs(row.timestamp),
          row.endpoint || 'n/a',
          row.status_final || 'n/a',
          row.correlation_id || 'n/a',
        ])}
      />
    </section>
  )
}

function TableCard({ title, headers, rows }) {
  return (
    <div className="rounded-2xl border border-surface-border bg-surface-card/90 p-4 shadow-xl shadow-black/30">
      <h3 className="mb-3 text-base font-semibold text-slate-100">{title}</h3>
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse">
          <thead>
            <tr>
              {headers.map((header) => (
                <th key={header} className="border-b border-surface-border px-3 py-2 text-left text-[11px] uppercase tracking-wide text-slate-400">
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length > 0 ? (
              rows.map((row, rowIdx) => (
                <tr key={`row-${rowIdx}`}>
                  {row.map((cell, colIdx) => (
                    <td key={`cell-${rowIdx}-${colIdx}`} className={tableCellClass(colIdx === 1)}>
                      <span className={colIdx === row.length - 1 ? 'font-mono break-all' : ''}>{cell}</span>
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={headers.length} className="px-3 py-4 text-xs text-slate-500">
                  Aucune donnée.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
