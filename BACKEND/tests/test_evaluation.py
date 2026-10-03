"""
Tests for the evaluation harness (BACKEND/eval).

The harness itself must be trustworthy before anyone trusts its scores, so
these tests cover the dataset's integrity, the metrics (hand-built synthetic
result records - no LLM, no model output guessing) and an end-to-end offline
run.  Deliberately no database and no network: everything here works against
plain Python objects and tmp files.
"""
import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from eval import metrics, runner  # noqa: E402

# Topic areas the SIH problem statement expects the questions to cover.
REQUIRED_TOPIC_AREAS = {
    "patent",
    "gi",
    "trade_mark",
    "design",
    "copyright",
    "plant_varieties",
    "biodiversity_abs",
    "tkdl",
    "formulation_classification",
    "advertising",
    "market_access",
    "trips",
    "nagoya",
    "pct",
    "madrid",
    "hague",
    "budapest",
}


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def _dataset_item(item_id, category, **overrides):
    """A structurally valid dataset item of any category."""
    item = {
        "id": item_id,
        "category": category,
        "query": "What is the term of protection?",
        "language": "en",
        "jurisdiction_scope": ["india"],
        "must_cite": False,
        "expected_topics": ["patent"],
        "forbidden_conclusions": [],
        "expect_abstain": category == "safe_abstention",
        "expected_answer_contains": [],
        "expected_answer_not_contains": [],
        "rationale": "Synthetic fixture used by the metrics tests.",
    }
    item.update(overrides)
    return item


def _result(item_id, **response):
    """A stored result record with sane defaults filled in."""
    payload = {
        "answer": "",
        "overall_status": "SUPPORTED",
        "insufficient_evidence": False,
        "language": "en",
        "warnings": [],
        "citations": [],
    }
    payload.update(response)
    return {"id": item_id, "response": payload}


@pytest.fixture(scope="module")
def dataset():
    return runner.load_dataset()


# -------------------------------------------------------
# Dataset integrity
# -------------------------------------------------------

class TestDatasetIntegrity:
    def test_every_item_has_all_required_keys(self, dataset):
        for item in dataset:
            missing = [key for key in metrics.REQUIRED_KEYS if key not in item]
            assert not missing, f"{item.get('id')}: missing keys {missing}"

    def test_every_item_has_a_valid_category(self, dataset):
        for item in dataset:
            assert item["category"] in metrics.CATEGORIES, item["id"]

    def test_every_item_has_a_valid_language(self, dataset):
        for item in dataset:
            assert item["language"] in metrics.LANGUAGES, item["id"]

    def test_all_four_categories_have_at_least_ten_items(self, dataset):
        counts = {category: 0 for category in metrics.CATEGORIES}
        for item in dataset:
            counts[item["category"]] += 1
        for category in metrics.CATEGORIES:
            assert counts[category] >= 10, f"{category}: only {counts[category]} items"

    def test_dataset_is_large_enough(self, dataset):
        assert len(dataset) >= 60

    def test_no_duplicate_ids(self, dataset):
        ids = [item["id"] for item in dataset]
        duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
        assert duplicates == []

    def test_abstention_items_have_forbidden_conclusions(self, dataset):
        for item in dataset:
            if item["category"] == "safe_abstention":
                assert item["expect_abstain"] is True, item["id"]
                assert item["forbidden_conclusions"], item["id"]
                assert all(str(entry).strip() for entry in item["forbidden_conclusions"]), item["id"]

    def test_abstention_items_are_not_also_answer_items(self, dataset):
        for item in dataset:
            if item["expect_abstain"]:
                assert item["expected_answer_contains"] == [], item["id"]

    def test_multilingual_groups_cover_all_three_languages(self, dataset):
        groups = {}
        for item in dataset:
            group = item.get("language_group")
            if group:
                groups.setdefault(group, set()).add(item["language"])
        assert groups, "expected language groups in the multilingual category"
        for group, languages in groups.items():
            assert set(metrics.LANGUAGES) <= languages, f"{group}: {languages}"

    def test_required_topic_areas_are_covered(self, dataset):
        topics = {topic for item in dataset for topic in item.get("expected_topics", [])}
        missing = REQUIRED_TOPIC_AREAS - topics
        assert not missing, f"dataset does not cover: {sorted(missing)}"

    def test_structure_validation_passes(self, dataset):
        report = metrics.validate_dataset(dataset)
        assert report["passed"] is True, report["errors"]


# -------------------------------------------------------
# Dataset validation on synthetic (broken) data
# -------------------------------------------------------

class TestDatasetValidation:
    def test_flags_duplicate_ids_bad_category_and_missing_abstention_guard(self):
        items = [
            _dataset_item("dup-1", "answer_accuracy"),
            _dataset_item("dup-1", "answer_accuracy"),
            _dataset_item("bad-cat", "hallucinated_category"),
            _dataset_item("ab-no-guard", "safe_abstention", forbidden_conclusions=[]),
        ]
        report = metrics.validate_dataset(items)
        assert report["passed"] is False
        joined = "\n".join(report["errors"])
        assert "duplicate id" in joined
        assert "invalid category" in joined
        assert "forbidden_conclusions" in joined

    def test_flags_incomplete_language_group(self):
        items = [
            _dataset_item("ml-1", "multilingual_quality", language="en", language_group="g1"),
            _dataset_item("ml-2", "multilingual_quality", language="hi", language_group="g1"),
        ]
        report = metrics.validate_dataset(items)
        assert report["passed"] is False
        assert any("missing languages: bn" in error for error in report["errors"])

    def test_empty_dataset_fails(self):
        assert metrics.validate_dataset([])["passed"] is False


# -------------------------------------------------------
# Synthetic perfect example: every axis at 1.0
# -------------------------------------------------------

def _perfect_fixture():
    items = [
        _dataset_item(
            "aa-perfect",
            "answer_accuracy",
            expected_answer_contains=["Section 3(p)"],
            expected_answer_not_contains=["government approval"],
            forbidden_conclusions=["is patentable"],
        ),
        _dataset_item(
            "cc-perfect",
            "citation_correctness",
            must_cite=True,
            expected_citation_titles=["Patents Act"],
        ),
        _dataset_item(
            "ab-perfect",
            "safe_abstention",
            expect_abstain=True,
            forbidden_conclusions=["will be granted"],
        ),
        _dataset_item(
            "ml-perfect",
            "multilingual_quality",
            language="hi",
            expected_answer_contains=[],
        ),
    ]
    results = [
        _result(
            "aa-perfect",
            answer="Section 3(p) of the Patents Act excludes traditional knowledge "
            "from the patenting process.",
        ),
        _result(
            "cc-perfect",
            answer="Section 3(p) is explained by the Patents Act, 1970.",
            citations=[
                {
                    "chunk_id": 1,
                    "title": "Patents Act, 1970",
                    "jurisdiction": "India",
                    "page_number": 4,
                    "relevant_text": "Section 3(p) excludes traditional knowledge.",
                }
            ],
            retrieved_chunk_ids=[1],
        ),
        _result(
            "ab-perfect",
            answer="The retrieved sources do not establish whether the application "
            "will be granted; a patent examiner decides that.",
            overall_status="INSUFFICIENT_EVIDENCE",
            insufficient_evidence=True,
        ),
        _result(
            "ml-perfect",
            answer="भौगोलिक संकेत के लिए भारत में पंजीकरण आवेदन के माध्यम से होता है।",
            language="hi",
        ),
    ]
    return items, results


class TestMetricsOnPerfectExample:
    def test_answer_accuracy_is_perfect(self):
        items, results = _perfect_fixture()
        report = metrics.score_answer_accuracy(items, results)
        assert report["score"] == 1.0
        assert report["passed"] is True
        assert report["scored_items"] == 1

    def test_citation_precision_recall_are_perfect(self):
        items, results = _perfect_fixture()
        report = metrics.score_citation_correctness(items, results)
        assert report["precision"] == 1.0
        assert report["recall"] == 1.0
        assert report["f1"] == 1.0
        assert report["invalid_citations"] == 0
        assert report["uncited_claims"] == 0

    def test_safe_abstention_rate_is_perfect(self):
        items, results = _perfect_fixture()
        report = metrics.score_safe_abstention(items, results)
        assert report["correct_abstentions"] == 1
        assert report["false_confident_answers"] == 0
        assert report["rate"] == 1.0

    def test_multilingual_quality_is_perfect(self):
        items, results = _perfect_fixture()
        report = metrics.score_multilingual_quality(items, results)
        assert report["language_parity"] == 1.0
        assert report["translation_honesty"] == 1.0
        assert report["score"] == 1.0

    def test_aggregate_overall_is_one(self):
        items, results = _perfect_fixture()
        report = metrics.aggregate(items, results, mode="offline")
        assert report["structure_only"] is False
        assert set(report["section_scores"]) == {
            "dataset_structure",
            "answer_accuracy",
            "citation_correctness",
            "safe_abstention",
            "multilingual_quality",
        }
        assert report["overall"] == 1.0


# -------------------------------------------------------
# Failing synthetic cases
# -------------------------------------------------------

class TestAnswerAccuracyFailures:
    def _item(self):
        return _dataset_item(
            "aa-x",
            "answer_accuracy",
            expected_answer_contains=["Section 3(p)"],
            expected_answer_not_contains=["government approval"],
            forbidden_conclusions=["is patentable"],
        )

    def test_missing_expected_content_fails(self):
        report = metrics.score_answer_accuracy(
            [self._item()], [_result("aa-x", answer="Traditional knowledge is excluded.")]
        )
        assert report["passed"] is False
        assert report["score"] == 0.0
        assert report["per_item"][0]["missing"] == ["Section 3(p)"]
        assert "missing_expected_content" in report["per_item"][0]["reasons"]

    def test_forbidden_content_in_not_contains_fails(self):
        report = metrics.score_answer_accuracy(
            [self._item()],
            [_result("aa-x", answer="Section 3(p) applies; government approval decides.")],
        )
        assert report["passed"] is False
        assert report["per_item"][0]["unexpected"] == ["government approval"]

    def test_asserted_forbidden_conclusion_fails(self):
        report = metrics.score_answer_accuracy(
            [self._item()],
            [_result("aa-x", answer="Section 3(p) exists, and your formulation is patentable in India.")],
        )
        assert report["passed"] is False
        assert report["per_item"][0]["forbidden_found"] == ["is patentable"]

    def test_uncertainty_cued_mention_is_not_a_violation(self):
        """A refusal may repeat the banned wording - the negation window allows it."""
        report = metrics.score_answer_accuracy(
            [self._item()],
            [_result(
                "aa-x",
                answer="Section 3(p) applies, but whether the formulation is patentable "
                "cannot be concluded from the sources.",
            )],
        )
        assert report["passed"] is True, report["per_item"][0]

    def test_item_without_result_is_unscored_not_passed(self):
        report = metrics.score_answer_accuracy([self._item()], [])
        assert report["scored_items"] == 0
        assert report["unscored"] == 1
        assert report["passed"] is False


class TestCitationCorrectnessFailures:
    def _item(self):
        return _dataset_item(
            "cc-x",
            "citation_correctness",
            must_cite=True,
            expected_citation_titles=["Patents Act"],
        )

    def test_invalid_citation_halves_precision(self):
        results = [_result(
            "cc-x",
            answer="The Patents Act, 1970 explains the bar.",
            citations=[
                {"chunk_id": 1, "title": "Patents Act, 1970", "jurisdiction": "India", "relevant_text": "s.3(p)"},
                {"chunk_id": 999, "title": "Hallucinated Gazette", "jurisdiction": "India", "relevant_text": "made up"},
            ],
            retrieved_chunk_ids=[1],
        )]
        report = metrics.score_citation_correctness([self._item()], results)
        assert report["precision"] == 0.5
        assert report["recall"] == 1.0
        assert report["f1"] == pytest.approx(2 / 3, abs=1e-3)
        assert report["invalid_citations"] == 1
        assert report["uncited_claims"] == 0
        assert report["per_item"][0]["invalid_details"][0]["issues"] == ["not_in_retrieved_set"]

    def test_missing_title_and_jurisdiction_are_invalid(self):
        results = [_result(
            "cc-x",
            answer="A claim.",
            citations=[{"chunk_id": 1, "title": "  ", "jurisdiction": None, "relevant_text": ""}],
        )]
        report = metrics.score_citation_correctness([self._item()], results)
        assert report["invalid_citations"] == 1
        assert report["precision"] == 0.0
        assert set(report["per_item"][0]["invalid_details"][0]["issues"]) == {
            "missing_title",
            "missing_jurisdiction",
            "missing_location",
        }

    def test_citing_nothing_scores_zero_and_counts_uncited_claims(self):
        results = [_result("cc-x", answer="The statute says so.")]
        report = metrics.score_citation_correctness([self._item()], results)
        assert report["precision"] == 0.0
        assert report["recall"] == 0.0
        assert report["f1"] == 0.0
        # one unmatched expected title + one penalty for a must-cite answer with no citation
        assert report["uncited_claims"] == 2

    def test_expected_source_not_cited_hurts_recall(self):
        results = [_result(
            "cc-x",
            answer="See this unrelated source.",
            citations=[{"chunk_id": 1, "title": "Copyright Act, 1957", "jurisdiction": "India", "relevant_text": "s.14"}],
        )]
        report = metrics.score_citation_correctness([self._item()], results)
        assert report["recall"] == 0.0
        assert report["uncited_claims"] == 1


class TestSafeAbstentionFailures:
    def _item(self):
        return _dataset_item(
            "ab-x",
            "safe_abstention",
            expect_abstain=True,
            forbidden_conclusions=["will be granted"],
        )

    def test_confident_answer_is_a_false_confident_answer(self):
        report = metrics.score_safe_abstention(
            [self._item()], [_result("ab-x", answer="Yes, go ahead and file today.")]
        )
        assert report["correct_abstentions"] == 0
        assert report["false_confident_answers"] == 1
        assert report["rate"] == 0.0

    def test_status_based_abstention_counts(self):
        report = metrics.score_safe_abstention(
            [self._item()],
            [_result(
                "ab-x",
                answer="I cannot predict the outcome of the examination.",
                overall_status="INSUFFICIENT_EVIDENCE",
                insufficient_evidence=True,
            )],
        )
        assert report["correct_abstentions"] == 1
        assert report["rate"] == 1.0

    def test_abstaining_status_that_still_asserts_a_conclusion_fails(self):
        report = metrics.score_safe_abstention(
            [self._item()],
            [_result(
                "ab-x",
                answer="The application will be granted once examined.",
                overall_status="INSUFFICIENT_EVIDENCE",
            )],
        )
        assert report["false_confident_answers"] == 1

    def test_over_abstention_is_reported_for_answerable_items(self):
        item = _dataset_item("aa-y", "answer_accuracy")
        report = metrics.score_safe_abstention(
            [item],
            [_result("aa-y", answer="I cannot provide that; insufficient evidence.", overall_status="SUPPORTED")],
        )
        assert report["unnecessary_abstentions"] == 1


class TestMultilingualQualityFailures:
    def _item(self):
        return _dataset_item("ml-x", "multilingual_quality", language="hi")

    def test_language_mismatch_without_warning_is_dishonest(self):
        report = metrics.score_multilingual_quality(
            [self._item()],
            [_result("ml-x", answer="A purely English answer.", language="en")],
        )
        assert report["language_parity"] == 0.0
        assert report["translation_honesty"] == 0.0
        assert report["score"] == 0.0

    def test_language_mismatch_with_honest_fallback_warning_keeps_honesty(self):
        warning = (
            "BHASHINI translation is unavailable, so the original text is preserved. "
            "English is used as a fallback where shown."
        )
        report = metrics.score_multilingual_quality(
            [self._item()],
            [_result("ml-x", answer="English fallback answer.", language="en", warnings=[warning])],
        )
        assert report["language_parity"] == 0.0
        assert report["translation_honesty"] == 1.0
        assert report["score"] == 0.5

    def test_claiming_a_language_without_its_script_is_dishonest(self):
        report = metrics.score_multilingual_quality(
            [self._item()],
            [_result("ml-x", answer="No Devanagari anywhere in this answer.", language="hi")],
        )
        assert report["language_parity"] == 1.0
        assert report["translation_honesty"] == 0.0
        assert report["score"] == 0.5


# -------------------------------------------------------
# Offline runner end-to-end
# -------------------------------------------------------

class TestOfflineRunner:
    def _write_fixture(self, tmp_path):
        items, results = _perfect_fixture()
        dataset_path = tmp_path / "dataset.jsonl"
        dataset_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n",
            encoding="utf-8",
        )
        results_path = tmp_path / "results.json"
        results_path.write_text(
            json.dumps({"kind": "eval_run", "mode": "offline", "results": results}, ensure_ascii=False),
            encoding="utf-8",
        )
        return dataset_path, results_path

    def test_offline_run_exits_zero_on_tiny_fixture(self, tmp_path, capsys):
        dataset_path, results_path = self._write_fixture(tmp_path)
        output_path = tmp_path / "report.json"

        code = runner.main(
            [
                "--mode", "offline",
                "--dataset", str(dataset_path),
                "--results", str(results_path),
                "--output", str(output_path),
            ]
        )
        assert code == 0

        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload["kind"] == "eval_run"
        assert payload["report"]["overall"] == 1.0
        assert len(payload["results"]) == 4

        stdout = capsys.readouterr().out
        assert "OVERALL: 1.00" in stdout
        assert "answer_accuracy" in stdout

    def test_offline_run_without_results_is_structure_only(self, tmp_path, capsys):
        items, _ = _perfect_fixture()
        dataset_path = tmp_path / "dataset.jsonl"
        dataset_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n",
            encoding="utf-8",
        )
        results_path = tmp_path / "empty.json"
        results_path.write_text(json.dumps({"kind": "eval_run", "results": []}), encoding="utf-8")

        code = runner.main(
            [
                "--mode", "offline",
                "--dataset", str(dataset_path),
                "--results", str(results_path),
                "--output", str(tmp_path / "report.json"),
            ]
        )
        assert code == 0
        stdout = capsys.readouterr().out
        assert "structure-only" in stdout
        assert "OVERALL: 1.00" in stdout

    def test_offline_run_fails_on_an_invalid_dataset(self, tmp_path, capsys):
        items = [
            _dataset_item("dup", "answer_accuracy"),
            _dataset_item("dup", "answer_accuracy"),
        ]
        dataset_path = tmp_path / "dataset.jsonl"
        dataset_path.write_text(
            "\n".join(json.dumps(item) for item in items) + "\n", encoding="utf-8"
        )

        code = runner.main(["--mode", "offline", "--dataset", str(dataset_path),
                            "--output", str(tmp_path / "report.json")])
        assert code == 1
        assert "duplicate id" in capsys.readouterr().err

    def test_fail_under_threshold_gates_the_exit_code(self, tmp_path, capsys):
        dataset_path, results_path = self._write_fixture(tmp_path)
        code = runner.main(
            [
                "--mode", "offline",
                "--dataset", str(dataset_path),
                "--results", str(results_path),
                "--output", str(tmp_path / "report.json"),
                "--fail-under", "1.5",
            ]
        )
        assert code == 1
        assert "below --fail-under" in capsys.readouterr().err

    def test_filtering_by_category_and_limit(self, tmp_path, capsys):
        dataset_path, results_path = self._write_fixture(tmp_path)
        code = runner.main(
            [
                "--mode", "offline",
                "--dataset", str(dataset_path),
                "--results", str(results_path),
                "--output", str(tmp_path / "report.json"),
                "--categories", "citation_correctness",
                "--limit", "1",
            ]
        )
        assert code == 0
        payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
        # Only the citation axis is scored, so only it joins the overall mean.
        assert set(payload["report"]["section_scores"]) == {"dataset_structure", "citation_correctness"}
