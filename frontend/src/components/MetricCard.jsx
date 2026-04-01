import React from 'react'
import Card from './Card'

export default function MetricCard({ label, value, hint, accent = 'text-[#3B82F6]' }) {
  return (
    <Card className="p-4 shadow-black/15">
      <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`mt-2 text-2xl font-semibold ${accent}`}>{value}</p>
      {hint && <p className="text-xs text-slate-500 mt-1">{hint}</p>}
    </Card>
  )
}
