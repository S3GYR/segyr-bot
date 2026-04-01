import React, { useEffect, useRef, useState } from 'react'
import { sendMessage } from '../lib/api'
import Card from './Card'
import StatusBadge from './StatusBadge'

export default function ChatBox() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [mode, setMode] = useState('auto')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const handleSend = async () => {
    if (!input.trim()) return
    setLoading(true)
    setError('')
    const userMsg = { role: 'user', content: input, mode }
    setMessages((prev) => [...prev, userMsg])
    try {
      const res = await sendMessage({ text: input, chat_id: 'web', mode })
      const meta = {
        model: res?.metadata?.model || 'unknown',
        fallback: Boolean(res?.metadata?.fallback),
        latency_ms: res?.metadata?.latency_ms || 0,
        mode,
      }
      setMessages((prev) => [...prev, { role: 'assistant', content: res?.reply || res?.content || '', meta }])
      setInput('')
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Erreur envoi message')
    } finally {
      setLoading(false)
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2 p-4 h-[70vh] flex flex-col">
        <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-4 pr-2">
          {messages.map((m, idx) => (
            <MessageBubble key={idx} message={m} />
          ))}
          {messages.length === 0 && <p className="text-sm text-slate-500">Aucun message. Démarrez une conversation.</p>}
        </div>
        {error && <p className="mt-2 text-sm text-danger">{error}</p>}
        <div className="mt-3 flex gap-2">
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            className="rounded-xl border border-[#1F2937] bg-[#0B0F1A] px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-[#3B82F6]/50"
          >
            <option value="auto">Auto</option>
            <option value="fast">Fast ⚡</option>
            <option value="quality">Quality 🧠</option>
          </select>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Pose ta question..."
            className="flex-1 rounded-xl border border-[#1F2937] bg-[#0B0F1A] px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-[#3B82F6]/50"
            rows={2}
            disabled={loading}
          />
          <button
            type="button"
            onClick={handleSend}
            disabled={loading}
            className="rounded-xl bg-[#3B82F6] px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-[#3B82F6]/20 hover:bg-[#2563eb] transition disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {loading ? '...' : 'Envoyer'}
          </button>
        </div>
      </Card>
      <Card className="p-4 space-y-4">
        <h3 className="text-base font-semibold text-slate-100">Guide rapide</h3>
        <p className="text-sm text-slate-400">Choisis le mode :
          <span className="text-[#3B82F6]"> Fast</span> pour vitesse, <span className="text-[#10B981]">Quality</span> pour précision, <span className="text-[#F59E0B]">Auto</span> laisse le router décider.</p>
        <p className="text-sm text-slate-400">Les réponses affichent le modèle, le fallback et la latence quand disponibles.</p>
      </Card>
    </div>
  )
}

function MessageBubble({ message }) {
  const isUser = message.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-3xl rounded-2xl px-4 py-3 text-sm shadow-lg shadow-black/20 border border-[#1F2937] ${
          isUser ? 'bg-[#3B82F6]/10 text-[#E5E7EB]' : 'bg-[#121826] text-slate-100'
        }`}
      >
        <div className="whitespace-pre-wrap leading-relaxed">{message.content}</div>
        {message.meta && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
            <StatusBadge status={message.meta.fallback ? 'degraded' : 'ok'}>
              {message.meta.fallback ? 'Fallback' : 'Primary'}
            </StatusBadge>
            <span>Mode: {message.meta.mode}</span>
            <span>Model: {message.meta.model}</span>
            <span>Latency: {message.meta.latency_ms} ms</span>
          </div>
        )}
      </div>
    </div>
  )
}
