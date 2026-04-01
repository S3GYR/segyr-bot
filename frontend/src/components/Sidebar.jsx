import React from 'react'
import { NavLink } from 'react-router-dom'

const navItems = [
  { to: '/', label: 'Dashboard' },
  { to: '/chat', label: 'Chat' },
  { to: '/monitoring', label: 'Monitoring' },
  { to: '/logs', label: 'Logs' },
  { to: '/system', label: 'Système' },
]

export default function Sidebar() {
  return (
    <aside className="w-60 bg-[#121826] border-r border-[#1F2937] min-h-screen hidden md:flex flex-col">
      <div className="px-6 py-5 text-xl font-semibold tracking-tight">SEGYR BOT</div>
      <nav className="flex-1 px-4 space-y-1">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `block px-3 py-2 rounded-lg transition-colors ${
                isActive ? 'bg-[#121826] text-[#3B82F6]' : 'text-slate-300 hover:bg-[#121826]'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="px-6 py-4 text-xs text-slate-500 border-t border-[#1F2937]">Console IA</div>
    </aside>
  )
}
