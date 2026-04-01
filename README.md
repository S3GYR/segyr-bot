# SEGYR BOT - Observabilité temps réel (FastAPI + WebSocket + Redis + React)

## Présentation

Console d’observabilité temps réel : dashboards live, logs en continu,
métriques live, détection de fallback LLM, scoring de performance et
timelines par request_id.

## Architecture

- Backend : FastAPI (HTTP + WebSocket `/ws/logs`, `/ws/metrics`)
- WebSockets : ping/pong heartbeat, reconnexion backoff, contrôle
  d’origine/token
- Redis : Pub/Sub pour diffusion des logs
- Frontend : React (Vite) avec streaming temps réel (logs + metrics)
- Flux WebSocket (texte) :
  - Client → ping / données optionnelles
  - Serveur → pong + `server_ping` périodique, messages JSON (logs/metrics)

## Fonctionnalités

- Logs en temps réel (groupement par request_id, timeline, scoring,
  debug mode)
- Metrics live (latence, queue, fallbacks, requêtes)
- Détection fallback LLM et badge visuel
- Scoring performance (latence, erreurs, fallback)
- Heartbeat WebSocket + reconnexion automatique

## Installation

### Backend

```bash
python -m venv .venv
source .venv/bin/activate  # ou .venv\Scripts\activate sous Windows
pip install -r requirements.txt
export REDIS_URL=redis://localhost:6379
uvicorn segyr_bot.gateway:app --host 0.0.0.0 --port 8090
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # ou npm run build && npm run preview
```

## Variables d’environnement

### Backend

- REDIS_URL (ex: redis://redis:6379)
- MAX_WS_CONNECTIONS (limite globale WS, 0 = illimité)
- WS_MAX_SIZE (bytes max par message WS)
- WS_PING_INTERVAL (intervalle ping serveur, sec)
- MAX_WS_PER_IP / MAX_WS_PER_MIN_IP (throttle IP)
- WS_ALLOWED_ORIGINS (ex: <http://localhost:3200>)
- WS_TOKEN (optionnel, header X-WS-Token)

### Frontend

- VITE_API_BASE (ex: <http://localhost:8090>)
- VITE_WS_LOGS (ex: ws://localhost:8090/ws/logs)
- VITE_WS_METRICS (ex: ws://localhost:8090/ws/metrics)

## Lancement avec Docker

```bash
docker-compose up --build
```

- backend : gunicorn + uvicorn workers, port 8090
- frontend : Vite dev/preview ou build statique, port 3200
- redis : service pub/sub

## Notes production

- Scaling WebSocket : sticky sessions ou nœuds dédiés WS, LB compatible
  Upgrade/Connection, augmenter `ulimit -n`.
- Redis tuning : surveiller pub/sub (latence, buffer),
  client-output-buffer-limit, ops/sec.
- Load balancer : timeout > intervalle ping, proxy WebSocket activé.
