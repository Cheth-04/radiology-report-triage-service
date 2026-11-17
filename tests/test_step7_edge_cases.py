"""Boundary/contract tests with no live LLM, Redis, or PostgreSQL."""
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import get_current_user
from app.db.session import get_db
from app.services.extraction import InvalidLLMResponse, mock_extraction, parse_extraction

BASE = {
    "modality": "CT", "body_part": "Head", "findings": ["Synthetic finding"],
    "impression": "Synthetic impression", "is_critical": False, "critical_reason": None,
}

@pytest.mark.parametrize('change',[
    {"extra": "unexpected"},
    {"findings": "not-an-array"},
    {"findings": [""]},
    {"findings": ["  "]},
    {"findings": []},
    {"is_critical": 1},
    {"impression": ""},
    {"is_critical": True, "critical_reason": ""},
    {"critical_reason": "Not allowed on non-critical"},
])
def test_extraction_fails_closed_on_invalid_fields(change):
    with pytest.raises(InvalidLLMResponse):
        parse_extraction(json.dumps(BASE | change))


def test_unknown_mock_cannot_be_marked_noncritical_by_default():
    with pytest.raises(InvalidLLMResponse):
        mock_extraction("SYNTHETIC: an unsupported scenario not among the five fixtures")


@pytest.fixture(autouse=True)
def cleanup_dependencies():
    yield
    app.dependency_overrides.clear()


def authenticated(role='radiologist'):
    person = SimpleNamespace(id=uuid.uuid4(), role=role, email='fixture@example.com',
                             created_at=datetime.now(timezone.utc))
    db = Mock()
    app.dependency_overrides[get_current_user] = lambda: person
    app.dependency_overrides[get_db] = lambda: db
    return person, db


@pytest.mark.parametrize('payload', [
    {}, {"report_text": None}, {"report_text": 12},
    {"report_text": " " * 50}, {"report_text": "x" * 20001},
])
def test_report_upload_rejects_bad_input_without_database_or_enqueue(payload):
    _, db = authenticated()
    with patch('app.api.reports.process_report.apply_async') as send, TestClient(app) as client:
        response = client.post('/reports', json=payload)
    assert response.status_code == 422, response.text
    db.add.assert_not_called()
    send.assert_not_called()


def test_two_valid_submissions_have_unique_job_ids_and_queue_ids():
    _, db = authenticated()
    with patch('app.api.reports.process_report.apply_async') as send, TestClient(app) as client:
        a = client.post('/reports', json={"report_text": "Synthetic CT head impression with findings."})
        b = client.post('/reports', json={"report_text": "Synthetic X-ray chest impression with findings."})
    assert a.status_code == b.status_code == 202
    ids = {a.json()['job_id'], b.json()['job_id']}
    assert len(ids) == 2
    assert all(str(uuid.UUID(x)) == x for x in ids)
    assert send.call_count == 2
    assert {c.kwargs['task_id'] for c in send.call_args_list} == ids
    assert db.commit.call_count == 2


def test_job_excludes_original_report_text_and_internal_fields():
    person, db = authenticated()
    now = datetime.now(timezone.utc)
    job_id = uuid.uuid4()
    db.get.return_value = SimpleNamespace(
        id=job_id, owner_id=person.id, status='done',
        report_text='SYNTHETIC PRIVATE TEXT', error_message=None,
        created_at=now, updated_at=now,
    )
    db.scalar.return_value = SimpleNamespace(**BASE)
    with TestClient(app) as client:
        response = client.get(f'/jobs/{job_id}')
    assert response.status_code == 200, response.text
    assert 'SYNTHETIC PRIVATE TEXT' not in response.text
    assert set(response.json()) == {'job_id','status','result','error','created_at','updated_at'}
    assert set(response.json()['result']) == {
        'modality','body_part','findings','impression','is_critical','critical_reason'
    }


def test_job_ownership_denial_does_not_query_result_table():
    person, db = authenticated()
    other_id = uuid.uuid4()
    db.get.return_value = SimpleNamespace(id=other_id, owner_id=uuid.uuid4(), status='done')
    with TestClient(app) as client:
        response = client.get(f'/jobs/{other_id}')
    assert response.status_code == 404
    db.scalar.assert_not_called()
