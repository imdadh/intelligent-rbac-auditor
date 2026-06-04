"""SQLAlchemy ORM models for the RBAC Auditor data layer.

All model modules are imported here so that Alembic's autogenerate command
can discover every mapped class via ``Base.metadata``.  Any new model added
to the package must also be imported in this file; failing to do so means
Alembic will silently omit the corresponding table from generated migrations.
"""

from app.models.audit import Audit
from app.models.base import Base
from app.models.dataset import Dataset
from app.models.finding import Finding
from app.models.query_log import QueryLog

__all__ = [
    "Audit",
    "Base",
    "Dataset",
    "Finding",
    "QueryLog",
]
