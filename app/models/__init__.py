# Import every model so Alembic can discover its tables through Base.metadata.
from app.models.user import User
from app.models.report import Report
from app.models.report_result import ReportResult

__all__ = ["User", "Report", "ReportResult"]
