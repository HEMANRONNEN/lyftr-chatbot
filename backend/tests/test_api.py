import litellm

CHAT = "/chat"


def chat(client, sid, msg, headers=None, **extra):
    return client.post(CHAT, json={"session_id": sid, "message": msg, **extra}, headers=headers or {})


# ---------- health ----------
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


# ---------- caching ----------
def test_live_then_cache_across_sessions(client):
    a = chat(client, "s-1", "What is the capital of France?").json()
    b = chat(client, "s-2", "What is the capital of France?").json()
    assert a["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert a["metadata"]["key_id"] == "key_1"
    assert a["metadata"]["fallback_attempts"] == 0
    assert b["metadata"]["resolution_source"] == "LLM_CACHE"
    assert b["metadata"]["key_id"] is None
    assert b["metadata"]["fallback_attempts"] == 0
    assert b["reply"] == a["reply"]
    assert b["metadata"]["input_tokens"] == a["metadata"]["input_tokens"]
    assert b["metadata"]["output_tokens"] == a["metadata"]["output_tokens"]
    assert isinstance(b["metadata"]["latency_ms"], int)


def test_different_message_is_never_cached(client):
    chat(client, "s-1", "What is the capital of France?")
    r = chat(client, "s-2", "What is the capital of Spain?").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"


# ---------- tokens ----------
def test_tokens_are_per_request_not_running_total(client):
    a = chat(client, "s-a", "aaaa bbbb cccc").json()["metadata"]["input_tokens"]
    b = chat(client, "s-b", "dddd eeee ffff").json()["metadata"]["input_tokens"]
    assert abs(a - b) <= 3
    meta = chat(client, "s-c", "hello there friend").json()["metadata"]
    assert isinstance(meta["input_tokens"], int) and meta["input_tokens"] > 0
    assert isinstance(meta["output_tokens"], int) and meta["output_tokens"] > 0


# ---------- multi-turn / history ----------
def test_multi_turn_history_is_sent_to_llm(client, monkeypatch, real_completion):
    seen = []

    def spy(**kwargs):
        seen.append(kwargs["messages"])
        return real_completion(**kwargs)

    monkeypatch.setattr(litellm, "completion", spy)
    chat(client, "s-m", "My name is Asha")
    chat(client, "s-m", "What is my name?")
    roles = [m["role"] for m in seen[1]]
    assert roles == ["system", "user", "assistant", "user"]
    assert seen[1][1]["content"] == "My name is Asha"


def test_sessions_are_separate_and_history_endpoint(client):
    chat(client, "s-x", "one")
    chat(client, "s-y", "two")
    x = client.get("/sessions/s-x/messages").json()
    assert x["session_id"] == "s-x"
    assert [m["role"] for m in x["messages"]] == ["user", "assistant"]
    assert x["messages"][0]["content"] == "one"
    assert "metadata" not in x["messages"][0]
    assert x["messages"][1]["metadata"]["resolution_source"] in {"LIVE_INFERENCE", "LLM_CACHE"}
    y = client.get("/sessions/s-y/messages").json()
    assert y["messages"][0]["content"] == "two"


def test_custom_system_prompt_is_used_and_not_in_history(client, monkeypatch, real_completion):
    seen = []

    def spy(**kwargs):
        seen.append(kwargs["messages"])
        return real_completion(**kwargs)

    monkeypatch.setattr(litellm, "completion", spy)
    chat(client, "s-p", "hi", system_prompt="You are a pirate.")
    chat(client, "s-p", "hi again")
    assert seen[0][0] == {"role": "system", "content": "You are a pirate."}
    assert seen[1][0] == {"role": "system", "content": "You are a pirate."}
    msgs = client.get("/sessions/s-p/messages").json()["messages"]
    assert all(m["role"] != "system" for m in msgs)


def test_unknown_session_404(client):
    r = client.get("/sessions/nope/messages")
    assert r.status_code == 404
    assert r.json() == {"detail": "session not found"}


# ---------- validation ----------
def test_validation_errors(client):
    assert client.post(CHAT, json={"session_id": "s", "message": ""}).status_code == 422
    assert client.post(CHAT, json={"session_id": "s", "message": "   "}).status_code == 422
    assert client.post(CHAT, json={"message": "hi"}).status_code == 422
    assert client.post(CHAT, json={"session_id": "", "message": "hi"}).status_code == 422
    assert client.post(CHAT, json={"session_id": "s", "message": "x" * 4001}).status_code == 422
    assert client.post(CHAT, json={"session_id": "s", "message": 123}).status_code == 422
    bad = client.post(CHAT, content="{not json", headers={"content-type": "application/json"})
    assert bad.status_code == 422
    assert "detail" in bad.json()
    assert client.get("/sessions/s/messages").status_code == 404  # nothing stored


def test_message_of_exactly_4000_chars_ok(client):
    assert chat(client, "s-big", "x" * 4000).status_code == 200


# ---------- failover ----------
def test_simulated_key1_429_falls_over_to_key2(client):
    r = chat(client, "s-f", "fresh question 1", headers={"X-Simulate-Failure": "key_1=429"})
    assert r.status_code == 200
    m = r.json()["metadata"]
    assert m["key_id"] == "key_2" and m["fallback_attempts"] == 1
    assert m["resolution_source"] == "LIVE_INFERENCE"
    assert r.json()["reply"]


def test_simulated_key1_500_falls_over_to_key2(client):
    r = chat(client, "s-f", "fresh question 2", headers={"X-Simulate-Failure": "key_1=500"})
    assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_2"


def test_simulated_all_keys_fail_gives_503_and_nothing_stored(client):
    for header in ("*=429", "key_1=429,key_2=500"):
        r = chat(client, "s-503", "will fail", headers={"X-Simulate-Failure": header})
        assert r.status_code == 503
        assert r.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/s-503/messages").status_code == 404


def test_simulation_header_ignored_when_disabled(make_client):
    c = make_client(simulation=False)
    r = chat(c, "s-off", "hello", headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_1"


def test_real_provider_failure_triggers_failover(client, monkeypatch, real_completion):
    def flaky(**kwargs):
        if kwargs["api_key"] == "k1":
            raise litellm.RateLimitError("quota", "gemini", kwargs["model"])
        return real_completion(**kwargs)

    monkeypatch.setattr(litellm, "completion", flaky)
    r = chat(client, "s-real", "hello real")
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_2"
    assert r.json()["metadata"]["fallback_attempts"] == 1


def test_all_real_providers_failing_gives_clean_503(client, monkeypatch):
    def boom(**kwargs):
        raise litellm.InternalServerError("down", "gemini", kwargs["model"])

    monkeypatch.setattr(litellm, "completion", boom)
    r = chat(client, "s-down", "hello")
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/s-down/messages").status_code == 404


def test_cors_allows_frontend_origin(client):
    r = client.options(
        CHAT,
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-simulate-failure",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
