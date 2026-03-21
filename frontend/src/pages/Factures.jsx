import React, { useEffect, useState } from 'react'
import { fetchFactures, relanceFacture } from '../api'
import Badge from '../components/Badge'

const statusTone = (statut = '') => {
  if (statut.toLowerCase().includes('pay')) return 'success'
  return 'danger'
}

export default function Factures() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const load = () => {
    setLoading(true)
    fetchFactures()
      .then((res) => setItems(res.factures || []))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  const handleRelance = async (id) => {
    setBusy(true)
    try {
      await relanceFacture(id)
    } finally {
      setBusy(false)
      load()
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Factures</h1>
        <p className="text-slate-400">Suivi des factures et relances impayés.</p>
      </header>

      <div className="bg-surface-card border border-surface-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-surface-alt text-slate-400">
            <tr>
              <th className="text-left px-4 py-3">Référence</th>
              <th className="text-left px-4 py-3">Client</th>
              <th className="text-left px-4 py-3">Montant HT</th>
              <th className="text-left px-4 py-3">Due date</th>
              <th className="text-left px-4 py-3">Statut</th>
              <th className="text-left px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td className="px-4 py-3 text-slate-500" colSpan={6}>
                  Chargement...
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td className="px-4 py-3 text-slate-500" colSpan={6}>
                  Aucune facture.
                </td>
              </tr>
            )}
            {items.map((f) => (
              <tr key={f.id} className="border-t border-surface-border/60 hover:bg-surface-alt/60">
                <td className="px-4 py-3 font-semibold text-slate-100">{f.reference || `FCT-${f.id}`}</td>
                <td className="px-4 py-3 text-slate-300">{f.client_id || '-'}</td>
                <td className="px-4 py-3 text-slate-300">{f.montant_ht ?? 0} €</td>
                <td className="px-4 py-3 text-slate-300">{f.due_date || '-'}</td>
                <td className="px-4 py-3">
                  <Badge label={f.statut || 'impayée'} tone={statusTone(f.statut || '')} />
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    className="px-3 py-2 rounded-lg bg-accent/20 text-accent text-xs border border-accent/40 disabled:opacity-50"
                    onClick={() => handleRelance(f.id)}
                    disabled={busy}
                  >
                    Relancer
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
