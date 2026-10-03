"""
Tests for the authoritative-sources registry.

What these tests protect:
* the registry is a real, filterable list of official databases (finding:
  "NO links to any official registry");
* FREE / FREE_REGISTRATION is distinguished from PAID_SUBSCRIPTION, and
  anything paid or restricted is always returned with ``requires_permission``
  plus a ``restricted_note`` - never as if it were directly accessible;
* TKDL is never marked FREE (it is RESTRICTED_NOT_ACCESSED and the platform
  does not query it);
* every entry carries a real URL and a verification date.
"""
from __future__ import annotations

from app.data.official_sources import (
    ACCESS_FREE,
    ACCESS_PAID_SUBSCRIPTION,
    ACCESS_RESTRICTED,
    ACCESS_THIRD_PARTY_API,
    ACCESS_VALUES,
    OFFICIAL_SOURCES,
    SOURCES,
    VERIFIED_ON,
    distinct_topics,
    get_official_source,
    list_official_sources,
    sources_for_topic,
)
from app.main import app
from app.routers.privacy import router as privacy_router
from app.routers.sources_registry import router as sources_registry_router

# Mounted idempotently so these tests pass before and after the integrator
# registers the routers in app/main.py.
def _mount(path: str, router) -> None:
    if not any(getattr(route, "path", None) == path for route in app.routes):
        app.include_router(router)


_mount("/api/privacy/notice", privacy_router)
_mount("/api/official-sources", sources_registry_router)

BASE = "/api/official-sources"


# -------------------------------------------------------
# Registry data quality
# -------------------------------------------------------

class TestRegistryData:
    def test_every_entry_has_required_fields(self):
        for entry in OFFICIAL_SOURCES:
            for field in (
                "id",
                "title",
                "authority",
                "jurisdiction",
                "ip_types",
                "topics",
                "access",
                "url",
                "what_you_can_do",
                "notes",
                "verified_on",
            ):
                assert field in entry, f"{entry.get('id')} missing {field}"
            assert entry["url"].startswith("http"), entry["id"]
            assert entry["verified_on"] == VERIFIED_ON
            assert entry["access"] in ACCESS_VALUES, entry["id"]
            assert entry["ip_types"] and entry["topics"]

    def test_ids_are_unique(self):
        ids = [entry["id"] for entry in OFFICIAL_SOURCES]
        assert len(ids) == len(set(ids))

    def test_paid_and_restricted_entries_carry_requires_permission(self):
        gated = [
            entry
            for entry in SOURCES
            if entry["access"]
            in (ACCESS_PAID_SUBSCRIPTION, ACCESS_THIRD_PARTY_API, ACCESS_RESTRICTED)
        ]
        assert gated, "the registry must contain gated connectors"
        for entry in gated:
            assert entry["requires_permission"] is True, entry["id"]
            assert entry["direct_access"] is False, entry["id"]
            assert entry["restricted_note"], entry["id"]

    def test_free_entries_are_directly_accessible(self):
        free = [entry for entry in SOURCES if entry["access"] == ACCESS_FREE]
        assert free
        for entry in free:
            assert entry["requires_permission"] is False
            assert entry["direct_access"] is True
            assert entry["restricted_note"] is None

    def test_india_patent_search_is_present_and_free(self):
        entry = get_official_source("ip-india-patent-search")
        assert entry is not None
        assert entry["access"] == ACCESS_FREE
        assert "ipindiaonline.gov.in" in entry["url"]

    def test_tkdl_is_never_free_and_never_claimed_accessible(self):
        entry = get_official_source("tkdl-india")
        assert entry is not None
        assert entry["access"] == ACCESS_RESTRICTED
        assert entry["access"] != ACCESS_FREE
        assert entry["requires_permission"] is True
        assert entry["direct_access"] is False
        assert "NOT ACCESSED" in entry["notes"]

        # Not reachable as "free" through any filter either.
        assert all(
            e["id"] != "tkdl-india" for e in list_official_sources(access=ACCESS_FREE)
        )
        assert any(
            e["id"] == "tkdl-india" for e in list_official_sources(access=ACCESS_RESTRICTED)
        )

    def test_official_domains_cover_the_required_bodies(self):
        urls = " ".join(entry["url"] for entry in OFFICIAL_SOURCES)
        for needle in (
            "ipindiaonline.gov.in",
            "ipindia.gov.in",
            "gisearch.ipindiaonline.gov.in",
            "nbaindia.org",
            "tkdl.res.in",
            "ayush.gov.in",
            "cdsco.gov.in",
            "fssai.gov.in",
            "egazette.nic.in",
            "indiacode.nic.in",
            "plantauthority.gov.in",
            "patentscope.wipo.int",
            "madridmonitor.wipo.int",
            "hague.wipo.int",
            "branddb.wipo.int",
            "wipolex",
            "worldwide.espacenet.com",
            "euipo.europa.eu",
            "uspto.gov",
            "patents.google.com",
            "wto.org",
            "cbd.int",
            "absch.cbd.int",
        ):
            assert needle in urls, f"missing official source: {needle}"

    def test_filters(self):
        india = list_official_sources(jurisdiction="India")
        assert india
        assert all(entry["jurisdiction"] == "India" for entry in india)

        patents = list_official_sources(ip_type="patent")
        assert patents
        assert all("patent" in entry["ip_types"] for entry in patents)

        paid = list_official_sources(access="PAID_SUBSCRIPTION")
        assert paid
        assert all(entry["access"] == ACCESS_PAID_SUBSCRIPTION for entry in paid)

        combined = list_official_sources(jurisdiction="India", ip_type="patent")
        assert combined
        assert all(
            entry["jurisdiction"] == "India" and "patent" in entry["ip_types"]
            for entry in combined
        )

        assert list_official_sources(jurisdiction="Atlantis") == []

    def test_sources_for_topic_matches_keywords(self):
        hits = sources_for_topic("geographical indication ayurveda")
        assert hits
        assert any("gi" in entry["id"] or "geographical" in entry["title"].lower()
                   for entry in hits)
        assert sources_for_topic("") == []

    def test_distinct_topics_are_sorted_and_non_empty(self):
        topics = distinct_topics()
        assert topics and topics == sorted(topics)
        assert "prior art" in topics


# -------------------------------------------------------
# API
# -------------------------------------------------------

class TestSourcesApi:
    def test_requires_authentication(self, client):
        assert client.get(BASE).status_code == 401
        assert client.get(f"{BASE}/topics").status_code == 401
        assert client.get(f"{BASE}/ip-india-patent-search").status_code == 401

    def test_list_distinguishes_free_from_paid(self, client, auth_headers):
        response = client.get(BASE, headers=auth_headers)
        assert response.status_code == 200, response.json()
        data = response.json()["data"]

        assert data["count"] == len(data["sources"])
        assert data["direct_access_count"] > 0
        assert data["permission_required_count"] > 0
        assert data["verified_on"] == VERIFIED_ON
        assert data["direct_access_count"] + data["permission_required_count"] == data["count"]

        by_id = {entry["id"]: entry for entry in data["sources"]}
        assert by_id["ip-india-patent-search"]["requires_permission"] is False
        assert by_id["derwent-innovation"]["access"] == "PAID_SUBSCRIPTION"
        assert by_id["derwent-innovation"]["requires_permission"] is True
        assert by_id["derwent-innovation"]["restricted_note"]

    def test_list_filters(self, client, auth_headers):
        india = client.get(
            f"{BASE}?jurisdiction=India", headers=auth_headers
        ).json()["data"]
        assert india["sources"]
        assert all(entry["jurisdiction"] == "India" for entry in india["sources"])

        patents = client.get(f"{BASE}?ip_type=patent", headers=auth_headers).json()["data"]
        assert patents["sources"]
        assert all("patent" in entry["ip_types"] for entry in patents["sources"])

        paid = client.get(
            f"{BASE}?access=PAID_SUBSCRIPTION", headers=auth_headers
        ).json()["data"]
        assert paid["sources"]
        assert all(entry["requires_permission"] for entry in paid["sources"])

        restricted = client.get(
            f"{BASE}?access=RESTRICTED_NOT_ACCESSED", headers=auth_headers
        ).json()["data"]
        assert any(entry["id"] == "tkdl-india" for entry in restricted["sources"])

        invalid = client.get(f"{BASE}?access=OPEN", headers=auth_headers)
        assert invalid.status_code == 400
        assert invalid.json()["detail"]["code"] == "INVALID_ACCESS_FILTER"

    def test_keyword_search(self, client, auth_headers):
        data = client.get(f"{BASE}?q=nagoya", headers=auth_headers).json()["data"]
        assert data["sources"]
        assert any("nagoya" in entry["id"] for entry in data["sources"])

    def test_topics_endpoint(self, client, auth_headers):
        data = client.get(f"{BASE}/topics", headers=auth_headers).json()["data"]
        assert "prior art" in data["topics"]
        assert "India" in data["jurisdictions"]
        assert set(ACCESS_VALUES) == set(data["access_values"])

    def test_detail_of_paid_source_never_looks_free(self, client, auth_headers):
        response = client.get(f"{BASE}/derwent-innovation", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["access"] == "PAID_SUBSCRIPTION"
        assert data["requires_permission"] is True
        assert data["direct_access"] is False
        assert data["restricted_note"]
        assert data["permission_required"] is True
        assert data["your_permission"] is None
        assert data["consent_endpoint"] == "POST /api/privacy/sources/consent"
        assert data["access_endpoint"] == "POST /api/privacy/sources/access"

    def test_detail_of_restricted_tkdl(self, client, auth_headers):
        data = client.get(f"{BASE}/tkdl-india", headers=auth_headers).json()["data"]
        assert data["access"] == ACCESS_RESTRICTED
        assert data["requires_permission"] is True
        assert "Restricted" in data["restricted_note"]

    def test_detail_shows_your_permission_once_granted(self, client, auth_headers):
        granted = client.post(
            "/api/privacy/sources/consent",
            json={
                "source_id": "derwent-innovation",
                "access_type": "PAID_SUBSCRIPTION",
                "scope": ["search my licence"],
                "confirm": True,
            },
            headers=auth_headers,
        )
        assert granted.status_code == 200, granted.json()

        data = client.get(f"{BASE}/derwent-innovation", headers=auth_headers).json()["data"]
        assert data["your_permission"] is not None
        assert data["your_permission"]["permission"] == "GRANTED"
        assert data["your_permission"]["scope"] == ["search my licence"]

    def test_detail_unknown_source_is_404(self, client, auth_headers):
        response = client.get(f"{BASE}/does-not-exist", headers=auth_headers)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "SOURCE_NOT_FOUND"
