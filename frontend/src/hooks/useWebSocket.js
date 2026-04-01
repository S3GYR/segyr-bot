import { useEffect, useRef, useState } from 'react'

const MIN_BACKOFF = 1000
const MAX_BACKOFF = 15000
const MAX_RETRIES = 8
const CLIENT_PING_INTERVAL = 10000
const STALE_THRESHOLD_MS = 25000

export default function useWebSocket(url, { onMessage } = {}) {
  const [status, setStatus] = useState(url ? 'connecting' : 'paused')
  const [latencyMs, setLatencyMs] = useState(null)
  const [lastMessage, setLastMessage] = useState(null)
  const [lastMessageAt, setLastMessageAt] = useState(null)
  const retryRef = useRef(0)
  const wsRef = useRef(null)
  const timerRef = useRef(null)
  const pingTimerRef = useRef(null)
  const idleTimerRef = useRef(null)
  const lastActivityRef = useRef(null)
  const lastPongRef = useRef(null)
  const callbackRef = useRef(onMessage)

  useEffect(() => {
    callbackRef.current = onMessage
  }, [onMessage])

  useEffect(() => {
    if (!url) {
      setStatus('paused')
      return undefined
    }

    const connect = () => {
      try {
        if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
          return
        }
        const ws = new WebSocket(url)
        wsRef.current = ws
        setStatus('connecting')

        ws.onopen = () => {
          retryRef.current = 0
          setStatus('open')
        }

        ws.onmessage = (event) => {
          let payload = event.data
          try {
            payload = JSON.parse(event.data)
          } catch (e) {
            // keep raw
          }
          setLastMessage(payload)
          const nowTs = Date.now()
          lastActivityRef.current = nowTs
          setLastMessageAt(nowTs)

          if (payload && typeof payload === 'object') {
            if (payload.type === 'server_ping') {
              ws.send(JSON.stringify({ type: 'pong', ts: payload.ts || nowTs }))
            }
            if (payload.type === 'ping') {
              ws.send(JSON.stringify({ type: 'pong', ts: payload.ts || nowTs }))
            }
            if (payload.type === 'pong' && payload.ts) {
              const rtt = Date.now() - Number(payload.ts)
              if (Number.isFinite(rtt) && rtt >= 0) setLatencyMs(rtt)
              lastPongRef.current = Date.now()
            }
          }

          if (typeof callbackRef.current === 'function') {
            callbackRef.current(payload)
          }
        }

        const scheduleReconnect = () => {
          if (timerRef.current) clearTimeout(timerRef.current)
          const attempt = Math.min(retryRef.current + 1, MAX_RETRIES)
          retryRef.current = attempt
          const jitter = 1 + Math.random() * 0.2
          const backoff = Math.min(MAX_BACKOFF, MIN_BACKOFF * 2 ** attempt) * jitter
          setStatus('reconnecting')
          timerRef.current = setTimeout(connect, backoff)
        }

        ws.onclose = () => {
          setStatus('closed')
          scheduleReconnect()
        }
        ws.onerror = () => {
          setStatus('error')
          scheduleReconnect()
        }
      } catch (e) {
        setStatus('reconnecting')
        const jitter = 1 + Math.random() * 0.2
        const backoff = Math.min(MAX_BACKOFF, MIN_BACKOFF * 2 ** (retryRef.current + 1)) * jitter
        timerRef.current = setTimeout(connect, backoff)
      }
    }

    connect()

    if (pingTimerRef.current) clearInterval(pingTimerRef.current)
    pingTimerRef.current = setInterval(() => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        const ts = Date.now()
        wsRef.current.send(JSON.stringify({ type: 'ping', ts }))
      }
    }, CLIENT_PING_INTERVAL)

    if (idleTimerRef.current) clearInterval(idleTimerRef.current)
    idleTimerRef.current = setInterval(() => {
      const last = lastActivityRef.current || 0
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && Date.now() - last > STALE_THRESHOLD_MS) {
        setStatus('stale')
        wsRef.current.close()
      }
    }, 5000)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      if (pingTimerRef.current) clearInterval(pingTimerRef.current)
      if (idleTimerRef.current) clearInterval(idleTimerRef.current)
      const ws = wsRef.current
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        ws.close()
      }
    }
  }, [url])

  return { status, latencyMs, lastMessage, lastActivity: lastMessageAt }
}
