from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db.models import ImportHistory, Project, ProjectPlatform, SNSAccount, WatchTerm, WatchTopic, ProviderConnection
from app.normalizers.common import FieldNormalizationError, normalize_hashtags
from app.repositories.settings_repository import SettingsRepository
from app.schemas.settings import AccountResponse, HistoryResponse, HistoryDetail, HistoryPage, TermResponse
from app.services.matching_service import normalize_term
from app.services.rematch_service import RematchService
from app.services.trend_service import TrendService


class SettingsFailure(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


class SettingsService:
    def __init__(self, session_factory, repository=None, rematch=None, trend=None):
        self.session_factory = session_factory
        self.repository = repository or SettingsRepository()
        self.trend = trend or TrendService()
        self.rematch = rematch or RematchService(trend_service=self.trend)

    @contextmanager
    def transaction(self):
        try:
            with self.session_factory() as session, session.begin():
                yield session
        except SettingsFailure:
            raise
        except IntegrityError:
            raise SettingsFailure(409, "CONFLICT", "A conflicting setting already exists") from None
        except Exception:
            raise SettingsFailure(500, "SETTINGS_ERROR", "Settings could not be processed") from None

    def project(self, session, project_id, *, lock=False):
        project = self.repository.project(session, project_id, lock=lock)
        if project is None:
            raise SettingsFailure(404, "NOT_FOUND", "Project was not found")
        return project

    @staticmethod
    def entity(session, model, resource_id, **scope):
        pk = next(iter(model.__table__.primary_key))
        entity = session.scalar(select(model).where(pk == resource_id, *(
            getattr(model, key) == value for key, value in scope.items())))
        if entity is None:
            raise SettingsFailure(404, "NOT_FOUND", "Resource was not found")
        return entity

    @staticmethod
    def update(entity, request):
        values = request.model_dump(exclude_unset=True)
        changed = {key for key, value in values.items() if getattr(entity, key) != value}
        for key, value in values.items():
            setattr(entity, key, value)
        return changed

    def list_projects(self):
        with self.transaction() as s:
            return self.repository.projects(s)

    def get_project(self, project_id):
        with self.transaction() as s:
            return self.repository.project_response(self.project(s, project_id), self.repository.platforms(s, project_id))

    def create_project(self, request):
        with self.transaction() as s:
            p = Project(name=request.name, description=request.description, data_mode=request.data_mode)
            s.add(p)
            s.flush()
            s.add_all([ProjectPlatform(project_id=p.project_id, platform=v) for v in request.platforms])
            if p.data_mode == "LIVE":
                s.add_all([ProviderConnection(project_id=p.project_id, provider_type=kind)
                           for kind in ("X_API", "INSTAGRAM_API")])
            s.flush()
            return self.repository.project_response(p, self.repository.platforms(s, p.project_id))

    def patch_project(self, project_id, request):
        with self.transaction() as s:
            p = self.project(s, project_id, lock=True)
            self.update(p, request)
            s.flush()
            return self.repository.project_response(p, self.repository.platforms(s, project_id))

    def get_platforms(self, project_id):
        with self.transaction() as s:
            self.project(s, project_id)
            return {"platforms": self.repository.platforms(s, project_id)}

    def put_platforms(self, project_id, request):
        with self.transaction() as s:
            self.project(s, project_id, lock=True)
            old = set(self.repository.platforms(s, project_id))
            new = set(request.platforms)
            if old != new:
                s.execute(delete(ProjectPlatform).where(ProjectPlatform.project_id == project_id,
                                                        ProjectPlatform.platform.in_(old - new)))
                s.add_all([ProjectPlatform(project_id=project_id, platform=v) for v in new - old])
                s.flush()
                self.trend.rebuild_project(s, project_id)
            return {"platforms": self.repository.platforms(s, project_id)}

    def check_account(self, s, account):
        if not account.is_active:
            return
        if account.platform not in self.repository.platforms(s, account.project_id):
            raise SettingsFailure(400, "PLATFORM_DISABLED", "Platform is not enabled for this project")
        if account.account_role == "OWN":
            query = select(SNSAccount.account_id).where(SNSAccount.project_id == account.project_id,
                SNSAccount.platform == account.platform, SNSAccount.account_role == "OWN", SNSAccount.is_active.is_(True))
            if account.account_id is not None:
                query = query.where(SNSAccount.account_id != account.account_id)
            with s.no_autoflush:
                if s.scalar(query) is not None:
                    raise SettingsFailure(409, "OWN_CONFLICT", "An active OWN account already exists for this platform")

    def list_accounts(self, project_id):
        with self.transaction() as s:
            self.project(s, project_id)
            return [AccountResponse.model_validate(a) for a in s.scalars(select(SNSAccount).where(
                SNSAccount.project_id == project_id).order_by(SNSAccount.platform, SNSAccount.account_role,
                                                             SNSAccount.account_name, SNSAccount.account_id))]

    def create_account(self, project_id, request):
        with self.transaction() as s:
            project = self.project(s, project_id, lock=True)
            if project.data_mode != "DEMO":
                raise SettingsFailure(409, "LIVE_ACCOUNT_REQUIRES_PROVIDER", "Live accounts must be created through a provider")
            a = SNSAccount(project_id=project_id, is_active=True, **request.model_dump())
            self.check_account(s, a)
            s.add(a)
            s.flush()
            return AccountResponse.model_validate(a)

    def patch_account(self, project_id, account_id, request):
        with self.transaction() as s:
            self.project(s, project_id, lock=True)
            a = self.entity(s, SNSAccount, account_id, project_id=project_id)
            self.update(a, request)
            with s.no_autoflush:
                self.check_account(s, a)
            s.flush()
            return AccountResponse.model_validate(a)

    def list_topics(self, project_id):
        with self.transaction() as s:
            self.project(s, project_id)
            return self.repository.topics(s, project_id)

    def topic_response(self, s, project_id, topic_id):
        return next(t for t in self.repository.topics(s, project_id) if t.topic_id == topic_id)

    def create_topic(self, project_id, request):
        with self.transaction() as s:
            self.project(s, project_id, lock=True)
            t = WatchTopic(project_id=project_id, topic_name=request.topic_name, description=request.description)
            s.add(t)
            s.flush()
            for term_request in request.terms:
                value, key = self.canonical_term(term_request.term, term_request.term_type)
                s.add(WatchTerm(topic_id=t.topic_id, term=value, normalized_term=key, term_type=term_request.term_type))
            s.flush()
            if request.terms:
                self.rematch.refresh_project(s, project_id)
            return self.topic_response(s, project_id, t.topic_id)

    def patch_topic(self, project_id, topic_id, request):
        with self.transaction() as s:
            self.project(s, project_id, lock=True)
            t = self.entity(s, WatchTopic, topic_id, project_id=project_id)
            changed = self.update(t, request)
            s.flush()
            if "is_active" in changed:
                self.rematch.refresh_project(s, project_id)
            return self.topic_response(s, project_id, topic_id)

    @staticmethod
    def canonical_term(value, kind):
        if kind == "HASHTAG":
            try:
                tags = normalize_hashtags(value)
                if len(tags) != 1 or ";" in value:
                    raise ValueError()
                value = tags[0]
            except (FieldNormalizationError, ValueError):
                raise SettingsFailure(400, "INVALID_HASHTAG", "Enter a single non-empty hashtag without spaces") from None
        key = normalize_term(value)
        if not key or len(value) > 255 or len(key) > 255:
            raise SettingsFailure(400, "INVALID_TERM", "Term must contain 1 to 255 characters after normalization")
        return value, key

    def create_term(self, project_id, topic_id, request):
        with self.transaction() as s:
            self.project(s, project_id, lock=True)
            self.entity(s, WatchTopic, topic_id, project_id=project_id)
            value, key = self.canonical_term(request.term, request.term_type)
            term = WatchTerm(topic_id=topic_id, term=value, normalized_term=key, term_type=request.term_type)
            s.add(term)
            s.flush()
            self.rematch.refresh_project(s, project_id)
            return TermResponse.model_validate(term)

    def patch_term(self, project_id, topic_id, term_id, request):
        with self.transaction() as s:
            self.project(s, project_id, lock=True)
            self.entity(s, WatchTopic, topic_id, project_id=project_id)
            term = self.entity(s, WatchTerm, term_id, topic_id=topic_id)
            changed = self.update(term, request)
            if {"term", "term_type"} & changed:
                term.term, term.normalized_term = self.canonical_term(term.term, term.term_type)
            s.flush()
            if changed:
                self.rematch.refresh_project(s, project_id)
            return TermResponse.model_validate(term)

    def histories(self, project_id, limit, offset, status, import_type, page, page_size):
        with self.transaction() as s:
            self.project(s, project_id)
            items, total = self.repository.histories(s, project_id, limit, offset, status, import_type)
            return HistoryPage(items=[HistoryResponse.model_validate(i) for i in items], total=total,
                               limit=limit, offset=offset, page=page, page_size=page_size)

    def history(self, project_id, import_id):
        with self.transaction() as s:
            self.project(s, project_id)
            return HistoryDetail.model_validate(self.entity(s, ImportHistory, import_id, project_id=project_id))
