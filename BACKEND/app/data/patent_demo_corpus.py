"""
Frozen demonstration patent corpus (Phase 6, demo mode).

**What this is.** The platform has no live patent database and the master prompt
explicitly forbids pretending a fake patent record is real or claiming a live
government search. So patent screening runs against this small, frozen corpus of
*illustrative* records.

**What this is not.** These are not real patents. Every record is marked
``is_demo=True``, uses a ``DEMO-...`` identifier instead of a real patent number,
names an illustrative assignee, and is surfaced in the API as
``record_source = "DEMO_CORPUS"`` with a prominent note. The corpus version is
exposed so a result can be tied to the exact data it came from.

The corpus exists to exercise the *workflow* - feature extraction, feature
comparison and careful labelling - not to make any claim about the real patent
landscape. When a real public source is configured (``DEMO_MODE=false`` with a
data source), results are labelled ``LIVE_SOURCE`` instead; that path is not part
of this phase.
"""

from __future__ import annotations

from typing import Any, Dict, List

#: Version of the frozen corpus. Bump when the records below change.
CORPUS_VERSION = "demo-patents-2026.09"

#: The provenance label attached to records drawn from this corpus.
DEMO_SOURCE = "DEMO_CORPUS"

#: Human-readable note attached to every demo screening response.
DEMO_CORPUS_NOTE = (
    "Patent screening ran against a frozen demonstration corpus of illustrative "
    "records. This is NOT a live patent search and these are NOT real patent "
    "records; they exist to demonstrate the comparison workflow. Always verify "
    "against an official patent database (e.g. IP India, WIPO PATENTSCOPE, "
    "Espacenet) and a registered patent agent."
)

#: Canonical technical-feature vocabulary (master prompt section 18).
FEATURE_TYPES = (
    "botanical_species",
    "plant_part",
    "extraction_method",
    "solvent",
    "temperature",
    "pressure",
    "duration",
    "active_compounds",
    "standardization",
    "delivery_form",
    "technical_effect",
    "intended_use",
)


def _features(**kwargs: str) -> List[Dict[str, str]]:
    """Build a feature list from keyword arguments, skipping empty values."""
    return [
        {"feature_type": key, "feature_value": value}
        for key, value in kwargs.items()
        if value
    ]


#: The frozen corpus. Deliberately small and transparent: every feature is
#: explicit so a reviewer can see exactly what was compared.
DEMO_PATENT_RECORDS: List[Dict[str, Any]] = [
    {
        "record_id": "DEMO-PAT-0001",
        "patent_number": None,
        "title": "Cold-press extraction process for Withania somnifera root (illustrative record)",
        "assignee": "Illustrative demo record - not a real patent",
        "jurisdiction": "IN",
        "publication_date": "2019-04-11",
        "abstract": (
            "An illustrative process for cold-pressing Withania somnifera root at "
            "low temperature to obtain an extract enriched in withanolides."
        ),
        "source_passage": (
            "The process comprises comminuting Withania somnifera root and pressing "
            "it at approximately 4 degrees Celsius without added solvent, yielding an "
            "extract reported to show improved bioavailability of withanolides."
        ),
        "features": _features(
            botanical_species="Withania somnifera",
            plant_part="root",
            extraction_method="cold-press",
            solvent="none",
            temperature="4 C",
            active_compounds="withanolides",
            technical_effect="improved bioavailability",
            delivery_form="extract",
        ),
    },
    {
        "record_id": "DEMO-PAT-0002",
        "patent_number": None,
        "title": "Solvent extraction of Withania somnifera root withanolides (illustrative record)",
        "assignee": "Illustrative demo record - not a real patent",
        "jurisdiction": "IN",
        "publication_date": "2016-09-02",
        "abstract": (
            "An illustrative solvent-extraction process for recovering withanolides "
            "from Withania somnifera root with a standardised content."
        ),
        "source_passage": (
            "Withania somnifera root is extracted with ethanol at elevated temperature "
            "and the extract is standardised to a defined withanolide content."
        ),
        "features": _features(
            botanical_species="Withania somnifera",
            plant_part="root",
            extraction_method="solvent extraction",
            solvent="ethanol",
            temperature="60 C",
            active_compounds="withanolides",
            standardization="withanolide-standardised",
            delivery_form="extract",
        ),
    },
    {
        "record_id": "DEMO-PAT-0003",
        "patent_number": None,
        "title": "Curcuma longa rhizome extract and anti-inflammatory use (illustrative record)",
        "assignee": "Illustrative demo record - not a real patent",
        "jurisdiction": "IN",
        "publication_date": "2015-02-19",
        "abstract": (
            "An illustrative Curcuma longa rhizome extract characterised by curcumin "
            "content, for use in inflammatory conditions."
        ),
        "source_passage": (
            "Curcuma longa rhizome is extracted with ethanol and the resulting extract, "
            "containing curcumin, is described for anti-inflammatory use."
        ),
        "features": _features(
            botanical_species="Curcuma longa",
            plant_part="rhizome",
            extraction_method="solvent extraction",
            solvent="ethanol",
            active_compounds="curcumin",
            intended_use="anti-inflammatory",
        ),
    },
    {
        "record_id": "DEMO-PAT-0004",
        "patent_number": None,
        "title": "Ocimum sanctum leaf aqueous extract for stress support (illustrative record)",
        "assignee": "Illustrative demo record - not a real patent",
        "jurisdiction": "IN",
        "publication_date": "2017-07-06",
        "abstract": (
            "An illustrative aqueous extraction of Ocimum sanctum leaf and its use as "
            "an adaptogenic composition."
        ),
        "source_passage": (
            "Ocimum sanctum leaf is extracted with water and the aqueous extract is "
            "used as an adaptogenic composition for stress support."
        ),
        "features": _features(
            botanical_species="Ocimum sanctum",
            plant_part="leaf",
            extraction_method="aqueous decoction",
            solvent="water",
            technical_effect="adaptogenic activity",
            intended_use="stress support",
        ),
    },
    {
        "record_id": "DEMO-PAT-0005",
        "patent_number": None,
        "title": "Spray-dried Withania somnifera root powder formulation (illustrative record)",
        "assignee": "Illustrative demo record - not a real patent",
        "jurisdiction": "IN",
        "publication_date": "2020-11-12",
        "abstract": (
            "An illustrative spray-dried powder formulation prepared from Withania "
            "somnifera root for nutraceutical delivery."
        ),
        "source_passage": (
            "An aqueous extract of Withania somnifera root is spray-dried to obtain a "
            "free-flowing powder for nutraceutical delivery."
        ),
        "features": _features(
            botanical_species="Withania somnifera",
            plant_part="root",
            extraction_method="aqueous extraction",
            delivery_form="powder",
            intended_use="nutraceutical",
        ),
    },
    {
        "record_id": "DEMO-PAT-0006",
        "patent_number": None,
        "title": "Cold-press extraction of Curcuma longa rhizome (illustrative record)",
        "assignee": "Illustrative demo record - not a real patent",
        "jurisdiction": "IN",
        "publication_date": "2021-03-25",
        "abstract": (
            "An illustrative cold-press process for Curcuma longa rhizome producing a "
            "curcumin-containing paste."
        ),
        "source_passage": (
            "Curcuma longa rhizome is cold-pressed at approximately 4 degrees Celsius to "
            "yield a curcumin-containing paste."
        ),
        "features": _features(
            botanical_species="Curcuma longa",
            plant_part="rhizome",
            extraction_method="cold-press",
            solvent="none",
            temperature="4 C",
            active_compounds="curcumin",
        ),
    },
]


def get_demo_records() -> List[Dict[str, Any]]:
    """Return a defensive copy of the frozen corpus (callers must not mutate it)."""
    return [
        {
            **record,
            "features": [dict(feature) for feature in record.get("features", [])],
        }
        for record in DEMO_PATENT_RECORDS
    ]
