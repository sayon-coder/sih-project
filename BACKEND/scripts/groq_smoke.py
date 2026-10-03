"""Quick GROQ key verification: one short chat completion, print the reply.

The key is read from the environment (.env via python-dotenv); never printed.
Run from BACKEND:  python scripts/groq_smoke.py
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()

    api_key = (os.getenv("GROQ_API_KEY") or "").strip()
    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    model = (os.getenv("LLM_MODEL") or "").strip()

    if not api_key:
        print("GROQ_API_KEY is missing/empty in .env")
        return 1
    if provider != "groq":
        print(f"LLM_PROVIDER is '{provider}', not 'groq' - skipping Groq check.")
        return 0

    import httpx

    resp = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "max_tokens": 200,
        },
        timeout=45,
    )
    print("status:", resp.status_code)
    if resp.status_code != 200:
        body = resp.text
        print("error body:", body[:400])
        return 1
    data = resp.json()
    print("model:", data.get("model", model))
    print("reply:", data["choices"][0]["message"]["content"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
