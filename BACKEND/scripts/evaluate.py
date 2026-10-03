"""
scripts/evaluate.py

CLI entry point for the IP-SAKTI Sahayak evaluation harness (BACKEND/eval).

The harness scores the assistant on the four axes the SIH problem statement
requires: answer accuracy, citation correctness, safe abstention on
out-of-scope or uncertain queries, and multilingual quality.  See
BACKEND/EVALUATION.md for the full guide.

Usage:

    python scripts/evaluate.py                     # offline (default): structure + stored results
    python scripts/evaluate.py --mode offline      # same, explicit
    python scripts/evaluate.py --mode live         # query the running server, then score
    python scripts/evaluate.py --mode live --limit 5
    python scripts/evaluate.py --results path/to/results.json

Offline mode needs no API key, no database and no network.  Live mode needs a
running server (uvicorn app.main:app) and GROQ_API_KEY; it fails fast with a
clear message when either is missing.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from eval.runner import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
