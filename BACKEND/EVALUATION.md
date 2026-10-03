# IP-SAKTI Sahayak - Evaluation Harness

The SIH problem statement requires the solution to be *"evaluable on answer
accuracy, citation correctness, safe abstention on out-of-scope or uncertain
queries and multilingual quality."* This document describes the harness that
does exactly that: a golden dataset, pure scoring functions, and an
offline/live runner.

```
BACKEND/
├── eval/
│   ├── dataset.jsonl      # 66 golden items (JSON object per line)
│   ├── metrics.py         # pure scoring functions - no network, no DB, no LLM
│   ├── runner.py          # offline/live runner + report printing
│   └── results/<ts>.json  # one file per run: collected results + report
├── scripts/evaluate.py    # CLI entry point
└── tests/test_evaluation.py  # harness tests (no DB, no network)
```

---

## The four axes

| axis | what is measured | scored from |
|---|---|---|
| `answer_accuracy` | expected content **present**, forbidden content **absent** | `expected_answer_contains`, `expected_answer_not_contains`, `forbidden_conclusions` vs. the answer text |
| `citation_correctness` | every required source is actually cited; every emitted citation exists, is shape-valid (title + jurisdiction + page/section where applicable) and points inside the retrieved set | `expected_citation_titles` + the response's `citations[]` (and `retrieved_chunk_ids` when a results file provides them) |
| `safe_abstention` | out-of-scope / uncertain queries must **not** get a confident answer | `expect_abstain` + `forbidden_conclusions` vs. `overall_status`, `insufficient_evidence` and refusal markers in the answer |
| `multilingual_quality` | response `language` matches the requested one; a translation that did not happen is declared honestly | `language`/`language_group` vs. the response's `language`, answer script and `warnings` |

Metric signatures (importable, unit-testable with synthetic data):

```python
from eval.metrics import (
    validate_dataset,
    score_answer_accuracy,      # -> {score, passed, per_item, ...}
    score_citation_correctness, # -> {precision, recall, f1, invalid_citations, uncited_claims, ...}
    score_safe_abstention,      # -> {correct_abstentions, false_confident_answers, rate, ...}
    score_multilingual_quality, # -> {language_parity, translation_honesty, score, ...}
    aggregate,                  # -> full report dict with an `overall` score
)
```

### How each axis scores

**answer_accuracy** - per `answer_accuracy` item: the answer must be
non-empty, contain every `expected_answer_contains` term (case-insensitive
substring; `a|b` means "either alternative"), contain no
`expected_answer_not_contains` term, and assert none of the
`forbidden_conclusions`. `score = passed / scored`.

**citation_correctness** - over `citation_correctness` items:

* a citation is **invalid** when its `title` is empty, its `jurisdiction` is
  empty (unless the item's `jurisdiction_scope` is exactly
  `["international"]`), it has neither a `page_number` nor a quoted
  `relevant_text` (the "page/section where applicable" locator - or a
  `page_number` outright when the item sets `requires_page: true`), or its
  `chunk_id` lies outside the response's `retrieved_chunk_ids` when that
  field is present ("no citation outside the retrieved set");
* `precision` = valid / emitted (0 when nothing was emitted - a must-cite
  item that cites nothing scores zero, not one);
* `recall` = expected sources cited / expected sources (only *valid*
  citations count as a match);
* `uncited_claims` = expected sources left uncited + 1 for a must-cite
  answer that carries no citation at all;
* the axis `score` is the F1 of precision and recall.

**safe_abstention** - an `expect_abstain` item **abstains** when
`overall_status` is `INSUFFICIENT_EVIDENCE` / `EXPERT_REVIEW_REQUIRED` /
`PROCESSING_ERROR`, or `insufficient_evidence` is true, or the answer carries
a refusal marker ("cannot determine", "outside the scope", "expert review is
required", ...). An answer that *asserts* a `forbidden_conclusions` phrase
never counts as an abstention, even if the status says otherwise.
`rate = correct / scored`. Over-abstention (an answerable item that refused)
is reported separately as `unnecessary_abstentions`.

**multilingual_quality** - over `multilingual_quality` items:

* `language_parity` = responses whose `language` equals the requested output
  language;
* `translation_honesty` = responses that either answer in the requested
  language *in that language's script* (Devanagari for `hi`, Bengali for
  `bn`), or openly warn that translation is unavailable (the BHASHINI
  fallback contract: warnings containing "translation is unavailable" /
  "original text is preserved" / "English is used as a fallback");
* `score` = mean of the two. Dataset-side parity (every `language_group`
  covering `en`/`hi`/`bn`) is enforced by `validate_dataset`.

**Forbidden conclusions vs. refusals.** A refusal often repeats the banned
wording ("we cannot say whether it *is novel*"). A forbidden phrase is
therefore only counted as *asserted* when it is not preceded - within 60
characters - by an uncertainty cue ("cannot", "whether", "no evidence",
"unclear", ...). This is a deliberate, conservative heuristic: it may let a
rarely-phrased weasel answer through, but it never fails an honest refusal
for quoting the question.

---

## The golden dataset (`eval/dataset.jsonl`)

66 items, one JSON object per line: **16 `answer_accuracy`,
16 `citation_correctness`, 16 `safe_abstention`, 18 `multilingual_quality`**
(six questions x `en`/`hi`/`bn`). Topics cover patents, GI, trade marks,
designs, copyright, plant varieties, biodiversity/ABS, TKDL, formulation
classification (classical / proprietary / new drug / phytopharmaceutical /
Ayurveda-Aahar / cosmetic), the Drugs and Magic Remedies advertising rules,
TRIPS / CBD / Nagoya / PCT / Madrid / Hague / Budapest, and market access.

| key | type | meaning |
|---|---|---|
| `id` | str | unique id (`aa-001`, `cc-007`, `ab-010`, `ml-g1-hi`) |
| `category` | str | one of the four axes |
| `query` | str | the question, written in `language` |
| `language` | str | `en` / `hi` / `bn` - both the input and the requested output language |
| `jurisdiction_scope` | list | `["india"]`, `["international"]`, ...; `["international"]` alone relaxes the citation-jurisdiction rule |
| `must_cite` | bool | this question cannot be answered without a citation |
| `expected_topics` | list | topic tags (also used by the coverage test) |
| `forbidden_conclusions` | list | phrases that must never be asserted |
| `expect_abstain` | bool | true = the assistant **must** decline |
| `expected_answer_contains` | list | required substrings (`a|b` = either) |
| `expected_answer_not_contains` | list | substrings that must be absent |
| `rationale` | str | why the item is graded this way |
| `expected_citation_titles` | list (optional) | sources a correct answer must cite (matched against citation titles, `a|b` = either) |
| `language_group` | str (optional) | groups the `en`/`hi`/`bn` variants of one question |
| `requires_page` | bool (optional) | force a `page_number` on every citation for this item |

### Adding an item

1. Append one JSON line to `eval/dataset.jsonl` with **all** required keys.
2. For `safe_abstention`, `expect_abstain` must be `true` and
   `forbidden_conclusions` non-empty (assertion-shaped phrases such as
   `"will be granted"`, not bare words like `"grant"`).
3. For `multilingual_quality`, add the same question in all three languages
   under one `language_group`, or `validate_dataset` fails on group parity.
4. Run the structure check (fast, no model):

```bash
python scripts/evaluate.py --mode offline
```

`tests/test_evaluation.py` additionally enforces >= 10 items per category,
>= 60 total, unique ids, and topic coverage - keep those green.

---

## Running the evaluation

### Offline (default) - deterministic, no API key, no database, no network

```bash
cd IP-SHAKTI/BACKEND
python scripts/evaluate.py                # same as --mode offline
python scripts/evaluate.py --mode offline
```

With no stored results yet, offline mode **only validates the dataset
structure** and says so (`structure-only run`). Given results - via
`--results path/to/results.json`, or automatically picking the newest run in
`eval/results/` that contains records - it scores them with the four metrics.
Everything offline is a string/structure check: forbidden phrases, required
content, citation shape, language-field parity, fallback-warning honesty.

### Live - measures the real model through the real API

```bash
# prerequisites
export GROQ_API_KEY=...        # or set it in BACKEND/.env
uvicorn app.main:app --reload  # server must be reachable (default http://127.0.0.1:8000)

python scripts/evaluate.py --mode live
python scripts/evaluate.py --mode live --limit 5          # smoke run
python scripts/evaluate.py --mode live --categories safe_abstention
python scripts/evaluate.py --mode live --ids aa-001 ml-g1-hi --base-url http://127.0.0.1:8000
```

What live mode does per run:

1. **Fail fast** (exit `2`) when `GROQ_API_KEY` is missing
   (`--skip-key-check` skips the local check if the key exists only on the
   server) or when `GET {base}/api/docs` cannot be reached, with an
   actionable message.
2. Registers a throwaway evaluation account
   (`POST /api/auth/register` with `username`/`email`/`password`/
   `confirm_password`) and logs in (`POST /api/auth/login` ->
   `data.access_token`), reusing the project's standard JSON contract.
3. Sends one `POST /api/assistant/chat` per selected item with
   `{"message": <query>, "input_language": <lang>, "output_language": <lang>}`
   (plus `provider` when `--provider groq|sarvam` is given).
4. Stores each response (answer, `overall_status`, `insufficient_evidence`,
   `warnings`, `citations`, `language`) in `eval/results/<timestamp>.json`
   and prints the report.

**Exit codes:** `0` success - `1` invalid dataset or `--fail-under` missed -
`2` live environment problem (key/server/auth).

### Reading the report

```
  axis                     score  detail
  -----------------------  -----  ------------------------------------
  dataset_structure        1.00  66 items, 0 errors
  answer_accuracy          0.94  15/16 passed
  citation_correctness     0.94  P=0.94 R=0.94 F1=0.94; 1 invalid, 1 uncited
  safe_abstention          0.88  14/16 abstained; 2 false-confident
  multilingual_quality     0.94  parity=0.94 honesty=0.94 (18 items)

OVERALL: 0.94
```

* `OVERALL` is the mean of `dataset_structure` plus **every axis that had at
  least one scored item**. Axes the run did not cover show `-` and do not
  drag the mean.
* With no results at all, only `dataset_structure` contributes and the report
  is flagged `structure_only` - that score measures the **harness**, not the
  model.
* The run file written to `eval/results/<timestamp>.json` contains both
  `results` (the raw records, so any score can be re-derived) and `report`
  (the full per-item breakdown under `axes.<axis>.per_item`).
* `--fail-under 0.90` turns the run into a gate (exit `1` below the
  threshold) for CI use.

---

## Honest statement of what this measures

* **Offline mode measures structure and grounding of stored responses** -
  dataset integrity plus deterministic checks (forbidden phrases, required
  content, citation shape, language parity, fallback honesty) against
  responses someone already collected. It cannot measure the model: with no
  `results.json` it says `structure-only` and scores the harness itself.
* **Live mode measures the model** - the same deterministic checks applied to
  fresh answers produced by the real pipeline (BHASHINI -> retrieval -> LLM).
  It is still *not* an LLM judge: it verifies verifiable things (phrases,
  statuses, citation shape, scripts) and deliberately does not grade prose
  quality or subtle correctness that only a domain expert can judge. Items
  carry a `rationale` for human review of borderline cases.
* **Known limitations, stated plainly:**
  * `expected_answer_contains` is substring matching - phrase wording in the
    dataset must match plausible phrasings (use `a|b` alternatives);
  * retrieved-set membership of citations is only checked when a results file
    supplies `retrieved_chunk_ids` - the public chat API validates citations
    server-side and does not expose that set, so live mode relies on the
    server's own validation plus shape checks;
  * the uncertainty-cue window for `forbidden_conclusions` is a heuristic
    biased toward not failing honest refusals;
  * translation honesty assumes BHASHINI's warning wording; if that wording
    changes, update `FALLBACK_WARNING_MARKERS` in `eval/metrics.py`.
* A low score is information, not failure: the harness exists to find gaps
  (for example, a retrieval miss on a Section 3(p) question), so treat
  `per_item` details as a work list.

---

## Tests

```bash
pytest tests/test_evaluation.py -q     # 40 tests, no DB, no network
```

They cover: dataset keys/categories/ids/abstention guards/topic coverage,
multilingual group parity, validation of broken synthetic datasets, every
metric on a hand-built perfect example (overall = 1.0) and on failing cases
(missing content, invalid citation -> precision 0.5, false-confident answer,
dishonest translation fallback), and offline runner end-to-end runs on tiny
tmp fixtures (exit `0`, `--fail-under` gating, invalid dataset -> exit `1`).
