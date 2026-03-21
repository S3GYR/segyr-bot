import React from 'react'
import Sidebar from './Sidebar'

export default function Layout({ children }) {
  return (
    <div className="min-h-screen bg-surface text-slate-100 flex">
      <Sidebar />
      <main className="flex-1 p-6 lg:p-8 space-y-6 overflow-y-auto bg-[radial-gradient(circle_at_20%_20%,rgba(34,211,238,0.12),transparent_25%),radial-gradient(circle_at_80%_0%,rgba(59,130,246,0.12),transparent_22%),radial-gradient(circle_at_50%_80%,rgba(52,211,153,0.12),transparent_18%)]">
        {children}
      </main>
    </div>
  )
}
