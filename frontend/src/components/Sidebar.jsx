import React from 'react'
import { NavLink } from 'react-router-dom'

const navItems = [
  { to: '/', label: 'Dashboard' },
  { to: '/chantiers', label: 'Chantiers' },
  { to: '/factures', label: 'Factures' },
  { to: '/alertes', label: 'Alertes' },
]

export default function Sidebar() {
  return (
    <aside className="w-60 bg-surface-alt border-r border-surface-border min-h-screen hidden md:flex flex-col">
      <div className="px-6 py-5 text-xl font-semibold tracking-tight">SEGYR-BOT</div>
      <nav className="flex-1 px-4 space-y-1">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `block px-3 py-2 rounded-lg transition-colors ${
                isActive ? 'bg-surface-card text-accent' : 'text-slate-300 hover:bg-surface-card'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="px-6 py-4 text-xs text-slate-500 border-t border-surface-border">Pilotage BTP</div>
    </aside>
  )
}
