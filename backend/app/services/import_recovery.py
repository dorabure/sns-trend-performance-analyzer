"""Startup recovery for the current single-process deployment."""
import logging

from sqlalchemy import inspect, literal, update
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models import ImportHistory

INTERRUPTED = {"row": None, "field": "system", "code": "IMPORT_INTERRUPTED",
               "message": "Import was interrupted before completion"}
logger = logging.getLogger(__name__)


def recover_interrupted_imports(session_factory):
    # One atomic UPDATE; no candidate rows or CSV metadata are loaded into memory.
    try:
        with session_factory() as session, session.begin():
            # First installation still uses the existing explicit Alembic command.
            # No table means no histories to recover; never auto-create schema.
            if not inspect(session.connection()).has_table("import_histories"):
                logger.info("IMPORT_RECOVERY_SCHEMA_NOT_READY")
                return 0
            result = session.execute(update(ImportHistory).where(ImportHistory.status == "PROCESSING")
                .values(status="FAILED", error_detail=ImportHistory.error_detail.op("||")(
                    literal([INTERRUPTED], type_=JSONB))))
            count = result.rowcount
        logger.info("IMPORT_RECOVERY completed count=%s", count)
        return count
    except Exception:
        # Fail startup rather than accepting imports after unsuccessful recovery.
        logger.error("IMPORT_RECOVERY_FAILED")
        raise RuntimeError("Import recovery could not complete") from None
