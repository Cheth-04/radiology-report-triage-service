"""Worker failures/replay tests; database sessions and LLM are mocked."""
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.extraction import TemporaryLLMError, InvalidLLMResponse, mock_extraction
from app.workers.tasks import process_report

SAMPLE = 'Large right-sided pneumothorax with partial lung collapse. Impression: Large right pneumothorax.'

class DB:
    def __init__(self, record, existing=None):
        self.record, self.existing, self.commits = record, existing, 0
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def get(self, model, key): return self.record
    def query(self, model): return self
    def filter(self, *args): return self
    def one_or_none(self): return self.existing
    def add(self, value): self.existing = value
    def commit(self): self.commits += 1


def record(status='queued'):
    return SimpleNamespace(id=uuid.uuid4(), status=status, error_message=None, report_text=SAMPLE)


def test_bad_queue_job_id_never_opens_database():
    with patch('app.workers.tasks.SessionLocal') as session:
        result = process_report.run('not-a-uuid')
    assert result['status'] == 'invalid_id'
    session.assert_not_called()


def test_missing_report_never_calls_llm():
    db = DB(None)
    with patch('app.workers.tasks.SessionLocal', return_value=db), patch('app.workers.tasks.extract_report') as llm:
        output = process_report.run(str(uuid.uuid4()))
    assert output['status'] == 'not_found'
    llm.assert_not_called()


def test_failed_job_is_not_reprocessed():
    item = record('failed')
    with patch('app.workers.tasks.SessionLocal', return_value=DB(item)), patch('app.workers.tasks.extract_report') as llm:
        assert process_report.run(str(item.id))['status'] == 'failed'
    llm.assert_not_called()


def test_existing_extraction_is_updated_not_duplicated():
    item = record()
    old = SimpleNamespace(report_id=item.id, is_critical=False)
    first, second = DB(item), DB(item, existing=old)
    with patch('app.workers.tasks.SessionLocal', side_effect=[first, second]), \
         patch('app.workers.tasks.extract_report', return_value=mock_extraction(SAMPLE)), \
         patch('app.workers.tasks.emit_critical_alert'):
        result = process_report.run(str(item.id))
    assert result['status'] == 'done'
    assert second.existing is old
    assert old.is_critical is True
    assert second.commits == 1


def test_final_timeout_marks_failed_without_report_text_leak():
    item = record()
    first, last = DB(item), DB(item)
    with patch('app.workers.tasks.SessionLocal', side_effect=[first,last]), \
         patch('app.workers.tasks.extract_report', side_effect=TemporaryLLMError('secret LLM traceback')):
        # Celery's public request-stack API simulates the last retry attempt.
        process_report.push_request(retries=3)
        try:
            result = process_report.run(str(item.id))
        finally:
            process_report.pop_request()
    assert result['status'] == 'failed'
    assert item.status == 'failed'
    assert item.error_message == 'LLM unavailable after retries'
    assert 'secret' not in item.error_message


def test_invalid_extraction_does_not_save_partial_result():
    item = record()
    first, last = DB(item), DB(item)
    with patch('app.workers.tasks.SessionLocal', side_effect=[first,last]), \
         patch('app.workers.tasks.extract_report', side_effect=InvalidLLMResponse('raw response')):
        result = process_report.run(str(item.id))
    assert result['status'] == 'failed'
    assert item.status == 'failed'
    assert last.existing is None
    assert item.error_message == 'Invalid or unsupported LLM extraction'
