import React from 'react'

export default function Badge({ label, tone = 'default' }) {
  const toneClasses = {
    success: 'bg-success/20 text-success',
    warning: 'bg-warning/20 text-warning',
    danger: 'bg-danger/20 text-danger',
    default: 'bg-slate-700/50 text-slate-200',
  }
  return <span className={`px-2 py-1 rounded-full text-xs font-medium ${toneClasses[tone] || toneClasses.default}`}>{label}</span>
}
