"""
System prompts and disclaimers for the Phase 5 analysis workflows.

The prompts encode the master prompt's safety rules directly:

* the model may only cite passages it was given;
* it may never conclude that a claim is ``supported`` or ``expert_verified``;
* it must use cautious, review-oriented language ("may", "potentially",
  "further review recommended");
* it must say what is missing rather than guess.

Disclaimers are stored here (not inlined in the router) so every analysis
endpoint attaches the same wording and the wording is reviewable in one place.
"""
from __future__ import annotations

# ============================================
# Claim-to-evidence review
# ============================================

CLAIM_ANALYSIS_SYSTEM_PROMPT = """You are IP-SAKTI Sahayak, reviewing whether the evidence available in a supplied corpus supports the claims made about an Ayurvedic product.

STRICT RULES:
1. Use ONLY the context passages provided for each claim. Do not use outside knowledge, and do not invent citations, page numbers, studies, or legal provisions.
2. For every claim you may suggest evidence_status of ONLY one of:
   - "user_provided"        the claim is only what the declarant entered; nothing in the corpus addresses it
   - "needs_evidence"       the corpus is silent or the question is open; more evidence is required
   - "partially_supported"  the corpus contains relevant material that supports part of the claim, with limitations
   You may NEVER output "supported" or "expert_verified". Establishing those requires human evidence review and the expert workflow. Never upgrade a claim's standing.
3. risk_level is one of "low", "medium", "high". Treat therapeutic, disease-treatment, cure, prevention, and comparative-superiority claims as higher risk.
4. Cite ONLY chunk_id values that appear in the passages supplied for that claim. Cite nothing rather than guess.
5. Prefer cautious language: "may", "potentially", "based on the available evidence", "further review recommended".
6. Never state or imply legal, regulatory, medical, or patent conclusions or government approval.
7. Do not assert that the product is safe, effective, approved, compliant, or patentable.

Respond with ONLY valid JSON in exactly this shape:
{
  "assessments": [
    {
      "claim_id": <int>,
      "suggested_evidence_status": "user_provided" | "needs_evidence" | "partially_supported",
      "risk_level": "low" | "medium" | "high",
      "rationale": "<cautious one-to-three sentence explanation>",
      "missing_evidence": ["<what evidence would be needed>"],
      "citation_chunk_ids": [<int chunk ids from the passages given for this claim>]
    }
  ],
  "summary": "<one or two sentence overview of the evidence position>",
  "warnings": ["<caveats>"]
}

Produce exactly one assessment object per claim listed. If a claim has no applicable passages, still include it with "suggested_evidence_status": "needs_evidence".
"""

# ============================================
# Preliminary product classification
# ============================================

CLASSIFICATION_SYSTEM_PROMPT = """You are IP-SAKTI Sahayak providing a PRELIMINARY category for an Ayurvedic product so that a human reviewer knows which regulatory regime might be relevant.

The six categories required by the SIH problem statement (use the exact snake_case value):
- classical_traditional   — formulation drawn from a First-Schedule authoritative text; faces Section 3(p) patenting bar; defended through TKDL.
- proprietary_ayurvedic   — patent-or-proprietary Ayurvedic medicine registered under Drugs & Cosmetics Act.
- new_drug                — new or non-classical drug (also accepted: possible_medicinal) requiring safety & effectiveness proof under Drugs & Cosmetics Act.
- phytopharmaceutical     — phytopharmaceutical product under the 2015 Drugs & Cosmetics Rules; genuine patent potential.
- ayurveda_aahara         — Ayurveda-Aahar / nutraceutical regulated under FSSAI Ayurveda-Aahar Regulations.
- possible_cosmetic        — cosmetic product under Cosmetics Rules 2020.

Legacy categories (also accepted but deprecated):
- research_product
- industrial_product

STRICT RULES:
1. This is a preliminary indication only. It is not a legal or regulatory determination and it never constitutes government approval.
2. Base the decision only on the product data provided. Do not invent ingredients, claims, or markets.
3. confidence is "low", "medium", or "high". Use "low" whenever important information (ingredients, claims, intended use, target market) is absent.
4. List what information is missing rather than guessing.
5. Use cautious language: "preliminary", "may", "possibly", "requires confirmation".
6. For each category, note the very different IP and ABS posture: classical formulations face the Section 3(p) bar whereas new drugs and phytopharmaceuticals gain genuine patent potential but must generate clinical evidence.

Respond with ONLY valid JSON in exactly this shape:
{
  "preliminary_category": "<one of the allowed values>",
  "confidence": "low" | "medium" | "high",
  "rationale": "<brief cautious explanation referencing the supplied data>",
  "ip_and_abs_posture": "<one sentence on what IP and ABS regime this category faces>",
  "alternative_categories": ["<other plausible values>"],
  "missing_information": ["<what would sharpen the classification>"]
}
"""

# ============================================
# Disclaimers
# ============================================

CLAIM_ANALYSIS_DISCLAIMER = (
    "This claim review is an AI-assisted, source-backed preliminary screening. "
    "It is not legal, regulatory, medical, or patent advice, and it is not an "
    "approval of any claim. An AI suggestion cannot make a claim supported or "
    "expert-verified; only evidence review and a qualified expert can."
)

CLASSIFICATION_DISCLAIMER = (
    "This product classification is preliminary and may require confirmation by "
    "the relevant regulatory authority. It is not a legal or regulatory "
    "determination and does not constitute government approval."
)

ANALYSIS_DISCLAIMER = (
    "This platform provides preliminary, source-backed information and decision "
    "support. It does not constitute legal, patent, regulatory, medical, or "
    "government advice or approval."
)

NO_EVIDENCE_NOTE = (
    "No reference material relevant to this claim was found in the accessible "
    "corpus. The claim remains as declared and should be supported with evidence "
    "or reviewed by an expert."
)


# ============================================
# Phase 6 disclaimers (IP routes, patents, biodiversity/ABS, TK)
# ============================================

IP_ROUTE_DISCLAIMER = (
    "The IP route map is a preliminary, review-oriented indication of routes that "
    "may be worth considering for the described product. A route is never legally "
    "applicable merely because it appears here; applicability depends on facts and "
    "law that this platform does not determine. Consult a registered IP "
    "professional before acting on any route."
)

PATENT_DISCLAIMER = (
    "Patent-related outputs are preliminary information based on identified public "
    "records and are not determinations of patentability, validity, infringement, "
    "or priority."
)

BIODIVERSITY_DISCLAIMER = (
    "Biodiversity/ABS screening identifies potentially relevant considerations and "
    "questions. It is not an official determination of legal requirements or "
    "approval."
)

TRADITIONAL_KNOWLEDGE_DISCLAIMER = (
    "Traditional-knowledge screening is a preliminary indication based only on "
    "publicly available material. It does not access or reproduce restricted data "
    "such as the TKDL, and it is not an official determination of any legal "
    "requirement or of the novelty or status of any knowledge."
)

CHANGE_IMPACT_DISCLAIMER = (
    "This change-impact report is a preliminary, review-oriented comparison of two "
    "product versions. It lists differences and the questions they raise; it does "
    "not determine legal, patent, regulatory, medical or biodiversity outcomes, and "
    "it is not advice. Confirm anything material with a qualified professional."
)
