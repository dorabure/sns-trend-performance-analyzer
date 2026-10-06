from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ImportHistory, Project, ProjectPlatform, WatchTerm, WatchTopic
from app.schemas.settings import ProjectResponse, TopicResponse, TermResponse


class SettingsRepository:
    def project(self, session: Session, project_id: UUID, *, lock=False):
        query = select(Project).where(Project.project_id == project_id)
        if lock:
            query = query.with_for_update()
        return session.scalar(query)

    def platforms(self, session: Session, project_id: UUID):
        return list(session.scalars(select(ProjectPlatform.platform).where(
            ProjectPlatform.project_id == project_id).order_by(ProjectPlatform.platform)))

    def projects(self, session: Session):
        projects = session.scalars(select(Project).order_by(Project.created_at, Project.project_id)).all()
        platforms = session.execute(select(ProjectPlatform.project_id, ProjectPlatform.platform)
                                    .order_by(ProjectPlatform.platform)).all()
        grouped = {}
        for project_id, platform in platforms:
            grouped.setdefault(project_id, []).append(platform)
        return [self.project_response(p, grouped.get(p.project_id, [])) for p in projects]

    @staticmethod
    def project_response(project, platforms):
        return ProjectResponse(project_id=project.project_id, name=project.name,
                               data_mode=project.data_mode,
                               description=project.description, is_active=project.is_active,
                               created_at=project.created_at, updated_at=project.updated_at,
                               platforms=platforms)

    def topics(self, session: Session, project_id: UUID):
        topics = session.scalars(select(WatchTopic).where(WatchTopic.project_id == project_id)
                                 .order_by(WatchTopic.topic_name, WatchTopic.topic_id)).all()
        terms = session.scalars(select(WatchTerm).join(WatchTopic).where(
            WatchTopic.project_id == project_id).order_by(WatchTerm.term_type, WatchTerm.term, WatchTerm.term_id)).all()
        grouped = {}
        for term in terms:
            grouped.setdefault(term.topic_id, []).append(TermResponse.model_validate(term))
        return [TopicResponse(topic_id=t.topic_id, project_id=t.project_id, topic_name=t.topic_name,
                              description=t.description, is_active=t.is_active,
                              terms=grouped.get(t.topic_id, [])) for t in topics]

    @staticmethod
    def histories(session: Session, project_id: UUID, limit, offset, status, import_type):
        filters = [ImportHistory.project_id == project_id]
        if status is not None:
            filters.append(ImportHistory.status == status)
        if import_type is not None:
            filters.append(ImportHistory.import_type == import_type)
        total = session.scalar(select(func.count()).select_from(ImportHistory).where(*filters))
        items = session.scalars(select(ImportHistory).where(*filters).order_by(
            ImportHistory.imported_at.desc(), ImportHistory.import_id.desc()).limit(limit).offset(offset)).all()
        return items, total
