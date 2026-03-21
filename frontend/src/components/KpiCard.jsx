import React from 'react'

export default function KpiCard({ title, value, subtitle, accent = '#22d3ee' }) {
  return (
    <div className="bg-surface-card border border-surface-border rounded-xl p-4 shadow-lg shadow-black/30">
      <div className="text-sm text-slate-400 flex items-center justify-between">
        <span>{title}</span>
        <span className="h-2 w-2 rounded-full" style={{ background: accent }}></span>
      </div>
      <div className="text-2xl font-semibold mt-2 text-slate-50">{value}</div>
      {subtitle && <div className="text-xs text-slate-500 mt-1">{subtitle}</div>}
    </div>
  )
}
