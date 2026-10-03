"""
Authoritative-source registry for IP-SAKTI Sahayak.

Why this module exists
----------------------
The SIH problem statement requires the platform to give Ayurveda-IP users
"access to authoritative sources - free official databases directly and the
user's own paid subscriptions only with explicit, logged permission".

This module is the first half of that promise: a curated, machine-readable
registry of the **free official databases** an Ayurveda-IP user actually needs
(patents, trademarks, geographical indications, biodiversity/ABS, Ayurveda
regulation, legislation), plus a small number of **paid / restricted**
connectors that are only ever reachable through the explicit, logged consent
flow in ``app/routers/privacy.py`` (SourceConsent + SourceAccessLog).

Honesty rules baked into the data
---------------------------------
* ``access`` is one of FREE | FREE_REGISTRATION | PAID_SUBSCRIPTION |
  THIRD_PARTY_API | RESTRICTED_NOT_ACCESSED.
* Anything that is not FREE/FREE_REGISTRATION carries
  ``requires_permission = True`` and a ``restricted_note`` - the API never
  presents it as directly accessible.
* TKDL is RESTRICTED_NOT_ACCESSED: the platform has no access, never queries
  it and never reproduces it. It is listed only so a reviewer knows to consult
  it through the authorised channel (patent offices).
* The platform does not proxy, scrape or fetch any of these sources. Every
  paid/restricted hand-off is a ``mode: "HANDOFF"`` - the user opens the
  source themselves in their own subscription.

URL verification
----------------
``verified_on`` records when the URLs were last checked by the build that
wrote this file. Re-verify before relying on any entry: official sites move,
and a top-level domain is deliberately preferred over a deep link that may
rot. Nothing in this file is a citation - citations are only ever emitted
when a real passage is retrieved from the corpus.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

#: When every URL in this registry was last verified.
VERIFIED_ON = "2026-09-28"

VERIFICATION_NOTE = (
    "URLs were verified on "
    + VERIFIED_ON
    + " and are kept to well-known top-level official domains where possible. "
    "Re-verify before relying on an entry - official sites move. "
    "This registry is a pointer to sources, not a citation to their contents."
)

# -------------------------------------------------------
# Access vocabulary
# -------------------------------------------------------

ACCESS_FREE = "FREE"
ACCESS_FREE_REGISTRATION = "FREE_REGISTRATION"
ACCESS_PAID_SUBSCRIPTION = "PAID_SUBSCRIPTION"
ACCESS_THIRD_PARTY_API = "THIRD_PARTY_API"
ACCESS_RESTRICTED = "RESTRICTED_NOT_ACCESSED"

#: Access values a user can reach without granting this platform any permission.
DIRECT_ACCESS = (ACCESS_FREE, ACCESS_FREE_REGISTRATION)

ACCESS_VALUES = (
    ACCESS_FREE,
    ACCESS_FREE_REGISTRATION,
    ACCESS_PAID_SUBSCRIPTION,
    ACCESS_THIRD_PARTY_API,
    ACCESS_RESTRICTED,
)

#: Access values that are only reachable through the logged-permission flow.
PERMISSIONED_ACCESS = (
    ACCESS_PAID_SUBSCRIPTION,
    ACCESS_THIRD_PARTY_API,
    ACCESS_RESTRICTED,
)


# -------------------------------------------------------
# The registry
# -------------------------------------------------------

OFFICIAL_SOURCES: List[Dict[str, Any]] = [
    # =================================================
    # India - patents / trademarks / GI / plant varieties
    # =================================================
    {
        "id": "ip-india-patent-search",
        "title": "IP India - Patent Search (Public)",
        "authority": "Indian Patent Office, DPIIT, Ministry of Commerce and Industry",
        "jurisdiction": "India",
        "ip_types": ["patent"],
        "topics": ["prior art", "patent status", "section 3(d)", "section 3(p)"],
        "access": ACCESS_FREE,
        "url": "https://ipindiaonline.gov.in/patentssearch/",
        "what_you_can_do": (
            "Search published Indian patent applications and granted patents by "
            "application number, applicant/assignee, inventor, international patent "
            "classification and date ranges. Use it for prior-art checks and to "
            "follow the prosecution status of an application."
        ),
        "notes": (
            "Primary Indian prior-art database. Section 3(d) and section 3(p) "
            "objections are decided by the examiner on this data - always confirm "
            "the live legal status on the official register, not on an aggregator."
        ),
    },
    {
        "id": "ip-india-e-register",
        "title": "IP India - e-Register of Patents",
        "authority": "Indian Patent Office, DPIIT",
        "jurisdiction": "India",
        "ip_types": ["patent"],
        "topics": ["patent status", "application status", "renewals"],
        "access": ACCESS_FREE,
        "url": "https://ipindia.gov.in/",
        "what_you_can_do": (
            "Check the current legal status of an Indian patent application "
            "(filed, published, examined, refused, granted, lapsed) and see the "
            "register entries maintained by the Indian Patent Office."
        ),
        "notes": (
            "The e-Register is published from the IP India site; use the Patents "
            "section of ipindia.gov.in to reach it, since the IPO reorganises its "
            "paths from time to time."
        ),
    },
    {
        "id": "ip-india-tm-public-search",
        "title": "IP India - Trademark Public Search",
        "authority": "Trade Marks Registry, IP India, DPIIT",
        "jurisdiction": "India",
        "ip_types": ["trademark"],
        "topics": ["trademark", "brand clearance", "prior art"],
        "access": ACCESS_FREE,
        "url": "https://ipindiaonline.gov.in/tmrpublicsearch/",
        "what_you_can_do": (
            "Search the Indian trade mark register by wordmark, device and class "
            "(Nice classification) to clear a brand name before adoption and to "
            "find marks cited against an application."
        ),
        "notes": "Wordmark, Vienna (device) and class-wise search modes are offered.",
    },
    {
        "id": "ip-india-gi-search",
        "title": "Geographical Indications Registry - GI Search",
        "authority": "Geographical Indications Registry, Controller General of Patents, "
        "Designs and Trade Marks, Chennai",
        "jurisdiction": "India",
        "ip_types": ["geographical_indication"],
        "topics": ["geographical indication", "traditional products", "prior art"],
        "access": ACCESS_FREE,
        "url": "https://gisearch.ipindiaonline.gov.in/",
        "what_you_can_do": (
            "Search registered and applied-for geographical indications (for example "
            "region-specific Ayurvedic and herbal products) to check whether a name "
            "or tagline is already protected."
        ),
        "notes": "The official GI search portal published by the GI Registry.",
    },
    {
        "id": "ppvfr-authority",
        "title": "PPV&FR Authority - Plant Variety Register",
        "authority": "Protection of Plant Varieties and Farmers' Rights Authority, "
        "Ministry of Agriculture and Farmers Welfare",
        "jurisdiction": "India",
        "ip_types": ["plant_variety"],
        "topics": [
            "plant variety",
            "plant breeder rights",
            "farmers rights",
            "traditional varieties",
        ],
        "access": ACCESS_FREE,
        "url": "https://plantauthority.gov.in/",
        "what_you_can_do": (
            "Read the Protection of Plant Varieties and Farmers' Rights Act 2001 "
            "framework, browse registered varieties (including farmers' varieties "
            "and traditional/known varieties) and the DUS guidelines that govern "
            "registration."
        ),
        "notes": (
            "Relevant when an Ayurveda formulation depends on a specific "
            "cultivar or landrace; registration is a separate right from patents."
        ),
    },
    # =================================================
    # India - biodiversity, ABS, Ayurveda regulation
    # =================================================
    {
        "id": "nba-india",
        "title": "National Biodiversity Authority (NBA)",
        "authority": "National Biodiversity Authority, Ministry of Environment, Forest and Climate Change",
        "jurisdiction": "India",
        "ip_types": ["access_and_benefit_sharing", "traditional_knowledge"],
        "topics": [
            "access and benefit sharing",
            "biodiversity",
            "nagoya protocol",
            "traditional knowledge",
        ],
        "access": ACCESS_FREE,
        "url": "https://www.nbaindia.org/",
        "what_you_can_do": (
            "Read Indian access-and-benefit-sharing guidance, prior intimation "
            "requirements for using biological resources, NBA notifications and "
            "the Bennett model for benefit sharing."
        ),
        "notes": (
            "Guidance only: whether a particular use needs NBA approval is an "
            "official determination, not something this platform decides."
        ),
    },
    {
        "id": "tkdl-india",
        "title": "Traditional Knowledge Digital Library (TKDL)",
        "authority": "CSIR (TKDL Unit) with the Ministry of AYUSH / IP India",
        "jurisdiction": "India",
        "ip_types": ["traditional_knowledge", "patent"],
        "topics": ["traditional knowledge", "prior art", "bio-piracy"],
        "access": ACCESS_RESTRICTED,
        "url": "https://www.tkdl.res.in/",
        "what_you_can_do": (
            "TKDL translates codified Indian traditional knowledge (Ayurveda, "
            "Unani, Siddha, Sowa Rigpa, Yoga) into patent-examiner languages so "
            "that patent offices can search it. Access to the database is granted "
            "to patent offices under the TKDL Access Agreement - not to the public."
        ),
        "notes": (
            "TKDL: RESTRICTED - NOT ACCESSED OR REPRODUCED. This platform has no "
            "access, cannot search TKDL and never reproduces its contents. Listed "
            "only so a reviewer knows the database exists and must be consulted "
            "through the authorised channel (that is, a patent office)."
        ),
    },
    {
        "id": "ayush-ministry",
        "title": "Ministry of AYUSH",
        "authority": "Ministry of AYUSH, Government of India",
        "jurisdiction": "India",
        "ip_types": ["regulatory"],
        "topics": [
            "ayurveda",
            "regulation",
            "policy",
            "traditional medicine",
            "notifications",
        ],
        "access": ACCESS_FREE,
        "url": "https://www.ayush.gov.in/",
        "what_you_can_do": (
            "Read national policy for Ayurveda, Yoga & Naturopathy, Unani, Siddha "
            "and Homoeopathy: regulations, standards, advisories and the "
            "institute network (including CCRAS and the Pharmacopoeia Commission)."
        ),
        "notes": "The parent ministry for Ayurveda regulation in India.",
    },
    {
        "id": "cdsco",
        "title": "Central Drugs Standard Control Organisation (CDSCO)",
        "authority": "CDSCO, Directorate General of Health Services, Ministry of Health and Family Welfare",
        "jurisdiction": "India",
        "ip_types": ["regulatory"],
        "topics": ["drug approval", "clinical trials", "regulation", "licensing"],
        "access": ACCESS_FREE,
        "url": "https://cdsco.gov.in/",
        "what_you_can_do": (
            "Check drug and device approval pathways, clinical-trial requirements, "
            "licensing of manufacturing premises and the Indian cosmetic/drug "
            "classification rules that a proprietary Ayurveda medicine must satisfy."
        ),
        "notes": (
            "Ayurvedic proprietary medicines are also covered by the Drugs and "
            "Cosmetics Act rules; CDSCO publishes the national framework while "
            "state licensing authorities issue most licences."
        ),
    },
    {
        "id": "fssai",
        "title": "Food Safety and Standards Authority of India (FSSAI)",
        "authority": "FSSAI, Ministry of Health and Family Welfare",
        "jurisdiction": "India",
        "ip_types": ["regulatory"],
        "topics": [
            "food safety",
            "nutraceutical",
            "labelling",
            "health claims",
            "regulation",
        ],
        "access": ACCESS_FREE,
        "url": "https://www.fssai.gov.in/",
        "what_you_can_do": (
            "Read the Food Safety and Standards Regulations, the nutraceutical and "
            "health-claim provisions, labelling rules and additive lists that decide "
            "whether a product is a food or a drug."
        ),
        "notes": (
            "The food-vs-drug boundary matters for Ayurveda products marketed as "
            "foods or supplements; FSSAI standards and additives regulations are "
            "the starting point."
        ),
    },
    {
        "id": "ccras",
        "title": "Central Council for Research in Ayurvedic Sciences (CCRAS)",
        "authority": "CCRAS, Ministry of AYUSH",
        "jurisdiction": "India",
        "ip_types": ["regulatory"],
        "topics": ["ayurveda", "clinical evidence", "research", "traditional medicine"],
        "access": ACCESS_FREE,
        "url": "https://ccras.nic.in/",
        "what_you_can_do": (
            "Browse publicly published Ayurveda research output, clinical studies, "
            "journal articles and the council's institutes - useful when looking for "
            "evidence to support (or refute) a traditional-use claim."
        ),
        "notes": "Research publications only; it is not a drug-approval register.",
    },
    # =================================================
    # India - legislation and gazette
    # =================================================
    {
        "id": "egazette-india",
        "title": "e-Gazette of India",
        "authority": "Department of Publication, Ministry of Home Affairs / Government of India",
        "jurisdiction": "India",
        "ip_types": ["regulatory"],
        "topics": ["notifications", "legislation", "rules", "amendments"],
        "access": ACCESS_FREE,
        "url": "https://egazette.nic.in/",
        "what_you_can_do": (
            "Read the authentic published text of central government notifications, "
            "orders and rules - including IP and AYUSH rule amendments - as notified."
        ),
        "notes": "The gazette is the authoritative publication date for a rule.",
    },
    {
        "id": "india-code",
        "title": "India Code - Laws of India",
        "authority": "Ministry of Law and Justice, Government of India",
        "jurisdiction": "India",
        "ip_types": ["regulatory"],
        "topics": ["legislation", "statutes", "acts", "amendments"],
        "access": ACCESS_FREE,
        "url": "https://www.indiacode.nic.in/",
        "what_you_can_do": (
            "Read consolidated central acts and subordinate legislation - the Patents "
            "Act 1970 and Patents Rules, the Trade Marks Act, the Geographical "
            "Indications Act, the Plants Varieties Act and the Drugs and Cosmetics "
            "Act among them."
        ),
        "notes": "Always confirm amendments against the gazette notification.",
    },
    # =================================================
    # International - patents
    # =================================================
    {
        "id": "wipo-patentscope",
        "title": "WIPO PATENTSCOPE",
        "authority": "World Intellectual Property Organization (WIPO)",
        "jurisdiction": "International",
        "ip_types": ["patent"],
        "topics": ["prior art", "international filings", "PCT", "patent status"],
        "access": ACCESS_FREE,
        "url": "https://patentscope.wipo.int/",
        "what_you_can_do": (
            "Search PCT applications and dozens of national collections, follow "
            "international publication stages and use chemical-structure and "
            "sequence searching for formulation prior art."
        ),
        "notes": "The primary international entry point for PCT prior art.",
    },
    {
        "id": "epo-espacenet",
        "title": "EPO Espacenet",
        "authority": "European Patent Office (EPO)",
        "jurisdiction": "International",
        "ip_types": ["patent"],
        "topics": ["prior art", "patent families", "patent status", "classification"],
        "access": ACCESS_FREE,
        "url": "https://worldwide.espacenet.com/",
        "what_you_can_do": (
            "Search over a hundred million documents, build patent families, read "
            "European Patent Classification (ECLA) / IPC entries and use the "
            "inpadoc legal-status information."
        ),
        "notes": "Espacenet is a search tool, not a legal register of record.",
    },
    {
        "id": "uspto",
        "title": "USPTO - United States Patent and Trademark Office",
        "authority": "United States Patent and Trademark Office",
        "jurisdiction": "United States",
        "ip_types": ["patent", "trademark"],
        "topics": ["prior art", "patent status", "trademark", "prosecution history"],
        "access": ACCESS_FREE,
        "url": "https://www.uspto.gov/",
        "what_you_can_do": (
            "Use Patent Public Search for full-text US patent searching, TSDR for "
            "trademark file histories, and the USPTO assignment database to see who "
            "owns a right today."
        ),
        "notes": "Official register for US rights; free to search without an account.",
    },
    {
        "id": "google-patents",
        "title": "Google Patents",
        "authority": "Google (private aggregator of public patent data)",
        "jurisdiction": "International",
        "ip_types": ["patent"],
        "topics": ["prior art", "patent families", "non-patent literature"],
        "access": ACCESS_FREE,
        "url": "https://patents.google.com/",
        "what_you_can_do": (
            "Fast full-text patent and non-patent-literature searching with family "
            "links, classification and a clean reading interface."
        ),
        "notes": (
            "Convenience index, NOT an official registry: it lags and it merges "
            "sources. Verify the legal status on the official office register "
            "before relying on it."
        ),
    },
    {
        "id": "the-lens",
        "title": "The Lens - scholarly and patent search",
        "authority": "Cambia (non-profit)",
        "jurisdiction": "International",
        "ip_types": ["patent"],
        "topics": ["prior art", "scholarly literature", "metrics"],
        "access": ACCESS_FREE_REGISTRATION,
        "url": "https://www.lens.org/",
        "what_you_can_do": (
            "Search patents and scholarly works together, build collections and "
            "export search results; a free account raises rate limits."
        ),
        "notes": "Free with optional registration; not an official register of record.",
    },
    # =================================================
    # International - trademarks, designs, GI
    # =================================================
    {
        "id": "wipo-madrid-monitor",
        "title": "WIPO Madrid Monitor",
        "authority": "World Intellectual Property Organization (WIPO)",
        "jurisdiction": "International",
        "ip_types": ["trademark"],
        "topics": ["trademark", "international marks", "madrid system"],
        "access": ACCESS_FREE,
        "url": "https://madridmonitor.wipo.int/",
        "what_you_can_do": (
            "Track international trademark applications and designations under the "
            "Madrid System, follow protection in each designated member and read "
            "provisional refusals."
        ),
        "notes": "Covers international registrations only, not purely national marks.",
    },
    {
        "id": "wipo-global-brand-database",
        "title": "WIPO Global Brand Database",
        "authority": "World Intellectual Property Organization (WIPO)",
        "jurisdiction": "International",
        "ip_types": ["trademark"],
        "topics": ["trademark", "brand clearance", "prior art"],
        "access": ACCESS_FREE,
        "url": "https://branddb.wipo.int/",
        "what_you_can_do": (
            "Search millions of brand records from WIPO and national offices side "
            "by side, including image and phonetic searching."
        ),
        "notes": "Coverage varies by member state; confirm on the national register.",
    },
    {
        "id": "wipo-hague-system",
        "title": "WIPO Hague System (industrial designs)",
        "authority": "World Intellectual Property Organization (WIPO)",
        "jurisdiction": "International",
        "ip_types": ["design"],
        "topics": ["design", "international filings", "hague system"],
        "access": ACCESS_FREE,
        "url": "https://hague.wipo.int/",
        "what_you_can_do": (
            "Search international design applications, published garments and "
            "container designs, and check the status of a design application."
        ),
        "notes": "Useful for packaging and product-shape protection around a formulation.",
    },
    {
        "id": "euipo",
        "title": "EUIPO - European Union Intellectual Property Office",
        "authority": "European Union Intellectual Property Office",
        "jurisdiction": "European Union",
        "ip_types": ["trademark", "design"],
        "topics": ["trademark", "design", "brand clearance"],
        "access": ACCESS_FREE,
        "url": "https://euipo.europa.eu/",
        "what_you_can_do": (
            "Search EUTMs and registered Community designs, read opposition decisions "
            "and use the eSearch plus / TMview tools for European clearance."
        ),
        "notes": "Also useful as a gateway to TMview, which spans many offices.",
    },
    # =================================================
    # International - law, policy, biodiversity, health
    # =================================================
    {
        "id": "wipo-lex",
        "title": "WIPO Lex - IP legislation and treaties",
        "authority": "World Intellectual Property Organization (WIPO)",
        "jurisdiction": "International",
        "ip_types": ["patent", "trademark", "design", "copyright"],
        "topics": ["legislation", "treaties", "policy", "amendments"],
        "access": ACCESS_FREE,
        "url": "https://www.wipo.int/wipolex/",
        "what_you_can_do": (
            "Compare patent, trademark and copyright legislation and treaties across "
            "jurisdictions, with official texts and publication metadata."
        ),
        "notes": "Secondary publication of official texts - confirm on the national source.",
    },
    {
        "id": "wto-trips",
        "title": "WTO - TRIPS Agreement",
        "authority": "World Trade Organization (WTO)",
        "jurisdiction": "International",
        "ip_types": ["patent", "trademark", "copyright"],
        "topics": ["trips", "international rules", "legislation", "prior art"],
        "access": ACCESS_FREE,
        "url": "https://www.wto.org/english/tratop_e/trips_e/trips_e.htm",
        "what_you_can_do": (
            "Read the TRIPS Agreement text - the baseline IP standards WTO members "
            "must apply, including the patentability and TRIPS-article-27.3(b) "
            "flexibilities relevant to plant varieties and traditional knowledge."
        ),
        "notes": "The starting point for any cross-border IP comparison.",
    },
    {
        "id": "cbd",
        "title": "Convention on Biological Diversity (CBD)",
        "authority": "Secretariat of the Convention on Biological Diversity",
        "jurisdiction": "International",
        "ip_types": ["access_and_benefit_sharing", "traditional_knowledge"],
        "topics": ["biodiversity", "nagoya protocol", "access and benefit sharing"],
        "access": ACCESS_FREE,
        "url": "https://www.cbd.int/",
        "what_you_can_do": (
            "Read the CBD texts, national biodiversity strategies and decision "
            "material on traditional knowledge and benefit sharing."
        ),
        "notes": "Framework material, not a country-specific compliance determination.",
    },
    {
        "id": "nagoya-absch",
        "title": "Nagoya Protocol ABS Clearing-House (ABSCH)",
        "authority": "Secretariat of the Convention on Biological Diversity",
        "jurisdiction": "International",
        "ip_types": ["access_and_benefit_sharing"],
        "topics": [
            "access and benefit sharing",
            "nagoya protocol",
            "checklists",
            "biodiversity",
        ],
        "access": ACCESS_FREE,
        "url": "https://absch.cbd.int/",
        "what_you_can_do": (
            "Check whether a country is a Party to the Nagoya Protocol, find its ABS "
            "legislation and competent national authority, and read legal take-"
            "permit / checkpoint requirements before sourcing a biological material."
        ),
        "notes": (
            "ABS compliance is country-specific; this platform reports what the "
            "clearing-house publishes and never gives a legal determination."
        ),
    },
    {
        "id": "eurlex",
        "title": "EUR-Lex - EU law",
        "authority": "Publications Office of the European Union",
        "jurisdiction": "European Union",
        "ip_types": ["regulatory", "patent"],
        "topics": ["legislation", "regulation", "herbal medicine", "novel food"],
        "access": ACCESS_FREE,
        "url": "https://eur-lex.europa.eu/",
        "what_you_can_do": (
            "Read EU regulations and directives - the Traditional Herbal Medicinal "
            "Products Directive, the Novel Food Regulation and the EUTM framework - "
            "in authentic language versions."
        ),
        "notes": "Relevant when an Ayurveda product is exported to the EU.",
    },
    {
        "id": "ema-herbal-medicines",
        "title": "EMA - herbal medicines (HMPC)",
        "authority": "European Medicines Agency",
        "jurisdiction": "European Union",
        "ip_types": ["regulatory"],
        "topics": ["herbal medicine", "monographs", "regulation", "clinical evidence"],
        "access": ACCESS_FREE,
        "url": "https://www.ema.europa.eu/",
        "what_you_can_do": (
            "Read the Committee on Herbal Medicinal Products (HMPC) monographs and "
            "community herbal monographs that describe accepted uses and evidence "
            "for herbal substances."
        ),
        "notes": (
            "Monographs describe EU regulatory positions; they are not a claim you "
            "may simply copy into another jurisdiction."
        ),
    },
    {
        "id": "who",
        "title": "World Health Organization (WHO) - traditional medicine",
        "authority": "World Health Organization (WHO)",
        "jurisdiction": "International",
        "ip_types": ["regulatory"],
        "topics": ["traditional medicine", "monographs", "health policy", "evidence"],
        "access": ACCESS_FREE,
        "url": "https://www.who.int/",
        "what_you_can_do": (
            "Read WHO publications on traditional medicine, botanical monographs and "
            "guidance documents used internationally as reference material."
        ),
        "notes": "Reference material; not a registration or approval anywhere.",
    },
    # =================================================
    # Paid subscriptions and third-party APIs
    # (reachable only through the logged-permission flow)
    # =================================================
    {
        "id": "derwent-innovation",
        "title": "Derwent Innovation (paid subscription)",
        "authority": "Clarivate (commercial provider)",
        "jurisdiction": "International",
        "ip_types": ["patent"],
        "topics": ["prior art", "patent analytics", "citation analysis"],
        "access": ACCESS_PAID_SUBSCRIPTION,
        "url": "https://clarivate.com/",
        "what_you_can_do": (
            "With your own paid licence: enhanced patent search, Derwent world "
            "patents indexing, citation analytics and portfolio tracking."
        ),
        "notes": (
            "Commercial product. This platform never proxies, fetches or caches "
            "paid data - you must hold your own subscription and open the source "
            "yourself. Access here is only ever recorded after explicit, logged "
            "permission."
        ),
    },
    {
        "id": "questel-orbit",
        "title": "Questel Orbit (paid subscription)",
        "authority": "Questel (commercial provider)",
        "jurisdiction": "International",
        "ip_types": ["patent", "trademark"],
        "topics": ["prior art", "patent analytics", "trademark"],
        "access": ACCESS_PAID_SUBSCRIPTION,
        "url": "https://www.questel.com/",
        "what_you_can_do": (
            "With your own paid licence: patent and trademark searching, family "
            "and legal-status analysis, and annuity/portfolio management."
        ),
        "notes": (
            "Commercial product, not a free official database. Requires your own "
            "subscription; access is gated behind explicit, logged permission."
        ),
    },
    {
        "id": "totalpatent-one",
        "title": "TotalPatent One (paid subscription)",
        "authority": "LexisNexis | RELX (commercial provider)",
        "jurisdiction": "International",
        "ip_types": ["patent"],
        "topics": ["prior art", "full text", "patent families"],
        "access": ACCESS_PAID_SUBSCRIPTION,
        "url": "https://www.lexisnexis.com/",
        "what_you_can_do": (
            "With your own paid licence: full-text patent searching across a large "
            "document collection with family and legal-status tools."
        ),
        "notes": (
            "Commercial product. Not directly accessible here - covered by the "
            "explicit, logged permission flow only."
        ),
    },
    {
        "id": "google-patents-bigquery",
        "title": "Google Patents Public Data (BigQuery dataset)",
        "authority": "Google Cloud (third-party API / bulk dataset)",
        "jurisdiction": "International",
        "ip_types": ["patent"],
        "topics": ["prior art", "bulk data", "analytics"],
        "access": ACCESS_THIRD_PARTY_API,
        "url": "https://cloud.google.com/bigquery",
        "what_you_can_do": (
            "With your own cloud account: run analytical SQL queries over the public "
            "Google Patents dataset for bulk prior-art or landscape studies."
        ),
        "notes": (
            "A third-party API/warehouse, not an official register, and its use can "
            "incur cloud cost. Recorded as THIRD_PARTY_API access - explicit, logged "
            "permission is required before this platform will even hand off to it."
        ),
    },
]


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def _annotate(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a copy of ``entry`` carrying the derived access flags.

    ``requires_permission`` is True for anything that is not directly
    reachable for free, and ``restricted_note`` explains why in plain
    language, so no API response can present a paid or restricted source as
    if it were open to everyone.
    """
    out = dict(entry)
    access = out.get("access")
    out["requires_permission"] = access not in DIRECT_ACCESS
    out["direct_access"] = access in DIRECT_ACCESS
    out["verified_on"] = out.get("verified_on", VERIFIED_ON)

    if access == ACCESS_PAID_SUBSCRIPTION:
        out["restricted_note"] = (
            "Paid subscription: you need your own licence with this provider. "
            "This platform never proxies or fetches paid data - granting "
            "permission records your consent and hands off to the provider's "
            "own website."
        )
    elif access == ACCESS_THIRD_PARTY_API:
        out["restricted_note"] = (
            "Third-party API / paid usage: requires your own account and may "
            "incur cost. Access is only recorded after explicit, logged "
            "permission."
        )
    elif access == ACCESS_RESTRICTED:
        out["restricted_note"] = (
            "Restricted: not accessible to this platform at all. It is listed "
            "for awareness only and is never queried or reproduced."
        )
    else:
        out["restricted_note"] = None
    return out


#: Every entry in the registry, annotated with its derived access flags.
#: ``verified_on`` is stamped on the source dicts first so the raw registry
#: (what a maintainer edits) and the served registry cannot drift apart.
for _entry in OFFICIAL_SOURCES:
    _entry.setdefault("verified_on", VERIFIED_ON)

SOURCES: List[Dict[str, Any]] = [_annotate(dict(e)) for e in OFFICIAL_SOURCES]

_BY_ID = {entry["id"]: entry for entry in SOURCES}


def list_official_sources(
    *,
    jurisdiction: Optional[str] = None,
    ip_type: Optional[str] = None,
    topic: Optional[str] = None,
    access: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return registry entries, optionally filtered.

    Args:
        jurisdiction: case-insensitive exact match ("India", "International", ...)
        ip_type: case-insensitive exact match against the entry's ip_types
        topic: case-insensitive match against any entry topic (substring allowed)
        access: case-insensitive exact match on the access vocabulary
    """
    entries = SOURCES

    if jurisdiction:
        wanted = jurisdiction.strip().lower()
        entries = [e for e in entries if str(e.get("jurisdiction", "")).lower() == wanted]

    if ip_type:
        wanted = ip_type.strip().lower()
        entries = [
            e for e in entries
            if any(str(t).lower() == wanted for t in e.get("ip_types", []))
        ]

    if topic:
        wanted = topic.strip().lower()
        entries = [
            e for e in entries
            if any(wanted in str(t).lower() for t in e.get("topics", []))
        ]

    if access:
        wanted = access.strip().upper()
        entries = [e for e in entries if str(e.get("access", "")).upper() == wanted]

    return [dict(e) for e in entries]


def get_official_source(source_id: str) -> Optional[Dict[str, Any]]:
    """Return one annotated registry entry by id, or None."""
    entry = _BY_ID.get(source_id)
    return dict(entry) if entry is not None else None


def sources_for_topic(query: str) -> List[Dict[str, Any]]:
    """
    Simple keyword match over the registry.

    Tokens from ``query`` are scored against title, topics, authority,
    jurisdiction, what_you_can_do and notes. Returns the best-scoring
    entries first; an empty or unmatchable query returns an empty list.
    """
    tokens = [t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(t) > 1]
    if not tokens:
        return []

    scored: List[tuple] = []
    for entry in SOURCES:
        haystacks = {
            "title": str(entry.get("title", "")).lower(),
            "topics": " ".join(str(t) for t in entry.get("topics", [])).lower(),
            "authority": str(entry.get("authority", "")).lower(),
            "jurisdiction": str(entry.get("jurisdiction", "")).lower(),
            "what": str(entry.get("what_you_can_do", "")).lower(),
            "notes": str(entry.get("notes", "")).lower(),
            "ip_types": " ".join(str(t) for t in entry.get("ip_types", [])).lower(),
        }
        score = 0
        for token in tokens:
            if token in haystacks["topics"]:
                score += 3
            if token in haystacks["title"]:
                score += 2
            if token in haystacks["ip_types"]:
                score += 2
            for key in ("authority", "jurisdiction", "what", "notes"):
                if token in haystacks[key]:
                    score += 1
                    break
        if score > 0:
            scored.append((score, entry["id"], entry))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [dict(entry) for _, _, entry in scored]


def distinct_topics() -> List[str]:
    """All distinct topics in the registry, sorted."""
    return sorted({str(t) for e in SOURCES for t in e.get("topics", [])})


def distinct_jurisdictions() -> List[str]:
    """All distinct jurisdictions in the registry, sorted."""
    return sorted({str(e.get("jurisdiction")) for e in SOURCES if e.get("jurisdiction")})
