"use client";
import Link from 'next/link';
import { useProjectScope, useFeatureProject, FeatureGate } from './project-scope';
import { t as tr, displayLabel, intlLocale, errorText, countText } from '../i18n';
import { useLocale } from '../i18n/react';
import { classificationColors as colors, scatterSeries } from '../lib/gap-scatter';
import OverviewLink from './overview-link';
import AIInsightsLink from './ai-insights-link';

import { scopedCriteria, period, parseCriteria, normalized, formCriteria, validPeriod, criteriaQuery, replaceQuery } from '../lib/analysis-filters';
import { useRead } from '../lib/use-analysis-read';

import { FormEvent, ReactNode, useCallback, useEffect, useState } from 'react';
import { CartesianGrid, Cell, ReferenceArea, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts';
import { api, ApiError, Project } from '../lib/api';
import { Classification, GapAnalysis, gapAnalysisApi, GapItem } from '../lib/gap-analysis-api';

type Criteria = { platform: string; from: string; to: string };
const show = (n: number | null) => n === null ? '—' : n.toLocaleString(intlLocale(), { maximumFractionDigits: 4 });
const percent = (n: number | null) => n === null ? '—' : `${show(n)}%`;
const descriptions: Record<Classification, string> = {
  OPPORTUNITY: 'gap.opportunityDescription', BALANCED: 'gap.balancedDescription',
  HIGH_COVERAGE: 'gap.highCoverageDescription', LOW_PRIORITY: 'gap.lowPriorityDescription',
};
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
function Badge({ value }: { value: Classification | null }) {
  useLocale();
  return value ? <span className="inline-block rounded px-2 py-1 text-xs font-semibold" style={{ color: colors[value], background: `${colors[value]}15` }}>{displayLabel(value)}</span> : <span className="text-sm text-slate-500">{tr('common.unavailable')}</span>;
}

export default function GapAnalysisPage() {
  useLocale();
  const scope = useProjectScope(); const projects = {data:scope.projects,loading:scope.loading,error:scope.error,reload:scope.reload};
  const [initial, setInitial] = useState<Criteria | null>(null);
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    setInitial({ ...parseCriteria(p) });
  }, []);
  const project = useFeatureProject('gap');
  return <main className="mx-auto max-w-7xl px-5 py-10">
    <header className="mb-8 flex flex-wrap justify-between gap-5"><div><p className="text-xs font-bold tracking-widest text-teal-700">SNS TREND &amp; PERFORMANCE ANALYZER</p><h1 className="mt-3 text-3xl font-bold">{tr('nav.gap')}</h1><p className="mt-2 text-slate-600">{tr('gap.description')}</p></div>
      <nav className="flex flex-wrap gap-4 text-sm text-teal-800 underline"><OverviewLink/><AIInsightsLink/><Link href="/dashboard/my-account">{tr('nav.account')}</Link><Link href="/dashboard/trends">{tr('nav.trends')}</Link><Link href="/dashboard/competitors">{tr('nav.competitor')}</Link><Link href="/dashboard/settings">{tr('nav.settings')}</Link><Link href="/">{tr('nav.health')}</Link></nav></header>

    <Status state={projects}>{!initial ? <p role="status">{tr('common.loading')}</p> : project ? <FeatureGate feature="gap"><Analysis key={project.project_id} project={project} initial={normalized(project, initial)} onCriteria={setInitial}/></FeatureGate> : <Empty>{tr('common.createProjectFirst')}</Empty>}</Status>
  </main>;
}

function Analysis({ project, initial, onCriteria }: { project: Project; initial: Criteria; onCriteria: (c: Criteria) => void }) {
  useLocale();
  const [draft, setDraft] = useState(initial), [criteria, setCriteria] = useState(initial), [preset, setPreset] = useState('custom'), [validation, setValidation] = useState('');
  const q = criteriaQuery(scopedCriteria(project,criteria));
  useEffect(() => { replaceQuery(q); onCriteria(criteria); }, [q, criteria, onCriteria]);
  const read = useRead(useCallback(() => gapAnalysisApi(project.project_id, q), [project.project_id, q]));
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
      <p className="mt-4 text-sm text-slate-500">{tr('gap.filterNote')}</p>
      <p className="mt-2 text-sm text-slate-500">{tr('gap.formulaNote')}</p>
    </Section>
    <Section title={tr('gap.scatter')}><Status state={read}>{read.data && (read.data.items.length ? <GapScatter data={read.data}/> : <Empty>{tr('common.noTopics')}</Empty>)}</Status></Section>
    <Section title={tr('gap.table')}><Status state={read}>{read.data && (read.data.items.length ? <GapTable items={read.data.items}/> : <Empty>{tr('common.noTopics')}</Empty>)}</Status></Section>
  </div>;
}

function GapScatter({ data }: { data: GapAnalysis }) {
  useLocale();
  const series = scatterSeries(data.items);
  const points = series.flatMap(s => s.data);
  const missing = data.items.length - points.length;
  return <>
    <p className="mb-3 text-sm text-slate-500">{tr('gap.coordinatesNote', { own: data.own_ratio_threshold, trend: data.trend_threshold, unavailable: tr('gap.unavailableCount', { items: countText('items', missing) }) })}</p>
    {points.length ? <div className="h-[440px] min-w-0" role="img" aria-label={tr('gap.scatterLabel')}><ResponsiveContainer width="100%" height="100%"><ScatterChart margin={{ top: 20, right: 30, bottom: 35, left: 25 }}>
      <CartesianGrid strokeDasharray="3 3"/><XAxis type="number" dataKey="own_post_ratio" name={tr('metric.ownRatio')} unit="%" domain={[0, 100]} ticks={[0,25,50,75,100]} label={{ value: tr('gap.ownRatioAxis'), position: 'bottom', offset: 10 }}/><YAxis type="number" dataKey="trend_score" name={tr('metric.trendScore')} domain={[0, 100]} ticks={[0,25,50,75,100]} label={{ value: tr('metric.trendScore'), angle: -90, position: 'insideLeft' }}/>
      <ReferenceArea x1={0} x2={data.own_ratio_threshold} y1={data.trend_threshold} y2={100} fill="#ccfbf1" fillOpacity={0.6} label={tr('gap.zone')}/>
      <ReferenceLine x={data.own_ratio_threshold} stroke="#64748b" strokeDasharray="5 5"/><ReferenceLine y={data.trend_threshold} stroke="#64748b" strokeDasharray="5 5"/>
      <Tooltip content={({ active, payload }) => { const p = payload?.[0]?.payload as GapItem | undefined; return active && p ? <div className="rounded border bg-white p-3 text-sm shadow"><p className="font-semibold">{p.topic_name} / {p.platform}</p><p>{tr('label.trendScore')} {show(p.trend_score)} / {p.trend_date ?? tr('common.unknown')}</p><p>{tr('label.ownPostRatio')} {percent(p.own_post_ratio)}</p><p>{tr('label.competitorPostRatio')} {percent(p.competitor_post_ratio)}</p><p>{tr('label.gapScore')} {show(p.gap_score)}</p><Badge value={p.classification}/></div> : null; }}/>
      {series.map(({ platform, shape, data: platformPoints, isAnimationActive }) => <Scatter key={platform} name={platform} shape={shape} data={platformPoints} isAnimationActive={isAnimationActive}>{platformPoints.map(p => <Cell key={`${p.topic_id}-${p.platform}`} fill={colors[p.classification!]} />)}</Scatter>)}
    </ScatterChart></ResponsiveContainer></div> : <Empty>{tr('gap.noCoordinates')}</Empty>}
    <p className="mt-3 text-xs text-slate-500">{tr('label.platformXInstagramThresholdsTrend')} {data.trend_threshold} {tr('label.own')} {data.own_ratio_threshold}%。</p>
    <ul className="mt-4 grid gap-3 text-sm sm:grid-cols-2">{(Object.keys(descriptions) as Classification[]).map(value => <li key={value}><Badge value={value}/> <span className="text-slate-600">{tr(descriptions[value])}</span></li>)}</ul>
  </>;
}
function GapTable({ items }: { items: GapItem[] }) {
  useLocale();
  return <><p className="mb-4 text-xs text-slate-500">{tr('gap.sortNote')}</p><div className="overflow-auto"><table><thead><tr>{['Topic','SNS','Trend Score / Date','Own Post Ratio','Competitor Post Ratio','Gap Score','Classification'].map(h => <th key={h}>{displayLabel(h)}</th>)}</tr></thead><tbody>{items.map(p => <tr key={`${p.topic_id}-${p.platform}`}>
    <td>{p.topic_name}</td><td>{p.platform}</td><td>{show(p.trend_score)}<p className="text-xs text-slate-500">{p.trend_date ?? tr('gap.noTrend')}</p></td><td>{percent(p.own_post_ratio)}<p className="text-xs text-slate-500">{p.own_posts} / {p.own_total_posts} {tr('label.postsSuffix')}</p></td><td>{percent(p.competitor_post_ratio)}<p className="text-xs text-slate-500">{p.competitor_posts} / {p.competitor_total_posts} {tr('label.postsSuffix')}</p></td><td>{show(p.gap_score)}</td><td><Badge value={p.classification}/></td>
  </tr>)}</tbody></table></div></>;
}
