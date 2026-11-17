import logging
import uuid
from unittest.mock import patch
from app.services.alerts import emit_critical_alert
from app.services.extraction import mock_extraction
from app.workers.tasks import process_report
SAMPLE = "Large right-sided pneumothorax with partial lung collapse. Impression: Large right pneumothorax."

class DB:
    def __init__(self, record):
        self.record = record
        self.result = None
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def get(self, cls, record_id): return self.record
    def query(self, cls): return self
    def filter(self, *args): return self
    def one_or_none(self): return self.result
    def add(self, obj): self.result = obj
    def commit(self): pass

from types import SimpleNamespace


def test_alert_log_contains_id_but_not_report_or_reason(caplog):
    job_id = uuid.uuid4()
    with caplog.at_level(logging.WARNING, logger="radiology_triage.alerts"):
        emit_critical_alert(job_id, "Synthetic medical details")
    assert "CRITICAL TRIAGE ALERT" in caplog.text
    assert str(job_id) in caplog.text
    assert "Synthetic medical details" not in caplog.text


def test_critical_worker_emits_alert_only_after_successful_persist():
    ident = uuid.uuid4()
    item = SimpleNamespace(id=ident, status="queued", report_text=SAMPLE, error_message=None)
    with patch("app.workers.tasks.SessionLocal", side_effect=[DB(item), DB(item)]), patch("app.workers.tasks.extract_report", return_value=mock_extraction(SAMPLE)), patch("app.workers.tasks.emit_critical_alert") as alert:
        assert process_report.run(str(ident))["status"] == "done"
        alert.assert_called_once_with(ident, "Large pneumothorax with partial lung collapse")


def test_noncritical_worker_does_not_emit_alert():
    ident = uuid.uuid4()
    sample = "Partial-thickness tear of the anterior cruciate ligament. Mild joint effusion. Impression: Partial ACL tear."
    item = SimpleNamespace(id=ident, status="queued", report_text=sample, error_message=None)
    with patch("app.workers.tasks.SessionLocal", side_effect=[DB(item), DB(item)]), patch("app.workers.tasks.extract_report", return_value=mock_extraction(sample)), patch("app.workers.tasks.emit_critical_alert") as alert:
        assert process_report.run(str(ident))["status"] == "done"
        alert.assert_not_called()
