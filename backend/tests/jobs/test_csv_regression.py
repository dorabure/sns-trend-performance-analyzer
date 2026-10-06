import pytest
from sqlalchemy import select
from app.db.models import PostMetric,AccountMetric,ImportHistory,SNSPost
from app.providers.base import CsvDatasetType
from tests.imports.conftest import context
from tests.providers.helpers import row,csv_text


@pytest.mark.parametrize('dataset',[CsvDatasetType.OWN_POSTS,CsvDatasetType.ACCOUNT_DAILY])
def test_csv_stays_synchronous_and_all_job_fields_null(context,tmp_path,dataset):
    path=tmp_path/'demo.csv'
    path.write_text(csv_text(dataset,[row(dataset)]),encoding='utf-8')
    identifier,started=context.service.start(context.project_id,dataset,path.name)
    result=context.service.run(identifier,started,context.project_id,dataset,path)
    assert result.status=='SUCCESS'
    with context.factory() as s:
        assert s.get(ImportHistory,identifier).job_run_id is None
        query=(select(PostMetric).join(SNSPost).where(SNSPost.project_id==context.project_id)
               if dataset==CsvDatasetType.OWN_POSTS else select(AccountMetric).where(AccountMetric.account_id==context.own_id))
        metrics=list(s.scalars(query))
        assert len(metrics)==1
        assert metrics[0].ingest_key is None and metrics[0].ingest_job_run_id is None
