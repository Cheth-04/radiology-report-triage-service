import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://triage:test@db:5432/triage_db")
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
os.environ.setdefault("LLM_BASE_URL", "http://localhost:1234/v1")
os.environ.setdefault("LLM_MODEL", "fake")
os.environ["JWT_SECRET"] = "test-only-secret-for-pytest-very-long-string"
