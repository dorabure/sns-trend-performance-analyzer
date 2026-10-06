"use client";
import Link from 'next/link';
import { useProjectScope, useFeatureProject, FeatureGate } from './project-scope';
import { t as tr, displayLabel, intlLocale, errorText, ratePostCount } from '../i18n';
import { useLocale } from '../i18n/react';

import { scopedCriteria, period, parseCriteria, normalized, formCriteria, validPeriod, criteriaQuery, replaceQuery } from '../lib/analysis-filters';
import { useRead } from '../lib/use-analysis-read';

import { FormEvent, ReactNode, useCallback, useEffect, useState } from 'react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api, ApiError, Project } from '../lib/api';
import { overviewApi, Overview, Summary, CountKPI } from '../lib/overview-api';
import { RateGroup } from '../lib/my-account-api';

type Criteria = { platform: string; from: string; to: string };
const show = (n: number | null) => n === null ? '—' : n.toLocaleString(intlLocale(), { maximumFractionDigits: 4 });
const percent = (n: number | null) => n === null ? '—' : `${show(n)}%`;
function Field({ label, children }: { label: string; children: ReactNode }) {
  useLocale();
  return <label className="grid gap-2 text-sm font-medium text-slate-700">{displayLabel(label)}{children}</label>;
}
function Section({ title, children }: { title: string; children: ReactNode }) {
  useLocale();
  return <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="mb-5 text-lg font-semibold">{title}</h2>{children}</section>;
}
function Empty({ children }: { children: ReactNode }) {
  useLocale(); const {selectedMode} = useProjectScope();
  return <p className="text-sm text-slate-600">{selectedMode === 'LIVE' ? tr('availability.NoData') : children} <Link className="text-teal-800 underline" href={selectedMode === 'LIVE' ? '/dashboard/settings?tab=providers' : '/dashboard/settings?tab=import'}>{tr('common.goSettings')}</Link></p>;
}
function Status({ state, children }: { state: { loading: boolean; error: string; reload: () => Promise<void> }; children: ReactNode }) {
  useLocale();
  if (state.loading) return <div role="status" aria-label={tr('common.loadingLabel')} className="animate-pulse space-y-3"><div className="h-8 rounded bg-slate-100"/><div className="h-32 rounded bg-slate-100"/><p>{tr('common.loading')}</p></div>;
  if (state.error) return <div role="alert" className="rounded bg-red-50 p-4 text-red-800">{state.error}<button className="ml-3" onClick={() => void state.reload()}>{tr('common.retry')}</button></div>;
  return <>{children}</>;
}
export default function OverviewPage() {
  useLocale();
  const scope = useProjectScope(); const projects = {data:scope.projects,loading:scope.loading,error:scope.error,reload:scope.reload};
  const [initial, setInitial] = useState<Criteria | null>(null);
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    setInitial({ ...parseCriteria(p) });
  }, []);
  const project = useFeatureProject('overview');
  return <main className="mx-auto max-w-7xl px-5 py-10">
    <header className="mb-8 flex flex-wrap justify-between gap-5"><div><p className="text-xs font-bold tracking-widest text-teal-700">SNS TREND &amp; PERFORMANCE ANALYZER</p><h1 className="mt-3 text-3xl font-bold">{tr('nav.overview')}</h1><p className="mt-2 text-slate-600">{tr('overview.description')}</p></div>
      <nav aria-label={tr('common.primaryNav')} className="flex flex-wrap gap-4 text-sm text-teal-800 underline"><span aria-current="page" className="font-bold">{tr('nav.overview')}</span><Link href={`/dashboard/gap${initial ? `?${new URLSearchParams(initial)}` : ""}`}>{tr('nav.gap')}</Link><Link href={`/dashboard/account${initial ? `?${new URLSearchParams(initial)}` : ""}`}>{tr('nav.account')}</Link><Link href={`/dashboard/trends${initial ? `?${new URLSearchParams(initial)}` : ""}`}>{tr('nav.trends')}</Link><Link href={`/dashboard/competitors${initial ? `?${new URLSearchParams(initial)}` : ""}`}>{tr('nav.competitor')}</Link><Link href={`/dashboard/insights${initial ? `?${new URLSearchParams(initial)}` : ""}`}>{tr('nav.insights')}</Link><Link href="/dashboard/settings">{tr('nav.settings')}</Link><Link href="/">{tr('nav.health')}</Link></nav></header>

    <Status state={projects}>{!initial ? <p role="status">{tr('common.loading')}</p> : project ? <FeatureGate feature="overview"><Analysis key={project.project_id} project={project} initial={normalized(project, initial)} onCriteria={setInitial}/></FeatureGate> : <Empty>{tr('common.createProjectFirst')}</Empty>}</Status>
  </main>;
}

function Analysis({ project, initial, onCriteria }: { project: Project; initial: Criteria; onCriteria: (c: Criteria) => void }) {
  useLocale();
  const [draft, setDraft] = useState(initial), [criteria, setCriteria] = useState(initial), [preset, setPreset] = useState('custom'), [validation, setValidation] = useState('');
  const q = criteriaQuery(scopedCriteria(project,criteria));
  useEffect(() => { replaceQuery(q); onCriteria(criteria); }, [q, criteria, onCriteria]);
  const read = useRead(useCallback(() => overviewApi(project.project_id, q), [project.project_id, q]));
  const submit = (e: FormEvent) => {
    e.preventDefault(); const actual = formCriteria(e.currentTarget as HTMLFormElement, draft);
    if (!validPeriod(actual)) { setValidation(tr('validation.period')); return; }
    setValidation(''); setDraft(actual); setCriteria(actual); onCriteria(actual);
    const url = new URL(window.location.href); url.search = new URLSearchParams(actual).toString(); window.history.replaceState(null, '', url);
  };
  return <div className="space-y-6">
    <Section title={tr('analysis.conditions')}><form onSubmit={submit} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Field label={tr('common.platform')}><select value={draft.platform} onChange={e => setDraft(c => ({ ...c, platform: e.target.value }))}><option value="ALL">{tr('common.allPlatforms')}</option><option value="X" disabled={!project.platforms.includes('X')}>X</option><option value="INSTAGRAM" disabled={!project.platforms.includes('INSTAGRAM')}>Instagram</option></select></Field>
      <Field label={tr('common.period')}><select value={preset} onChange={e => { setPreset(e.target.value); if (e.target.value !== 'custom') setDraft(c => ({ ...c, ...period(Number(e.target.value)) })); }}><option value="7">{tr('common.last7')}</option><option value="30">{tr('common.last30')}</option><option value="90">{tr('common.last90')}</option><option value="custom">{tr('common.custom')}</option></select></Field>
      {(['from', 'to'] as const).map(name => <Field key={name} label={name === 'from' ? tr('common.from') : tr('common.to')}><input type="date" name={name} required value={draft[name]} onChange={e => { setPreset('custom'); setDraft(c => ({ ...c, [name]: e.target.value })); }}/></Field>)}
      <div className="flex gap-2"><button className="primary" type="submit" disabled={read.loading}>{tr('common.search')}</button><button type="button" disabled={read.loading} onClick={() => void read.reload()}>{tr('common.refresh')}</button></div>
    </form>{validation && <p role="alert" className="mt-3 text-red-800">{validation}</p>}
      <p className="mt-4 text-sm text-slate-500">{tr('overview.filterNote')}</p>
    </Section>
    <Status state={read}>{read.data && <Dashboard data={read.data} query={q}/>}</Status>
  </div>;
}

function RateGroups({ groups }: { groups: RateGroup[] }) {
  useLocale();
  return <ul className="mt-2 space-y-1 text-xs text-slate-600">{groups.map(g => <li key={`${g.platform}-${g.denominator_type}`}>{g.platform} / {displayLabel(g.denominator_type)}: {percent(g.avg_engagement_rate)} {ratePostCount(g.post_count)}</li>)}</ul>;
}
function CountCard({ title, kpi }: { title: string; kpi: CountKPI }) {
  useLocale();
  return <Section title={title}><p className="text-3xl font-bold">{show(kpi.value)}</p><p className="mt-3 text-sm text-slate-500">{tr('label.previousPeriod')} {show(kpi.previous_value)} {tr('label.change')} {show(kpi.change)} / {percent(kpi.change_rate)}</p></Section>;
}
function SummaryBlock({ title, value }: { title: string; value: Summary }) {
  useLocale();
  return <div className="rounded-lg bg-slate-50 p-4"><h3 className="font-semibold">{title}</h3><p className="mt-2 text-sm">{value.account_count} {tr('label.accounts')} {show(value.posts)} {tr('label.postsSuffix')}</p><p className="text-sm">{tr('label.averageEngagement')} {show(value.avg_engagement)}</p><p className="text-sm">{tr('label.averageEr')} {percent(value.avg_engagement_rate)}</p><RateGroups groups={value.rate_groups}/></div>;
}
function Dashboard({ data, query }: { data: Overview; query: string }) {
  useLocale();
  const k = data.kpis, opportunity = data.top_opportunity, ai = data.ai_summary;
  const summary = ai && typeof ai.content === 'object' && ai.content !== null && 'summary' in ai.content && typeof ai.content.summary === 'string' ? ai.content.summary : null;
  const href = (path: string) => `${path}?${query}`;
  return <div className="space-y-6">
    <p className="text-sm text-slate-600">{tr('overview.periodLabel')} {data.period.from}〜{data.period.to} {tr('label.utcPrevious')} {data.previous_period ? `${data.previous_period.from}〜${data.previous_period.to}` : tr('overview.noPrevious')}</p>
    {!k.posts.value && <Empty>{tr('overview.noOwn')}</Empty>}
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <CountCard title={tr('metric.totalReach')} kpi={k.reach}/>
      <Section title={tr('metric.rate')}><p className="text-3xl font-bold">{percent(k.engagement_rate.value)}</p>{k.engagement_rate.rate_groups.length > 1 && <p className="mt-2 text-sm">{tr('overview.mixed')}</p>}<RateGroups groups={k.engagement_rate.rate_groups}/><p className="mt-3 text-sm text-slate-500">{tr('label.previousPeriod')} {percent(k.engagement_rate.previous_value)} {tr('label.change')} {show(k.engagement_rate.change_point)}pt</p><RateGroups groups={k.engagement_rate.previous_rate_groups}/></Section>
      <Section title={tr('metric.followers')}><p className="text-3xl font-bold">{show(k.followers.value)}</p>{k.followers_by_account.length > 1 && <p className="mt-2 text-xs text-slate-500">{tr('overview.byAccount')}</p>}<ul className="mt-3 space-y-2 text-sm">{k.followers_by_account.map(a => <li key={a.account_id}>{a.platform} / {a.account_name}: {show(a.followers)}<span className="block text-xs text-slate-500">{a.recorded_date ?? tr('overview.noSnapshot')}</span></li>)}</ul><p className="mt-3 text-xs text-slate-500">{tr('label.previousPeriod')} {show(k.followers.previous_value)} / {percent(k.followers.change_rate)}</p></Section>
      <CountCard title={tr('metric.posts')} kpi={k.posts}/>
    </div>
    <div className="grid gap-4 md:grid-cols-2"><CountCard title={tr('metric.impressions')} kpi={k.impressions}/><CountCard title={tr('metric.engagement')} kpi={k.engagement}/></div>
    <div className="grid gap-6 xl:grid-cols-2">
      <Section title={tr('overview.performance')}><Performance data={data}/></Section>
      <Section title={tr('overview.topics')}><p className="mb-3 text-xs text-slate-500">{tr('overview.topNote')}</p>{data.top_trends.length ? <div className="overflow-auto"><table><thead><tr>{['Rank','Topic / SNS','Score / Date','Post Growth','Engagement Growth','Direction'].map(t => <th key={t}>{displayLabel(t)}</th>)}</tr></thead><tbody>{data.top_trends.map((t, i) => <tr key={`${t.topic_id}-${t.platform}`}><td>{i + 1}</td><td>{t.topic_name}<p className="text-xs">{t.platform}</p></td><td>{show(t.trend_score)}<p className="text-xs">{t.trend_date}</p></td><td>{percent(t.post_growth_rate)}</td><td>{percent(t.engagement_growth_rate)}</td><td>{displayLabel(t.trend_direction)}</td></tr>)}</tbody></table></div> : <Empty>{tr('overview.noTrend')}</Empty>}<Link className="mt-4 inline-block text-sm text-teal-800 underline" href={href('/dashboard/trends')}>{tr('overview.openTrends')}</Link></Section>
      <Section title={tr('overview.competitors')}><div className="grid gap-3 sm:grid-cols-2"><SummaryBlock title={tr('overview.own')} value={data.own_summary}/><SummaryBlock title={tr('overview.aggregate')} value={data.competitor_aggregate}/></div>{data.competitor_aggregate.account_count === 0 && <Empty>{tr('overview.noCompetitors')}</Empty>}<p className="mt-4 text-xs text-slate-500">{tr('overview.competitorNote')}</p><ul className="mt-3 space-y-3">{data.competitor_summary.map(a => <li key={a.account_id} className="rounded-lg border border-slate-200 p-3"><p className="font-semibold">{a.account_name} / {a.platform}</p><p className="text-sm">{tr('label.posts')} {show(a.posts)} {tr('label.averageEngagementSuffix')} {show(a.avg_engagement)} {tr('label.followers')} {show(a.followers)}</p><RateGroups groups={a.engagement_rate_groups}/></li>)}</ul><Link className="mt-4 inline-block text-sm text-teal-800 underline" href={href('/dashboard/competitors')}>{tr('overview.openCompetitor')}</Link></Section>
      <Section title={tr('overview.opportunity')}>{opportunity ? <><h3 className="text-xl font-bold">{opportunity.topic_name} / {opportunity.platform}</h3><dl className="mt-4 grid grid-cols-2 gap-3 text-sm">{[['Gap Score',show(opportunity.gap_score)],['Trend Score',show(opportunity.trend_score)],['Own Post Ratio',percent(opportunity.own_post_ratio)],['Competitor Post Ratio',percent(opportunity.competitor_post_ratio)],['Classification',opportunity.classification ?? tr('common.unavailable')]].map(([label, value]) => <div key={displayLabel(label)}><dt className="text-slate-500">{displayLabel(label)}</dt><dd className="mt-1 font-semibold">{displayLabel(value)}</dd></div>)}</dl><p className="mt-4 text-xs text-slate-500">{tr('overview.opportunityNote')}</p></> : <Empty>{tr('overview.noOpportunity')}</Empty>}<Link className="mt-4 inline-block text-sm text-teal-800 underline" href={href('/dashboard/gap')}>{tr('overview.openGap')}</Link></Section>
    </div>
    <Section title={tr('overview.ai')}>{ai ? <><p className="whitespace-pre-wrap text-slate-700">{summary ?? tr('overview.hasAi')}</p><p className="mt-3 text-sm text-slate-500">{ai.platform ?? 'ALL'} {tr('label.analysisPeriodSuffix')} {ai.analysis_from}〜{ai.analysis_to} {tr('label.created')} {ai.created_at}</p><p className="mt-2 text-xs text-slate-500">{ai.model_name ?? tr('overview.noModel')} / {ai.prompt_version ?? tr('overview.noVersion')}</p></> : <p className="text-sm text-slate-600">{tr('overview.noAi')}</p>}<Link className="mt-4 inline-block text-sm text-teal-800 underline" href={href("/dashboard/insights")}>{tr('overview.openAi')}</Link></Section>
  </div>;
}
function Performance({ data }: { data: Overview }) {
  useLocale();
  const [metric, setMetric] = useState<'reach' | 'engagement' | 'followers' | 'posts'>('reach');
  const followers = data.performance_trend.follower_series;
  // Only reshape the Backend series for Recharts; no summation or gap filling.
  const chart = metric === 'followers' ? data.performance_trend.daily.map((d, i) => ({ date: d.date, ...Object.fromEntries(followers.map(a => [a.account_id, a.values[i].followers])) })) : data.performance_trend.daily;
  const hasValues = metric === 'followers' ? followers.some(a => a.values.some(v => v.followers !== null)) : data.performance_trend.daily.some(d => metric === 'posts' ? d.posts > 0 : d[metric] !== null);
  const colors = ['#0f766e','#2563eb','#a16207','#7c3aed'];
  return <><div className="mb-4 flex flex-wrap gap-2">{(['reach','engagement','followers','posts'] as const).map(m => <button key={m} aria-pressed={metric === m} className={metric === m ? 'primary' : ''} onClick={() => setMetric(m)}>{displayLabel(m)}</button>)}</div>
    <p className="mb-3 text-xs text-slate-500">{tr('overview.chartNote')}</p>
    {!hasValues && <Empty>{tr('overview.noObservations')}</Empty>}
    <div className="h-80 min-w-0" role="img" aria-label={tr('chart.trend',{metric:displayLabel(metric)})}><ResponsiveContainer width="100%" height="100%"><LineChart data={chart} margin={{ top: 15, right: 20, left: 10, bottom: 10 }}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="date" tick={{ fontSize: 11 }}/><YAxis tick={{ fontSize: 11 }}/><Tooltip filterNull={false}/><Legend/>{metric === 'followers' ? followers.map((a, i) => <Line key={a.account_id} dataKey={a.account_id} name={`${a.platform} / ${a.account_name}`} stroke={colors[i % colors.length]} connectNulls={false} dot={{ r: 2 }}/>) : <Line dataKey={metric} name={displayLabel(metric)} stroke="#0f766e" connectNulls={false} dot={{ r: 2 }}/>}</LineChart></ResponsiveContainer></div>
  </>;
}
