import json
import pytest
from pydantic import ValidationError
from unittest.mock import Mock, patch

from app.schemas.extraction import ExtractionResult
from app.services.extraction import (
    InvalidLLMResponse, TemporaryLLMError, extract_report, mock_extraction, parse_extraction,
)

REPORTS = [
    ("Acute intraparenchymal hemorrhage in the left basal ganglia measuring 3.2 cm with 4 mm midline shift. Impression: Acute intracranial hemorrhage.", True, "CT"),
    ("Large right-sided pneumothorax with partial lung collapse. Impression: Large right pneumothorax.", True, "X-ray"),
    ("Partial-thickness tear of the anterior cruciate ligament. Mild joint effusion. Impression: Partial ACL tear.", False, "MRI"),
    ("Lungs are clear. Heart size normal. No pleural effusion. Impression: No acute cardiopulmonary abnormality.", False, "X-ray"),
    ("Simple 1.5 cm cyst in the right kidney. Liver, spleen and pancreas are unremarkable. Impression: Benign renal cyst.", False, "CT"),
]

@pytest.mark.parametrize("text,critical,modality", REPORTS)
def test_five_synthetic_samples(text, critical, modality):
    value = mock_extraction(text)
    assert value.is_critical is critical
    assert value.modality == modality
    assert bool(value.critical_reason) is critical
    assert value.findings


def test_mock_rejects_unknown_report():
    with pytest.raises(InvalidLLMResponse):
        mock_extraction("A totally unrelated sample")


def test_valid_json_parsed():
    data = mock_extraction(REPORTS[0][0]).model_dump()
    assert parse_extraction(json.dumps(data)).is_critical is True


@pytest.mark.parametrize("raw", [
    "not json", "[]", "{}",
    json.dumps({"modality": "CT", "body_part": "Head", "findings": [], "impression": "A", "is_critical": False}),
    json.dumps({"modality": "CT", "body_part": "Head", "findings": ["hemorrhage"], "impression": "A", "is_critical": "false", "critical_reason": None}),
    json.dumps({"modality": "CT", "body_part": "Head", "findings": ["hemorrhage"], "impression": "A", "is_critical": True, "critical_reason": None}),
])
def test_invalid_json_is_rejected(raw):
    with pytest.raises(InvalidLLMResponse):
        parse_extraction(raw)


def test_mock_mode_does_not_call_external_provider():
    config = Mock(llm_mode="mock")
    with patch("app.services.extraction.get_settings", return_value=config), patch("app.services.extraction.OpenAI") as client:
        result = extract_report(REPORTS[1][0])
    assert result.is_critical is True
    client.assert_not_called()


def test_lmstudio_response_is_validated_without_network():
    config = Mock(llm_mode="lmstudio", llm_base_url="http://host.docker.internal:1234/v1", llm_api_key="lm-studio", llm_model="fake", llm_timeout_seconds=5)
    response = Mock()
    response.choices = [Mock(message=Mock(content=json.dumps(mock_extraction(REPORTS[2][0]).model_dump())))]
    with patch("app.services.extraction.get_settings", return_value=config), patch("app.services.extraction.OpenAI") as factory:
        factory.return_value.chat.completions.create.return_value = response
        value = extract_report(REPORTS[2][0])
    assert value.is_critical is False
    factory.return_value.chat.completions.create.assert_called_once()
