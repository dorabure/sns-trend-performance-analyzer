from dataclasses import replace
from datetime import timedelta, datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from sqlalchemy import select, func, update
from app.db.models import (Project, SNSAccount, SNSPost, AccountMetric, PostMetric, JobRun, JobStep,
    ProviderConnection, ProviderSyncState, ImportHistory, WatchTopic, WatchTerm, PostTerm, PostTopic)
from app.jobs.runner import JobRunner
from app.providers.core import ProviderError, ProviderRegistry
from app.services.live_import_service import LiveImportService, ProviderSyncStateService
from app.services.provider_sync_handler import ProviderSyncHandler
from app.services.provider_service import ProviderService
from app.services.settings_service import SettingsFailure
from tests.provider_core.mocks import OBSERVED


def run(context):
    jid = context.jobs.create(context.project, 'LIVE', context.provider)
    assert JobRunner(context.jobs, context.handler).execute(jid) == 'SUCCESS'
    return jid


def counts(context):
    with context.factory() as s:
        return {model.__tablename__: s.scalar(select(func.count()).select_from(model).where(
            model.project_id == context.project)) for model in (SNSAccount, SNSPost, ImportHistory)} | {
            'post_metrics': s.scalar(select(func.count()).select_from(PostMetric).join(SNSPost).where(SNSPost.project_id == context.project)),
            'account_metrics': s.scalar(select(func.count()).select_from(AccountMetric).join(SNSAccount).where(SNSAccount.project_id == context.project))}


def test_mock_end_to_end_provenance_metrics_optional_and_matching(live_context):
    c = live_context
    with c.factory() as s, s.begin():
        topic = WatchTopic(project_id=c.project, topic_name='test topic')
        s.add(topic); s.flush()
        s.add(WatchTerm(topic_id=topic.topic_id, term='test topic', normalized_term='test topic', term_type='KEYWORD'))
    jid = run(c)
    assert counts(c) == {'sns_accounts':1,'sns_posts':2,'post_metrics':2,'account_metrics':1,'import_histories':2}
    with c.factory() as s:
        account = s.scalar(select(SNSAccount).where(SNSAccount.project_id == c.project))
        assert account.data_origin == c.kind and account.provider_connection_id == c.provider
        posts = list(s.scalars(select(SNSPost).where(SNSPost.project_id == c.project)))
        assert all(p.source_type == 'OWN' and p.data_origin == c.kind and p.account_id == account.account_id for p in posts)
        for p in posts:
            assert s.scalar(select(PostTerm.post_id).where(PostTerm.post_id == p.post_id)) is not None
            assert s.scalar(select(PostTopic.post_id).where(PostTopic.post_id == p.post_id)) is not None
        pm = list(s.scalars(select(PostMetric).where(PostMetric.post_id.in_([p.post_id for p in posts]))))
        assert all(p.ingest_key and p.ingest_job_run_id == jid and p.recorded_at == OBSERVED for p in pm)
        am = s.scalar(select(AccountMetric).where(AccountMetric.account_id == account.account_id))
        assert am.followers == 0 and am.following is None and am.ingest_key and am.ingest_job_run_id == jid
        history = list(s.scalars(select(ImportHistory).where(ImportHistory.job_run_id == jid)))
        assert all(h.data_origin == c.kind and h.provider_connection_id == c.provider for h in history)
        steps = list(s.scalars(select(JobStep).where(JobStep.job_run_id == jid).order_by(JobStep.sequence_no)))
        assert [p.status for p in steps] == ['SUCCESS','SUCCESS','SKIPPED','SKIPPED']
        assert steps[2].result_summary['reason'] == 'capability_unavailable'
        assert steps[3].result_summary['reason'] == 'phase_not_enabled'
        states = list(s.scalars(select(ProviderSyncState).where(ProviderSyncState.provider_connection_id == c.provider)))
        assert {p.sync_resource_type for p in states} == {'ACCOUNT','POSTS','METRICS'}
        assert next(p for p in states if p.sync_resource_type == 'POSTS').cursor is not None
        provider = s.get(ProviderConnection,c.provider)
        assert provider.connection_status == 'CONNECTED' and provider.last_error_code is None and provider.last_record_count == 3


def test_redelivery_and_new_job_same_snapshot(live_context):
    c = live_context
    first = run(c)
    calls = c.remote.calls
    assert JobRunner(c.jobs,c.handler).execute(first) == 'NO_OP'
    assert c.remote.calls == calls
    second = run(c)
    assert second != first
    assert counts(c) == {'sns_accounts':1,'sns_posts':2,'post_metrics':2,'account_metrics':1,'import_histories':4}


def test_new_observation_keeps_posts_adds_snapshot_preserves_daily(live_context):
    c = live_context
    run(c)
    c.remote.observation = OBSERVED + timedelta(hours=1)
    run(c)
    assert counts(c)['post_metrics'] == 4
    assert counts(c)['sns_posts'] == 2 and counts(c)['account_metrics'] == 1


def test_cursor_after_commit_and_import_failure_keeps_cursor(live_context):
    c = live_context
    original = LiveImportService(c.factory)
    class CheckingStates(ProviderSyncStateService):
        def checkpoint(self, *args):
            assert counts(c)['sns_posts'] == 2  # A separate connection observes committed data.
            super().checkpoint(*args)
    c.handler.states = CheckingStates(c.factory)
    run(c)
    class BadImport:
        def import_data(self,*args):
            raise ProviderError('PROVIDER_IMPORT_FAILED')
    c.handler.importer = BadImport()
    jid = c.jobs.create(c.project,'LIVE',c.provider)
    assert JobRunner(c.jobs,c.handler).execute(jid) == 'FAILED'
    with c.factory() as s:
        states = list(s.scalars(select(ProviderSyncState).where(ProviderSyncState.provider_connection_id == c.provider)))
        assert all(p.last_success_at == OBSERVED for p in states)
        assert s.get(JobRun,jid).error_code == 'PROVIDER_IMPORT_FAILED'
    c.handler.importer = original


def test_checkpoint_failure_business_is_idempotent(live_context):
    c = live_context
    class FailedCheckpoint:
        def checkpoint(self,*args):
            raise ProviderError('PROVIDER_CHECKPOINT_FAILED')
    c.handler.states = FailedCheckpoint()
    jid = c.jobs.create(c.project,'LIVE',c.provider)
    assert JobRunner(c.jobs,c.handler).execute(jid) == 'FAILED'
    assert counts(c)['sns_posts'] == 2
    with c.factory() as s:
        assert not list(s.scalars(select(ProviderSyncState).where(ProviderSyncState.provider_connection_id == c.provider)))
    c.handler.states = ProviderSyncStateService(c.factory)
    run(c)
    assert counts(c)['post_metrics'] == 2


@pytest.mark.parametrize('failure', ['PROVIDER_AUTH_FAILED','PROVIDER_PERMISSION_DENIED','PROVIDER_NOT_CONFIGURED'])
def test_provider_failure_safe_job_state(live_context, failure):
    c = live_context
    c.remote.failure = failure
    jid = c.jobs.create(c.project,'LIVE',c.provider)
    assert JobRunner(c.jobs,c.handler).execute(jid) == 'FAILED'
    with c.factory() as s:
        steps = list(s.scalars(select(JobStep).where(JobStep.job_run_id == jid).order_by(JobStep.sequence_no)))
        assert [p.status for p in steps] == ['FAILED','SKIPPED','SKIPPED','SKIPPED']
        assert steps[0].error_code == failure
        assert s.get(ProviderConnection,c.provider).last_error_code == failure
    assert counts(c)['sns_posts'] == 0


def test_scope_platform_and_rollback(live_context):
    c = live_context
    jid = c.jobs.create(c.project,'LIVE',c.provider)
    c.jobs.claim(jid)
    account = c.remote.fetch_account(None)
    profile, metric = c.remote.normalizer().normalize_account(account, OBSERVED)
    posts = c.remote.normalizer().normalize_posts(c.remote.fetch_posts(None, account).records, account)
    bad = replace(posts[1], platform='WRONG')
    with pytest.raises(ProviderError,match='PROVIDER_SCOPE_INVALID'):
        LiveImportService(c.factory).import_data(jid,profile,metric,[posts[0],bad],OBSERVED)
    assert counts(c)['sns_posts'] == 0 and counts(c)['sns_accounts'] == 0


def test_existing_wrong_provider_account_rejected(live_context):
    c = live_context
    with c.factory() as s, s.begin():
        s.add(SNSAccount(project_id=c.project,platform='X' if c.kind=='X_API' else 'INSTAGRAM',account_name='unrelated',account_role='OWN',platform_account_id='other',data_origin='DEMO_CSV'))
    jid = c.jobs.create(c.project,'LIVE',c.provider)
    assert JobRunner(c.jobs,c.handler).execute(jid) == 'FAILED'
    assert counts(c)['sns_posts'] == 0
    with c.factory() as s:
        assert s.get(JobRun,jid).error_code == 'PROVIDER_SCOPE_INVALID'


def test_default_registry_and_live_disabled_never_fetch(live_context):
    c = live_context
    c.handler.registry = ProviderRegistry({})
    jid = c.jobs.create(c.project,'LIVE',c.provider)
    assert JobRunner(c.jobs,c.handler).execute(jid) == 'FAILED'
    with c.factory() as s:
        assert s.get(JobRun,jid).error_code == 'PROVIDER_NOT_IMPLEMENTED'
    c.handler.enabled = lambda: False
    jid = c.jobs.create(c.project,'LIVE',c.provider)
    assert JobRunner(c.jobs,c.handler).execute(jid) == 'FAILED'
    with c.factory() as s:
        assert s.get(JobRun,jid).error_code == 'LIVE_MODE_DISABLED'
    assert c.remote.calls == 0


def test_validate_capabilities_and_disabled_contract(live_context):
    c = live_context
    service = ProviderService(c.factory,registry=c.registry,resolver=c.resolver,enabled=lambda:True)
    response = service.validate(c.project,c.kind)
    assert response['valid'] and response['credential_configured'] and response['connection_status']=='CONNECTED'
    assert 'credential_ref' not in response and 'test-only-' not in str(response)
    caps = service.capabilities(c.project,c.kind)['capabilities']
    assert len(caps)==6 and caps['OWN_POSTS'] and not caps['MARKET_POSTS']
    with c.factory() as s,s.begin():
        s.get(ProviderConnection,c.provider).enabled=False
    assert service.validate(c.project,c.kind)['connection_status']=='DISABLED'
    with c.factory() as s:
        assert s.get(ProviderConnection,c.provider).enabled is False


@pytest.mark.parametrize('failure',['PROVIDER_AUTH_FAILED','PROVIDER_PERMISSION_DENIED'])
def test_validate_failure_persists_safe_state(live_context,failure):
    c=live_context;c.remote.failure=failure
    service=ProviderService(c.factory,registry=c.registry,resolver=c.resolver,enabled=lambda:True)
    with pytest.raises(SettingsFailure) as error:
        service.validate(c.project,c.kind)
    assert error.value.code==failure
    with c.factory() as s:
        assert s.get(ProviderConnection,c.provider).connection_status=='ERROR'


@pytest.mark.parametrize('index,end,expected',[(0,'FAILED','FAILED'),(1,'FAILED','FAILED'),(0,'CANCELED','FAILED'),(1,'CANCELED','FAILED'),(2,'FAILED','PARTIAL_ERROR'),(3,'FAILED','PARTIAL_ERROR'),(2,'PARTIAL_ERROR','PARTIAL_ERROR'),(3,'PARTIAL_ERROR','PARTIAL_ERROR'),(2,'SKIPPED','SUCCESS'),(3,'SKIPPED','SUCCESS')])
def test_formal_final_status(live_context,index,end,expected):
    c=live_context;jid=c.jobs.create(c.project,'LIVE',c.provider);c.jobs.claim(jid)
    for i,kind in enumerate(['PROVIDER_SYNC','NORMALIZE_IMPORT','TREND_REBUILD','AI_INSIGHT_GENERATE']):
        target=end if i==index else 'SUCCESS'
        if target not in ('SKIPPED','CANCELED'):
            c.jobs.transition_step(jid,kind,'RUNNING')
        c.jobs.transition_step(jid,kind,target)
    assert c.jobs.finish(jid)==expected


def test_heartbeat_stale_recovery_redelivery_and_new_job(live_context):
    c=live_context;jid=c.jobs.create(c.project,'LIVE',c.provider);c.jobs.claim(jid)
    c.jobs.transition_step(jid,'PROVIDER_SYNC','RUNNING')
    now=datetime.now(timezone.utc)
    assert c.jobs.heartbeat(jid,now)
    assert c.jobs.recover_stale(now=now+timedelta(seconds=899))==0
    assert c.jobs.recover_stale(now=now+timedelta(seconds=901))==1
    assert not c.jobs.heartbeat(jid)
    assert JobRunner(c.jobs,c.handler).execute(jid)=='NO_OP'
    assert c.remote.calls==0
    with c.factory() as s:
        job=s.get(JobRun,jid)
        assert job.status=='FAILED' and job.error_code=='WORKER_HEARTBEAT_TIMEOUT'
        steps=list(s.scalars(select(JobStep).where(JobStep.job_run_id==jid).order_by(JobStep.sequence_no)))
        assert [p.status for p in steps]==['FAILED','SKIPPED','SKIPPED','SKIPPED']
    assert c.jobs.create(c.project,'LIVE',c.provider)!=jid


def test_locked_stale_job_skipped_then_recovered(live_context):
    c=live_context;jid=c.jobs.create(c.project,'LIVE',c.provider);c.jobs.claim(jid)
    now=datetime.now(timezone.utc)+timedelta(seconds=901)
    with c.factory() as s,s.begin():
        s.scalar(select(JobRun).where(JobRun.id==jid).with_for_update())
        with ThreadPoolExecutor(1) as pool:
            assert pool.submit(c.jobs.recover_stale,now).result(timeout=5)==0
    assert c.jobs.recover_stale(now=now)==1


def test_running_duplicate_only_one_fetch(live_context):
    c=live_context;jid=c.jobs.create(c.project,'LIVE',c.provider)
    entered,release=Event(),Event()
    original=c.remote.fetch_account
    def fetch(context):
        entered.set();assert release.wait(10)
        return original(context)
    c.remote.fetch_account=fetch
    runner=JobRunner(c.jobs,c.handler)
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(runner.execute,jid);assert entered.wait(10)
        second=pool.submit(runner.execute,jid)
        try:
            assert second.result(timeout=5)=='NO_OP'
        finally:
            release.set()
        assert first.result(timeout=10)=='SUCCESS'
    assert c.remote.calls==2


def test_normalizer_failure_marks_required_step_failed(live_context):
    c=live_context
    class InvalidNormalizer:
        def normalize_account(self,*args):
            raise ProviderError('PROVIDER_RESPONSE_INVALID')
    c.handler.registry=ProviderRegistry({c.kind:lambda:(c.remote,InvalidNormalizer())})
    jid=c.jobs.create(c.project,'LIVE',c.provider)
    assert JobRunner(c.jobs,c.handler).execute(jid)=='FAILED'
    with c.factory() as s:
        steps=list(s.scalars(select(JobStep).where(JobStep.job_run_id==jid).order_by(JobStep.sequence_no)))
        assert [p.status for p in steps]==['SUCCESS','FAILED','SKIPPED','SKIPPED']
    assert counts(c)['sns_posts']==0


def test_optional_trend_failure_keeps_import_and_partial_error(live_context):
    from app.providers.core import ProviderCapability
    c=live_context
    original=c.remote.capabilities
    c.remote.capabilities=lambda:original() | {ProviderCapability.TREND_DATA}
    def failed_trend(pid):
        raise RuntimeError('test-only-sensitive-error')
    c.handler.trend=failed_trend
    jid=c.jobs.create(c.project,'LIVE',c.provider)
    assert JobRunner(c.jobs,c.handler).execute(jid)=='PARTIAL_ERROR'
    assert counts(c)['sns_posts']==2
    with c.factory() as s:
        steps=list(s.scalars(select(JobStep).where(JobStep.job_run_id==jid).order_by(JobStep.sequence_no)))
        assert [p.status for p in steps]==['SUCCESS','SUCCESS','FAILED','SKIPPED']
        assert 'test-only-' not in str(steps[2].error_summary)


def test_cross_project_provider_job_rejected_before_fetch(live_context):
    c=live_context
    with c.factory() as s,s.begin():
        other=Project(name='Other isolated project',data_mode='LIVE');s.add(other);s.flush()
        other_id=other.project_id
    try:
        jid=c.jobs.create(c.project,'LIVE',c.provider)
        with c.factory() as s,s.begin():
            s.get(JobRun,jid).project_id=other_id
        assert JobRunner(c.jobs,c.handler).execute(jid)=='FAILED'
        assert c.remote.calls==0
        with c.factory() as s:
            assert s.get(JobRun,jid).error_code=='PROVIDER_SCOPE_INVALID'
    finally:
        from sqlalchemy import delete
        with c.factory() as s,s.begin():
            s.execute(delete(Project).where(Project.project_id==other_id))


def test_fetch_account_id_mismatch_rejected(live_context):
    from app.providers.core import ProviderPage
    c=live_context
    original=c.remote.fetch_posts
    def invalid(context, account):
        page=original(context, account)
        return ProviderPage([replace(p,remote_account_id='another-account') for p in page.records])
    c.remote.fetch_posts=invalid
    jid=c.jobs.create(c.project,'LIVE',c.provider)
    assert JobRunner(c.jobs,c.handler).execute(jid)=='FAILED'
    assert counts(c)['sns_posts']==0
