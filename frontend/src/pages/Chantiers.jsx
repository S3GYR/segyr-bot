import React, { useEffect, useState } from 'react'
import { fetchChantiers } from '../api'
import Badge from '../components/Badge'

const riskTone = (score = 0) => {
  if (score > 80) return 'danger'
  if (score > 60) return 'warning'
  return 'success'
}

export default function Chantiers() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchChantiers()
      .then((res) => setItems(res.chantiers || res.projets || []))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Chantiers</h1>
        <p className="text-slate-400">Suivi des chantiers et niveaux de risque.</p>
      </header>

      <div className="bg-surface-card border border-surface-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-surface-alt text-slate-400">
            <tr>
              <th className="text-left px-4 py-3">Titre</th>
              <th className="text-left px-4 py-3">Client</th>
              <th className="text-left px-4 py-3">Statut</th>
              <th className="text-left px-4 py-3">Avancement</th>
              <th className="text-left px-4 py-3">Risque</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td className="px-4 py-3 text-slate-500" colSpan={5}>
                  Chargement...
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td className="px-4 py-3 text-slate-500" colSpan={5}>
                  Aucun chantier.
                </td>
              </tr>
            )}
            {items.map((c) => (
              <tr key={c.id} className="border-t border-surface-border/60 hover:bg-surface-alt/60">
                <td className="px-4 py-3 font-semibold text-slate-100">{c.titre || c.name || `Chantier ${c.id}`}</td>
                <td className="px-4 py-3 text-slate-300">{c.client_id || '-'}</td>
                <td className="px-4 py-3">
                  <Badge label={c.statut || 'brouillon'} tone={c.statut === 'terminé' ? 'success' : 'warning'} />
                </td>
                <td className="px-4 py-3 text-slate-300">{Math.round(c.avancement || 0)}%</td>
                <td className="px-4 py-3">
                  <Badge label={`Score ${c.risk_score ?? 0}`} tone={riskTone(c.risk_score)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
