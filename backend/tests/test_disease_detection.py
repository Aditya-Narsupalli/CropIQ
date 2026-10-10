import io

from PIL import Image

from app.api.endpoints.disease import _identification
from app.services import disease_classifier
from app.services.kcc_archive import _disease_keywords


def _jpeg(color=(60, 140, 60)):
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), color).save(buf, "JPEG")
    return buf.getvalue()


def test_classifier_runs_for_enabled_crop_and_restricts_to_that_crop():
    result = disease_classifier.classify(_jpeg(), "rice")
    assert result is not None
    assert result["crop"] == "Rice"
    assert abs(sum(p["probability"] for p in result["top_predictions"]) - 1) < 0.05 or len(result["possible_diseases"]) > 3
    assert all(p["disease"] in result["possible_diseases"] for p in result["top_predictions"])


def test_classifier_skips_crops_below_accuracy_bar_or_not_covered():
    # Tomato/potato are in the training data but below the deploy accuracy bar;
    # wheat isn't covered at all - both are left to Gemini.
    assert disease_classifier.classify(_jpeg(), "tomato") is None
    assert disease_classifier.classify(_jpeg(), "wheat") is None


def test_identification_line_is_parsed_from_gemini_reply():
    assert _identification("IDENTIFICATION: Early Blight\n1. ...") == "Early Blight"
    assert _identification("**IDENTIFICATION:** Late blight (Phytophthora infestans)\n") == "Late blight (Phytophthora infestans)"
    assert _identification("IDENTIFICATION: Healthy\n") is None
    assert _identification("No identification line here") is None


def test_disease_keywords_match_free_text_names():
    assert _disease_keywords("Blast") == ["blast"]
    assert "late blight" in _disease_keywords("Late Blight (Phytophthora infestans)")
    assert "leaf curl" in _disease_keywords("Leaf curl virus disease")
