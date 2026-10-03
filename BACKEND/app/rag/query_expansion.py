"""
Query term expansion for retrieval recall.

A user writes "ashwagandha"; the corpus may say "Withania somnifera". A user
writes "4°C"; the corpus may say "temperature". Expansion appends the missing
variants to the retrieval query string:

  * the keyword arm ORs every term, so added terms only widen recall;
  * the vector arm embeds the expanded string, so semantic neighbours travel
    together;
  * ranking (ts_rank_cd / cosine / reranker) keeps precision.

Expansion never removes the user's own words, and every added term is logged
by the caller so retrieval stays explainable.
"""
from __future__ import annotations

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Each group lists equivalent ways of expressing the same concept. If the
# query mentions any term of a group, the remaining terms are added.
SYNONYM_GROUPS: List[List[str]] = [
    ["ashwagandha", "withania somnifera", "winter cherry"],
    ["cold press", "cold-press", "cold pressing"],
    ["extraction", "extract", "extracting"],
    ["4°c", "4 degrees", "temperature"],
    ["bioavailability", "bioavailable"],
    ["40%", "40 percent"],
    ["cultivated", "cultivation", "cultivated farms"],
    ["wild", "wild-harvested", "wild harvested"],
    ["conference", "presentation"],
    ["disclosure", "public disclosure", "disclosed"],
    ["patent", "patent application", "prior art"],
    ["biodiversity", "bioresource"],
    ["abs", "access and benefit sharing"],
    ["nutraceutical", "dietary supplement", "supplement"],
    ["medicine", "medicinal", "pharmaceutical", "drug"],
    ["cosmetic", "cosmetics", "topical"],
    ["claim", "claims"],
    ["evidence", "study", "study data"],
    ["india", "indian"],
    ["germany", "german"],
    ["root", "roots"],
]

# Short terms are matched on word boundaries so that "abs" does not fire on
# "absorption" while "germany" still matches inside "German-based".
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’%°\-]*")


def expand_query_terms(query: str) -> Tuple[str, List[str]]:
    """Return ``(expanded_query, added_terms)`` for a raw query.

    Terms already present in the query are never duplicated; groups are
    only applied when the query actually mentions one of their members.
    """
    if not query or not query.strip():
        return query, []

    lowered = query.lower()
    present = {m.group(0) for m in _WORD_RE.finditer(lowered)}

    def mentioned(term: str) -> bool:
        if " " in term or "-" in term or "%" in term or "°" in term:
            return term in lowered
        return term in present

    added: List[str] = []
    for group in SYNONYM_GROUPS:
        if not any(mentioned(t) for t in group):
            continue
        for term in group:
            if mentioned(term) or term in added:
                continue
            # Do not duplicate a word that is merely part of a longer word
            # already in the query (e.g. query has "extracting").
            if any(term in p or p in term for p in present):
                continue
            added.append(term)

    if not added:
        return query, []

    expanded = query.rstrip() + " " + " ".join(added)
    logger.debug("Query expansion added %d term(s): %s", len(added), added)
    return expanded, added
