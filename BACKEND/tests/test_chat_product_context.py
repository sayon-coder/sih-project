"""The selected Product Passport must be usable knowledge for the chatbot.

Regression for the reported question "can you access my product that i have
created" (Context Options: AshwaBio-X / Version 1): the chatbot answered
"I do not have the ability to access external product files or databases..."
even though the passport JSON was inside its own prompt. Two causes:

1. The single-answer system prompt said "Answer ONLY using the provided
   context passages" while the passport arrived under a bare
   "=== PRODUCT CONTEXT ===" header with no instruction to use it.
2. generate_rag_answer() early-exited before calling the LLM whenever the
   corpus returned no chunks - even when a passport was selected - so a
   passport-only question could never be answered at all.
"""
from __future__ import annotations

import json

from app.rag.generation import (
    SYSTEM_PROMPT,
    build_context_prompt,
    generate_rag_answer,
)
from app.rag.partial_answer import (
    PARTIAL_SYSTEM_PROMPT,
    SectionContext,
    SubQuestion,
    build_partial_prompt,
)
from tests.test_chat_jurisdiction import ScriptedLLM, chat, make_product

PASSPORT = {
    "product_name": "AshwaBio-X",
    "product_description": "Ashwagandha root extract",
    "version_number": 1,
    "snapshot": {"target_markets": ["India", "Germany"]},
}


def _passport_answer():
    return json.dumps(
        {
            "answer": (
                "Yes - your selected Product Passport AshwaBio-X, Version 1 is "
                "available to me: Ashwagandha root, 100 g, Uttarakhand, "
                "cold-press at 4 C. The 40% bioavailability claim is "
                "user-provided and not independently verified."
            ),
            "insufficient_evidence": False,
            "citations": [],
            "warnings": [],
        }
    )


# -------------------------------------------------------
# System prompts grant access to the passport + knowledge base
# -------------------------------------------------------

class TestSystemPromptsGrantPassportAccess:
    def test_single_path_no_longer_denies_access(self):
        # The old rule 1 is what produced the denial answer.
        assert "Answer ONLY using the provided context passages" not in SYSTEM_PROMPT
        lowered = SYSTEM_PROMPT.lower()
        assert "product context" in lowered
        assert "never say you cannot access the product" in lowered
        assert "knowledge base" in lowered

    def test_single_path_explains_what_is_available(self):
        for token in (
            "RETRIEVED CONTEXT PASSAGES",
            "PRODUCT CONTEXT",
            "USER-ATTACHED DOCUMENT",
        ):
            assert token in SYSTEM_PROMPT, f"missing inventory block: {token}"

    def test_partial_path_never_denies_access(self):
        assert "never say you cannot access the product" in (
            PARTIAL_SYSTEM_PROMPT.lower()
        )


# -------------------------------------------------------
# Prompt builders label the passport as available knowledge
# -------------------------------------------------------

class TestPromptBlocks:
    def test_product_context_block_instructs_the_model(self):
        prompt = build_context_prompt(
            "can you access my product that i have created",
            [],
            product_context=PASSPORT,
        )
        assert "=== PRODUCT CONTEXT ===" in prompt
        assert "It IS available to you" in prompt
        assert "never say you cannot access the product" in prompt
        # The passport data itself travels with the instruction.
        assert "AshwaBio-X" in prompt
        # The knowledge base passages are declared available too.
        assert "knowledge base" in prompt

    def test_no_passport_means_no_passport_instruction(self):
        prompt = build_context_prompt("What is biodiversity origin?", [])
        assert "PRODUCT CONTEXT" not in prompt

    def test_partial_prompt_carries_the_passport_instruction(self):
        ctx = SectionContext(
            subquestion=SubQuestion(
                topic="Evidence and provenance",
                question="What is in my product?",
            ),
            chunks=[],
        )
        prompt = build_partial_prompt(
            "What is in my product?", [ctx], product_context=PASSPORT
        )
        assert "=== PRODUCT CONTEXT (system data) ===" in prompt
        assert "It IS available to you" in prompt
        assert "AshwaBio-X" in prompt


# -------------------------------------------------------
# Generation layer answers from the passport alone
# -------------------------------------------------------

class TestPassportOnlyGeneration:
    def test_passport_alone_reaches_the_llm_and_can_answer(self):
        fake = ScriptedLLM(_passport_answer())
        resp = generate_rag_answer(
            query="can you access my product that i have created",
            chunks=[],
            llm=fake,
            product_context=PASSPORT,
        )
        assert fake.calls == 1
        user_prompt = fake.user_prompts[0]
        assert "AshwaBio-X" in user_prompt
        assert "It IS available to you" in user_prompt
        assert resp.insufficient_evidence is False
        assert resp.citations == []

    def test_model_flagged_insufficient_stays_insufficient(self):
        """Honest abstention is preserved even when a passport is selected."""
        fake = ScriptedLLM(
            json.dumps(
                {
                    "answer": "Not enough information was retrieved.",
                    "insufficient_evidence": True,
                    "citations": [],
                    "warnings": [],
                }
            )
        )
        resp = generate_rag_answer(
            query="q", chunks=[], llm=fake, product_context=PASSPORT
        )
        assert fake.calls == 1
        assert resp.insufficient_evidence is True

    def test_no_passport_no_document_no_chunks_never_calls_the_llm(self):
        class Boom:
            def generate(self, system_prompt, user_prompt):
                raise AssertionError("must not call the LLM")

        resp = generate_rag_answer(query="q", chunks=[], llm=Boom())
        assert resp.insufficient_evidence is True

    def test_launch_question_with_passport_still_skips_the_model(self):
        """Launch readiness is never answered from a passport alone.

        With no retrieved source the deterministic evidence-gap answer is
        returned and the model is not consulted (spec TEST 4/5 guarantee).
        """

        class Boom:
            def generate(self, system_prompt, user_prompt):
                raise AssertionError("must not call the LLM")

        resp = generate_rag_answer(
            query="Can I launch my product in India and Germany?",
            chunks=[],
            llm=Boom(),
            product_context=PASSPORT,
            launch_question=True,
        )
        assert resp.insufficient_evidence is True
        assert resp.citations == []


# -------------------------------------------------------
# Endpoint: the reported question with AshwaBio-X V1 selected
# -------------------------------------------------------

class TestEndpointPassportContext:
    def test_selected_passport_reaches_the_prompt(
        self, client, auth_headers, db_session, monkeypatch
    ):
        pid, vid = make_product(
            client, auth_headers, markets=("India", "Germany")
        )
        fake = ScriptedLLM(_passport_answer())
        monkeypatch.setattr(
            "app.routers.assistant.get_llm_provider", lambda: fake
        )

        r = chat(
            client,
            auth_headers,
            {
                "message": "can you access my product that i have created",
                "product_id": pid,
                "product_version_id": vid,
                "include_my_documents": True,
            },
        )
        assert r.status_code == 200, r.text
        # Corpus is empty here: without the early-exit fix the LLM was
        # never called and the generic insufficient message was returned.
        assert fake.calls == 1
        user_prompt = fake.user_prompts[0]
        assert "PRODUCT CONTEXT" in user_prompt
        assert "It IS available to you" in user_prompt
        assert "AshwaBio-" in user_prompt  # the created product name

        body = r.json()
        assert body["market_context"], "market panel metadata missing"
        assert body["insufficient_evidence"] is False

    def test_passport_context_flows_to_the_selective_path(
        self, client, auth_headers, db_session, monkeypatch
    ):
        pid, vid = make_product(
            client, auth_headers, markets=("India", "Germany")
        )
        section_row = {
            "topic": "Product",
            "status": "USER_PROVIDED_ONLY",
            "answer": (
                "Your Product Passport AshwaBio-X, Version 1 is available: "
                "Ashwagandha root 100 g, cold-press at 4 C."
            ),
            "provenance": ["USER_PROVIDED"],
            "citations": [],
            "claims": [],
            "next_action": "Review the passport data with a qualified expert.",
        }
        # Two question marks -> should_decompose() routes to the
        # selective path: decompose_query first, then the section answer.
        fake = ScriptedLLM(
            json.dumps(
                {
                    "subquestions": [
                        {"topic": "Product", "question": "What is in my product?"}
                    ]
                }
            ),
            json.dumps(
                {
                    "user_provided_facts": ["Ashwagandha root 100 g"],
                    "verified_external_facts": [],
                    "system_inferences": [],
                    "sections": [section_row],
                    "warnings": [],
                }
            ),
        )
        monkeypatch.setattr(
            "app.routers.assistant.get_llm_provider", lambda: fake
        )

        r = chat(
            client,
            auth_headers,
            {
                "message": (
                    "What is in my product? Is my 40% claim substantiated?"
                ),
                "product_id": pid,
                "product_version_id": vid,
                "include_my_documents": True,
            },
        )
        assert r.status_code == 200, r.text
        assert fake.calls >= 2
        # The generation prompt (not the decompose prompt) must carry the
        # passport instruction.
        generation_prompts = fake.user_prompts[1:]
        assert generation_prompts
        assert "PRODUCT CONTEXT" in generation_prompts[0]
        assert "It IS available to you" in generation_prompts[0]
        body = r.json()
        assert "AshwaBio-X" in body["answer"]
