import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import ImportHistory, Project, ProjectPlatform, SNSAccount, WatchTerm, WatchTopic
from app.dto.normalized import (NormalizedAccountMetric, NormalizedCompetitorData, NormalizedPost,
                                NormalizedTrendData, SourceType, ValidationError)
from app.providers.base import CsvDatasetType, DataProvider, ProviderFileError
from app.providers.csv_provider import CSVProvider
from app.repositories.import_repository import ImportRepository
from app.services.matching_service import TermCandidate
from app.services.trend_service import TrendService

logger = logging.getLogger(__name__)


def error_json(error: ValidationError) -> dict:
    value = asdict(error)
    value["row"] = value.pop("row_number")
    return value


@dataclass(frozen=True)
class ImportResult:
    import_id: UUID
    status: str
    total_count: int
    success_count: int
    error_count: int
    errors: list[dict]


class ImportFailure(Exception):
    def __init__(self, status_code: int, error: ValidationError, result: ImportResult | None = None):
        self.status_code = status_code
        self.error = error
        self.result = result
        super().__init__(error.message)


class ImportService:
    def __init__(self, session_factory: Callable[[], Session], provider: DataProvider | None = None,
                 repository: ImportRepository | None = None,
                 now_provider: Callable[[], datetime] | None = None,
                 trend_service: TrendService | None = None):
        self.session_factory = session_factory
        self.provider = provider if provider is not None else CSVProvider()
        self.repository = repository if repository is not None else ImportRepository()
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.trend_service = trend_service if trend_service is not None else TrendService()

    def start(self, project_id: UUID, dataset: CsvDatasetType, filename: str) -> tuple[UUID, datetime]:
        try:
            started = self.now_provider()
            if started.tzinfo is None or started.utcoffset() is None:
                raise ValueError("Clock must be timezone-aware")
            with self.session_factory() as session, session.begin():
                project = session.get(Project, project_id)
                if project is None:
                    raise ImportFailure(404, ValidationError(None, "project_id", "PROJECT_NOT_FOUND", "Project was not found"))
                if not project.is_active:
                    raise ImportFailure(409, ValidationError(None, "project_id", "PROJECT_INACTIVE", "Project is inactive"))
                if project.data_mode != "DEMO":
                    raise ImportFailure(409, ValidationError(None, "project_id", "CSV_IMPORT_REQUIRES_DEMO", "CSV import requires a DEMO project"))
                history = ImportHistory(project_id=project_id, import_type=dataset.value,
                                        filename=filename, status="PROCESSING", imported_at=started)
                session.add(history)
                session.flush()
                import_id = history.import_id
            return import_id, started
        except ImportFailure:
            raise
        except Exception:
            raise ImportFailure(500, self.database_error()) from None

    @staticmethod
    def database_error() -> ValidationError:
        return ValidationError(None, "database", "IMPORT_DATABASE_ERROR", "Import could not be completed")

    def fail(self, import_id: UUID, error: ValidationError, status_code: int,
             total: int = 0, skipped: int = 0) -> ImportFailure:
        result = ImportResult(import_id, "FAILED", total, 0, skipped, [error_json(error)])
        try:
            with self.session_factory() as session, session.begin():
                self.finish_history(session, result)
        except Exception:
            # No exception text, SQL, connection string, or CSV content in logs.
            logger.error("IMPORT_AUDIT_FAILED: failure history could not be persisted")
        return ImportFailure(status_code, error, result)

    @staticmethod
    def finish_history(session: Session, result: ImportResult) -> None:
        changed = session.execute(update(ImportHistory).where(ImportHistory.import_id == result.import_id).values(
            status=result.status, total_count=result.total_count, success_count=result.success_count,
            error_count=result.error_count, error_detail=result.errors))
        if changed.rowcount != 1:
            raise RuntimeError("Import history must exist")

    def run(self, import_id: UUID, started: datetime, project_id: UUID,
            dataset: CsvDatasetType, path: Path) -> ImportResult:
        total = skipped = 0
        try:
            parsed = self.provider.read(path, dataset)
            total = parsed.total_rows
            errors = list(parsed.errors)
            with self.session_factory() as session, session.begin():
                # Post imports and full rebuilds serialize per project until commit.
                project = session.scalars(select(Project).where(Project.project_id == project_id)
                                          .with_for_update(read=dataset == CsvDatasetType.ACCOUNT_DAILY)).one_or_none()
                if project is None or not project.is_active:
                    raise ImportFailure(409, ValidationError(None, "project_id", "PROJECT_UNAVAILABLE", "Project is unavailable"))
                if project.data_mode != "DEMO":
                    raise ImportFailure(409, ValidationError(None, "project_id", "CSV_IMPORT_REQUIRES_DEMO", "CSV import requires a DEMO project"))
                platforms = set(session.scalars(select(ProjectPlatform.platform).where(ProjectPlatform.project_id == project_id)))
                accounts = list(session.scalars(select(SNSAccount).where(SNSAccount.project_id == project_id)))
                terms = session.scalars(select(WatchTerm).join(WatchTopic).where(
                    WatchTopic.project_id == project_id, WatchTopic.is_active.is_(True), WatchTerm.is_active.is_(True))).all()
                candidates = [TermCandidate(t.term_id, t.topic_id, t.term, t.normalized_term, t.term_type) for t in terms]
                prepared = []
                for record in parsed.records:
                    entity = self.check_contract(record, dataset)
                    if entity.platform.value not in platforms:
                        errors.append(ValidationError(entity.row_number, "platform", "PLATFORM_NOT_ENABLED", "Platform is not enabled for this project"))
                        continue
                    account_id = None
                    if dataset != CsvDatasetType.TREND_POSTS:
                        role = "COMPETITOR" if dataset == CsvDatasetType.COMPETITOR_POSTS else "OWN"
                        found = [a for a in accounts if a.platform == entity.platform.value and a.account_name == entity.account_name]
                        if len(found) > 1:
                            raise RuntimeError("Account contract violation")
                        if not found or not found[0].is_active:
                            errors.append(ValidationError(entity.row_number, "account_name", "ACCOUNT_NOT_FOUND", "Active account was not found"))
                            continue
                        if found[0].account_role != role:
                            errors.append(ValidationError(entity.row_number, "account_name", "ACCOUNT_ROLE_MISMATCH", "Account role does not match the import type"))
                            continue
                        account_id = found[0].account_id
                    prepared.append((record, entity, account_id))
                skipped = total - len(prepared)
                if total < 0 or skipped < 0:
                    raise RuntimeError("Provider count contract violation")
                for record, entity, account_id in prepared:
                    if type(entity) is NormalizedAccountMetric:
                        self.repository.save_account_metric(session, account_id, entity)
                    else:
                        self.repository.save_post(session, project_id, account_id, entity, started, candidates)
                        if type(record) is NormalizedCompetitorData and record.followers is not None:
                            self.repository.save_followers(session, account_id, entity, record.followers)
                if dataset != CsvDatasetType.ACCOUNT_DAILY:
                    self.trend_service.rebuild_project(session, project_id)
                result = ImportResult(import_id, "PARTIAL_ERROR" if errors else "SUCCESS", total,
                                      len(prepared), skipped, [error_json(e) for e in errors])
                self.finish_history(session, result)
            return result
        except ProviderFileError as exc:
            raise self.fail(import_id, exc.error, 400) from None
        except ImportFailure as exc:
            raise self.fail(import_id, exc.error, exc.status_code, total, skipped) from None
        except Exception:
            raise self.fail(import_id, self.database_error(), 500, total, skipped) from None

    @staticmethod
    def check_contract(record, dataset: CsvDatasetType) -> NormalizedPost | NormalizedAccountMetric:
        expected = {CsvDatasetType.OWN_POSTS: (NormalizedPost, SourceType.OWN),
                    CsvDatasetType.ACCOUNT_DAILY: (NormalizedAccountMetric, None),
                    CsvDatasetType.TREND_POSTS: (NormalizedTrendData, SourceType.MARKET),
                    CsvDatasetType.COMPETITOR_POSTS: (NormalizedCompetitorData, SourceType.COMPETITOR)}
        dto_type, source = expected[dataset]
        if type(record) is not dto_type:
            raise TypeError("Provider DTO contract violation")
        entity = record.post if dto_type in (NormalizedTrendData, NormalizedCompetitorData) else record
        if source is not None and (type(entity) is not NormalizedPost or entity.source_type != source):
            raise TypeError("Provider source contract violation")
        return entity
