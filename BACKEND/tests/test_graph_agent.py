"""
Knowledge graph + agentic orchestration endpoints (Stage 2, now mounted).

Covers: graph build (idempotent), node listing/filtering/detail, shortest
paths (including the honest no-path reply), the tool registry, a fully
deterministic agent run (no model), trace persistence + ownership, request
validation and auth boundaries.

No network: the model resolver is patched to raise so every run uses the
deterministic planner/summariser. Retrieval inside tools is real (SQLite
keyword arm on an empty corpus - honest abstention, never invented).
"""


def _no_llm(monkeypatch):
    """Force the deterministic fallback: model resolution always fails."""

    def _raise(*args, **kwargs):
        raise RuntimeError("no model in tests")

    monkeypatch.setattr("app.routers.graph.get_llm_provider", _raise)
    monkeypatch.setattr("app.routers.graph.get_llm_provider_for", _raise)


def _build(client, headers, full=False):
    return client.post(
        "/api/graph/build", json={"full": full}, headers=headers
    )


def test_build_is_idempotent(client, auth_headers):
    first = _build(client, auth_headers).json()
    assert first["success"] is True
    assert first["data"]["nodes_total"] > 0
    second = _build(client, auth_headers).json()
    assert second["data"]["nodes_total"] == first["data"]["nodes_total"]
    assert second["data"]["edges_total"] == first["data"]["edges_total"]


def test_nodes_filter_and_validation(client, auth_headers):
    _build(client, auth_headers)
    body = client.get("/api/graph/nodes", headers=auth_headers).json()
    assert body["success"] is True
    assert body["data"]["count"] > 0
    assert body["data"]["review_required"] is True

    filtered = client.get(
        "/api/graph/nodes", params={"node_type": "IP_TYPE"}, headers=auth_headers
    ).json()
    assert all(n["node_type"] == "IP_TYPE" for n in filtered["data"]["nodes"])

    bad = client.get(
        "/api/graph/nodes", params={"node_type": "BOGUS"}, headers=auth_headers
    )
    assert bad.status_code == 400


def test_node_detail_and_404(client, auth_headers):
    _build(client, auth_headers)
    nodes = client.get("/api/graph/nodes", headers=auth_headers).json()["data"][
        "nodes"
    ]
    node_id = nodes[0]["id"]
    detail = client.get(f"/api/graph/nodes/{node_id}", headers=auth_headers).json()
    assert detail["success"] is True
    assert detail["data"]["node"]["id"] == node_id
    assert "edges" in detail["data"]

    missing = client.get("/api/graph/nodes/999999", headers=auth_headers)
    assert missing.status_code == 404


def test_paths_between_listed_nodes_and_honest_miss(client, auth_headers):
    _build(client, auth_headers)
    nodes = client.get("/api/graph/nodes", headers=auth_headers).json()["data"][
        "nodes"
    ]
    assert len(nodes) >= 2
    between = client.get(
        "/api/graph/paths",
        params={"from": nodes[0]["id"], "to": nodes[1]["id"]},
        headers=auth_headers,
    )
    assert between.status_code == 200

    miss = client.get(
        "/api/graph/paths",
        params={"from": "zzz-no-such-concept", "to": "zzz-no-such-other"},
        headers=auth_headers,
    ).json()
    assert miss["success"] is True
    assert miss["data"] is None
    assert "No relational path" in (miss.get("message") or "")


def test_tool_registry_lists_tools(client, auth_headers):
    body = client.get("/api/agent/tools", headers=auth_headers).json()
    assert body["success"] is True
    assert len(body["data"]) > 0
    assert all("name" in t and "description" in t for t in body["data"])


def test_agent_run_deterministic_persists_and_scopes_traces(
    client, auth_headers, second_user_headers, monkeypatch
):
    _no_llm(monkeypatch)
    _build(client, auth_headers)
    result = client.post(
        "/api/agent/run",
        json={"query": "What IP routes apply to an Ayurvedic oil?", "max_steps": 2},
        headers=auth_headers,
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["answer"]
    assert body["disclaimer"]
    assert body["review_required"] is True
    assert body["run_id"] is not None
    assert body["steps_used"] <= 2

    traces = client.get("/api/agent/traces", headers=auth_headers).json()
    assert traces["success"] is True
    assert any(t["id"] == body["run_id"] for t in traces["data"]["traces"])

    detail = client.get(
        f"/api/agent/traces/{body['run_id']}", headers=auth_headers
    ).json()
    assert detail["success"] is True
    assert detail["data"]["id"] == body["run_id"]
    assert "trace" in detail["data"]

    # Another user's run id is not confirmable through this caller.
    other = client.get(
        f"/api/agent/traces/{body['run_id']}", headers=second_user_headers
    )
    assert other.status_code == 404


def test_agent_run_request_validation(client, auth_headers):
    empty = client.post(
        "/api/agent/run", json={"query": ""}, headers=auth_headers
    )
    assert empty.status_code == 422
    bad_provider = client.post(
        "/api/agent/run",
        json={"query": "hello", "provider": "bogus"},
        headers=auth_headers,
    )
    assert bad_provider.status_code == 400


def test_graph_and_agent_require_auth(client):
    assert client.get("/api/graph/nodes").status_code == 401
    assert client.get("/api/agent/tools").status_code == 401
    assert client.post("/api/agent/run", json={"query": "hi"}).status_code == 401
