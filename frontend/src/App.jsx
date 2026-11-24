import { useEffect, useRef, useState } from "react";

const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

const FAILURE_OPTIONS = [
  { value: "", label: "None (normal request)" },
  { value: "key_1=429", label: "key_1 rate-limited (429)" },
  { value: "key_1=500", label: "key_1 server error (500)" },
  { value: "key_1=429,key_2=500", label: "key_1 and key_2 fail" },
  { value: "*=429", label: "Every key rate-limited" },
];

// A new session on every page load.
const newSessionId = () => "s-" + Math.random().toString(36).slice(2, 10);

function readableError(status, body) {
  if (status === 503) return "All AI providers are unavailable right now. Try again in a moment.";
  if (status === 422) {
    const first = Array.isArray(body?.detail) ? body.detail[0]?.msg : body?.detail;
    return `Your message could not be sent: ${first || "invalid input"}.`;
  }
  if (typeof body?.detail === "string") return body.detail;
  return `Something went wrong (status ${status}). Try again.`;
}

function Meta({ meta }) {
  const cached = meta.resolution_source === "LLM_CACHE";
  return (
    <dl className="meta">
      <div>
        <dt>Source</dt>
        <dd data-testid="meta-source" className={cached ? "tag cache" : "tag live"}>
          {meta.resolution_source}
        </dd>
      </div>
      <div>
        <dt>Model</dt>
        <dd data-testid="meta-model">{meta.model}</dd>
      </div>
      <div>
        <dt>Latency</dt>
        <dd data-testid="meta-latency">{meta.latency_ms} ms</dd>
      </div>
      <div>
        <dt>Input tokens</dt>
        <dd data-testid="meta-input-tokens">{meta.input_tokens}</dd>
      </div>
      <div>
        <dt>Output tokens</dt>
        <dd data-testid="meta-output-tokens">{meta.output_tokens}</dd>
      </div>
      <div>
        <dt>Key</dt>
        <dd data-testid="meta-key">{meta.key_id ?? "none (cache)"}</dd>
      </div>
      <div>
        <dt>Fallbacks</dt>
        <dd data-testid="meta-fallbacks">{meta.fallback_attempts}</dd>
      </div>
    </dl>
  );
}

export default function App() {
  const [sessionId, setSessionId] = useState(newSessionId);
  const [items, setItems] = useState([]); // {kind: user|assistant|error, text, meta?}
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [simulate, setSimulate] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [items, busy]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setItems((prev) => [...prev, { kind: "user", text }]);
    setBusy(true);
    try {
      const headers = { "Content-Type": "application/json" };
      if (simulate) headers["X-Simulate-Failure"] = simulate;
      const payload = { session_id: sessionId, message: text };
      if (systemPrompt.trim()) payload.system_prompt = systemPrompt.trim();

      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });
      let body = null;
      try {
        body = await res.json();
      } catch {
        /* non-JSON body */
      }
      if (!res.ok) {
        setItems((prev) => [...prev, { kind: "error", text: readableError(res.status, body) }]);
      } else {
        setItems((prev) => [
          ...prev,
          { kind: "assistant", text: body.reply, meta: body.metadata },
        ]);
      }
    } catch {
      setItems((prev) => [
        ...prev,
        { kind: "error", text: "Cannot reach the server. Check your connection and try again." },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function startNew() {
    setSessionId(newSessionId());
    setItems([]);
  }

  return (
    <div className="app">
      <header className="top">
        <h1>Resilient Chat</h1>
        <p>Multi-turn chat with key failover and response caching.</p>
      </header>

      <div className="layout">
        <main className="chat" aria-label="Conversation">
          <div className="thread" role="log" aria-live="polite">
            {items.length === 0 && (
              <p className="empty">
                Ask anything. Send the same question twice (even in a new chat) to see a cache hit.
              </p>
            )}
            {items.map((it, i) =>
              it.kind === "user" ? (
                <div key={i} className="row user" data-testid="user-message">
                  <div className="bubble">{it.text}</div>
                </div>
              ) : it.kind === "error" ? (
                <div key={i} className="row">
                  <div className="bubble error" role="alert" data-testid="error-message">
                    {it.text}
                  </div>
                </div>
              ) : (
                <div key={i} className="row">
                  <div className="bubble assistant" data-testid="assistant-message">
                    <div className="reply">{it.text}</div>
                    <Meta meta={it.meta} />
                  </div>
                </div>
              )
            )}
            {busy && (
              <div className="row">
                <div className="bubble pending">Thinking…</div>
              </div>
            )}
            <div ref={endRef} />
          </div>

          <div className="composer">
            <textarea
              data-testid="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Type a message. Enter sends, Shift+Enter adds a line."
              rows={2}
              maxLength={4000}
              aria-label="Message"
            />
            <button data-testid="send-button" onClick={send} disabled={busy}>
              Send
            </button>
          </div>
        </main>

        <aside className="side" aria-label="Session settings">
          <section>
            <h2>Session</h2>
            <p className="mono">{sessionId}</p>
            <button className="ghost" onClick={startNew}>
              Start a new chat
            </button>
          </section>

          <section>
            <h2>System prompt</h2>
            <textarea
              data-testid="system-prompt-input"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="Optional. Sets how the assistant behaves in this session."
              rows={4}
              maxLength={4000}
              aria-label="System prompt"
            />
          </section>

          <section>
            <h2>Failover demo</h2>
            <label htmlFor="sim" className="hint">
              Sends the X-Simulate-Failure header with your next messages.
            </label>
            <select id="sim" value={simulate} onChange={(e) => setSimulate(e.target.value)}>
              {FAILURE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </section>
        </aside>
      </div>
    </div>
  );
}
