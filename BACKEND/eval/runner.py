"""
eval.runner
===========

Runs the IP-SAKTI Sahayak evaluation harness in one of two modes:

``--mode offline`` (default)
    Deterministic scoring.  Needs no API key, no database and no network.
    It either scores a stored ``results.json`` (``--results``, or the newest
    run in ``eval/results/``) with the four pure metrics, or - when no results
    exist yet - only validates the dataset structure and says so plainly.

``--mode live``
    Collects fresh responses from a running server (``POST /api/assistant/chat``
    after ``POST /api/auth/register`` + ``POST /api/auth/login``), stores them
    under ``eval/results/<timestamp>.json`` and scores them exactly like
    offline mode.  Fails fast with a clear message when ``GROQ_API_KEY`` is
    missing or the server is unreachable.

Exit codes: ``0`` success, ``1`` invalid dataset (or ``--fail-under`` missed),
``2`` live-mode environment problem (server unreachable / key missing / auth
failed).
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from eval import metrics  # noqa: E402  (path bootstrap above)

EVAL_DIR = BACKEND_DIR / "eval"
DEFAULT_DATASET = EVAL_DIR / "dataset.jsonl"
RESULTS_DIR = EVAL_DIR / "results"
DEFAULT_BASE_URL = os.environ.get("EVAL_BASE_URL", "http://127.0.0.1:8000")

# Columns of the printed summary table.
_AXIS_ORDER = (
    "dataset_structure",
    "answer_accuracy",
    "citation_correctness",
    "safe_abstention",
    "multilingual_quality",
)


class EvalEnvironmentError(RuntimeError):
    """Live mode cannot run (server unreachable, key missing, auth failed)."""


# -------------------------------------------------------
# Loading / storing
# -------------------------------------------------------

def load_dataset(path: Optional[os.PathLike] = None) -> List[Dict[str, Any]]:
    """Load the golden dataset from ``.jsonl`` (one object per line) or ``.json``."""
    dataset_path = Path(path) if path else DEFAULT_DATASET
    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset not found: {dataset_path}")
    text = dataset_path.read_text(encoding="utf-8")
    if dataset_path.suffix.lower() == ".json":
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError(f"{dataset_path}: expected a JSON array of items")
        return data
    items: List[Dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{dataset_path}:{line_number}: invalid JSON ({exc})") from exc
    return items


def _read_run_file(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"results": data}
    raise ValueError(f"{path}: expected a JSON object or array")


def find_results(path: Optional[os.PathLike] = None) -> Tuple[Optional[Path], List[Dict[str, Any]]]:
    """Resolve the stored results to score.

    With an explicit ``path`` it is always used.  Otherwise the newest run
    file in ``eval/results/`` that actually contains records wins; a
    structure-only run (empty ``results``) is skipped.
    """
    if path:
        explicit = Path(path)
        if not explicit.exists():
            raise FileNotFoundError(f"results file not found: {explicit}")
        payload = _read_run_file(explicit)
        return explicit, list(payload.get("results") or [])
    if not RESULTS_DIR.exists():
        return None, []
    for candidate in sorted(RESULTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            payload = _read_run_file(candidate)
        except (ValueError, OSError):
            continue
        records = payload.get("results")
        if isinstance(records, list) and records:
            return candidate, records
    return None, []


def filter_items(
    items: Sequence[Dict[str, Any]],
    categories: Optional[Sequence[str]] = None,
    ids: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Apply ``--categories`` / ``--ids`` / ``--limit`` to the dataset."""
    selected = list(items)
    if categories:
        wanted = set(categories)
        selected = [item for item in selected if item.get("category") in wanted]
    if ids:
        wanted_ids = {entry.strip() for entry in ids for entry in str(entry).split(",") if entry.strip()}
        selected = [item for item in selected if str(item.get("id")) in wanted_ids]
    if limit is not None:
        selected = selected[:limit]
    return selected


def write_run(
    report: Dict[str, Any],
    results: Sequence[Dict[str, Any]],
    mode: str,
    dataset_path: Path,
    results_source: Optional[Path],
    output: Optional[os.PathLike] = None,
) -> Path:
    """Persist one evaluation run (results + report) under ``eval/results/``."""
    destination = Path(output) if output else RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "eval_run",
        "mode": mode,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset_path": str(dataset_path),
        "results_path": str(results_source) if results_source else None,
        "results": list(results),
        "report": report,
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


# -------------------------------------------------------
# Live mode: HTTP against the running server
# -------------------------------------------------------

def _http(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 30.0,
) -> Tuple[Any, int]:
    """JSON request helper; returns ``(parsed_body, status_code)``.

    Connection-level failures (``URLError``, timeout) propagate to the caller
    so live mode can fail fast with a clear message.
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(base_url + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return _decode(raw), response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return _decode(raw) or {"detail": raw}, exc.code


def _decode(raw: str) -> Any:
    """Parse a JSON body; non-JSON bodies (for example /api/docs HTML) are kept as text."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def _require_api_key(skip_check: bool) -> None:
    if skip_check:
        return
    if not os.environ.get("GROQ_API_KEY"):
        raise EvalEnvironmentError(
            "GROQ_API_KEY is not set. The live assistant needs it to answer "
            "(the server reads the same variable from its .env). Export it, or "
            "pass --skip-key-check if the key is configured only server-side."
        )


def _require_server(base_url: str, timeout: float = 5.0) -> None:
    try:
        _http("GET", "/api/docs", base_url=base_url, timeout=timeout)
    except (urllib.error.URLError, OSError) as exc:
        raise EvalEnvironmentError(
            f"Server unreachable at {base_url}: {exc}. Start it with\n"
            f"    uvicorn app.main:app --reload\n"
            f"or point --base-url at the right host/port."
        ) from exc


def _authenticate(base_url: str) -> str:
    """Register a throwaway evaluation account and log in.

    Registration returns the user only; the bearer token comes from login
    (``data.access_token``), exactly like the rest of the project's scripts.
    """
    stamp = f"{int(time.time())}-{secrets.token_hex(3)}"
    username = f"eval-{stamp}"
    email = f"eval-{stamp}@example.com"
    password = f"Eval{secrets.token_hex(6)}a1!"
    _http(
        "POST",
        "/api/auth/register",
        {
            "username": username,
            "email": email,
            "password": password,
            "confirm_password": password,
        },
        base_url=base_url,
        timeout=30.0,
    )
    login, status = _http(
        "POST",
        "/api/auth/login",
        {"email": email, "password": password},
        base_url=base_url,
        timeout=30.0,
    )
    token = ((login or {}).get("data") or {}).get("access_token")
    if status != 200 or not token:
        raise EvalEnvironmentError(f"login failed for the evaluation account (HTTP {status}): {login}")
    return str(token)


def collect_live(
    items: Sequence[Dict[str, Any]],
    base_url: str,
    token: str,
    provider: Optional[str] = None,
    timeout: float = 120.0,
) -> List[Dict[str, Any]]:
    """Ask the real assistant one question per dataset item and store responses."""
    records: List[Dict[str, Any]] = []
    total = len(items)
    for position, item in enumerate(items, start=1):
        payload: Dict[str, Any] = {
            "message": item.get("query"),
            "input_language": item.get("language", "en"),
            "output_language": item.get("language", "en"),
        }
        if provider:
            payload["provider"] = provider
        started = time.monotonic()
        try:
            body, status = _http(
                "POST", "/api/assistant/chat", payload, token=token, base_url=base_url, timeout=timeout
            )
        except (urllib.error.URLError, OSError) as exc:
            records.append({"id": item.get("id"), "query": item.get("query"), "mode": "live", "error": str(exc)})
            print(f"[{position:3}/{total}] {item.get('id')}  ERROR {exc}")
            continue
        elapsed = time.monotonic() - started
        if status != 200 or not isinstance(body, dict) or "answer" not in body:
            detail = body.get("detail") if isinstance(body, dict) else body
            records.append(
                {
                    "id": item.get("id"),
                    "query": item.get("query"),
                    "mode": "live",
                    "error": f"HTTP {status}: {detail}",
                }
            )
            print(f"[{position:3}/{total}] {item.get('id')}  HTTP {status} ({elapsed:.1f}s)")
            continue
        records.append(
            {
                "id": item.get("id"),
                "query": item.get("query"),
                "language": item.get("language", "en"),
                "mode": "live",
                "response": {
                    "answer": body.get("answer") or "",
                    "overall_status": body.get("overall_status") or "",
                    "insufficient_evidence": bool(body.get("insufficient_evidence")),
                    "language": body.get("language") or "",
                    "warnings": body.get("warnings") or [],
                    "citations": body.get("citations") or [],
                    "provider": body.get("provider") or "",
                    "sections": [
                        {"topic": section.get("topic"), "status": section.get("status")}
                        for section in (body.get("sections") or [])
                        if isinstance(section, dict)
                    ],
                    # The API validates citations server-side and does not
                    # expose the retrieved chunk ids, so membership is only
                    # checked when a stored results file provides them.
                    "retrieved_chunk_ids": None,
                },
            }
        )
        print(f"[{position:3}/{total}] {item.get('id')}  ok ({elapsed:.1f}s)")
    return records


# -------------------------------------------------------
# Reporting
# -------------------------------------------------------

def _fmt(score: Optional[float]) -> str:
    return "-" if score is None else f"{score:.2f}"


def _axis_detail(name: str, report: Dict[str, Any]) -> str:
    axes = report.get("axes", {})
    if name == "dataset_structure":
        structure = report.get("dataset", {})
        return (
            f"{structure.get('total', 0)} items, {len(structure.get('errors', []))} errors"
        )
    axis = axes.get(name, {})
    if not axis.get("scored_items"):
        return axis.get("note") or f"no results for {name} items"
    if name == "answer_accuracy":
        passed = sum(1 for item in axis.get("per_item", []) if item.get("passed"))
        return f"{passed}/{axis.get('scored_items')} passed"
    if name == "citation_correctness":
        return (
            f"P={axis['precision']:.2f} R={axis['recall']:.2f} F1={axis['f1']:.2f}; "
            f"{axis['invalid_citations']} invalid, {axis['uncited_claims']} uncited"
        )
    if name == "safe_abstention":
        return (
            f"{axis['correct_abstentions']}/{axis['scored_items']} abstained; "
            f"{axis['false_confident_answers']} false-confident"
        )
    return (
        f"parity={axis['language_parity']:.2f} honesty={axis['translation_honesty']:.2f} "
        f"({axis['scored_items']} items)"
    )


def print_report(
    report: Dict[str, Any],
    dataset_path: Path,
    results_source: Optional[Path],
    run_path: Path,
    file=None,
) -> None:
    """Print the human-readable summary table; the last line is ``OVERALL: x.xx``."""
    out = file or sys.stdout
    structure = report.get("dataset", {})
    counts = structure.get("counts", {})
    separator = "=" * 74

    print(separator, file=out)
    print(" IP-SAKTI Sahayak - evaluation report", file=out)
    print(separator, file=out)
    print(f"Mode      : {report.get('mode', 'offline')}", file=out)
    print(f"Dataset   : {dataset_path} ({structure.get('total', 0)} items)", file=out)
    print(
        f"Structure : {'PASS' if structure.get('passed') else 'FAIL'} "
        f"({len(structure.get('errors', []))} errors)",
        file=out,
    )
    if report.get("results_count", 0):
        if results_source:
            print(f"Results   : {results_source} ({report['results_count']} records)", file=out)
        else:
            print(f"Results   : collected live this run ({report['results_count']} records)", file=out)
    else:
        print("Results   : none (structure-only run - the model is not scored)", file=out)

    print("", file=out)
    width = max(len(name) for name in counts) if counts else 10
    print(f"  {'category'.ljust(width)}  items", file=out)
    print(f"  {'-' * width}  -----", file=out)
    for name in metrics.CATEGORIES:
        print(f"  {name.ljust(width)}  {counts.get(name, 0):>5}", file=out)

    print("", file=out)
    print(f"  {'axis'.ljust(23)}  score  detail", file=out)
    print(f"  {'-' * 23}  -----  {'-' * 36}", file=out)
    sections = report.get("section_scores", {})
    for name in _AXIS_ORDER:
        score = sections.get(name)
        detail = _axis_detail(name, report)
        print(f"  {name.ljust(23)}  {_fmt(score)}  {detail}", file=out)

    if report.get("structure_only"):
        print("", file=out)
        print(
            "  Note: structure-only run - no stored results were found, so this run\n"
            "  only validates the harness, not the model. Produce results with:\n"
            "      python scripts/evaluate.py --mode live",
            file=out,
        )

    print("", file=out)
    print(f"Report written to {run_path}", file=out)
    print("", file=out)
    print(f"OVERALL: {report.get('overall', 0.0):.2f}", file=out)


# -------------------------------------------------------
# CLI
# -------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/evaluate.py",
        description="Evaluate the IP-SAKTI Sahayak assistant on answer accuracy, "
        "citation correctness, safe abstention and multilingual quality.",
    )
    parser.add_argument(
        "--mode",
        choices=("offline", "live"),
        default="offline",
        help="offline = deterministic scoring of stored results (default, no API key); "
        "live = query the running server, then score",
    )
    parser.add_argument("--dataset", help="path to the golden dataset (.jsonl or .json)")
    parser.add_argument(
        "--results",
        help="results file to score in offline mode (default: newest run in eval/results/)",
    )
    parser.add_argument("--output", help="where to write the run/report JSON (default: eval/results/<timestamp>.json)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"server base URL for live mode (default {DEFAULT_BASE_URL})")
    parser.add_argument("--provider", choices=("groq", "sarvam"), help="answering LLM for live mode")
    parser.add_argument("--categories", nargs="+", choices=list(metrics.CATEGORIES), help="score only these categories")
    parser.add_argument("--ids", nargs="+", help="score only these dataset ids")
    parser.add_argument("--limit", type=int, help="score/ask only the first N selected items")
    parser.add_argument("--timeout", type=float, default=120.0, help="per-request timeout in live mode (seconds)")
    parser.add_argument("--skip-key-check", action="store_true", help="live mode: skip the local GROQ_API_KEY check")
    parser.add_argument("--fail-under", type=float, help="exit 1 when OVERALL is below this value (0-1)")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    dataset_path = Path(args.dataset) if args.dataset else DEFAULT_DATASET
    try:
        items = load_dataset(dataset_path)
    except (OSError, ValueError) as exc:
        print(f"[FAIL] cannot load dataset: {exc}", file=sys.stderr)
        return 1

    # Structure is always validated on the full dataset, even when scoring a subset.
    structure = metrics.validate_dataset(items)
    if not structure["passed"]:
        print(f"[FAIL] dataset structure invalid ({len(structure['errors'])} errors):", file=sys.stderr)
        for error in structure["errors"][:20]:
            print(f"       - {error}", file=sys.stderr)
        return 1

    results_source: Optional[Path]
    results: List[Dict[str, Any]]
    if args.mode == "live":
        try:
            _require_api_key(args.skip_key_check)
            _require_server(args.base_url)
            token = _authenticate(args.base_url)
        except EvalEnvironmentError as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 2
        selected = filter_items(items, args.categories, args.ids, args.limit)
        print(f"Live evaluation: {len(selected)} items against {args.base_url}")
        results = collect_live(selected, args.base_url, token, provider=args.provider, timeout=args.timeout)
        results_source = None
    else:
        try:
            results_source, results = find_results(args.results)
        except (OSError, ValueError) as exc:
            print(f"[FAIL] cannot load results: {exc}", file=sys.stderr)
            return 1

    scored_items = filter_items(items, args.categories, args.ids, args.limit)
    report = metrics.aggregate(scored_items, results, mode=args.mode, structure=structure)
    run_path = write_run(report, results, args.mode, dataset_path, results_source, args.output)
    print_report(report, dataset_path, results_source, run_path)

    if args.fail_under is not None and report.get("overall", 0.0) < args.fail_under:
        print(
            f"[FAIL] OVERALL {report.get('overall', 0.0):.2f} is below --fail-under {args.fail_under:.2f}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via scripts/evaluate.py
    sys.exit(main())
