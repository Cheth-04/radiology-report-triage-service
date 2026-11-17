import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import jwt
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps import get_current_user
from app.db.session import get_db
from app.core.config import get_settings
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password

def user(role="radiologist"):
    return SimpleNamespace(id=uuid.uuid4(), email=f"{uuid.uuid4()}@example.com", role=role, created_at=datetime.now(timezone.utc))

@pytest.fixture(autouse=True)
def cleanup():
    yield
    app.dependency_overrides.clear()

def test_password_hash_and_jwt_expiration():
    hashed = hash_password("a-long-password-123")
    assert hashed != "a-long-password-123"
    assert verify_password("a-long-password-123", hashed)
    assert not verify_password("wrong-password", hashed)
    uid=uuid.uuid4()
    assert decode_access_token(create_access_token(uid)) == uid
    old = jwt.encode({"sub": str(uid), "type": "access", "iat": 1, "exp": 2}, get_settings().jwt_secret, algorithm="HS256")
    assert decode_access_token(old) is None

def test_missing_token_is_401():
    with TestClient(app) as client:
        assert client.get("/auth/me").status_code == 401

def test_me_and_admin_only_user_creation():
    radiologist = user()
    app.dependency_overrides[get_current_user] = lambda: radiologist
    with TestClient(app) as client:
        response = client.get("/auth/me")
        assert response.status_code == 200
        assert response.json()["role"] == "radiologist"
        assert "password_hash" not in response.json()
        assert client.post("/auth/users", json={"email":"new@example.com", "password":"strong-password-123"}).status_code == 403

def test_login_valid_and_invalid_password():
    from app.models.user import User
    real_user = user()
    real_user.password_hash = hash_password("strong-password-123")
    fake_db = Mock()
    fake_db.scalar.return_value = real_user
    app.dependency_overrides[get_db] = lambda: fake_db
    with TestClient(app) as client:
        bad = client.post("/auth/login", data={"username":real_user.email,"password":"wrong"})
        assert bad.status_code == 401
        good = client.post("/auth/login", data={"username":real_user.email,"password":"strong-password-123"})
        assert good.status_code == 200
        assert decode_access_token(good.json()["access_token"]) == real_user.id

def test_admin_creates_user_password_is_hashed():
    admin = user("admin")
    db = Mock()
    def refresh(obj):
        obj.id = uuid.uuid4()
        obj.created_at = datetime.now(timezone.utc)
    db.refresh.side_effect = refresh
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        res = client.post("/auth/users", json={"email":"doctor@example.com","password":"good-password-123","role":"radiologist"})
    assert res.status_code == 201, res.text
    created=db.add.call_args.args[0]
    assert created.role == "radiologist"
    assert verify_password("good-password-123", created.password_hash)
    assert "password_hash" not in res.json()

def test_admin_can_see_any_report_but_radiologist_cannot():
    from app.models.report import Report
    owner = user()
    admin = user("admin")
    another = user()
    report = SimpleNamespace(id=uuid.uuid4(), owner_id=another.id, report_text="SYNTHETIC TEST", status="done", error_message=None, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db=Mock()
    db.get.return_value=report
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: owner
    with TestClient(app) as client:
        assert client.get(f"/reports/{report.id}").status_code == 404
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as client:
        response=client.get(f"/reports/{report.id}")
        assert response.status_code == 200
        assert response.json()["id"] == str(report.id)

def test_radiologist_report_list_is_filtered():
    from app.models.report import Report
    doctor = user()
    db=Mock()
    db.scalars.return_value.all.return_value=[]
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: doctor
    with TestClient(app) as client:
        assert client.get('/reports').status_code == 200
    stmt=db.scalars.call_args.args[0]
    sql=str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "reports.owner_id" in sql
    assert doctor.id.hex in sql
