"""
Chatbot jurisdiction scope — market-launch spec TEST 1-10.

Selected target markets must control retrieval, prompt context, answer
structure and citations; U.S. law must never be used for an India +
Germany question; evidence gaps and claim provenance must be explicit.

Automated test areas:
   1. India + Germany: no U.S. CGMP anywhere, per-market structure
      instructions, CANNOT_BE_DETERMINED, INSUFFICIENT evidence status,
      why-panel counts, missing-information list, claim review,
      prompt scoping (the model never sees an out-of-scope chunk)
      1b. residual U.S. references in a produced answer are stripped
      1c. the multi-part (selective) path applies the same scope
   2. United States selected: U.S. sources allowed and labelled
   3. India only: Germany/EU (and everything else) excluded
   4. Germany only: no Germany/EU source -> explicit gap, no LLM call
   5. No verified sources: no invented answer, specific gap warnings
   6. Private document search: honest requested/performed flags,
      private sources counted separately, failed search never claimed
   7. Claim provenance: USER_PROVIDED_ONLY / NOT_FOUND / REVIEW_REQUIRED
   8. Version context: changing the Product Passport version changes the
      market context and claim list (no stale reuse)
   9. Demo patent corpus: synthetic records are never chat citations or
      regulatory evidence; the demo label stays exact
  10. Language switch (BHASHINI): citations, jurisdictions, evidence
      status and warnings survive the switch unchanged

No network: the LLM is scripted through get_llm_provider /
get_llm_provider_for patches at the router boundary. Retrieval is real
(SQLite keyword arm of hybrid_retrieve on seeded corpus documents).
"""
import json
import uuid

from app.analysis.ip_schemas import DEMO_RECORD_LABEL
from app.bhashini.translator import SERVICE_UNAVAILABLE_WARNING
from app.llm.base import LLMProvider
from app.models.rag_models import SourceChunk, SourceDocument
from app.rag.partial_answer import STATUS_INSUFFICIENT, STATUS_SUPPORTED


LAUNCH_Q = "What do you think, can I launch my product to market?"

SPEC_MISSING_ITEMS = [
    "Product category",
    "Dosage form",
    "Manufacturing/licensing details",
    "Complete formulation",
    "Safety and quality evidence",
    "Claim substantiation",
    "Final label and marketing material",
]
SPEC_EVIDENCE_REASON = (
    "The current evidence does not establish the product category, "
    "market-specific requirements, manufacturing status, or claim "
    "substantiation."
)
JURISDICTION_WARNING = (
    "Only sources relevant to the selected markets are used for "
    "market-entry guidance."
)
RULE6_GERMANY = (
    "No verified Germany-specific source was retrieved for this answer."
)
RULE6_BOTH = (
    "No verified India- or Germany-specific source was retrieved for this answer."
)
CLAIM_40 = (
    "Our cold-press extraction method increases bioavailability by 40%."
)


# -------------------------------------------------------
# Helpers (same conventions as the other suites)
# -------------------------------------------------------

def seed_corpus(db_session, title, text, *, public=True, jurisdiction=None,
                source_type="official_guidance", uploader_id=None):
    """Insert an indexed document + one chunk directly (no embeddings)."""
    doc = SourceDocument(
        title=title,
        source_type=source_type,
        language="en",
        is_public=public,
        status="INDEXED",
        jurisdiction=jurisdiction,
        uploader_id=uploader_id,
        document_hash=uuid.uuid4().hex,
        chunk_count=1,
    )
    db_session.add(doc)
    db_session.flush()
    chunk = SourceChunk(
        document_id=doc.id,
        chunk_index=0,
        text=text,
        page_number=1,
        metadata_json=json.dumps(
            {"page": 1, "provenance": "VERIFIED_PUBLIC_SOURCE"}
        ),
    )
    db_session.add(chunk)
    db_session.commit()
    return doc, chunk


def chat(client, auth_headers, payload):
    return client.post("/api/assistant/chat", json=payload, headers=auth_headers)


class ScriptedLLM(LLMProvider):
    """Returns queued JSON responses in order (the last one repeats)."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0
        self.system_prompts = []
        self.user_prompts = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        self.system_prompts.append(system_prompt)
        self.user_prompts.append(user_prompt)
        if len(self.responses) > 1:
            return self.responses.pop(0)
        if self.responses:
            return self.responses[0]
        return json.dumps({"sections": []})


def cite(chunk, doc, source_type="official_guidance"):
    """A citation row pointing at a real seeded chunk."""
    return {
        "chunk_id": chunk.id,
        "document_id": doc.id,
        "title": doc.title,
        "source_type": source_type,
        "relevant_text": chunk.text[:120],
    }


def launch_answer(citations, answer=None):
    """Single-path structured answer shaped like the spec's launch reply."""
    if answer is None:
        answer = (
            "Launch readiness: Cannot be determined from the current information.\n\n"
            "What is known:\n"
            "India requires a manufacturing licence before the product can be "
            "placed on the market [1].\n\n"
            "Germany/EU:\n" + RULE6_GERMANY + "\n\n"
            "Required next steps:\n- Provide the product category and "
            "manufacturing details.\n\n"
            "Professional review warning:\nConsult qualified regulatory "
            "professionals before any launch decision.\n\n"
            "Sources:\n[1] India Drug Licensing Guide"
        )
    return json.dumps({
        "answer": answer,
        "insufficient_evidence": False,
        "citations": citations,
        "warnings": [],
    })


def decompose_json(pairs):
    """Queued decompose_query response: [(topic, question), ...]."""
    return json.dumps(
        {"subquestions": [{"topic": t, "question": q} for t, q in pairs]}
    )


def section(topic, status, answer, citations=None, next_action=None):
    """One raw section row for a scripted selective-answer response."""
    row = {
        "topic": topic,
        "status": status,
        "answer": answer,
        "provenance": [],
        "citations": citations or [],
        "claims": [],
    }
    if next_action:
        row["next_action"] = next_action
    return row


def make_product(client, headers, *, name=None, markets=(), claims=(),
                 with_formulation=True):
    """Create a product + V1 with ingredient, formulation, claims, markets."""
    name = name or f"AshwaBio-{uuid.uuid4().hex[:6]}"
    r = client.post("/api/products", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    pid, vid = data["id"], data["current_version_id"]
    base = f"/api/products/{pid}/versions/{vid}"

    ir = client.post(
        f"{base}/ingredients",
        json={
            "common_name": "Ashwagandha",
            "botanical_name": "Withania somnifera",
            "plant_part": "root",
            "quantity": 100,
            "quantity_unit": "g",
            "source_type": "cultivated",
            "source_location": "Uttarakhand, India",
            "preparation_method": "powder",
        },
        headers=headers,
    )
    assert ir.status_code == 201, ir.text

    if with_formulation:
        fr = client.put(
            f"{base}/formulation",
            json={
                "process_description": "Cold-press extraction of the root at controlled temperature.",
                "extraction_method": "cold_press",
                "solvent": "",
                "pressure": "",
                "concentration": "",
                "temperature": 4,
                "temperature_unit": "C",
            },
            headers=headers,
        )
        assert fr.status_code in (200, 201), fr.text

    for claim in claims:
        cr = client.post(
            f"{base}/claims",
            json={"claim_text": claim, "claim_type": "structure_function"},
            headers=headers,
        )
        assert cr.status_code == 201, cr.text

    for country in markets:
        mr = client.post(
            f"{base}/target-markets", json={"country": country}, headers=headers
        )
        assert mr.status_code == 201, mr.text

    return pid, vid


def seed_india_and_us(db_session):
    """The reported scenario's corpus: an India source and the US CFR doc."""
    india_doc, india_chunk = seed_corpus(
        db_session,
        "India Drug Licensing Guide",
        "Launching an Ayurvedic product on the Indian market requires a "
        "manufacturing licence under the Drugs and Cosmetics Act.",
        jurisdiction="India",
    )
    us_doc, us_chunk = seed_corpus(
        db_session,
        "Cfr Title21 Part211 Cgmp",
        "Current good manufacturing practice for finished pharmaceuticals: "
        "21 CFR Parts 210 and 211 apply before product launch in the United "
        "States market.",
        jurisdiction="United States",
    )
    return india_doc, india_chunk, us_doc, us_chunk


def launch_payload(pid, vid, **extra):
    payload = {
        "message": LAUNCH_Q,
        "product_id": pid,
        "product_version_id": vid,
        "include_my_documents": True,
    }
    payload.update(extra)
    return payload


# -------------------------------------------------------
# TEST 1 - India + Germany (the reported scenario)
# -------------------------------------------------------

class Test1IndiaGermanyScope:
    def test_launch_answer_is_scoped_and_structured(
        self, client, auth_headers, db_session, monkeypatch
    ):
        india_doc, india_chunk, us_doc, us_chunk = seed_india_and_us(db_session)
        pid, vid = make_product(
            client, auth_headers,
            markets=["India", "Germany"], claims=[CLAIM_40],
        )
        fake = ScriptedLLM(launch_answer([cite(india_chunk, india_doc)]))
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        resp = chat(client, auth_headers, launch_payload(pid, vid))
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # --- markets control the jurisdiction scope -------------------
        assert body["market_context"] == ["India", "Germany/EU"]
        assert body["jurisdiction_filter"] == ["India", "Germany", "European Union"]
        assert body["unselected_jurisdiction_sources_excluded"] == ["United States"]
        assert body["jurisdiction_warning"] == JURISDICTION_WARNING

        # --- evidence status + launch decision ------------------------
        assert body["evidence_status"]["overall_status"] == "INSUFFICIENT"
        assert body["evidence_status"]["launch_decision"] == "CANNOT_BE_DETERMINED"
        assert body["evidence_status"]["reason"] == SPEC_EVIDENCE_REASON

        # --- no U.S. CGMP in the answer or the citations ---------------
        assert "21 CFR" not in body["answer"]
        assert body["citations"], "the in-scope India source must be cited"
        for c in body["citations"]:
            assert c["jurisdiction"] != "United States"
            assert "Cfr" not in c["title"] and "CFR" not in c["title"]
            assert c["jurisdiction"] in (None, "India", "Germany", "European Union")

        # --- explicit Germany evidence gap (rule 6) --------------------
        assert body["evidence_gap_warnings"] == [RULE6_GERMANY]

        # --- why-panel -------------------------------------------------
        why = body["why_this_answer"]
        assert why["selected_markets"] == ["India", "Germany"]
        assert why["sources_used"]["India"] >= 1
        assert why["sources_used"]["Germany/EU"] == 0
        assert why["sources_used"]["Private documents"] == 0
        assert "United States — not a selected target market" in why["sources_excluded"]
        assert why["missing_information"] == SPEC_MISSING_ITEMS

        # --- claim review (never "proven") -----------------------------
        claim = body["claim_reviews"][0]
        assert claim["claim_text"] == CLAIM_40
        assert claim["provenance"] == "USER_PROVIDED"
        assert claim["evidence_status"] == "USER_PROVIDED_ONLY"
        assert claim["independent_verification"] == "NOT_FOUND"
        assert claim["marketing_use"] == "REVIEW_REQUIRED"

        # --- honest private-search flags -------------------------------
        assert body["private_search_requested"] is True
        assert body["private_search_performed"] is True
        assert body["public_sources_found"] >= 1
        assert body["private_sources_found"] == 0

        # --- what the model was told (prompt scoping) ------------------
        prompt = fake.user_prompts[0]
        assert "=== MARKET CONTEXT" in prompt
        assert "Allowed source jurisdictions: India, Germany, European Union" in prompt
        assert '"India:"' in prompt and '"Germany/EU:"' in prompt
        assert "Never apply or cite the law of a jurisdiction outside the allowed list" in prompt
        assert "Launch readiness: Cannot be determined from the current information." in prompt
        # the US chunk never reaches the model at all
        assert "21 CFR" not in prompt
        assert "United States market" not in prompt

    def test_residual_us_reference_is_removed_from_answer(
        self, client, auth_headers, db_session, monkeypatch
    ):
        india_doc, india_chunk, _, _ = seed_india_and_us(db_session)
        pid, vid = make_product(client, auth_headers, markets=["India", "Germany"])
        scripted = launch_answer(
            [cite(india_chunk, india_doc)],
            answer=(
                "Launch readiness: Cannot be determined from the current information.\n"
                "India: a manufacturing licence is required [1].\n"
                "Products must follow 21 CFR Part 211 cGMP for launch.\n"
                "Germany/EU: " + RULE6_GERMANY
            ),
        )
        fake = ScriptedLLM(scripted)
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        resp = chat(client, auth_headers, launch_payload(pid, vid))
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # the U.S. sentence is dropped from the produced answer
        assert "21 CFR" not in body["answer"]
        assert "a manufacturing licence is required" in body["answer"]
        # and the filtering event is reported and logged via warnings
        assert any("U.S. regulatory reference" in w for w in body["warnings"])

    def test_multi_part_path_applies_the_same_scope(
        self, client, auth_headers, db_session, monkeypatch
    ):
        india_doc, india_chunk, _, _ = seed_india_and_us(db_session)
        pid, vid = make_product(client, auth_headers, markets=["India", "Germany"])

        fake = ScriptedLLM(
            decompose_json([
                ("General", "Can I launch my product to market?"),
                ("Regulatory", "What licensing is required?"),
            ]),
            json.dumps({
                "sections": [
                    section(
                        "General", STATUS_SUPPORTED,
                        "India: a manufacturing licence is required [1].",
                        citations=[cite(india_chunk, india_doc)],
                    ),
                    section(
                        "Regulatory", STATUS_INSUFFICIENT,
                        RULE6_GERMANY,
                        next_action="Add a verified Germany/EU source.",
                    ),
                ]
            }),
        )
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        resp = chat(
            client, auth_headers,
            launch_payload(pid, vid, message="What do you think? Can I launch my product to market?"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert any("=== MARKET CONTEXT" in p for p in fake.user_prompts)
        assert body["jurisdiction_filter"] == ["India", "Germany", "European Union"]
        assert body["unselected_jurisdiction_sources_excluded"] == ["United States"]
        assert body["evidence_status"]["overall_status"] == "INSUFFICIENT"
        assert body["evidence_gap_warnings"] == [RULE6_GERMANY]
        for c in body["citations"]:
            assert c["jurisdiction"] != "United States"
        assert "21 CFR" not in body["answer"]


# -------------------------------------------------------
# TEST 2 - United States selected: U.S. sources allowed + labelled
# -------------------------------------------------------

class Test2UnitedStatesSelected:
    def test_us_sources_allowed_and_labelled(
        self, client, auth_headers, db_session, monkeypatch
    ):
        india_doc, india_chunk, us_doc, us_chunk = seed_india_and_us(db_session)
        pid, vid = make_product(client, auth_headers, markets=["United States"])
        fake = ScriptedLLM(launch_answer([cite(us_chunk, us_doc)]))
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        resp = chat(client, auth_headers, launch_payload(pid, vid))
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["market_context"] == ["United States"]
        assert body["jurisdiction_filter"] == ["United States"]
        assert body["unselected_jurisdiction_sources_excluded"] == ["India"]

        us_citations = [c for c in body["citations"] if c["jurisdiction"] == "United States"]
        assert us_citations, "a U.S. source is allowed when the U.S. is selected"
        assert us_citations[0]["jurisdiction"] == "United States"  # human label, never raw code

        prompt = fake.user_prompts[0]
        assert "Selected target markets: United States" in prompt
        assert "Allowed source jurisdictions: United States" in prompt
        assert '"United States:"' in prompt
        # India/Germany requirements are not presented as U.S. sections
        assert "Germany/EU" not in prompt
        # but the no-substitution rule still holds
        assert "Do not substitute one country's law for another's" in prompt


# -------------------------------------------------------
# TEST 3 - India only
# -------------------------------------------------------

class Test3IndiaOnly:
    def test_india_only_excludes_germany_eu(
        self, client, auth_headers, db_session, monkeypatch
    ):
        india_doc, india_chunk = seed_corpus(
            db_session, "India Licensing Guide",
            "Launching a product on the Indian market requires a licence.",
            jurisdiction="India",
        )
        eu_doc, _ = seed_corpus(
            db_session, "EU Traditional Herbal Guidance",
            "Market entry in the European Union requires a traditional "
            "herbal registration.",
            jurisdiction="European Union",
        )
        pid, vid = make_product(client, auth_headers, markets=["India"])
        fake = ScriptedLLM(launch_answer([cite(india_chunk, india_doc)]))
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        resp = chat(client, auth_headers, launch_payload(pid, vid))
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["market_context"] == ["India"]
        assert body["jurisdiction_filter"] == ["India"]
        assert body["unselected_jurisdiction_sources_excluded"] == ["European Union"]
        assert body["evidence_status"]["overall_status"] in (
            "INSUFFICIENT", "PARTIALLY_SUPPORTED",
        )
        for c in body["citations"]:
            assert c["jurisdiction"] != "European Union"
            assert c["jurisdiction"] != "United States"

        prompt = fake.user_prompts[0]
        assert "Allowed source jurisdictions: India" in prompt
        assert "Germany/EU" not in prompt
        assert "European Union" not in prompt


# -------------------------------------------------------
# TEST 4 - Germany only: no Germany/EU source in the corpus
# -------------------------------------------------------

class Test4GermanyOnly:
    def test_germany_only_abstains_with_specific_gap(
        self, client, auth_headers, db_session, monkeypatch
    ):
        seed_corpus(
            db_session, "India Licensing Guide",
            "Launching a product on the Indian market requires a licence.",
            jurisdiction="India",
        )
        pid, vid = make_product(client, auth_headers, markets=["Germany"])
        fake = ScriptedLLM()
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        resp = chat(client, auth_headers, launch_payload(pid, vid))
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # no in-scope source -> the model is never asked to fill the gap
        assert fake.calls == 0
        assert body["insufficient_evidence"] is True
        assert body["jurisdiction_filter"] == ["Germany", "European Union"]
        assert body["unselected_jurisdiction_sources_excluded"] == ["India"]
        assert body["evidence_status"]["overall_status"] == "INSUFFICIENT"
        assert body["evidence_status"]["launch_decision"] == "CANNOT_BE_DETERMINED"
        assert body["evidence_gap_warnings"][0] == RULE6_GERMANY
        # professional review recommendation present, no country substitution
        assert any("qualified professional" in w.lower() for w in body["warnings"])
        assert "21 CFR" not in body["answer"]
        assert "Drugs and Cosmetics" not in body["answer"]


# -------------------------------------------------------
# TEST 5 - No verified sources at all
# -------------------------------------------------------

class Test5NoVerifiedSources:
    def test_evidence_gap_instead_of_invented_answer(
        self, client, auth_headers, db_session, monkeypatch
    ):
        pid, vid = make_product(
            client, auth_headers, markets=["India", "Germany"], claims=[CLAIM_40],
        )
        fake = ScriptedLLM()
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        resp = chat(client, auth_headers, launch_payload(pid, vid))
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # nothing retrieved -> no model call, no invented citations
        assert fake.calls == 0
        assert body["citations"] == []
        assert body["insufficient_evidence"] is True

        # specific evidence gap: rule 6 (both markets) + the launch sentence
        gaps = body["evidence_gap_warnings"]
        assert RULE6_BOTH in gaps
        assert any(
            g.startswith("The verified corpus does not contain enough India- or Germany")
            and g.endswith(
                "specific evidence to answer whether this product can be "
                "launched. Add verified sources or consult a qualified professional."
            )
            for g in gaps
        )
        assert body["evidence_status"]["overall_status"] == "INSUFFICIENT"
        # professional review recommendation (never launch-ready)
        assert any("qualified professional" in w.lower() for w in body["warnings"])
        assert any("legal" in w.lower() or "professional" in w.lower()
                   for w in body["warnings"])
        assert "21 CFR" not in body["answer"]
        assert body["jurisdiction_filter"] == ["India", "Germany", "European Union"]
        assert body["unselected_jurisdiction_sources_excluded"] == []


# -------------------------------------------------------
# TEST 6 - Private document search (honest status)
# -------------------------------------------------------

class Test6PrivateDocumentSearch:
    private_text = (
        "Internal launch checklist: this product may be launched only after "
        "the category is confirmed and the label is finalised."
    )

    def test_search_enabled_finds_and_counts_private_sources(
        self, client, auth_headers, db_session, test_user, monkeypatch
    ):
        india_doc, india_chunk = seed_corpus(
            db_session, "India Licensing Guide",
            "Launching a product on the Indian market requires a licence.",
            jurisdiction="India",
        )
        private_doc, private_chunk = seed_corpus(
            db_session, "Internal launch checklist.pdf",
            self.private_text,
            public=False,
            source_type="USER_UPLOAD",
            uploader_id=test_user.id,
        )
        pid, vid = make_product(client, auth_headers, markets=["India"])
        fake = ScriptedLLM(
            launch_answer([
                cite(india_chunk, india_doc),
                cite(private_chunk, private_doc, source_type="USER_UPLOAD"),
            ])
        )
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        resp = chat(client, auth_headers, launch_payload(pid, vid))
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["private_search_requested"] is True
        assert body["private_search_performed"] is True
        assert body["private_sources_found"] == 1
        assert body["public_sources_found"] >= 1
        # a private source is kept in scope (untagged) and labelled as user data
        assert any(
            c["document_id"] == private_doc.id for c in body["citations"]
        ), "the private document chunk must be citable"
        assert "USER_PROVIDED" in body["provenance"]
        assert body["why_this_answer"]["sources_used"]["Private documents"] == 1

    def test_search_disabled_is_reported_as_not_performed(
        self, client, auth_headers, db_session, test_user, monkeypatch
    ):
        private_doc, private_chunk = seed_corpus(
            db_session, "Internal launch checklist.pdf",
            self.private_text,
            public=False,
            source_type="USER_UPLOAD",
            uploader_id=test_user.id,
        )
        pid, vid = make_product(client, auth_headers, markets=["India"])
        # the model tries to cite the private doc even though it was not searched
        fake = ScriptedLLM(
            launch_answer([cite(private_chunk, private_doc, source_type="USER_UPLOAD")])
        )
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        resp = chat(
            client, auth_headers, launch_payload(pid, vid, include_my_documents=False),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["private_search_requested"] is False
        assert body["private_search_performed"] is False
        assert body["private_sources_found"] == 0
        # the citation to an unretrieved private document is dropped
        assert all(c["document_id"] != private_doc.id for c in body["citations"])

    def test_failed_search_is_never_claimed_as_performed(
        self, client, auth_headers, db_session, monkeypatch
    ):
        pid, vid = make_product(client, auth_headers, markets=["India"])

        def boom(**kwargs):
            raise RuntimeError("retrieval backend unavailable")

        monkeypatch.setattr("app.routers.assistant.hybrid_retrieve", boom)
        fake = ScriptedLLM(
            decompose_json([
                ("General", "Can I launch my product to market?"),
                ("Regulatory", "What licensing is required?"),
            ]),
        )
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        resp = chat(
            client, auth_headers,
            launch_payload(pid, vid, message="Can I launch my product? What are the requirements?"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # requested, but the retrieval failed: never claim it ran
        assert body["private_search_requested"] is True
        assert body["private_search_performed"] is False
        assert body["private_sources_found"] == 0
        assert body["public_sources_found"] == 0


# -------------------------------------------------------
# TEST 7 - Claim provenance
# -------------------------------------------------------

class Test7ClaimProvenance:
    def test_claim_json_carries_provenance_and_review_requirement(
        self, client, auth_headers, db_session, monkeypatch
    ):
        india_doc, india_chunk, _, _ = seed_india_and_us(db_session)
        pid, vid = make_product(client, auth_headers, markets=["India", "Germany"],
                                claims=[CLAIM_40])
        fake = ScriptedLLM(launch_answer([cite(india_chunk, india_doc)]))
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        resp = chat(client, auth_headers, launch_payload(pid, vid))
        assert resp.status_code == 200, resp.text
        reviews = resp.json()["claim_reviews"]

        assert len(reviews) == 1
        review = reviews[0]
        # exact spec JSON shape
        assert review["claim_text"] == CLAIM_40
        assert review["provenance"] == "USER_PROVIDED"
        assert review["evidence_status"] == "USER_PROVIDED_ONLY"
        assert review["independent_verification"] == "NOT_FOUND"
        assert review["marketing_use"] == "REVIEW_REQUIRED"
        # the 40% claim is never called proven / verified / permitted
        # (scan values only: the key "provenance" legitimately contains "proven")
        values = " ".join(str(v) for v in review.values()).lower()
        for banned in ("proven", "clinically established", "legally permitted"):
            assert banned not in values
        # claim substantiation shows up as missing information
        assert "Claim substantiation" in resp.json()["why_this_answer"]["missing_information"]

    def test_claim_json_values_never_claim_proof(
        self, client, auth_headers, db_session, monkeypatch
    ):
        india_doc, india_chunk, _, _ = seed_india_and_us(db_session)
        pid, vid = make_product(client, auth_headers, markets=["India", "Germany"],
                                claims=[CLAIM_40])
        fake = ScriptedLLM(launch_answer([cite(india_chunk, india_doc)]))
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        resp = chat(client, auth_headers, launch_payload(pid, vid))
        assert resp.status_code == 200, resp.text
        review = resp.json()["claim_reviews"][0]

        # scan VALUES only (the key "provenance" legitimately contains "proven")
        values = " ".join(str(v) for v in review.values()).lower()
        for banned in ("proven", "clinically established", "legally permitted",
                       "verified claim", "approved"):
            assert banned not in values, f"claim review must not say {banned!r}"


# -------------------------------------------------------
# TEST 8 - Version context (V1 vs V2)
# -------------------------------------------------------

class Test8VersionContext:
    def test_changing_the_version_changes_the_market_context(
        self, client, auth_headers, db_session, monkeypatch
    ):
        pid, vid1 = make_product(
            client, auth_headers, markets=["India"], claims=[CLAIM_40],
        )
        # V2: same product, now also targeting Germany + one more claim
        r = client.post(f"/api/products/{pid}/versions", json={}, headers=auth_headers)
        assert r.status_code == 201, r.text
        vid2 = r.json()["data"]["id"]
        base2 = f"/api/products/{pid}/versions/{vid2}"
        cr = client.post(
            f"{base2}/claims",
            json={"claim_text": "Treats insomnia", "claim_type": "wellness"},
            headers=auth_headers,
        )
        assert cr.status_code == 201, cr.text
        mr = client.post(
            f"{base2}/target-markets", json={"country": "Germany"}, headers=auth_headers
        )
        assert mr.status_code == 201, mr.text

        monkeypatch.setattr(
            "app.routers.assistant.get_llm_provider", lambda: ScriptedLLM()
        )

        first = chat(client, auth_headers, launch_payload(pid, vid1))
        assert first.status_code == 200, first.text
        b1 = first.json()

        second = chat(
            client, auth_headers,
            launch_payload(pid, vid2, session_id=b1["session_id"]),
        )
        assert second.status_code == 200, second.text
        b2 = second.json()

        # V1 context: India only, one claim
        assert b1["market_context"] == ["India"]
        assert b1["jurisdiction_filter"] == ["India"]
        assert [c["claim_text"] for c in b1["claim_reviews"]] == [CLAIM_40]

        # V2 context on the SAME session: Germany added, claim list updated
        assert b2["market_context"] == ["India", "Germany/EU"]
        assert b2["jurisdiction_filter"] == ["India", "Germany", "European Union"]
        claim_texts = [c["claim_text"] for c in b2["claim_reviews"]]
        assert CLAIM_40 in claim_texts
        assert "Treats insomnia" in claim_texts
        # no stale context: the V1-only scope never leaks into the V2 answer
        assert b2["jurisdiction_filter"] != b1["jurisdiction_filter"]


# -------------------------------------------------------
# TEST 9 - Demo patent corpus never becomes regulatory evidence
# -------------------------------------------------------

class Test9DemoPatentCorpus:
    def test_patent_records_are_not_chat_citations(
        self, client, auth_headers, db_session, monkeypatch
    ):
        # the demo corpus is a frozen in-code list; it is not part of the
        # RAG corpus (source_documents) and therefore cannot be retrieved
        assert DEMO_RECORD_LABEL == "DEMO CORPUS — SYNTHETIC RECORDS — NOT LIVE PATENT DATA"

        india_doc, india_chunk, _, _ = seed_india_and_us(db_session)
        pid, vid = make_product(client, auth_headers, markets=["India", "Germany"])
        fake = ScriptedLLM(launch_answer([cite(india_chunk, india_doc)]))
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        resp = chat(client, auth_headers, launch_payload(pid, vid))
        assert resp.status_code == 200, resp.text
        body = resp.json()

        corpus_ids = {india_doc.id}
        for c in body["citations"]:
            assert c["document_id"] in corpus_ids, (
                "only real corpus documents may be cited"
            )
            assert c["source_type"] != "patent"
            assert "DEMO CORPUS" not in c["title"]
        # no patent-screening payload is mixed into a regulatory answer
        assert "corpus_type" not in body
        assert "retrieval_mode" not in body


# -------------------------------------------------------
# TEST 10 - Language switch preserves scope, citations, warnings
# -------------------------------------------------------

class Test10LanguageSwitch:
    def test_language_switch_keeps_citations_and_scope(
        self, client, auth_headers, db_session, monkeypatch
    ):
        india_doc, india_chunk, _, _ = seed_india_and_us(db_session)
        pid, vid = make_product(client, auth_headers, markets=["India", "Germany"])
        fake = ScriptedLLM(launch_answer([cite(india_chunk, india_doc)]))
        monkeypatch.setattr("app.routers.assistant.get_llm_provider", lambda: fake)

        en = chat(client, auth_headers, launch_payload(pid, vid, output_language="en"))
        assert en.status_code == 200, en.text
        hi = chat(client, auth_headers, launch_payload(pid, vid, output_language="hi"))
        assert hi.status_code == 200, hi.text

        ben, bhi = en.json(), hi.json()

        # citations identical (chunk ids, jurisdictions, titles)
        assert [c["chunk_id"] for c in ben["citations"]] == [
            c["chunk_id"] for c in bhi["citations"]
        ]
        assert [c["jurisdiction"] for c in ben["citations"]] == [
            c["jurisdiction"] for c in bhi["citations"]
        ]
        # scope, evidence status and warnings survive the switch
        assert ben["jurisdiction_filter"] == bhi["jurisdiction_filter"]
        assert ben["market_context"] == bhi["market_context"]
        assert ben["jurisdiction_warning"] == bhi["jurisdiction_warning"] == JURISDICTION_WARNING
        assert ben["evidence_status"] == bhi["evidence_status"]
        assert ben["evidence_gap_warnings"] == bhi["evidence_gap_warnings"]
        assert ben["why_this_answer"] == bhi["why_this_answer"]
        assert ben["claim_reviews"] == bhi["claim_reviews"]
        # honest translation fallback: the answer stays English and says so
        assert any(SERVICE_UNAVAILABLE_WARNING in w for w in bhi["warnings"])
        assert "21 CFR" not in bhi["answer"]


# -------------------------------------------------------
# Provider parity - GROQ and SARVAM obey identical scope rules
# -------------------------------------------------------

class TestProviderParity:
    def test_sarvam_obeys_the_same_jurisdiction_rules(
        self, client, auth_headers, db_session, monkeypatch
    ):
        india_doc, india_chunk, _, _ = seed_india_and_us(db_session)
        pid, vid = make_product(client, auth_headers, markets=["India", "Germany"])
        fake = ScriptedLLM(launch_answer([cite(india_chunk, india_doc)]))
        monkeypatch.setattr(
            "app.routers.assistant.get_llm_provider_for", lambda name: fake
        )

        resp = chat(
            client, auth_headers,
            launch_payload(pid, vid, provider="sarvam"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["provider"] == "sarvam"
        assert body["jurisdiction_filter"] == ["India", "Germany", "European Union"]
        assert body["unselected_jurisdiction_sources_excluded"] == ["United States"]
        assert body["evidence_status"]["overall_status"] == "INSUFFICIENT"
        for c in body["citations"]:
            assert c["jurisdiction"] != "United States"
        prompt = fake.user_prompts[0]
        assert "=== MARKET CONTEXT" in prompt
        assert "21 CFR" not in prompt
