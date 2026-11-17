import uuid
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from app.services.extraction import InvalidLLMResponse, mock_extraction
from app.workers.tasks import process_report

SAMPLE = "Large right-sided pneumothorax with partial lung collapse. Impression: Large right pneumothorax."

class DB:
    def __init__(self, record, result=None):
        self.record = record
        self.result = result
        self.commits = 0

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def get(self, cls, record_id): return self.record
    def query(self, cls): return self
    def filter(self, *args): return self
    def one_or_none(self): return self.result
    def add(self, obj): self.result = obj
    def commit(self): self.commits += 1


def test_worker_saves_result_and_updates_state():
    ident = uuid.uuid4()
    record = SimpleNamespace(id=ident, status="queued", report_text=SAMPLE, error_message=None)
    first = DB(record)
    second = DB(record)
    with patch("app.workers.tasks.SessionLocal", side_effect=[first, second]), patch("app.workers.tasks.extract_report", return_value=mock_extraction(SAMPLE)):
        output = process_report.run(str(ident))
    assert output["status"] == "done"
    assert record.status == "done"
    assert second.result.report_id == ident
    assert second.result.is_critical is True
    assert first.commits == 1 and second.commits == 1


def test_worker_invalid_response_marks_failed():
    ident = uuid.uuid4()
    record = SimpleNamespace(id=ident, status="queued", report_text=SAMPLE, error_message=None)
    first, failure = DB(record), DB(record)
    with patch("app.workers.tasks.SessionLocal", side_effect=[first, failure]), patch("app.workers.tasks.extract_report", side_effect=InvalidLLMResponse("bad json")):
        output = process_report.run(str(ident))
    assert output["status"] == "failed"
    assert record.status == "failed"
    assert record.error_message == "Invalid or unsupported LLM extraction"
    assert "bad json" not in record.error_message


def test_done_worker_is_idempotent():
    ident = uuid.uuid4()
    record = SimpleNamespace(id=ident, status="done", report_text=SAMPLE)
    with patch("app.workers.tasks.SessionLocal", return_value=DB(record)), patch("app.workers.tasks.extract_report") as extract:
        assert process_report.run(str(ident))["status"] == "done"
    extract.assert_not_called()
