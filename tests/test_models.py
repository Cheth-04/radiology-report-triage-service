from app.db.base import Base
import app.models  # noqa: F401


def test_all_tables_registered():
    assert set(Base.metadata.tables) == {"users", "reports", "report_results"}


def test_report_has_owner_and_status():
    report = Base.metadata.tables["reports"]
    assert "owner_id" in report.c
    assert "status" in report.c


def test_report_result_is_unique_per_report():
    result = Base.metadata.tables["report_results"]
    assert result.c.report_id.unique
