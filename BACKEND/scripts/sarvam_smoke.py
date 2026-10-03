"""One working Sarvam AI API call — chat completion smoke test.

Per Sarvam's getting-started flow: initialise the client, make a chat
completion call with the sarvam-105b-conversations model, print the reply.

The key is read from the environment (.env via python-dotenv); it is never
hardcoded and never printed.

Run from BACKEND:  python scripts/sarvam_smoke.py
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()  # picks up BACKEND/.env

    api_key = (os.getenv("SARVAM_API_KEY") or "").strip()
    if not api_key:
        print("SARVAM_API_KEY is missing/empty in .env - paste it there first.")
        return 1

    from sarvamai import SarvamAI  # imported after the key check on purpose

    client = SarvamAI(api_subscription_key=api_key)
    response = client.chat.completions(
        model="sarvam-105b-conversations",
        messages=[
            {
                "role": "user",
                "content": "In one short sentence, what can you do for an Ayurveda IP research team?",
            }
        ],
        reasoning_effort=None,  # thinking off: keep the smoke call fast
    )

    reply = response.choices[0].message.content
    print("model: sarvam-105b-conversations")
    print("reply:", reply)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # show the failure honestly, key stays hidden
        print(f"FAILED: {type(exc).__name__}: {exc}")
        sys.exit(1)
