import React, { useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Card from '../components/Card'
import StatusBadge from '../components/StatusBadge'
import Spinner from '../components/Spinner'
import { getLogWebSocketUrl } from '../lib/api'
import useWebSocket from '../hooks/useWebSocket'

const MAX_LOGS = 1000
const LEVELS = ['all', 'error', 'warning', 'info']
const SEVERITY = { error: 3, warning: 2, info: 1 }
const MAX_GROUPS = 200
const MAX_LOGS_PER_GROUP = 200

function normalizeLog(raw) {
  if (!raw) return null
  let obj = raw
  if (typeof raw === 'string') {
    try {
      obj = JSON.parse(raw)
    } catch (e) {
      obj = { message: raw }
    }
  }
  if (typeof obj !== 'object') return null
  const level = String(obj.level || 'info').toLowerCase()
  const pretty = (() => {
    try {
      return JSON.stringify(obj, null, 2)
    } catch (e) {
      return String(obj)
    }
  })()
  return {
    ts: obj.timestamp || obj.ts || Date.now(),
    level,
    message: obj.message || '',
    request_id: obj.request_id || obj.req_id || '',
    service: obj.service || 'gateway',
    data: obj,
    pretty,
  }
}

function useDebounce(value, delay) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(id)
  }, [value, delay])
  return debounced
}

export default function Logs() {
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [paused, setPaused] = useState(false)
  const [search, setSearch] = useState('')
  const [level, setLevel] = useState('all')
  const [debugMode, setDebugMode] = useState(false)
  const [groups, setGroups] = useState([])
  const [openGroups, setOpenGroups] = useState(new Set())
  const scrollRef = useRef(null)

  const debouncedSearch = useDebounce(search, 300)

  const url = getLogWebSocketUrl()
  const { status: wsStatus, latencyMs, lastMessage } = useWebSocket(paused ? null : url)

  useEffect(() => {
    if (!lastMessage) return
    const entry = normalizeLog(lastMessage)
    if (!entry) return
    setLogs((prev) => [...prev, entry].slice(-MAX_LOGS))
    setGroups((prev) => {
      const next = updateGroups(prev, entry)
      const newestId = next.length ? next[next.length - 1].id : null
      if (newestId) {
        const set = new Set(openGroups)
        set.add(newestId)
        setOpenGroups(set)
      }
      return next
    })
  }, [lastMessage])

  useEffect(() => {
    setLoading(wsStatus === 'connecting')
    if (wsStatus === 'error') setError('WebSocket logs en erreur')
    if (wsStatus === 'open') setError('')
    if (wsStatus === 'paused') setLoading(false)
  }, [wsStatus])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs])

  const filteredGroups = useMemo(() => {
    const query = debouncedSearch.toLowerCase()
    return groups
      .map((g) => ({
        ...g,
        logs: g.logs.filter((l) => (debugMode ? true : l.level !== 'info')),
      }))
      .filter((g) => {
        const statusMatch = level === 'all' ? true : g.status === level
        const searchBase = `${g.request_id || ''} ${g.cacheSearch}`.toLowerCase()
        const searchMatch = searchBase.includes(query)
        return statusMatch && searchMatch && g.logs.length > 0
      })
  }, [groups, level, debouncedSearch, debugMode])

  const levelColor = (lvl) => {
    if (lvl === 'error') return 'text-[#EF4444]'
    if (lvl === 'warning') return 'text-[#F59E0B]'
    return 'text-slate-300'
  }

  return (
    <div className="space-y-6">
      <Card className="p-5 shadow-black/20">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-[#E5E7EB]">Logs</h1>
            <p className="text-sm text-slate-400">Flux JSON live · filtres niveau / request_id · pause & clear · WebSocket.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setPaused((p) => !p)}
              className="rounded-xl border border-[#1F2937] bg-[#121826] px-3 py-2 text-sm text-slate-200 hover:border-[#3B82F6]"
            >
              {paused ? 'Reprendre' : 'Pause'}
            </button>
            <button
              type="button"
              onClick={() => setLogs([])}
              className="rounded-xl border border-[#1F2937] bg-[#121826] px-3 py-2 text-sm text-slate-200 hover:border-[#EF4444]"
            >
              Clear
            </button>
          </div>
        </div>
      </Card>

      <Card className="p-4 space-y-3" hover={false}>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Recherche (request_id, message)"
            className="rounded-xl border border-[#1F2937] bg-[#0B0F1A] px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-[#3B82F6]/40"
          />
          <div className="flex items-center gap-2">
            {LEVELS.map((lvl) => (
              <button
                key={lvl}
                type="button"
                onClick={() => setLevel(lvl)}
                className={`rounded-xl px-3 py-2 text-sm border ${
                  level === lvl ? 'border-[#3B82F6] bg-[#121826]' : 'border-[#1F2937] bg-[#0B0F1A]'
                }`}
              >
                {lvl.toUpperCase()}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3 text-sm text-slate-400">
            <StatusBadge status={paused ? 'degraded' : wsStatus === 'open' ? 'ok' : 'degraded'}>
              {paused ? 'PAUSE' : wsStatus === 'open' ? 'LIVE' : 'RECONNECT'}
            </StatusBadge>
            <span className={`h-2 w-2 rounded-full animate-pulse ${wsStatus === 'open' ? 'bg-[#10B981]' : 'bg-[#F59E0B]'}`} aria-hidden />
            <span>Max {MAX_LOGS} lignes</span>
            {latencyMs != null && <span>WS {latencyMs.toFixed(0)} ms</span>}
            <label className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={debugMode} onChange={(e) => setDebugMode(e.target.checked)} />
              Debug
            </label>
          </div>
        </div>

        {loading ? (
          <Spinner label="Connexion WS logs..." />
        ) : error ? (
          <p className="text-sm text-[#EF4444]">{error}</p>
        ) : (
          <div ref={scrollRef} className="h-[60vh] overflow-y-auto rounded-2xl border border-[#1F2937] bg-[#0B0F1A] p-3 font-mono text-[12px] text-slate-200">
            <AnimatePresence>
              {filteredGroups.map((group) => {
                const open = openGroups.has(group.id)
                const duration = group.durationMs != null ? `${(group.durationMs / 1000).toFixed(2)}s` : '—'
                const stats = getGroupStats(group)
                return (
                  <motion.div
                    key={group.id}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.15 }}
                    className={`mb-3 rounded-xl bg-[#121826] p-3 shadow-inner shadow-black/20 border border-[#1F2937] ${
                      group.status === 'error' ? 'ring-1 ring-[#EF4444]/40' : group.status === 'warning' ? 'ring-1 ring-[#F59E0B]/40' : ''
                    }`}
                  >
                    <div className="flex items-center justify-between text-[12px] text-slate-300">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => toggleGroup(openGroups, setOpenGroups, group.id)}
                          className="rounded px-2 py-1 bg-[#0B0F1A] border border-[#1F2937]"
                        >
                          {open ? '−' : '+'}
                        </button>
                        <span className="font-semibold">{group.request_id || 'NO_REQUEST'}</span>
                        <StatusBadge status={group.status}>{group.status.toUpperCase()}</StatusBadge>
                        {stats.fallback && <span className="text-xs text-[#F59E0B]">Fallback</span>}
                        <span className="text-slate-500">{group.logs.length} logs</span>
                        <span className="text-slate-500">Durée: {duration}</span>
                        <span className="rounded-full bg-[#0B0F1A] px-2 py-1 text-[11px] text-slate-300 border border-[#1F2937]">Score {stats.score}</span>
                      </div>
                      <div className="text-slate-500">
                        {group.startTs ? new Date(group.startTs).toLocaleTimeString('fr-FR', { hour12: false }) : ''}
                        {group.endTs ? ` → ${new Date(group.endTs).toLocaleTimeString('fr-FR', { hour12: false })}` : ''}
                      </div>
                    </div>
                    {open && (
                      <motion.div layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-2 space-y-2">
                        <div className="flex flex-col gap-2">
                          {stats.timeline.map((step, idx) => (
                            <div key={`${group.id}-step-${idx}`} className="flex items-start gap-2 text-xs text-slate-300">
                              <span className={`mt-1 h-2 w-2 rounded-full ${step.level === 'error' ? 'bg-[#EF4444]' : step.level === 'warning' ? 'bg-[#F59E0B]' : 'bg-[#10B981]'}`} />
                              <div className="flex-1">
                                <div className="flex justify-between text-[11px] text-slate-500">
                                  <span>{new Date(step.ts).toLocaleTimeString('fr-FR', { hour12: false })}</span>
                                  <span className={`font-semibold ${levelColor(step.level)}`}>{step.level.toUpperCase()}</span>
                                </div>
                                <div className="text-[12px]">{step.message || 'event'}</div>
                              </div>
                            </div>
                          ))}
                        </div>
                        {group.logs.map((log, idx) => (
                          <div
                            key={`${group.id}-${idx}`}
                            className={`rounded-lg border border-[#1F2937] bg-[#0B0F1A] p-2 ${log.level === 'error' ? 'ring-1 ring-[#EF4444]/30' : ''}`}
                          >
                            <div className="flex items-center justify-between text-[11px] text-slate-500">
                              <span>{new Date(log.ts).toLocaleTimeString('fr-FR', { hour12: false })}</span>
                              <span className={`font-semibold ${levelColor(log.level)}`}>{log.level.toUpperCase()}</span>
                            </div>
                            <pre className={`whitespace-pre-wrap leading-relaxed ${levelColor(log.level)}`}>
                              {log.pretty}
                            </pre>
                          </div>
                        ))}
                      </motion.div>
                    )}
                  </motion.div>
                )
              })}
            </AnimatePresence>
          </div>
        )}
      </Card>
    </div>
  )
}

function toggleGroup(openSet, setOpen, id) {
  const next = new Set(openSet)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  setOpen(next)
}

function updateGroups(prev, log) {
  const reqId = log.request_id || 'no-request'
  const ts = Number(log.ts || Date.now())
  const next = [...prev]
  const idx = next.findIndex((g) => g.id === reqId)
  if (idx === -1) {
    next.push({
      id: reqId,
      request_id: reqId,
      logs: [log].slice(-MAX_LOGS_PER_GROUP),
      startTs: ts,
      endTs: ts,
      durationMs: 0,
      status: log.level,
      cacheSearch: `${reqId} ${log.message || ''}`,
    })
  } else {
    const g = { ...next[idx] }
    const logs = [...g.logs, log].slice(-MAX_LOGS_PER_GROUP)
    const endTs = ts
    const startTs = g.startTs || ts
    const durationMs = endTs - startTs
    const status = severityOf(log.level) >= severityOf(g.status) ? log.level : g.status
    g.logs = logs
    g.endTs = endTs
    g.durationMs = durationMs
    g.status = status
    g.cacheSearch = g.cacheSearch || `${reqId} ${log.message || ''}`
    next[idx] = g
  }
  return next.slice(-MAX_GROUPS)
}

function getGroupStats(group) {
  const errors = group.logs.filter((l) => l.level === 'error').length
  const warnings = group.logs.filter((l) => l.level === 'warning').length
  const fallback = group.logs.some((l) => (l.data && (l.data.fallback || l.data.fallback_used)) || (l.message || '').toLowerCase().includes('fallback'))
  const durationMs = group.durationMs || 0
  const score = Math.max(0, Math.min(100, Math.round(100 - durationMs / 100 - errors * 20 - warnings * 10 - (fallback ? 15 : 0))))
  const timeline = group.logs.map((l) => ({ ts: l.ts, level: l.level, message: l.message || l.data?.message || '' }))
  return { errors, warnings, fallback, durationMs, score, timeline }
}

function severityOf(level) {
  return SEVERITY[level] || 0
}
