import React from 'react'
import Sidebar from './Sidebar'
import Topbar from './Topbar'

export default function Layout({ children }) {
  return (
    <div className="min-h-screen bg-[#0B0F1A] text-[#E5E7EB] flex">
      <Sidebar />
      <div className="flex-1 flex flex-col min-h-screen bg-[radial-gradient(circle_at_20%_20%,rgba(34,211,238,0.08),transparent_25%),radial-gradient(circle_at_80%_0%,rgba(59,130,246,0.08),transparent_22%),radial-gradient(circle_at_50%_80%,rgba(16,185,129,0.08),transparent_18%)]">
        <Topbar />
        <main className="flex-1 p-4 md:p-6 lg:p-8 space-y-6 overflow-y-auto">{children}</main>
      </div>
    </div>
  )
}
