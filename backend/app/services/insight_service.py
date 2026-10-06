import logging
from copy import deepcopy
from time import monotonic

from pydantic import ValidationError
from sqlalchemy import select

from app.db.models import AIInsight
from app.schemas.insights import (AIInsightContent, Evidence, EvidenceItem, InsightResponse,
                                  LatestResponse, Sections)
from app.services.openai_insight_client import OpenAIInsightClient, PROMPT_VERSION, failure
from app.services.overview_service import OverviewService
from app.services.settings_service import SettingsFailure

logger = logging.getLogger(__name__)


def validated_snapshot(row):
    """Shared current/legacy boundary for Latest, Generate, and History."""
    return AIInsightContent.model_validate(row.content), Evidence.model_validate(row.evidence)


def without_names(value):
    """Only called on typed aggregate models, never on raw posts."""
    if isinstance(value, list):
        return [without_names(v) for v in value]
    if isinstance(value, dict):
        return {k: without_names(v) for k, v in value.items()
                if k not in ('account_name', 'display_name')}
    return value


def snapshot_input(project_id, filters, overview):
    data = overview.model_dump(mode='json', by_alias=True)
    kpis = without_names(data['kpis'])
    aggregate = without_names(data['competitor_aggregate'])
    # Followers are non-additive. Only the same three displayed competitors are sent.
    aggregate.pop('followers_by_account')
    competitors = without_names(data['competitor_summary'])
    opportunity = data['top_opportunity']
    summary = {
        'analysis_scope': {'project_id': str(project_id), 'platform': filters.platform or 'ALL',
            'analysis_from': filters.start.isoformat(), 'analysis_to': filters.end.isoformat(), 'timezone': 'UTC'},
        'previous_period': data['previous_period'], 'own_kpi': kpis,
        'market_trends': data['top_trends'], 'score_window_days': 7,
        'competitor_summary': competitors, 'competitor_aggregate': aggregate,
        'opportunity': opportunity,
        'data_limits': {'trends': 5, 'competitors': 3, 'opportunities': 1,
            'own_followers': 2, 'competitor_followers': 'Only selected accounts; not a total'},
    }
    evidence = Evidence(
        kpis=[EvidenceItem(id=f'KPI_{name.upper()}', label=name, values=value if isinstance(value, dict) else {'items': value})
              for name, value in kpis.items()],
        trends=[EvidenceItem(id=f'TREND:{t["topic_id"]}:{t["platform"]}', label=t['topic_name'], values=t)
                for t in summary['market_trends']],
        competitors=[EvidenceItem(id=f'COMPETITOR:{a["account_id"]}', label=f'Competitor / {a["platform"]}', values=a)
                     for a in competitors],
        opportunities=[EvidenceItem(id=f'GAP:{opportunity["topic_id"]}:{opportunity["platform"]}',
            label=opportunity['topic_name'], values=opportunity)] if opportunity else [])
    return summary, evidence


class InsightService(OverviewService):
    def __init__(self, session_factory, client=None):
        super().__init__(session_factory)
        self.client = client or OpenAIInsightClient()

    @staticmethod
    def response(row):
        legacy = None
        try:
            content, evidence = validated_snapshot(row)
            sections = Sections.model_validate(content.model_dump(include={
                'market_trend', 'own_analysis', 'improvement_points', 'post_ideas'}))
        except ValidationError:
            # Read historical Ver1.1 JSON without inventing evidence links or rewriting its row.
            content = None
            sections = Sections.model_validate({name: row.content.get(name, '判断材料不足。' if name in (
                'market_trend', 'own_analysis') else []) for name in (
                'market_trend', 'own_analysis', 'improvement_points', 'post_ideas')})
            evidence = Evidence(kpis=[], trends=[], competitors=[], opportunities=[])
            legacy = row.evidence
        return InsightResponse(insight_id=row.insight_id, project_id=row.project_id,
            platform=row.platform or 'ALL', analysis_from=row.analysis_from, analysis_to=row.analysis_to,
            generated_at=row.created_at, sections=sections, content=content,
            evidence=evidence, input_summary=row.input_summary,
            model_name=row.model_name, prompt_version=row.prompt_version, legacy_evidence=legacy)

    def latest(self, project_id, filters):
        with self.read(project_id) as s:
            self.scope(s, project_id, filters)
            row = s.scalar(select(AIInsight).where(AIInsight.project_id == project_id,
                AIInsight.platform == filters.platform, AIInsight.analysis_from == filters.start,
                AIInsight.analysis_to == filters.end).order_by(AIInsight.created_at.desc(), AIInsight.insight_id.desc()).limit(1))
            return LatestResponse(insight=self.response(row) if row else None,
                                  ai_generation_available=self.client.available)

    def generate(self, project_id, filters):
        started = monotonic()
        try:
            if not self.client.available:
                raise failure('AI_KEY_NOT_CONFIGURED', 'OpenAI API Keyを設定してください。')
            # A: Consistent aggregate/evidence snapshot, closed BEFORE external API waiting.
            with self.read(project_id) as s:
                overview = self.overview_in_session(s, project_id, filters)
                summary, evidence = snapshot_input(project_id, filters, overview)
            # B: No Session or Connection is held here.
            external_summary = deepcopy(summary)
            external_summary['analysis_scope'].pop('project_id', None)
            content, model = self.client.generate(external_summary, evidence.model_dump(mode='json'))
            try:
                content = AIInsightContent.model_validate(content)
            except ValidationError:
                raise failure('AI_INVALID_OUTPUT', 'AI応答の形式を確認できませんでした。再試行してください。') from None
            refs = content.references
            used = set(refs.market_trend + refs.own_analysis)
            for group in refs.improvement_points + refs.post_ideas:
                used.update(group)
            if not used <= evidence.ids():
                raise failure('AI_INVALID_EVIDENCE', 'AI提案の根拠を確認できませんでした。再試行してください。')
            # C: New INSERT only. Response is built before commit; no expired ORM reload afterward.
            try:
                with self.session_factory() as s, s.begin():
                    row = AIInsight(project_id=project_id, platform=filters.platform,
                        analysis_from=filters.start, analysis_to=filters.end, content=content.model_dump(mode='json'),
                        evidence=evidence.model_dump(mode='json'), input_summary=summary,
                        model_name=model, prompt_version=PROMPT_VERSION)
                    s.add(row)
                    s.flush()
                    result = self.response(row)
                logger.info('AI_GENERATED project=%s platform=%s elapsed=%.2f', project_id,
                            filters.platform or 'ALL', monotonic() - started)
                return result
            except Exception:
                raise SettingsFailure(500, 'AI_SAVE_ERROR', 'AI分析を保存できませんでした。再試行してください。') from None
        except SettingsFailure as exc:
            logger.warning('AI_FAILED project=%s platform=%s code=%s elapsed=%.2f', project_id,
                           filters.platform or 'ALL', exc.code, monotonic() - started)
            raise
