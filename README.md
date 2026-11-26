# Resilient Chat: LLM chatbot with key failover and response caching

React + FastAPI + SQLite, with LiteLLM as the LLM gateway.

## 1. Live URLs

| What | URL |
|------|-----|
| Frontend | https://lyftr-chatbot-5l2xdovp8-lyftr.vercel.app/ |
| Backend | https://lyftr-chatbot-backend-wsq3.onrender.com |
| Health | https://lyftr-chatbot-backend-wsq3.onrender.com/health |
| Demo video | https://lyftr-chatbot-5l2xdovp8-lyftr.vercel.app/ |

## 2. Run locally

### With Docker (required path)

```bash
cp .env.example .env      # then put 2+ real keys in LLM_API_KEYS
make up                   # backend :8000, frontend :3000
make down
```

`make up` also creates `.env` from `.env.example` if it is missing. SQLite lives on the
named volume `appdata`, mounted at `/data`, so history survives restarts.

### Without Docker

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export LLM_API_KEYS=key1,key2 DATABASE_URL=sqlite:///./app.db \
       ALLOWED_ORIGINS=http://localhost:3000 ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --port 8000

# frontend (second terminal)
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

Tests: `make test` (or `cd backend && python -m pytest`). They need no real keys.

### Deploying

* **Backend** (Render / Railway / Fly.io): deploy `backend/` as a Docker service. Set
  `LLM_API_KEYS`, `ALLOWED_ORIGINS=<frontend URL>`, `ENABLE_FAILURE_SIMULATION=true`,
  `DATABASE_URL=sqlite:////data/app.db` and attach a persistent disk at `/data`. The
  container honors `$PORT`.
* **Frontend** (Vercel / Netlify / Cloudflare Pages): root `frontend/`, build `npm run build`,
  output `dist`, env var `VITE_API_URL=<backend URL>` (no trailing slash).

## 3. Design decisions

**Key fallback.** `LLM_API_KEYS` is split into a pool with ids `key_1`, `key_2`, ... in order.
For each request the gateway tries the keys in order, calling `litellm.completion(api_key=...)`
with `num_retries=0`. Any provider failure (429, quota, 5xx, timeout, connection error, empty
reply) moves to the next key. The response reports which key answered (`key_id`, never the key
itself) and how many failed first (`fallback_attempts`). If every key fails the API returns
`503 {"detail": "all providers unavailable"}`, and nothing is written to history. Keys are never
logged or returned. `X-Simulate-Failure` (only when `ENABLE_FAILURE_SIMULATION=true`) marks the
chosen keys as failed for that single request, and the remaining keys make a real call.
Simulated requests bypass the cache so they always show a real failover.

**Caching.** LiteLLM's built-in in-memory cache (`litellm.cache = Cache(type="local")`).
LiteLLM builds the key from the model and the complete message list (system prompt + history +
new message), so the same first message in a new session is a hit, and any different message is
a miss. A hit is detected through LiteLLM's `cache_hit` flag and reported as `LLM_CACHE`, with
the identical reply, the usage stored with the cached response, `key_id: null` and
`fallback_attempts: 0`. The cache is per process and is cleared on restart.

**SQLite session storage.** Tables `messages` (the schema from the brief, plus an index on
`session_id, id`) and `sessions` (per-session system prompt). The schema is created on startup.
The client sends only the new message. The backend loads the last `MAX_HISTORY_MESSAGES`
messages, prepends the system prompt, and sends them to the model. The user and assistant rows
are written in one transaction only after a successful reply, so failed requests (422/503) never
enter history. The system prompt is stored on the session and is not returned by the history
endpoint.

**Other choices.** All errors, including unexpected ones, are JSON with a `detail` field.
Token counts come from the provider's usage for that request only. Latency is measured on the
server with a monotonic clock around the whole request.

## 4. Verification

Set `B` to your backend URL.

```bash
B=http://localhost:8000
curl $B/health

# live call, then the same message in a NEW session -> LLM_CACHE, key_id null, same reply
curl -s $B/chat -H 'content-type: application/json' \
  -d '{"session_id":"s-a","message":"What is the capital of France?"}'
curl -s $B/chat -H 'content-type: application/json' \
  -d '{"session_id":"s-b","message":"What is the capital of France?"}'

# failover -> 200, key_id key_2, fallback_attempts 1
curl -s $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"s-c","message":"Name a prime number"}'

# all keys fail -> 503 {"detail":"all providers unavailable"}, nothing stored
curl -si $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"s-d","message":"hello"}'

# history, and 404 for unknown sessions
curl -s $B/sessions/s-a/messages
curl -si $B/sessions/nope/messages
```

In the UI each assistant reply shows source, model, latency, input tokens and output tokens
for that request only (plus the key and fallback count). The "Failover demo" selector in the
side panel sends `X-Simulate-Failure` for you.

## 5. Setup used

* Editor: _fill in (e.g. VS Code)_
* AI tools: Claude (generated the first version of the code, tests and this README),
  reviewed and tested by me. _Edit to match what you actually used._

## 6. Bonus features

* System-prompt field (stored per session, shown in the side panel).
* Failover demo selector in the UI, so failover can be shown without curl.
* Key id and fallback count shown on every reply.
* Backend test-suite (17 tests, no real keys needed) covering caching, failover, validation,
  multi-turn, sessions and CORS.
* Non-root container, container health check, `$PORT` support for PaaS hosts.

## Notes

* If `gemini-2.0-flash` has been retired for your key, set
  `LLM_MODEL=gemini/gemini-2.5-flash` (any LiteLLM model name works).
* `LLM_MOCK_RESPONSE` makes LiteLLM return fixed text instead of calling a provider. It is for
  tests and key-less demos only; leave it unset in production.
* Pair `ENABLE_FAILURE_SIMULATION=true` with caution: it is required by the assignment on the
  deployed backend, but should be off in a real production system.
