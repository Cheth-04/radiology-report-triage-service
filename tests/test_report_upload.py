import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.report import Report

TEXT = "SYNTHETIC TEST: acute left basal ganglia hemorrhage with midline shift."

def user(role="radiologist"):
    return SimpleNamespace(id=uuid.uuid4(), role=role, email="test@example.com", created_at=datetime.now(timezone.utc))

@pytest.fixture(autouse=True)
def reset():
    yield
    app.dependency_overrides.clear()

def test_upload_returns_202_and_enqueues_uuid_without_text():
    doctor = user()
    db = Mock()
    app.dependency_overrides[get_current_user] = lambda: doctor
    app.dependency_overrides[get_db] = lambda: db
    with patch("app.api.reports.process_report.apply_async") as queue:
        with TestClient(app) as client:
            response = client.post("/reports", json={"report_text": TEXT})
    assert response.status_code == 202, response.text
    result = response.json()
    assert result["status"] == "queued"
    job_id = uuid.UUID(result["job_id"])
    saved = db.add.call_args.args[0]
    assert isinstance(saved, Report)
    assert saved.id == job_id
    assert saved.owner_id == doctor.id
    assert saved.report_text == TEXT
    assert saved.status == "queued"
    db.commit.assert_called_once()
    queue.assert_called_once_with(args=[str(job_id)], task_id=str(job_id))

def test_upload_requires_authentication():
    with TestClient(app) as client:
        assert client.post("/reports", json={"report_text": TEXT}).status_code == 401

def test_admin_cannot_upload():
    db = Mock()
    app.dependency_overrides[get_current_user] = lambda: user("admin")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.post("/reports", json={"report_text": TEXT}).status_code == 403
    db.add.assert_not_called()

def test_empty_or_short_report_rejected():
    app.dependency_overrides[get_current_user] = lambda: user()
    app.dependency_overrides[get_db] = lambda: Mock()
    with TestClient(app) as client:
        for report in ["", "   ", "short"]:
            assert client.post("/reports", json={"report_text": report}).status_code == 422

def test_enqueue_failure_marks_report_failed_and_returns_503():
    db = Mock()
    app.dependency_overrides[get_current_user] = lambda: user()
    app.dependency_overrides[get_db] = lambda: db
    with patch("app.api.reports.process_report.apply_async", side_effect=ConnectionError("redis down")):
        with TestClient(app) as client:
            response = client.post("/reports", json={"report_text": TEXT})
    assert response.status_code == 503
    record = db.add.call_args.args[0]
    assert record.status == "failed"
    assert record.error_message == "Could not enqueue background processing"
    assert db.commit.call_count == 2
    assert "redis down" not in response.text

def test_database_error_does_not_publish_task():
    from sqlalchemy.exc import SQLAlchemyError
    db = Mock()
    db.commit.side_effect = SQLAlchemyError("db unavailable")
    app.dependency_overrides[get_current_user] = lambda: user()
    app.dependency_overrides[get_db] = lambda: db
    with patch("app.api.reports.process_report.apply_async") as queue:
        with TestClient(app) as client:
            response = client.post("/reports", json={"report_text": TEXT})
    assert response.status_code == 503
    db.rollback.assert_called_once()
    queue.assert_not_called()

