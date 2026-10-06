"use client";
import Link from 'next/link';
import { useProjectScope, useFeatureProject, FeatureGate } from './project-scope';
import { t as tr, displayLabel, intlLocale, errorText } from '../i18n';
import { useLocale } from '../i18n/react';

import { scopedCriteria, period, parseCriteria, normalized, formCriteria, validPeriod, criteriaQuery, replaceQuery } from '../lib/analysis-filters';

import { FormEvent, ReactNode, useEffect, useRef, useState } from 'react';
import { api, ApiError, Project } from '../lib/api';
import { Criteria, EvidenceItem, Insight, insightsApi, Latest } from '../lib/insights-api';
import { Section, InsightReport } from './ai-report';
import { AIHistory } from './ai-history';

const message = (e: unknown) => e instanceof ApiError ? e.message : tr('error.unexpected');
function Field({ label, children }: { label: string; children: ReactNode }) {
  useLocale();
  return <label className="grid gap-2 text-sm font-medium text-slate-700">{displayLabel(label)}{children}</label>;
}
export default function AIInsightsPage() {
  useLocale();
  const scope = useProjectScope();
  const [initial, setInitial] = useState<Criteria | null>(null);
  useEffect(() => { setInitial({...parseCriteria(new URLSearchParams(window.location.search))}); },[]);
  const project = useFeatureProject('insights');
  return <main className="mx-auto max-w-7xl px-5 py-10"><header className="mb-8 flex flex-wrap justify-between gap-5"><div>
    <p className="text-xs font-bold tracking-widest text-teal-700">SNS TREND &amp; PERFORMANCE ANALYZER</p><h1 className="mt-3 text-3xl font-bold">{tr('nav.insights')}</h1>
    <p className="mt-2 text-slate-600">{tr('ai.description')}</p></div>
    <nav aria-label={tr('common.primaryNav')} className="flex flex-wrap gap-4 text-sm text-teal-800 underline">
      {['Overview','My Account','Trend Explorer','Competitor','Gap Analysis'].map((label,i) => <Link key={displayLabel(label)} href={`${['/dashboard','/dashboard/account','/dashboard/trends','/dashboard/competitors','/dashboard/gap'][i]}${initial ? `?${new URLSearchParams(initial)}` : ''}`}>{displayLabel(label)}</Link>)}
      <span className="font-bold" aria-current="page">{tr('nav.insights')}</span><Link href="/dashboard/settings">{tr('nav.settings')}</Link></nav></header>

    {scope.error ? <div role="alert">{scope.error}<button onClick={() => void scope.reload()}>{tr('common.retry')}</button></div> : scope.loading || !initial ? <Loading/> : project ?
      <FeatureGate feature="insights"><Analysis key={project.project_id} project={project} initial={normalized(project, initial)} onCriteria={setInitial}/></FeatureGate> :
      <p>{tr('common.createProjectFirst')}<Link href="/dashboard/settings" className="underline">{tr('common.goSettings')}</Link></p>}
    <p className="mt-8 text-sm text-slate-600">{tr('ai.supportOnly')}</p>
  </main>;
}
function Loading() {
  useLocale(); return <div role="status" aria-label={tr('common.loadingLabel')} className="animate-pulse rounded-xl bg-slate-100 p-6">{tr('common.loading')}</div>; }
function Analysis({ project, initial, onCriteria }: { project: Project; initial: Criteria; onCriteria: (c: Criteria) => void }) {
  useLocale();
  const [draft, setDraft] = useState(initial), [criteria, setCriteria] = useState(initial), [preset, setPreset] = useState('custom');
  const [data, setData] = useState<Latest | null>(null), [loading, setLoading] = useState(true), [generating, setGenerating] = useState(false), [error, setError] = useState('');
  const version = useRef(0), busy = useRef(false);
  const [refresh, setRefresh] = useState(0);
  const [historyRefresh, setHistoryRefresh] = useState(0);
  useEffect(() => {
    const token = ++version.current; busy.current = false; setGenerating(false); setData(null); setError(''); setLoading(true);
    replaceQuery(criteriaQuery(scopedCriteria(project,criteria)));
    onCriteria(criteria);
    insightsApi.latest(project.project_id, scopedCriteria(project,criteria)).then(value => { if (version.current === token) setData(value); })
      .catch(e => { if (version.current === token) setError(message(e)); }).finally(() => { if (version.current === token) setLoading(false); });
    return () => { ++version.current; };
  }, [project.project_id, criteria, refresh, onCriteria]);
  const change = (next: Criteria) => {
    // Clear/invalidate immediately at the event boundary, before a new request effect runs.
    ++version.current; busy.current = false; setData(null); setError(''); setGenerating(false); setLoading(true);
    setCriteria(next); onCriteria(next);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const next = formCriteria(e.currentTarget as HTMLFormElement, draft);
    if (!validPeriod(next)) { setError(tr('validation.period')); return; }
    setDraft(next); change(normalized(project, next)); setRefresh(v => v + 1);
  };
  const generate = async () => {
    if (busy.current || !data?.ai_generation_available) return;
    busy.current = true; const token = ++version.current; setGenerating(true); setError('');
    try { const insight = await insightsApi.generate(project.project_id, scopedCriteria(project,criteria)); if (version.current === token) { setData({ insight, ai_generation_available: true }); setHistoryRefresh(v => v + 1); } }
    catch (e) { if (version.current === token) setError(message(e)); }
    finally { if (version.current === token) { busy.current = false; setGenerating(false); } }
  };
  const insight = data?.insight;
  return <div className="space-y-6"><Section title={tr('analysis.conditions')}><form onSubmit={submit} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
    <Field label={tr('common.platform')}><select value={draft.platform} onChange={e => { const next = { ...draft, platform: e.target.value }; setDraft(next); change(next); }}><option value="ALL">{tr('common.allPlatforms')}</option><option value="X" disabled={!project.platforms.includes('X')}>X</option><option value="INSTAGRAM" disabled={!project.platforms.includes('INSTAGRAM')}>Instagram</option></select></Field>
    <Field label={tr('common.period')}><select value={preset} onChange={e => { setPreset(e.target.value); if (e.target.value !== 'custom') { const next = { ...draft, ...period(Number(e.target.value)) }; setDraft(next); change(next); } }}><option value="7">{tr('common.last7')}</option><option value="30">{tr('common.last30')}</option><option value="90">{tr('common.last90')}</option><option value="custom">{tr('common.custom')}</option></select></Field>
    {(['from','to'] as const).map(name => <Field key={name} label={name === 'from' ? tr('common.from') : tr('common.to')}><input type="date" name={name} required value={draft[name]} onChange={e => { setPreset('custom'); setDraft(c => ({ ...c, [name]: e.target.value })); }}/></Field>)}
    <div className="flex gap-2"><button type="submit" disabled={loading || generating} className="primary">{tr('common.search')}</button><button type="button" disabled={loading || generating} onClick={() => { ++version.current; setData(null); setRefresh(v => v + 1); }}>{tr('common.refresh')}</button></div>
  </form><p className="mt-4 text-sm text-slate-500">{tr('ai.filterNote')}</p></Section>
  {loading && <Loading/>}
  {error && <div role="alert" className="rounded-lg bg-red-50 p-4 text-red-800">{error}<button className="ml-3" onClick={() => data ? void generate() : setRefresh(v => v + 1)} disabled={generating}>{tr('common.tryAgain')}</button></div>}
  {data && <Section title={tr('ai.latestReport')}><div className="flex flex-wrap items-center justify-between gap-4"><p className="text-sm">{tr('label.analysisPeriod')} {criteria.from}〜{criteria.to} / {scopedCriteria(project,criteria).platform}</p>
    <button className="primary" disabled={generating || !data.ai_generation_available} onClick={() => void generate()}>{generating ? (insight ? tr('ai.regenerating') : tr('ai.generating')) : insight ? tr('ai.regenerate') : tr('ai.generate')}</button></div>
    {!data.ai_generation_available && <p role="status" className="mt-4 rounded-lg bg-amber-50 p-4">{tr('ai.keyMissing')}</p>}
    {generating && <p role="status" className="mt-4" aria-label={insight ? tr('ai.regeneratingLabel') : tr('ai.generatingLabel')}>{insight ? tr('ai.keepSaved') : tr('ai.wait')}</p>}
    {!insight && <p className="mt-5 text-slate-600">{tr('ai.noReport')}<Link className="ml-2 underline" href="/dashboard/settings?tab=import">{tr('common.goSettings')}</Link></p>}
    {insight && <><p className="mt-4 text-xs text-slate-500">{tr('label.lastGenerated')} {insight.generated_at} / {insight.model_name ?? '—'} / {insight.prompt_version ?? '—'}</p><h3 className="mt-6 font-semibold">{tr('overview.ai')}</h3><p className="mt-3 whitespace-pre-wrap">{insight.content?.summary ?? tr('ai.legacy')}</p></>}
  </Section>}
  <AIHistory project={project} criteria={criteria} refresh={refresh + historyRefresh}/>
  {insight && <InsightReport key={insight.insight_id} insight={insight}/>}
  </div>;
}

