"""
Static regulatory spine for the knowledge graph.

This module is *reference data*, hard-coded on purpose: it is the part of the
graph that is not extracted from database rows because no table in the system
stores it. Everything here is a well-known instrument, registry, regulator,
IP route or formulation category - no facts are invented at runtime.

Structure
---------
``SEED_NODES``     list of dicts (``node_type``, ``canonical_name``,
                   ``jurisdiction``, ``aliases``, ``attributes``).
``SEED_EDGES``     list of dicts referencing seed nodes by canonical name
                   (``from``/``to``), plus a relation and evidence.
``CATEGORY_BY_KEY`` mapping from a recorded ``ProductCategory`` value (or an
                   analysis ``product_classification.category``) onto the
                   canonical formulation-category node name.
``IP_ROUTE_KEYS``  the nine IP routes of ``app.analysis.ip_routes`` expressed
                   as node names, so route-map output can be joined to the
                   graph.

Aliases are only used for one thing: confidently matching corpus documents
(``SourceDocument.title`` / ``source_url``) to instruments in
``app.graph.builder``. Matching is word-boundary based and never guesses.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.graph.schema import NodeType, Relation


def _node(
    node_type: NodeType,
    canonical_name: str,
    *,
    jurisdiction: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    attributes: Optional[Dict] = None,
) -> Dict:
    return {
        "node_type": node_type,
        "canonical_name": canonical_name,
        "jurisdiction": jurisdiction,
        "aliases": list(aliases or []),
        "attributes": dict(attributes or {}),
    }


# ============================================================
# Formulation categories (the six canonical categories, including the
# phytopharmaceutical category the problem statement calls out)
# ============================================================

FORMULATION_CATEGORIES: Dict[str, str] = {
    # recorded ProductCategory / analysis value -> canonical node name
    "classical_traditional": "Classical/Traditional Formulation",
    "proprietary_ayurvedic": "Proprietary Ayurvedic Formulation",
    "phytopharmaceutical": "Phytopharmaceutical Formulation",
    "ayurveda_aahara": "Ayurveda Aahara Formulation",
    "possible_medicinal": "Possible Medicinal Formulation",
    "possible_cosmetic": "Possible Cosmetic Formulation",
    # Recorded platform categories outside the six canonical formulation
    # categories still resolve - the builder creates their node on demand
    # rather than dropping the recorded classification.
    "research_product": "Research Product",
    "industrial_product": "Industrial Product",
}

#: The six canonical formulation categories (documented in GRAPH_AGENT.md).
CANONICAL_FORMULATION_CATEGORIES = [
    FORMULATION_CATEGORIES["classical_traditional"],
    FORMULATION_CATEGORIES["proprietary_ayurvedic"],
    FORMULATION_CATEGORIES["phytopharmaceutical"],
    FORMULATION_CATEGORIES["ayurveda_aahara"],
    FORMULATION_CATEGORIES["possible_medicinal"],
    FORMULATION_CATEGORIES["possible_cosmetic"],
]


# ============================================================
# IP routes (the nine routes of app.analysis.ip_routes)
# ============================================================

IP_ROUTE_KEYS: Dict[str, str] = {
    "patent": "Patent",
    "trademark": "Trademark",
    "copyright": "Copyright",
    "design": "Design",
    "gi": "Geographical Indication (GI)",
    "trade_secret": "Trade Secret",
    "plant_variety": "Plant Variety",
    "traditional_knowledge": "Traditional Knowledge",
    "biodiversity_abs": "Biodiversity / ABS",
}


# ============================================================
# Seed nodes
# ============================================================

SEED_NODES: List[Dict] = [
    # --------------------------------------------------------
    # Jurisdictions
    # --------------------------------------------------------
    _node(NodeType.JURISDICTION, "India", jurisdiction="India",
          aliases=["india", "in"],
          attributes={"kind": "country"}),
    _node(NodeType.JURISDICTION, "International", jurisdiction="International",
          aliases=["international", "global"],
          attributes={"kind": "multi-jurisdiction"}),

    # --------------------------------------------------------
    # Statutes and rules - India
    # --------------------------------------------------------
    _node(NodeType.STATUTE, "Patents Act 1970", jurisdiction="India",
          aliases=["patents act 1970", "patent act 1970", "1970 patents act"],
          attributes={"instrument_type": "Act", "year": 1970,
                      "in_force_in": "India",
                      "note": "Governs patents in India; section 3 bars (incl. 3(p)) apply to known substances/new forms."}),
    _node(NodeType.RULE, "Patents Rules 2024", jurisdiction="India",
          aliases=["patents rules 2024", "patent rules 2024"],
          attributes={"instrument_type": "Rules", "year": 2024}),
    _node(NodeType.STATUTE, "Trade Marks Act 1999", jurisdiction="India",
          aliases=["trade marks act 1999", "trademarks act 1999", "trade mark act 1999"],
          attributes={"instrument_type": "Act", "year": 1999}),
    _node(NodeType.RULE, "Trade Marks Rules 2017", jurisdiction="India",
          aliases=["trade marks rules 2017", "trademarks rules 2017"],
          attributes={"instrument_type": "Rules", "year": 2017}),
    _node(NodeType.STATUTE,
          "Geographical Indications of Goods (Registration and Protection) Act 1999",
          jurisdiction="India",
          aliases=["geographical indications act 1999", "gi act 1999",
                   "geographical indications of goods act 1999"],
          attributes={"instrument_type": "Act", "year": 1999}),
    _node(NodeType.STATUTE, "Designs Act 2000", jurisdiction="India",
          aliases=["designs act 2000", "design act 2000"],
          attributes={"instrument_type": "Act", "year": 2000}),
    _node(NodeType.STATUTE, "Copyright Act 1957", jurisdiction="India",
          aliases=["copyright act 1957"],
          attributes={"instrument_type": "Act", "year": 1957}),
    _node(NodeType.STATUTE,
          "Protection of Plant Varieties and Farmers' Rights Act 2001",
          jurisdiction="India",
          aliases=["protection of plant varieties and farmers rights act 2001",
                   "plant varieties and farmers rights act 2001",
                   "ppv fr act 2001", "ppv&fr act 2001"],
          attributes={"instrument_type": "Act", "year": 2001,
                      "acronym": "PPV&FR Act 2001"}),
    _node(NodeType.STATUTE, "Biological Diversity Act 2002", jurisdiction="India",
          aliases=["biological diversity act 2002", "bd act 2002"],
          attributes={"instrument_type": "Act", "year": 2002,
                      "amended": 2023,
                      "note": "Amended in 2023; governs access to biological resources and benefit sharing in India."}),
    _node(NodeType.STATUTE, "Biological Diversity (Amendment) Act 2023", jurisdiction="India",
          aliases=["biological diversity amendment act 2023",
                   "bd amendment act 2023"],
          attributes={"instrument_type": "Act", "year": 2023,
                      "amends": "Biological Diversity Act 2002"}),
    _node(NodeType.RULE, "Biological Diversity Rules 2004", jurisdiction="India",
          aliases=["biological diversity rules 2004", "bd rules 2004"],
          attributes={"instrument_type": "Rules", "year": 2004}),
    _node(NodeType.RULE, "Biological Diversity Rules 2024", jurisdiction="India",
          aliases=["biological diversity rules 2024", "bd rules 2024"],
          attributes={"instrument_type": "Rules", "year": 2024,
                      "supersedes": "Biological Diversity Rules 2004"}),
    _node(NodeType.STATUTE, "Drugs and Cosmetics Act 1940", jurisdiction="India",
          aliases=["drugs and cosmetics act 1940", "drugs and cosmetics act"],
          attributes={"instrument_type": "Act", "year": 1940}),
    _node(NodeType.RULE, "Drugs and Cosmetics Rules 1945", jurisdiction="India",
          aliases=["drugs and cosmetics rules 1945", "drugs and cosmetics rules"],
          attributes={"instrument_type": "Rules", "year": 1945}),
    _node(NodeType.STATUTE,
          "Drugs and Magic Remedies (Objectionable Advertisements) Act 1954",
          jurisdiction="India",
          aliases=["drugs and magic remedies act 1954",
                   "objectionable advertisements act 1954",
                   "magic remedies act 1954"],
          attributes={"instrument_type": "Act", "year": 1954}),
    _node(NodeType.RULE,
          "Food Safety and Standard (Ayurveda Aahar) Regulations 2022",
          jurisdiction="India",
          aliases=["ayurveda aahar regulations 2022",
                   "fss ayurveda aahar regulations 2022",
                   "ayurveda aahar regs 2022",
                   "food safety and standard ayurveda aahar regulations 2022"],
          attributes={"instrument_type": "Regulations", "year": 2022,
                      "acronym": "FSS Ayurveda Aahar Regulations 2022"}),

    # --------------------------------------------------------
    # Treaties
    # --------------------------------------------------------
    _node(NodeType.TREATY, "TRIPS Agreement 1994", jurisdiction="International",
          aliases=["trips agreement", "trips"],
          attributes={"instrument_type": "Treaty", "year": 1994,
                      "administered_by": "WTO",
                      "note": "Minimum standards of intellectual-property protection for WTO members."}),
    _node(NodeType.TREATY, "Convention on Biological Diversity 1992",
          jurisdiction="International",
          aliases=["convention on biological diversity", "cbd convention"],
          attributes={"instrument_type": "Treaty", "year": 1992,
                      "acronym": "CBD"}),
    _node(NodeType.TREATY,
          "Nagoya Protocol on Access and Benefit-Sharing 2010",
          jurisdiction="International",
          aliases=["nagoya protocol on access and benefit sharing", "nagoya protocol"],
          attributes={"instrument_type": "Protocol", "year": 2010,
                      "note": "Operationalises the CBD's access-and-benefit-sharing provisions."}),
    _node(NodeType.TREATY, "Patent Cooperation Treaty (PCT)",
          jurisdiction="International",
          aliases=["patent cooperation treaty", "pct treaty"],
          attributes={"instrument_type": "Treaty", "year": 1970,
                      "administered_by": "WIPO"}),
    _node(NodeType.TREATY, "Madrid Protocol on the International Registration of Marks",
          jurisdiction="International",
          aliases=["madrid protocol", "madrid system for the international registration of marks"],
          attributes={"instrument_type": "Protocol", "year": 1989,
                      "administered_by": "WIPO"}),
    _node(NodeType.TREATY,
          "Hague Agreement Concerning the International Registration of Industrial Designs",
          jurisdiction="International",
          aliases=["hague agreement concerning the international registration of industrial designs",
                   "hague system for industrial designs", "hague agreement"],
          attributes={"instrument_type": "Treaty", "year": 1925,
                      "administered_by": "WIPO"}),
    _node(NodeType.TREATY,
          "Budapest Treaty on the International Recognition of the Deposit of Microorganisms",
          jurisdiction="International",
          aliases=["budapest treaty on the international recognition of the deposit of microorganisms",
                   "budapest treaty"],
          attributes={"instrument_type": "Treaty", "year": 1977,
                      "administered_by": "WIPO"}),
    _node(NodeType.TREATY,
          "WIPO Treaty on Intellectual Property in Respect of Genetic Resources and Traditional Knowledge 2024",
          jurisdiction="International",
          aliases=["wipo treaty on intellectual property in respect of genetic resources and traditional knowledge",
                   "gratw treaty 2024"],
          attributes={"instrument_type": "Treaty", "year": 2024,
                      "acronym": "GRATK 2024", "administered_by": "WIPO"}),

    # --------------------------------------------------------
    # Registries
    # --------------------------------------------------------
    _node(NodeType.REGISTRY, "Indian Patent Office", jurisdiction="India",
          aliases=["indian patent office", "ip india patents", "patent office india"],
          attributes={"acronym": "IPO", "registers": "Patents"}),
    _node(NodeType.REGISTRY, "Trade Marks Registry", jurisdiction="India",
          aliases=["trade marks registry", "trademarks registry india"],
          attributes={"registers": "Trade marks"}),
    _node(NodeType.REGISTRY, "Geographical Indications Registry", jurisdiction="India",
          aliases=["geographical indications registry", "gi registry"],
          attributes={"registers": "Geographical indications",
                      "note": "GI applications are filed with the GI Registry (Chennai)."}),
    _node(NodeType.REGISTRY, "Copyright Office", jurisdiction="India",
          aliases=["copyright office india", "copyright office"],
          attributes={"registers": "Copyright"}),
    _node(NodeType.REGISTRY, "Designs Office", jurisdiction="India",
          aliases=["designs office india", "designs office"],
          attributes={"registers": "Designs"}),
    _node(NodeType.REGISTRY, "Plant Varieties and Farmers' Rights Registry",
          jurisdiction="India",
          aliases=["plant varieties and farmers rights registry", "ppv fr registry"],
          attributes={"registers": "Plant varieties",
                      "authority": "Protection of Plant Varieties and Farmers' Rights Authority"}),
    _node(NodeType.REGISTRY, "Traditional Knowledge Digital Library (TKDL)",
          jurisdiction="India",
          aliases=["traditional knowledge digital library", "tkdl"],
          attributes={"access": "restricted",
                      "note": "Restricted database: the platform never accesses, searches or reproduces its contents."}),
    _node(NodeType.REGISTRY, "WIPO", jurisdiction="International",
          aliases=["wipo"],
          attributes={"kind": "international organization"}),

    # --------------------------------------------------------
    # Regulators
    # --------------------------------------------------------
    _node(NodeType.REGULATOR, "National Biodiversity Authority",
          jurisdiction="India",
          aliases=["national biodiversity authority"],
          attributes={"acronym": "NBA",
                      "remit": "Access and benefit sharing under the Biological Diversity Act."}),
    _node(NodeType.REGULATOR,
          "Food Safety and Standards Authority of India (FSSAI)",
          jurisdiction="India",
          aliases=["food safety and standards authority of india", "fssai"],
          attributes={"acronym": "FSSAI", "remit": "Food and nutrition regulations, incl. Ayurveda Aahar."}),
    _node(NodeType.REGULATOR,
          "Central Drugs Standard Control Organisation (CDSCO)",
          jurisdiction="India",
          aliases=["central drugs standard control organisation", "cdsco"],
          attributes={"acronym": "CDSCO", "remit": "Drugs and cosmetics regulation."}),
    _node(NodeType.REGULATOR, "Ministry of AYUSH", jurisdiction="India",
          aliases=["ministry of ayush", "ayush ministry"],
          attributes={"remit": "Ayurveda, Yoga, Unani, Siddha and Homoeopathy."}),

    # --------------------------------------------------------
    # IP routes (nine)
    # --------------------------------------------------------
    _node(NodeType.IP_TYPE, "Patent",
          aliases=["patents route", "patent route"],
          attributes={"route_key": "patent"}),
    _node(NodeType.IP_TYPE, "Trademark",
          aliases=["trade mark route", "trademark route"],
          attributes={"route_key": "trademark"}),
    _node(NodeType.IP_TYPE, "Copyright",
          aliases=["copyright route"],
          attributes={"route_key": "copyright"}),
    _node(NodeType.IP_TYPE, "Design",
          aliases=["design route"],
          attributes={"route_key": "design"}),
    _node(NodeType.IP_TYPE, "Geographical Indication (GI)",
          aliases=["geographical indication route", "gi route"],
          attributes={"route_key": "gi"}),
    _node(NodeType.IP_TYPE, "Trade Secret",
          aliases=["trade secret route"],
          attributes={"route_key": "trade_secret"}),
    _node(NodeType.IP_TYPE, "Plant Variety",
          aliases=["plant variety route"],
          attributes={"route_key": "plant_variety"}),
    _node(NodeType.IP_TYPE, "Traditional Knowledge",
          aliases=["traditional knowledge route"],
          attributes={"route_key": "traditional_knowledge"}),
    _node(NodeType.IP_TYPE, "Biodiversity / ABS",
          aliases=["biodiversity route", "access and benefit sharing route"],
          attributes={"route_key": "biodiversity_abs"}),

    # --------------------------------------------------------
    # Formulation categories (six canonical + platform categories)
    # --------------------------------------------------------
    _node(NodeType.FORMULATION_CATEGORY, "Classical/Traditional Formulation",
          aliases=["classical traditional formulation", "classical formulation",
                   "classical traditional"],
          attributes={"category_key": "classical_traditional"}),
    _node(NodeType.FORMULATION_CATEGORY, "Proprietary Ayurvedic Formulation",
          aliases=["proprietary ayurvedic formulation", "proprietary ayurvedic"],
          attributes={"category_key": "proprietary_ayurvedic"}),
    _node(NodeType.FORMULATION_CATEGORY, "Phytopharmaceutical Formulation",
          aliases=["phytopharmaceutical formulation", "phytopharmaceutical",
                   "phytopharmaceutical drug"],
          attributes={"category_key": "phytopharmaceutical",
                      "note": "Plant-derived drug category (new-drug pathway); regulated as a drug."}),
    _node(NodeType.FORMULATION_CATEGORY, "Ayurveda Aahara Formulation",
          aliases=["ayurveda aahara formulation", "ayurveda aahara",
                   "ayurvedic food"],
          attributes={"category_key": "ayurveda_aahara"}),
    _node(NodeType.FORMULATION_CATEGORY, "Possible Medicinal Formulation",
          aliases=["possible medicinal formulation", "possible medicinal product"],
          attributes={"category_key": "possible_medicinal"}),
    _node(NodeType.FORMULATION_CATEGORY, "Possible Cosmetic Formulation",
          aliases=["possible cosmetic formulation", "possible cosmetic"],
          attributes={"category_key": "possible_cosmetic"}),
    _node(NodeType.FORMULATION_CATEGORY, "Research Product",
          aliases=["research product"],
          attributes={"category_key": "research_product"}),
    _node(NodeType.FORMULATION_CATEGORY, "Industrial Product",
          aliases=["industrial product"],
          attributes={"category_key": "industrial_product"}),

    # --------------------------------------------------------
    # Obligations
    # --------------------------------------------------------
    _node(NodeType.OBLIGATION, "Section 3(p) (Patents Act 1970)",
          jurisdiction="India",
          aliases=["section 3 p patents act 1970", "section 3p patents act 1970",
                   "section 3 p", "patenting bar", "known substance patenting bar"],
          attributes={"instrument": "Patents Act 1970",
                      "provision": "3(p)",
                      "summary": ("Bar on a mere discovery of a new form or new property of a "
                                  "known substance or mixture that does not enhance its efficacy."),
                      "review_required": True}),
    _node(NodeType.OBLIGATION, "Access and Benefit-Sharing Obligation",
          aliases=["access and benefit sharing obligation",
                   "prior informed consent obligation", "benefit sharing obligation"],
          attributes={"instruments": ["Convention on Biological Diversity 1992",
                                      "Nagoya Protocol on Access and Benefit-Sharing 2010",
                                      "Biological Diversity Act 2002"],
                      "summary": ("Prior informed consent and benefit-sharing considerations for "
                                  "access to genetic resources and associated traditional knowledge."),
                      "review_required": True}),
    _node(NodeType.OBLIGATION, "Prior Permission to Access Biological Resources",
          jurisdiction="India",
          aliases=["prior permission to access biological resources",
                   "prior approval biological resources"],
          attributes={"instrument": "Biological Diversity Act 2002",
                      "authority": "National Biodiversity Authority",
                      "summary": ("Access to biological resources for research or commercial "
                                  "utilisation generally requires prior permission under the "
                                  "Biological Diversity Act; which approvals apply depends on "
                                  "who accesses the resource and for what purpose."),
                      "review_required": True}),
]


# ============================================================
# Seed edges (referenced by canonical node name)
# ============================================================

def _edge(src: str, relation: Relation, dst: str, *,
          weight: float = 1.0, evidence: Optional[Dict] = None) -> Dict:
    return {
        "from": src,
        "relation": relation,
        "to": dst,
        "weight": weight,
        "evidence": dict(evidence or {}),
    }


_SPINE = "regulatory_spine"

SEED_EDGES: List[Dict] = [
    # ---------------- Patents ----------------
    _edge("Patents Act 1970", Relation.IMPLEMENTED_BY, "Patents Rules 2024",
          evidence={"basis": _SPINE, "note": "The Act is carried into practice by the Patents Rules."}),
    _edge("Patents Act 1970", Relation.IMPLEMENTED_BY, "Indian Patent Office",
          evidence={"basis": _SPINE, "note": "Administered by the Indian Patent Office."}),
    _edge("Patents Act 1970", Relation.GOVERNS, "Patent",
          evidence={"basis": _SPINE, "note": "Patent regime in India."}),
    _edge("Patents Act 1970", Relation.PROTECTS, "Patent",
          evidence={"basis": _SPINE, "note": "Confers and protects patent rights."}),
    _edge("Patents Act 1970", Relation.APPLIES_IN, "India",
          evidence={"basis": _SPINE}),
    _edge("Patents Rules 2024", Relation.APPLIES_IN, "India",
          evidence={"basis": _SPINE}),
    _edge("Section 3(p) (Patents Act 1970)", Relation.IMPLEMENTED_BY, "Patents Act 1970",
          evidence={"basis": _SPINE, "note": "Provision of the Patents Act 1970."}),
    _edge("Classical/Traditional Formulation", Relation.BARRED_BY, "Section 3(p) (Patents Act 1970)",
          weight=0.8,
          evidence={"basis": _SPINE, "review_required": True,
                    "note": ("Screening heuristic recorded in the regulatory spine: a classical "
                             "formulation built on known substances is exposed to the section 3(p) "
                             "known-substance/new-form bar. Preliminary - not a patentability finding.")}),
    _edge("Patent", Relation.REGISTERED_IN, "Indian Patent Office",
          evidence={"basis": _SPINE}),

    # ---------------- Trade marks ----------------
    _edge("Trade Marks Act 1999", Relation.IMPLEMENTED_BY, "Trade Marks Rules 2017",
          evidence={"basis": _SPINE}),
    _edge("Trade Marks Act 1999", Relation.IMPLEMENTED_BY, "Trade Marks Registry",
          evidence={"basis": _SPINE}),
    _edge("Trade Marks Act 1999", Relation.GOVERNS, "Trademark",
          evidence={"basis": _SPINE}),
    _edge("Trade Marks Act 1999", Relation.PROTECTS, "Trademark",
          evidence={"basis": _SPINE}),
    _edge("Trade Marks Act 1999", Relation.APPLIES_IN, "India",
          evidence={"basis": _SPINE}),
    _edge("Trademark", Relation.REGISTERED_IN, "Trade Marks Registry",
          evidence={"basis": _SPINE}),

    # ---------------- Geographical indications ----------------
    _edge("Geographical Indications of Goods (Registration and Protection) Act 1999",
          Relation.IMPLEMENTED_BY, "Geographical Indications Registry",
          evidence={"basis": _SPINE}),
    _edge("Geographical Indications of Goods (Registration and Protection) Act 1999",
          Relation.GOVERNS, "Geographical Indication (GI)",
          evidence={"basis": _SPINE}),
    _edge("Geographical Indications of Goods (Registration and Protection) Act 1999",
          Relation.PROTECTS, "Geographical Indication (GI)",
          evidence={"basis": _SPINE}),
    _edge("Geographical Indications of Goods (Registration and Protection) Act 1999",
          Relation.APPLIES_IN, "India",
          evidence={"basis": _SPINE}),
    _edge("Geographical Indication (GI)", Relation.REGISTERED_IN, "Geographical Indications Registry",
          evidence={"basis": _SPINE}),

    # ---------------- Designs ----------------
    _edge("Designs Act 2000", Relation.IMPLEMENTED_BY, "Designs Office",
          evidence={"basis": _SPINE}),
    _edge("Designs Act 2000", Relation.GOVERNS, "Design",
          evidence={"basis": _SPINE}),
    _edge("Designs Act 2000", Relation.PROTECTS, "Design",
          evidence={"basis": _SPINE}),
    _edge("Designs Act 2000", Relation.APPLIES_IN, "India",
          evidence={"basis": _SPINE}),
    _edge("Design", Relation.REGISTERED_IN, "Designs Office",
          evidence={"basis": _SPINE}),

    # ---------------- Copyright ----------------
    _edge("Copyright Act 1957", Relation.IMPLEMENTED_BY, "Copyright Office",
          evidence={"basis": _SPINE}),
    _edge("Copyright Act 1957", Relation.GOVERNS, "Copyright",
          evidence={"basis": _SPINE}),
    _edge("Copyright Act 1957", Relation.PROTECTS, "Copyright",
          evidence={"basis": _SPINE}),
    _edge("Copyright Act 1957", Relation.APPLIES_IN, "India",
          evidence={"basis": _SPINE}),
    _edge("Copyright", Relation.REGISTERED_IN, "Copyright Office",
          evidence={"basis": _SPINE}),

    # ---------------- Plant varieties ----------------
    _edge("Protection of Plant Varieties and Farmers' Rights Act 2001",
          Relation.IMPLEMENTED_BY, "Plant Varieties and Farmers' Rights Registry",
          evidence={"basis": _SPINE}),
    _edge("Protection of Plant Varieties and Farmers' Rights Act 2001",
          Relation.GOVERNS, "Plant Variety",
          evidence={"basis": _SPINE}),
    _edge("Protection of Plant Varieties and Farmers' Rights Act 2001",
          Relation.PROTECTS, "Plant Variety",
          evidence={"basis": _SPINE}),
    _edge("Protection of Plant Varieties and Farmers' Rights Act 2001",
          Relation.APPLIES_IN, "India",
          evidence={"basis": _SPINE}),
    _edge("Plant Variety", Relation.REGISTERED_IN, "Plant Varieties and Farmers' Rights Registry",
          evidence={"basis": _SPINE}),

    # ---------------- Biodiversity / ABS ----------------
    _edge("Biological Diversity Act 2002", Relation.IMPLEMENTED_BY, "Biological Diversity Rules 2004",
          evidence={"basis": _SPINE}),
    _edge("Biological Diversity Act 2002", Relation.IMPLEMENTED_BY, "Biological Diversity Rules 2024",
          evidence={"basis": _SPINE}),
    _edge("Biological Diversity Act 2002", Relation.IMPLEMENTED_BY, "National Biodiversity Authority",
          evidence={"basis": _SPINE, "note": "Administered by the National Biodiversity Authority."}),
    _edge("Biological Diversity Act 2002", Relation.GOVERNS, "Biodiversity / ABS",
          evidence={"basis": _SPINE}),
    _edge("Biological Diversity Act 2002", Relation.GOVERNS, "Access and Benefit-Sharing Obligation",
          evidence={"basis": _SPINE}),
    _edge("Biological Diversity (Amendment) Act 2023", Relation.AMENDS,
          "Biological Diversity Act 2002",
          evidence={"basis": _SPINE, "note": "The 2023 amendment amends the Biological Diversity Act 2002."}),
    _edge("Biological Diversity Act 2002", Relation.GOVERNS,
          "Prior Permission to Access Biological Resources",
          evidence={"basis": _SPINE, "review_required": True}),
    _edge("Prior Permission to Access Biological Resources", Relation.REQUIRES_PERMIT_FROM,
          "National Biodiversity Authority",
          weight=0.9,
          evidence={"basis": _SPINE, "review_required": True,
                    "note": ("The National Biodiversity Authority is the approving authority "
                             "referenced by the obligation. Whether a permit is required for a "
                             "given access activity depends on the facts - preliminary reference "
                             "only, not a determination.")}),
    _edge("Biological Diversity Act 2002", Relation.APPLIES_IN, "India",
          evidence={"basis": _SPINE}),
    _edge("Biological Diversity Rules 2024", Relation.AMENDS, "Biological Diversity Rules 2004",
          evidence={"basis": _SPINE, "note": "The 2024 rules supersede/amend the 2004 rules."}),
    _edge("Convention on Biological Diversity 1992", Relation.IMPLEMENTED_BY,
          "Nagoya Protocol on Access and Benefit-Sharing 2010",
          evidence={"basis": _SPINE, "note": "The protocol operationalises the CBD's ABS provisions."}),
    _edge("Convention on Biological Diversity 1992", Relation.GOVERNS,
          "Access and Benefit-Sharing Obligation",
          evidence={"basis": _SPINE}),
    _edge("Convention on Biological Diversity 1992", Relation.APPLIES_IN, "International",
          evidence={"basis": _SPINE}),
    _edge("Nagoya Protocol on Access and Benefit-Sharing 2010", Relation.GOVERNS,
          "Access and Benefit-Sharing Obligation",
          evidence={"basis": _SPINE}),
    _edge("Nagoya Protocol on Access and Benefit-Sharing 2010", Relation.APPLIES_IN, "International",
          evidence={"basis": _SPINE}),

    # ---------------- Drugs, cosmetics and food ----------------
    _edge("Drugs and Cosmetics Act 1940", Relation.IMPLEMENTED_BY, "Drugs and Cosmetics Rules 1945",
          evidence={"basis": _SPINE}),
    _edge("Drugs and Cosmetics Act 1940", Relation.IMPLEMENTED_BY,
          "Central Drugs Standard Control Organisation (CDSCO)",
          evidence={"basis": _SPINE}),
    _edge("Drugs and Cosmetics Act 1940", Relation.GOVERNS, "Possible Medicinal Formulation",
          evidence={"basis": _SPINE, "note": "Medicinal products are governed as drugs."}),
    _edge("Drugs and Cosmetics Act 1940", Relation.GOVERNS, "Phytopharmaceutical Formulation",
          evidence={"basis": _SPINE, "note": "Phytopharmaceutical drugs are regulated as drugs."}),
    _edge("Drugs and Cosmetics Act 1940", Relation.APPLIES_IN, "India",
          evidence={"basis": _SPINE}),
    _edge("Drugs and Magic Remedies (Objectionable Advertisements) Act 1954",
          Relation.APPLIES_IN, "India",
          evidence={"basis": _SPINE}),
    _edge("Food Safety and Standard (Ayurveda Aahar) Regulations 2022",
          Relation.GOVERNS, "Ayurveda Aahara Formulation",
          evidence={"basis": _SPINE}),
    _edge("Food Safety and Standard (Ayurveda Aahar) Regulations 2022",
          Relation.IMPLEMENTED_BY, "Food Safety and Standards Authority of India (FSSAI)",
          evidence={"basis": _SPINE}),
    _edge("Food Safety and Standard (Ayurveda Aahar) Regulations 2022",
          Relation.APPLIES_IN, "India",
          evidence={"basis": _SPINE}),

    # ---------------- Treaties ----------------
    _edge("TRIPS Agreement 1994", Relation.GOVERNS, "Patent", evidence={"basis": _SPINE}),
    _edge("TRIPS Agreement 1994", Relation.GOVERNS, "Trademark", evidence={"basis": _SPINE}),
    _edge("TRIPS Agreement 1994", Relation.GOVERNS, "Copyright", evidence={"basis": _SPINE}),
    _edge("TRIPS Agreement 1994", Relation.GOVERNS, "Design", evidence={"basis": _SPINE}),
    _edge("TRIPS Agreement 1994", Relation.APPLIES_IN, "International", evidence={"basis": _SPINE}),
    _edge("Patent Cooperation Treaty (PCT)", Relation.GOVERNS, "Patent", evidence={"basis": _SPINE}),
    _edge("Patent Cooperation Treaty (PCT)", Relation.IMPLEMENTED_BY, "WIPO",
          evidence={"basis": _SPINE, "note": "Administered by WIPO."}),
    _edge("Patent Cooperation Treaty (PCT)", Relation.APPLIES_IN, "International", evidence={"basis": _SPINE}),
    _edge("Madrid Protocol on the International Registration of Marks", Relation.GOVERNS, "Trademark",
          evidence={"basis": _SPINE}),
    _edge("Madrid Protocol on the International Registration of Marks", Relation.IMPLEMENTED_BY, "WIPO",
          evidence={"basis": _SPINE}),
    _edge("Madrid Protocol on the International Registration of Marks", Relation.APPLIES_IN,
          "International", evidence={"basis": _SPINE}),
    _edge("Hague Agreement Concerning the International Registration of Industrial Designs",
          Relation.GOVERNS, "Design", evidence={"basis": _SPINE}),
    _edge("Hague Agreement Concerning the International Registration of Industrial Designs",
          Relation.IMPLEMENTED_BY, "WIPO", evidence={"basis": _SPINE}),
    _edge("Hague Agreement Concerning the International Registration of Industrial Designs",
          Relation.APPLIES_IN, "International", evidence={"basis": _SPINE}),
    _edge("Budapest Treaty on the International Recognition of the Deposit of Microorganisms",
          Relation.GOVERNS, "Patent", evidence={"basis": _SPINE}),
    _edge("Budapest Treaty on the International Recognition of the Deposit of Microorganisms",
          Relation.IMPLEMENTED_BY, "WIPO", evidence={"basis": _SPINE}),
    _edge("Budapest Treaty on the International Recognition of the Deposit of Microorganisms",
          Relation.APPLIES_IN, "International", evidence={"basis": _SPINE}),
    _edge("WIPO Treaty on Intellectual Property in Respect of Genetic Resources and Traditional Knowledge 2024",
          Relation.GOVERNS, "Traditional Knowledge", evidence={"basis": _SPINE}),
    _edge("WIPO Treaty on Intellectual Property in Respect of Genetic Resources and Traditional Knowledge 2024",
          Relation.IMPLEMENTED_BY, "WIPO", evidence={"basis": _SPINE}),
    _edge("WIPO Treaty on Intellectual Property in Respect of Genetic Resources and Traditional Knowledge 2024",
          Relation.APPLIES_IN, "International", evidence={"basis": _SPINE}),
]


def seed_node_names() -> List[str]:
    """Canonical names of every seed node (stable order)."""
    return [node["canonical_name"] for node in SEED_NODES]
