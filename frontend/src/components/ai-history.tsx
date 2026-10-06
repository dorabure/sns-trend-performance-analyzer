"use client";
import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { ApiError, Project } from '../lib/api';
import { scopedCriteria } from '../lib/analysis-filters';
import { Criteria, InsightHistoryItem, InsightHistoryDetail, InsightComparePrevious } from '../lib/insights-api';
import { comparisonLabels, createHistoryController, historyScopeKey } from '../lib/insight-history';
import { t as tr, intlLocale, errorText } from '../i18n';
import { useLocale } from '../i18n/react';
import { Section, InsightReport } from './ai-report';

export function SnapshotMetadata({ snapshot }: { snapshot: InsightHistoryItem }) {
  useLocale();
  const time = new Date(snapshot.generated_at).toLocaleString(intlLocale(), { timeZone:'UTC', year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',timeZoneName:'short' });
  return <div className="min-w-0 space-y-2 text-sm [overflow-wrap:anywhere]">
    <p>{tr('ai.generatedAt')} <time dateTime={snapshot.generated_at}>{time}</time></p>
    <p>{snapshot.platform} / {snapshot.analysis_from}〜{snapshot.analysis_to}</p>
    <p className="break-all">{tr('ai.model')} {snapshot.model_name ?? '—'} / {tr('ai.prompt')} {snapshot.prompt_version ?? '—'}</p>
    <span className="inline-block rounded bg-slate-100 px-2 py-1" title={snapshot.is_legacy ? tr('ai.legacyRefs') : undefined}>{snapshot.is_legacy ? tr('ai.legacyBadge') : tr('ai.currentSchema')}</span>
  </div>;
}
function Snapshot({ snapshot, title }: { snapshot: InsightHistoryDetail; title: string }) {
  return <article className="min-w-0 space-y-4 [overflow-wrap:anywhere]">
    <h3 className="text-lg font-semibold">{title}</h3><SnapshotMetadata snapshot={snapshot}/>
    <p className="whitespace-pre-wrap">{snapshot.content?.summary ?? tr('ai.legacy')}</p>
    <InsightReport key={snapshot.insight_id} insight={snapshot} comparison/>
  </article>;
}
export function CompareReports({ value }: { value: InsightComparePrevious }) {
  useLocale();
  return <><div className="mb-5 flex flex-wrap gap-2" role="status">{comparisonLabels(value.comparison).map(key => <span key={key} className="rounded bg-teal-50 px-3 py-2 text-sm text-teal-900">{tr(key)}</span>)}</div>
    <div className="grid min-w-0 gap-6 lg:grid-cols-2"><Snapshot snapshot={value.current} title={tr('ai.selectedSnapshot')}/>
      {value.previous ? <Snapshot snapshot={value.previous} title={tr('ai.previousSnapshot')}/> : <div className="min-w-0"><h3 className="text-lg font-semibold">{tr('ai.previousSnapshot')}</h3><p className="mt-4">{tr('ai.noPrevious')}</p></div>}
    </div></>;
}
const safeError = (error: unknown) => error instanceof ApiError ? errorText(undefined,error.status) : tr('error.unexpected');
export function AIHistory({ project, criteria, refresh }: { project: Project; criteria: Criteria; refresh: number }) {
  useLocale();
  const effective = scopedCriteria(project,criteria);
  const scopeKey = historyScopeKey(project.project_id,effective);
  // A fresh controller's empty snapshot is used immediately during scope render.
  const controller = useMemo(() => createHistoryController(project.project_id,effective), [scopeKey]);
  const state = useSyncExternalStore(controller.subscribe,controller.snapshot,controller.snapshot);
  useEffect(() => { void controller.reload(); return () => controller.dispose(); }, [controller,refresh]);
  return <><Section title={tr('ai.history')}>
    <p className="mb-4 text-sm text-slate-600">{effective.platform} / {effective.from}〜{effective.to}</p>
    {state.loading && <p role="status">{tr('ai.historyLoading')}</p>}
    {Boolean(state.historyError) && <div role="alert" className="my-3 rounded bg-red-50 p-3 text-red-800">{tr('ai.historyError')} {safeError(state.historyError)} <button onClick={() => void controller.retryHistory()} disabled={state.loading}>{tr('common.retry')}</button></div>}
    {!state.loading && !state.historyError && !state.items.length && <p>{tr('ai.historyEmpty')}</p>}
    <ul className="grid gap-3 sm:grid-cols-2">{state.items.map(item => <li key={item.insight_id} className={`min-w-0 rounded-xl border p-4 ${state.selected === item.insight_id ? 'border-teal-600 bg-teal-50' : 'border-slate-200'}`}>
      <SnapshotMetadata snapshot={item}/><button className="mt-3 underline text-teal-900 focus-visible:outline-2 focus-visible:outline-offset-4" aria-current={state.selected === item.insight_id ? 'true' : undefined} onClick={() => void controller.select(item.insight_id)}>
        {state.selected === item.insight_id ? tr('ai.snapshotSelected') : tr('ai.viewCompare')}
      </button></li>)}</ul>
    {state.cursor && <button className="mt-5 primary" disabled={state.loading} onClick={() => void controller.loadMore()}>{tr('ai.historyLoadMore')}</button>}
  </Section>
    {state.selected && <Section title={tr('ai.compare')}>
      {state.comparing && <p role="status">{tr('ai.compareLoading')}</p>}
      {Boolean(state.compareError) && <div role="alert" className="rounded bg-red-50 p-3 text-red-800">{tr('ai.compareError')} {safeError(state.compareError)} <button onClick={() => void controller.retryCompare()} disabled={state.comparing}>{tr('common.retry')}</button></div>}
      {state.comparison && <CompareReports value={state.comparison}/>}
    </Section>}
  </>;
}
