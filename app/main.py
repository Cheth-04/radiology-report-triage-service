from fastapi import FastAPI, HTTPException
from redis import Redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.core.config import get_settings
from app.db.session import engine

from app.api.auth import router as auth_router
from app.api.reports import router as reports_router
from app.api.jobs import router as jobs_router

app = FastAPI(title="Radiology Report Triage Service", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok", "service": "radiology-triage-api"}


@app.get("/ready")
def ready():
    settings = get_settings()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        redis_client = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        try:
            redis_client.ping()
        finally:
            redis_client.close()
    except (SQLAlchemyError, OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Dependency unavailable") from exc
    return {"status": "ready", "database": "ok", "redis": "ok"}


app.include_router(auth_router)
app.include_router(reports_router)

app.include_router(jobs_router)
