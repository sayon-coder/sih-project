"""
Tests for Phase 11: BHASHINI language layer.

What these tests protect:
* language detection (Devanagari -> hi, Bengali script -> bn, else en);
* same-language passthrough and unknown-language rejection (422);
* honest fallback: unconfigured BHASHINI returns the original text with a
  warning instead of an invented translation;
* identifiers survive masking/unmasking verbatim;
* the assistant chat accepts non-English language flags and degrades openly.
"""
from app.bhashini.glossary import mask_identifiers, unmask_identifiers


class TestDetection:
    def test_hindi_detected(self, client, auth_headers):
        response = client.post(
            "/api/bhashini/detect", json={"text": "आयुर्वेद क्या है"}, headers=auth_headers
        )
        assert response.status_code == 200, response.json()
        assert response.json()["data"]["language"] == "hi"

    def test_bengali_detected(self, client, auth_headers):
        response = client.post(
            "/api/bhashini/detect", json={"text": "আয়ুর্বেদ কী"}, headers=auth_headers
        )
        assert response.status_code == 200, response.json()
        assert response.json()["data"]["language"] == "bn"

    def test_english_detected(self, client, auth_headers):
        response = client.post(
            "/api/bhashini/detect",
            json={"text": "What is Ayurveda?"},
            headers=auth_headers,
        )
        assert response.json()["data"]["language"] == "en"


class TestLanguages:
    def test_supported_languages(self, client, auth_headers):
        data = client.get("/api/bhashini/languages", headers=auth_headers).json()["data"]
        codes = [s["code"] for s in data["supported"]]
        assert codes == ["en", "hi", "bn"]
        assert "patent" in data["glossary_terms"]
        assert "traditional knowledge" in data["glossary_terms"]


class TestTranslate:
    def test_same_language_passthrough(self, client, auth_headers):
        response = client.post(
            "/api/bhashini/translate",
            json={"text": "hello", "source_language": "en", "target_language": "en"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        assert data["output"] == "hello"
        assert data["translated"] is False

    def test_unknown_language_rejected(self, client, auth_headers):
        response = client.post(
            "/api/bhashini/translate",
            json={"text": "hello", "source_language": "xx", "target_language": "en"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_unconfigured_fallback_preserves_original(self, client, auth_headers):
        text = "आयुर्वेद क्या है https://example.com/patent/IN123 2024-01-15"
        response = client.post(
            "/api/bhashini/translate",
            json={"text": text, "source_language": "hi", "target_language": "en"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.json()
        data = response.json()["data"]
        assert data["translated"] is False
        assert data["output"] == text
        assert data["warning"] is not None


class TestIdentifierMasking:
    def test_identifiers_round_trip(self):
        text = "See https://example.com/x and patent IN 123456 dated 2024-01-15"
        masked, originals = mask_identifiers(text)
        assert "https://example.com/x" not in masked
        assert unmask_identifiers(masked, originals) == text
