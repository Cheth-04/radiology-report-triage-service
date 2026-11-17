"""GET /jobs/{id}: all four statuses, result visibility and authorization."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.deps import get_current_user
from app.db.session import get_db
from app.main import app


def user(role="radiologist", ident=None):
    return SimpleNamespace(id=ident or uuid.uuid4(), role=role)


def report(owner_id, state="queued", error=None):
    return SimpleNamespace(
        id=uuid.uuid4(), owner_id=owner_id, status=state,
        error_message=error,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def extraction(critical=False):
    return SimpleNamespace(
        modality="CT", body_part="Head", findings=["Synthetic finding"],
        impression="Synthetic impression", is_critical=critical,
        critical_reason="Synthetic urgent finding" if critical else None,
    )


@pytest.fixture(autouse=True)
def reset_overrides():
    yield
    app.dependency_overrides.clear()


def run_as(person, db, identifier):
    app.dependency_overrides[get_current_user] = lambda: person
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        return client.get(f"/jobs/{identifier}")


@pytest.mark.parametrize("state", ["queued", "processing"])
def test_pending_job_has_no_result_or_error(state):
    doctor = user()
    item = report(doctor.id, state)
    db = Mock()
    db.get.return_value = item
    response = run_as(doctor, db, item.id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == state
    assert response.json()["job_id"] == str(item.id)
    assert response.json()["result"] is None
    assert response.json()["error"] is None
    db.scalar.assert_not_called()


def test_completed_job_returns_extraction_including_critical_reason():
    doctor = user()
    item = report(doctor.id, "done")
    db = Mock()
    db.get.return_value = item
    db.scalar.return_value = extraction(critical=True)
    response = run_as(doctor, db, item.id)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["is_critical"] is True
    assert response.json()["result"]["critical_reason"] == "Synthetic urgent finding"
    assert response.json()["error"] is None


def test_failed_job_returns_sanitized_stored_error():
    doctor = user()
    item = report(doctor.id, "failed", "LLM unavailable after retries")
    db = Mock()
    db.get.return_value = item
    response = run_as(doctor, db, item.id)
    assert response.status_code == 200
    assert response.json()["result"] is None
    assert response.json()["error"] == "LLM unavailable after retries"
    db.scalar.assert_not_called()


def test_missing_and_non_owned_jobs_are_both_404():
    doctor = user()
    item = report(uuid.uuid4(), "done")
    db = Mock()
    db.get.return_value = item
    assert run_as(doctor, db, item.id).status_code == 404
    db.get.return_value = None
    assert run_as(doctor, db, item.id).status_code == 404
    db.scalar.assert_not_called()


def test_admin_can_access_other_users_job():
    admin = user("admin")
    item = report(uuid.uuid4(), "done")
    db = Mock()
    db.get.return_value = item
    db.scalar.return_value = extraction()
    response = run_as(admin, db, item.id)
    assert response.status_code == 200
    assert response.json()["result"]["is_critical"] is False


def test_missing_authentication_is_401():
    with TestClient(app) as client:
        assert client.get(f"/jobs/{uuid.uuid4()}").status_code == 401


def test_invalid_job_id_is_422():
    doctor = user()
    db = Mock()
    response = run_as(doctor, db, "not-a-uuid")
    assert response.status_code == 422


def test_inconsistent_done_without_result_returns_503():
    doctor = user()
    item = report(doctor.id, "done")
    db = Mock()
    db.get.return_value = item
    db.scalar.return_value = None
    response = run_as(doctor, db, item.id)
    assert response.status_code == 503
    assert response.json()["detail"] == "Job result temporarily unavailable"


def test_database_unavailable_returns_sanitized_503():
    doctor = user()
    db = Mock()
    db.get.side_effect = OperationalError("SELECT", {}, Exception("private details"))
    response = run_as(doctor, db, uuid.uuid4())
    assert response.status_code == 503
    assert "private details" not in response.text
