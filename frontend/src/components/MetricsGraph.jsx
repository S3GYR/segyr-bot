import React from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export default function MetricsGraph({ points }) {
  const chartData = Array.isArray(points) ? points : []

  return (
    <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <GraphCard title="Évolution du score">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="time" stroke="#64748b" tick={{ fontSize: 11 }} />
            <YAxis domain={[0, 100]} stroke="#64748b" tick={{ fontSize: 11 }} />
            <Tooltip contentStyle={{ background: '#0f1729', border: '1px solid #1f2937' }} />
            <Line type="monotone" dataKey="score" stroke="#22d3ee" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </GraphCard>

      <GraphCard title="Latence LLM (s)">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="time" stroke="#64748b" tick={{ fontSize: 11 }} />
            <YAxis stroke="#64748b" tick={{ fontSize: 11 }} />
            <Tooltip contentStyle={{ background: '#0f1729', border: '1px solid #1f2937' }} />
            <Line type="monotone" dataKey="llmLatency" stroke="#f59e0b" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </GraphCard>

      <GraphCard title="Nombre de réparations (fenêtre)">
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="time" stroke="#64748b" tick={{ fontSize: 11 }} />
            <YAxis stroke="#64748b" tick={{ fontSize: 11 }} />
            <Tooltip contentStyle={{ background: '#0f1729', border: '1px solid #1f2937' }} />
            <Bar dataKey="repairsCount" fill="#34d399" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </GraphCard>
    </section>
  )
}

function GraphCard({ title, children }) {
  return (
    <div className="rounded-2xl border border-surface-border bg-surface-card/90 p-4 shadow-xl shadow-black/30">
      <h3 className="mb-3 text-base font-semibold text-slate-100">{title}</h3>
      {children}
    </div>
  )
}
