import React from 'react'

export default function Spinner({ label = 'Chargement...' }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-400">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-[#3B82F6] border-t-transparent" />
      {label}
    </div>
  )
}
