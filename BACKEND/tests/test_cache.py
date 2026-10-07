"""
Tests for the response-cache layer (no Redis; in-process TTL).

What these tests protect:
* the TTL cache itself: hits, expiry, LRU eviction, prefix invalidation.
* analysis reuse: an unchanged version returns the stored COMPLETED run
  instead of spending another model call; any content edit forces a fresh
  run; ?reuse=false always forces a fresh run.
* overview caching: the second GET for an unchanged revision is served
  from cache; a new disclosure invalidates it.
* dashboard: COUNT-based roll-up stays correct and is cached per user.
* admin cache endpoints are ADMIN-only and report real counters.
"""
import json
import time
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.llm.schemas import StructuredRAGResponse
from app.models import Role, RoleName, User, UserRole
from app.models.rag_models import SourceDocument
from app.utils import hash_password
from app.utils.cache import TTLCache, cache


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


# -------------------------------------------------------
# Helpers (mirroring test_analysis.py / test_overview.py)
# -------------------------------------------------------

def _product_and_version(client, headers, name="Cache Product"):
    response = client.post("/api/products", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.json()
    data = response.json()["data"]
    return data["id"], data["current_version_id"]


def _base(pid, vid):
    return f"/api/products/{pid}/versions/{vid}"


def _add_claim(client, headers, pid, vid, text):
    response = client.post(
        f"{_base(pid, vid)}/claims",
        json={"claim_text": text, "claim_type": "wellness"},
        headers=headers,
    )
    assert response.status_code == 201, response.json()
    return response.json()["data"]


def _claim_llm_output():
    return json.dumps({"assessments": [], "summary": "No claims to review.", "warnings": []})


def _mock_llm(payload):
    llm = MagicMock()
    llm.generate.return_value = payload
    return llm


@contextmanager
def _patch_claim_analysis(payload):
    with patch("app.analysis.claim_analyzer.hybrid_retrieve", return_value=[]), patch(
        "app.analysis.claim_analyzer.get_llm_provider", return_value=_mock_llm(payload)
    ):
        yield


def _make_admin(client, db_session):
    user = User(
        username="cacheadmin",
        email="cacheadmin@example.com",
        password_hash=hash_password("cacheadmin123"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    role = db_session.query(Role).filter(Role.name == RoleName.ADMIN).first()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "cacheadmin@example.com", "password": "cacheadmin123"},
    )
    assert response.status_code == 200, response.json()
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


# -------------------------------------------------------
# TTLCache unit tests (no DB)
# -------------------------------------------------------

class TestTTLCache:
    def test_set_get_roundtrip(self):
        c = TTLCache(max_entries=8, default_ttl=60)
        assert c.get("a") is None
        c.set("a", {"x": 1})
        assert c.get("a") == {"x": 1}

    def test_expired_entries_miss(self):
        c = TTLCache(max_entries=8, default_ttl=60)
        c.set("a", 1, ttl=0.02)
        assert c.get("a") == 1
        time.sleep(0.05)
        assert c.get("a") is None

    def test_none_values_are_not_stored(self):
        c = TTLCache(max_entries=8, default_ttl=60)
        c.set("a", None)
        assert c.get("a") is None

    def test_lru_eviction_bounds_memory(self):
        c = TTLCache(max_entries=3, default_ttl=60)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        c.get("a")  # a is now most-recently used; b is oldest
        c.set("d", 4)
        assert c.get("b") is None
        assert c.get("a") == 1
        assert c.get("d") == 4

    def test_invalidate_prefix(self):
        c = TTLCache(max_entries=16, default_ttl=60)
        c.set("overview:v1:x", 1)
        c.set("overview:v1:y", 2)
        c.set("dashboard:u1", 3)
        assert c.invalidate_prefix("overview:v1:") == 2
        assert c.get("overview:v1:x") is None
        assert c.get("dashboard:u1") == 3

    def test_stats_count_hits_and_misses(self):
        c = TTLCache(max_entries=8, default_ttl=60)
        c.set("k", 1)
        c.get("k")
        c.get("missing")
        stats = c.stats()
        total_hits = sum(n["hits"] for n in stats["namespaces"].values())
        total_misses = sum(n["misses"] for n in stats["namespaces"].values())
        assert total_hits == 1
        assert total_misses == 1


# -------------------------------------------------------
# Analysis reuse
# -------------------------------------------------------

class TestAnalysisReuse:
    def test_second_run_reuses_the_stored_row(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        with _patch_claim_analysis(_claim_llm_output()):
            first = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)
        assert first.status_code == 200, first.json()
        assert first.json()["data"]["reused"] is False

        # No mocks at all here: a fresh LLM run would fail without them.
        # Reuse must return the stored row without touching the model.
        second = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)
        assert second.status_code == 200, second.json()
        assert second.json()["data"]["id"] == first.json()["data"]["id"]
        assert second.json()["data"]["reused"] is True

    def test_content_edit_forces_a_fresh_run(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        with _patch_claim_analysis(_claim_llm_output()):
            first = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)
        assert first.status_code == 200, first.json()

        _add_claim(client, auth_headers, pid, vid, "A claim added after the run")
        with _patch_claim_analysis(_claim_llm_output()):
            third = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)
        assert third.status_code == 200, third.json()
        assert third.json()["data"]["id"] != first.json()["data"]["id"]
        assert third.json()["data"]["reused"] is False

    def test_reuse_false_forces_a_fresh_run(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers)
        with _patch_claim_analysis(_claim_llm_output()):
            first = client.post(f"{_base(pid, vid)}/claims/analyze", headers=auth_headers)
        assert first.status_code == 200, first.json()
        with _patch_claim_analysis(_claim_llm_output()):
            forced = client.post(
                f"{_base(pid, vid)}/claims/analyze?reuse=false", headers=auth_headers
            )
        assert forced.status_code == 200, forced.json()
        assert forced.json()["data"]["id"] != first.json()["data"]["id"]
        assert forced.json()["data"]["reused"] is False


# -------------------------------------------------------
# Overview cache
# -------------------------------------------------------

class TestOverviewCache:
    def test_second_get_is_served_from_cache(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers, name="Overview Cache")
        first = client.get(f"{_base(pid, vid)}/overview", headers=auth_headers)
        assert first.status_code == 200, first.json()
        assert first.json()["data"]["served_from_cache"] is False
        second = client.get(f"{_base(pid, vid)}/overview", headers=auth_headers)
        assert second.status_code == 200, second.json()
        assert second.json()["data"]["served_from_cache"] is True
        # Same revision, same content.
        assert (
            second.json()["data"]["product"]["content_hash"]
            == first.json()["data"]["product"]["content_hash"]
        )

    def test_new_disclosure_invalidates_the_cache(self, client, auth_headers):
        pid, vid = _product_and_version(client, auth_headers, name="Overview Bust")
        assert client.get(f"{_base(pid, vid)}/overview", headers=auth_headers).status_code == 200
        cached = client.get(f"{_base(pid, vid)}/overview", headers=auth_headers).json()
        assert cached["data"]["served_from_cache"] is True

        created = client.post(
            f"{_base(pid, vid)}/disclosures",
            json={"disclosure_type": "conference_presentation", "description": "SIH demo"},
            headers=auth_headers,
        )
        assert created.status_code == 201, created.json()

        fresh = client.get(f"{_base(pid, vid)}/overview", headers=auth_headers).json()
        assert fresh["data"]["served_from_cache"] is False
        assert fresh["data"]["disclosures"]["event_count"] == 1


# -------------------------------------------------------
# Dashboard cache + COUNT rewrite
# -------------------------------------------------------

class TestDashboardCache:
    def test_counts_are_correct_and_cached(self, client, auth_headers):
        pid, _vid = _product_and_version(client, auth_headers, name="Dash Cache")
        first = client.get("/api/dashboard", headers=auth_headers).json()
        assert first["data"]["product_count"] == 1
        assert first["data"]["version_count"] == 1
        assert first["data"]["served_from_cache"] is False
        second = client.get("/api/dashboard", headers=auth_headers).json()
        assert second["data"]["product_count"] == 1
        assert second["data"]["served_from_cache"] is True


# -------------------------------------------------------
# Admin cache endpoints
# -------------------------------------------------------

class TestAdminCacheEndpoints:
    def test_non_admin_is_forbidden(self, client, auth_headers):
        assert client.get("/api/admin/cache/stats", headers=auth_headers).status_code == 403
        assert client.post("/api/admin/cache/clear", headers=auth_headers).status_code == 403

    def test_stats_and_clear(self, client, auth_headers, db_session):
        admin_headers = _make_admin(client, db_session)
        pid, vid = _product_and_version(client, auth_headers, name="Stats Product")
        assert client.get(f"{_base(pid, vid)}/overview", headers=auth_headers).status_code == 200
        assert client.get(f"{_base(pid, vid)}/overview", headers=auth_headers).status_code == 200

        stats = client.get("/api/admin/cache/stats", headers=admin_headers)
        assert stats.status_code == 200, stats.json()
        namespaces = stats.json()["data"]["namespaces"]
        assert namespaces["overview"]["hits"] >= 1

        cleared = client.post("/api/admin/cache/clear", headers=admin_headers)
        assert cleared.status_code == 200, cleared.json()
        assert cleared.json()["data"]["dropped_entries"] >= 1


# -------------------------------------------------------
# Chat answer cache
# -------------------------------------------------------

def _fake_rag(answer="Ashwagandha is an herb used in traditional practice."):
    return StructuredRAGResponse(
        answer=answer, citations=[], insufficient_evidence=False, warnings=[]
    )


def _seed_public_document(db_session, title):
    """Insert an indexed corpus document directly (changes the corpus revision)."""
    doc = SourceDocument(
        title=title,
        source_type="official_guidance",
        language="en",
        is_public=True,
        status="INDEXED",
        jurisdiction="IN",
        document_hash=uuid.uuid4().hex,
        chunk_count=1,
    )
    db_session.add(doc)
    db_session.commit()
    return doc.id


class TestChatAnswerCache:
    def test_identical_question_is_answered_once_per_context(
        self, client, auth_headers, db_session
    ):
        payload = {"message": "What is ashwagandha?", "include_my_documents": False}

        with patch(
            "app.routers.assistant.hybrid_retrieve", return_value=[]
        ) as retrieval, patch(
            "app.routers.assistant.generate_rag_answer",
            return_value=_fake_rag(),
        ):
            first = client.post("/api/assistant/chat", json=payload, headers=auth_headers)
            assert first.status_code == 200, first.text

            # Second turn continues the same session, exactly like the UI.
            sid = first.json()["session_id"]
            second = client.post(
                "/api/assistant/chat",
                json={**payload, "session_id": sid},
                headers=auth_headers,
            )
            assert second.status_code == 200, second.text

        # The second turn never touched retrieval or the LLM.
        assert retrieval.call_count == 1
        assert first.json()["answer"] == second.json()["answer"]
        assert second.json()["message_id"] != first.json()["message_id"]

        # Both turns are persisted - the conversation history stays complete.
        detail = client.get(f"/api/assistant/conversations/{sid}", headers=auth_headers)
        roles = [m["role"] for m in detail.json()["messages"]]
        assert roles == ["user", "assistant", "user", "assistant"]

    def test_new_corpus_document_invalidates_the_answer(self, client, auth_headers, db_session):
        payload = {"message": "What is ashwagandha?", "include_my_documents": False}

        with patch(
            "app.routers.assistant.hybrid_retrieve", return_value=[]
        ) as retrieval, patch(
            "app.routers.assistant.generate_rag_answer",
            return_value=_fake_rag(),
        ):
            first = client.post("/api/assistant/chat", json=payload, headers=auth_headers)
            assert first.status_code == 200, first.text
            sid = first.json()["session_id"]

            # A new corpus document changes what the same question should
            # answer, so the next turn must run retrieval again.
            _seed_public_document(db_session, "New AYUSH guidance")
            again = client.post(
                "/api/assistant/chat",
                json={**payload, "session_id": sid},
                headers=auth_headers,
            )
            assert again.status_code == 200, again.text

        assert retrieval.call_count == 2

    def test_a_different_context_never_reuses_the_answer(
        self, client, auth_headers
    ):
        with patch(
            "app.routers.assistant.hybrid_retrieve", return_value=[]
        ) as retrieval, patch(
            "app.routers.assistant.generate_rag_answer",
            return_value=_fake_rag(),
        ):
            base = {"message": "What is ashwagandha?", "include_my_documents": False}
            assert client.post(
                "/api/assistant/chat", json=base, headers=auth_headers
            ).status_code == 200
            # Same question, different jurisdiction scope -> different answer.
            other = {**base, "jurisdiction_mode": "india"}
            assert client.post(
                "/api/assistant/chat", json=other, headers=auth_headers
            ).status_code == 200

        assert retrieval.call_count == 2


# -------------------------------------------------------
# Screening reuse (patent / biodiversity / traditional knowledge)
# -------------------------------------------------------

class TestScreeningReuse:
    def _seed_demo_version(self, client, headers, name):
        pid, vid = _product_and_version(client, headers, name=name)
        client.post(
            f"{_base(pid, vid)}/ingredients",
            json={"botanical_name": "Withania somnifera", "common_name": "Ashwagandha"},
            headers=headers,
        )
        _add_claim(client, headers, pid, vid, "Supports stress resilience")
        return pid, vid

    def test_patent_search_is_reused_and_records_never_duplicate(
        self, client, auth_headers
    ):
        pid, vid = self._seed_demo_version(client, auth_headers, "Screen Reuse")

        first = client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)
        assert first.status_code == 200, first.json()
        assert first.json()["data"]["reused"] is False
        after_first = client.get(f"{_base(pid, vid)}/patents", headers=auth_headers).json()["data"]

        second = client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)
        assert second.status_code == 200, second.json()
        assert second.json()["data"]["reused"] is True
        assert second.json()["data"]["id"] == first.json()["data"]["id"]

        after_second = client.get(f"{_base(pid, vid)}/patents", headers=auth_headers).json()["data"]
        assert len(after_second) == len(after_first)  # no duplicate records

    def test_content_edit_forces_a_fresh_screening(self, client, auth_headers):
        pid, vid = self._seed_demo_version(client, auth_headers, "Screen Fresh")
        first = client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)
        assert first.status_code == 200, first.json()

        _add_claim(client, auth_headers, pid, vid, "A claim added after the screening")
        third = client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)
        assert third.status_code == 200, third.json()
        assert third.json()["data"]["reused"] is False
        assert third.json()["data"]["id"] != first.json()["data"]["id"]

    def test_biodiversity_and_tk_screenings_are_reused(self, client, auth_headers):
        pid, vid = self._seed_demo_version(client, auth_headers, "Bio TK Reuse")

        first_bio = client.post(f"{_base(pid, vid)}/biodiversity/screen", headers=auth_headers)
        assert first_bio.status_code == 200, first_bio.json()
        assert first_bio.json()["data"]["reused"] is False
        second_bio = client.post(f"{_base(pid, vid)}/biodiversity/screen", headers=auth_headers)
        assert second_bio.json()["data"]["reused"] is True
        assert second_bio.json()["data"]["id"] == first_bio.json()["data"]["id"]

        first_tk = client.post(f"{_base(pid, vid)}/traditional-knowledge/screen", headers=auth_headers)
        assert first_tk.status_code == 200, first_tk.json()
        assert first_tk.json()["data"]["reused"] is False
        second_tk = client.post(f"{_base(pid, vid)}/traditional-knowledge/screen", headers=auth_headers)
        assert second_tk.json()["data"]["reused"] is True
        assert second_tk.json()["data"]["id"] == first_tk.json()["data"]["id"]

    def test_reuse_false_forces_a_fresh_screening(self, client, auth_headers):
        pid, vid = self._seed_demo_version(client, auth_headers, "Screen OptOut")
        first = client.post(f"{_base(pid, vid)}/patents/search", headers=auth_headers)
        assert first.status_code == 200, first.json()
        forced = client.post(
            f"{_base(pid, vid)}/patents/search?reuse=false", headers=auth_headers
        )
        assert forced.status_code == 200, forced.json()
        assert forced.json()["data"]["reused"] is False
        assert forced.json()["data"]["id"] != first.json()["data"]["id"]
