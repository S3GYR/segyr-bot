import React from 'react'

const COLORS = {
  ok: 'bg-[#10B981]/15 text-[#10B981] border-[#10B981]/40',
  degraded: 'bg-[#F59E0B]/15 text-[#F59E0B] border-[#F59E0B]/40',
  error: 'bg-[#EF4444]/15 text-[#EF4444] border-[#EF4444]/40',
  unknown: 'bg-[#3B82F6]/15 text-[#3B82F6] border-[#3B82F6]/40',
}

export default function StatusBadge({ status = 'unknown', children }) {
  const cls = COLORS[status] || COLORS.unknown
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-semibold ${cls}`}>
      <span className="h-2 w-2 rounded-full bg-current" />
      {children || status.toUpperCase()}
    </span>
  )
}
