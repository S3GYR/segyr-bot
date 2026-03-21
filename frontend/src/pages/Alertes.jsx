import React, { useEffect, useState } from 'react'
import { fetchDashboard } from '../api'
import Badge from '../components/Badge'

export default function Alertes() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchDashboard()
      .then((res) => setItems(res.alertes || []))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Alertes</h1>
        <p className="text-slate-400">Alertes critiques et priorités.</p>
      </header>

      <div className="bg-surface-card border border-surface-border rounded-xl">
        {loading && <div className="p-4 text-slate-500">Chargement...</div>}
        {!loading && items.length === 0 && <div className="p-4 text-slate-500">Aucune alerte.</div>}
        <div className="divide-y divide-surface-border/60">
          {items.map((a, idx) => (
            <div key={idx} className="p-4 flex items-center justify-between hover:bg-surface-alt/60">
              <div>
                <div className="text-sm font-semibold text-slate-50">{a.type}</div>
                <div className="text-xs text-slate-400">{a.message}</div>
              </div>
              <Badge label="Critique" tone={a.type.includes('risque') || a.type.includes('critique') ? 'danger' : 'warning'} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
