"""Provider-independent reads. No AI client, credentials, or write transactions."""
import base64
import binascii
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select, tuple_

from app.db.models import AIInsight, Project
from app.schemas.insight_history import (InsightHistoryItem, InsightHistoryPage,
    InsightHistoryDetail, InsightComparisonMetadata, InsightComparePreviousResponse)
from app.services.insight_service import InsightService, validated_snapshot
from app.services.settings_service import SettingsFailure


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def input_summary_hash(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def is_legacy(row):
    # Same validation boundary as the shared Latest/Generate response converter.
    try:
        validated_snapshot(row)
        return False
    except ValidationError:
        return True


class InsightHistoryService:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    @contextmanager
    def read(self, project_id):
        try:
            with self.session_factory() as s:
                s.connection(execution_options={'isolation_level': 'REPEATABLE READ', 'postgresql_readonly': True})
                project = s.get(Project, project_id)
                if project is None:
                    raise SettingsFailure(404, 'NOT_FOUND', 'Project was not found')
                yield s, project.data_mode
        except SettingsFailure:
            raise
        except Exception:
            raise SettingsFailure(500, 'INSIGHT_HISTORY_ERROR', 'Insight history could not be retrieved') from None

    @staticmethod
    def scope(project_id, platform, start, end):
        if (start is None) != (end is None):
            raise SettingsFailure(422, 'INVALID_PERIOD', 'Specify both from and to')
        if start is not None:
            InsightService.filters(start, end, platform)
        return [str(project_id), platform, start.isoformat() if start else None, end.isoformat() if end else None]

    @staticmethod
    def cursor(row, scope):
        payload = [1, scope, row.created_at.astimezone(timezone.utc).isoformat(), str(row.insight_id)]
        return base64.urlsafe_b64encode(canonical_json(payload).encode('utf-8')).decode('ascii')

    @staticmethod
    def boundary(cursor, scope):
        try:
            if len(cursor) > 1024:
                raise ValueError()
            payload = json.loads(base64.b64decode(cursor, altchars=b'-_', validate=True))
            if not isinstance(payload, list) or len(payload) != 4 or payload[0] != 1 or payload[1] != scope:
                raise ValueError()
            timestamp = datetime.fromisoformat(payload[2])
            if timestamp.tzinfo is None:
                raise ValueError()
            return timestamp.astimezone(timezone.utc), UUID(payload[3])
        except (ValueError, TypeError, binascii.Error, UnicodeError, OverflowError, RecursionError):
            raise SettingsFailure(422, 'INVALID_CURSOR', 'History cursor is invalid for these filters') from None

    def history(self, project_id, platform=None, start=None, end=None, limit=20, cursor=None):
        if not 1 <= limit <= 100:
            raise SettingsFailure(422, 'INVALID_LIMIT', 'Limit must be between 1 and 100')
        scope = self.scope(project_id, platform, start, end)
        boundary = self.boundary(cursor, scope) if cursor else None
        # Bounded query; summary JSON is needed for the derived hash and legacy
        # validation, but never included in the lightweight list response.
        columns = [getattr(AIInsight, n) for n in ('insight_id', 'project_id', 'platform',
            'analysis_from', 'analysis_to', 'created_at', 'model_name', 'prompt_version',
            'input_summary', 'content', 'evidence')]
        query = select(*columns).where(AIInsight.project_id == project_id)
        if platform is not None:
            query = query.where(AIInsight.platform == (None if platform == 'ALL' else platform))
        if start is not None:
            query = query.where(AIInsight.analysis_from == start, AIInsight.analysis_to == end)
        if boundary:
            query = query.where(tuple_(AIInsight.created_at, AIInsight.insight_id) < tuple_(*boundary))
        query = query.order_by(AIInsight.created_at.desc(), AIInsight.insight_id.desc()).limit(limit + 1)
        with self.read(project_id) as (s, mode):
            rows = s.execute(query).all()
            page = rows[:limit]
            items = [InsightHistoryItem(insight_id=r.insight_id, project_id=r.project_id,
                data_mode=mode, platform=r.platform or 'ALL', analysis_from=r.analysis_from,
                analysis_to=r.analysis_to, generated_at=r.created_at, model_name=r.model_name,
                prompt_version=r.prompt_version, input_summary_hash=input_summary_hash(r.input_summary),
                is_legacy=is_legacy(r)) for r in page]
            return InsightHistoryPage(items=items,
                next_cursor=self.cursor(page[-1], scope) if len(rows) > limit else None)

    @staticmethod
    def row(s, project_id, insight_id):
        row = s.scalar(select(AIInsight).where(AIInsight.project_id == project_id,
            AIInsight.insight_id == insight_id))
        if row is None:
            raise SettingsFailure(404, 'NOT_FOUND', 'Insight was not found')
        return row

    @staticmethod
    def response(row, mode):
        result = InsightService.response(row)
        return InsightHistoryDetail(**result.model_dump(), data_mode=mode,
            input_summary_hash=input_summary_hash(row.input_summary), is_legacy=result.content is None)

    def detail(self, project_id, insight_id):
        with self.read(project_id) as (s, mode):
            return self.response(self.row(s, project_id, insight_id), mode)

    def compare_previous(self, project_id, insight_id):
        with self.read(project_id) as (s, mode):
            current = self.row(s, project_id, insight_id)
            previous = s.scalar(select(AIInsight).where(AIInsight.project_id == project_id,
                AIInsight.platform == current.platform, AIInsight.analysis_from == current.analysis_from,
                AIInsight.analysis_to == current.analysis_to,
                tuple_(AIInsight.created_at, AIInsight.insight_id) < tuple_(current.created_at, current.insight_id))
                .order_by(AIInsight.created_at.desc(), AIInsight.insight_id.desc()).limit(1))
            flags = dict(input_changed=None, prompt_version_changed=None, model_changed=None,
                content_changed=None, evidence_changed=None)
            if previous is not None:
                flags = dict(input_changed=input_summary_hash(current.input_summary) != input_summary_hash(previous.input_summary),
                    prompt_version_changed=current.prompt_version != previous.prompt_version,
                    model_changed=current.model_name != previous.model_name,
                    content_changed=canonical_json(current.content) != canonical_json(previous.content),
                    evidence_changed=canonical_json(current.evidence) != canonical_json(previous.evidence))
            return InsightComparePreviousResponse(current=self.response(current, mode),
                previous=self.response(previous, mode) if previous else None,
                comparison=InsightComparisonMetadata(has_previous=previous is not None,
                    changed=any(flags.values()) if previous else None, **flags,
                    generated_at_delta_seconds=(current.created_at - previous.created_at).total_seconds() if previous else None))
