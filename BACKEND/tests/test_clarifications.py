"""
Clarifying questions - the interactive classification loop.

``GET .../clarification-questions`` must ask the minimum deterministic
questions (spec order, genuine gaps only); answers round-trip per
(version, question); recording an answer never edits version content;
version scoping and auth match the rest of the version-content API.
"""
import uuid

from tests.test_chat_jurisdiction import make_product


def _bare_product(client, headers):
    r = client.post(
        "/api/products",
        json={"name": f"Clarify-{uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    return data["id"], data["current_version_id"]


def _questions(client, headers, pid, vid):
    r = client.get(
        f"/api/products/{pid}/versions/{vid}/clarification-questions",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _answer(client, headers, pid, vid, key, text="Recorded in the passport."):
    return client.post(
        f"/api/products/{pid}/versions/{vid}/clarifications",
        json={"question_key": key, "answer": text},
        headers=headers,
    )


def test_empty_version_asks_everything_in_order(client, auth_headers):
    pid, vid = _bare_product(client, auth_headers)
    body = _questions(client, auth_headers, pid, vid)
    keys = [q["question_key"] for q in body["questions"]]
    # No claims recorded: "claim substantiation" correctly stays silent
    # (nothing to substantiate yet); "intended claims" asks instead.
    assert keys == [
        "product_category",
        "dosage_form",
        "manufacturing_licensing",
        "complete_formulation",
        "safety_quality_evidence",
        "final_label",
        "intended_claims",
        "ingredient_list",
    ]
    assert body["answered"] == 0
    for q in body["questions"]:
        assert q["question_text"]
        assert q["destination"]["section"] in {
            "analysis", "formulation", "evidence", "claims", "ingredients",
        }
        assert q["answered"] is False


def test_questions_shrink_as_content_arrives(client, auth_headers):
    pid, vid = make_product(
        client,
        auth_headers,
        claims=["Supports joint mobility."],
        with_formulation=True,
    )
    body = _questions(client, auth_headers, pid, vid)
    keys = {q["question_key"] for q in body["questions"]}
    # Ingredients and claims now exist: presence checks stay silent.
    assert "intended_claims" not in keys
    assert "ingredient_list" not in keys
    # A recorded claim needs substantiation: its question appears.
    assert "claim_substantiation" in keys


def test_answer_roundtrip_and_update(client, auth_headers):
    pid, vid = _bare_product(client, auth_headers)
    r = _answer(client, auth_headers, pid, vid, "dosage_form", "Tablets, 500 mg.")
    assert r.status_code == 201, r.text

    body = _questions(client, auth_headers, pid, vid)
    assert body["answered"] == 1
    asked = {q["question_key"]: q for q in body["questions"]}
    assert asked["dosage_form"]["answered"] is True
    assert asked["dosage_form"]["answer"] == "Tablets, 500 mg."

    listed = client.get(
        f"/api/products/{pid}/versions/{vid}/clarifications",
        headers=auth_headers,
    ).json()["data"]
    assert listed["count"] == 1

    # Answering again updates the same row instead of duplicating it.
    r2 = _answer(client, auth_headers, pid, vid, "dosage_form", "Capsules.")
    assert r2.status_code == 201, r2.text
    listed2 = client.get(
        f"/api/products/{pid}/versions/{vid}/clarifications",
        headers=auth_headers,
    ).json()["data"]
    assert listed2["count"] == 1
    assert listed2["answers"][0]["answer"] == "Capsules."


def test_unknown_key_and_empty_answer_rejected(client, auth_headers):
    pid, vid = _bare_product(client, auth_headers)
    assert _answer(client, auth_headers, pid, vid, "nope", "x").status_code == 404
    assert _answer(client, auth_headers, pid, vid, "dosage_form", "  ").status_code == 422


def test_answers_never_edit_version_content(client, auth_headers):
    pid, vid = _bare_product(client, auth_headers)
    def _hash():
        body = client.get(f"/api/products/{pid}/passport", headers=auth_headers).json()
        return body["data"]["current_version"]["content_hash"]

    before = _hash()
    assert _answer(client, auth_headers, pid, vid, "dosage_form", "Syrup.").status_code == 201
    assert _hash() == before


def test_version_scoping_and_auth(
    client, auth_headers, second_user_headers
):
    pid, vid = _bare_product(client, auth_headers)
    other_pid, _ = _bare_product(client, second_user_headers)

    # Another user's product through my product id: 404, never 403/200.
    forbidden = client.get(
        f"/api/products/{pid}/versions/{vid}/clarification-questions",
        headers=second_user_headers,
    )
    assert forbidden.status_code == 404

    # A version id from another product: 404.
    mismatch = client.post(
        f"/api/products/{other_pid}/versions/{vid}/clarifications",
        json={"question_key": "dosage_form", "answer": "x"},
        headers=second_user_headers,
    )
    assert mismatch.status_code == 404

    # No token anywhere: 401.
    assert client.get(
        f"/api/products/{pid}/versions/{vid}/clarification-questions"
    ).status_code == 401
    assert client.post(
        f"/api/products/{pid}/versions/{vid}/clarifications",
        json={"question_key": "dosage_form", "answer": "x"},
    ).status_code == 401
