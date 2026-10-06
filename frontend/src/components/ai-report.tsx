"use client";
import { ReactNode } from 'react';
import { t as tr, displayLabel, intlLocale } from '../i18n';
import { useLocale } from '../i18n/react';
import { EvidenceItem, Insight } from '../lib/insights-api';
export function Section({ title, children, headingLevel = 2 }: { title: string; children: ReactNode; headingLevel?: 2 | 4 }) {
  useLocale();
  const Heading = headingLevel === 4 ? 'h4' : 'h2';
  return <section className="min-w-0 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm [overflow-wrap:anywhere]"><Heading className="mb-4 text-lg font-semibold">{title}</Heading>{children}</section>;
}
export function InsightReport({ insight, comparison = false }: { insight: Insight; comparison?: boolean }) {
  useLocale();
  const content = insight.content;
  if (!content) return <>{insight.model_name === 'demo-fixture' && <p role="status" className="rounded bg-amber-50 p-4">{tr('ai.fixture')}</p>}{Object.entries(insight.sections).map(([name,value]) => <Section headingLevel={comparison ? 4 : 2} key={name} title={({market_trend:tr('ai.market'),own_analysis:tr('ai.own'),improvement_points:tr('ai.improvements'),post_ideas:tr('ai.ideas')} as Record<string,string>)[name]}><p className="whitespace-pre-wrap">{Array.isArray(value) ? value.join('\n') : value}</p><p className="mt-3 text-sm text-slate-500">{tr('ai.legacyRefs')}</p></Section>)}</>;
  const refs = content.references;
  const items: [string, string[], string[][]][] = [
    [tr('ai.market'),[content.market_trend],[refs.market_trend]], [tr('ai.own'),[content.own_analysis],[refs.own_analysis]],
    [tr('ai.improvements'),content.improvement_points,refs.improvement_points], [tr('ai.ideas'),content.post_ideas,refs.post_ideas]];
  const evidence = Object.values(insight.evidence).flat();
  return <>{insight.model_name === 'demo-fixture' && <p role="status" className="rounded bg-amber-50 p-4">{tr('ai.fixture')}</p>}{items.map(([title, texts, references]) => <Section headingLevel={comparison ? 4 : 2} title={title} key={title}>{texts.length ? texts.map((text,i) => <article key={i} className="mb-5 last:mb-0"><p className="whitespace-pre-wrap leading-7">{text}</p>
    <details className="mt-3 rounded-lg border border-slate-200 p-3"><summary className="cursor-pointer text-sm font-medium text-teal-800">{tr('ai.evidence')}</summary>
      <div className="mt-3 space-y-4">{references[i].map(id => { const item = evidence.find(e => e.id === id); return item ? <Evidence key={id} item={item}/> : <p key={id} role="alert">{tr('ai.evidenceMissing')}</p>; })}</div></details>
    </article>) : <p className="text-sm text-slate-500">{tr('ai.noIdeas')}</p>}</Section>)}
    <Section headingLevel={comparison ? 4 : 2} title={tr('ai.cautions')}>{content.cautions.length ? <ul className="list-inside list-disc space-y-2">{content.cautions.map((text,i) => <li key={i}>{text}</li>)}</ul> : <p>{tr('ai.noCautions')}</p>}</Section></>;
}
function Evidence({ item }: { item: EvidenceItem }) {
  useLocale();
  return <div><h4 className="text-sm font-bold">{item.id.startsWith('KPI_') ? displayLabel(item.label) : item.id.startsWith('COMPETITOR:') ? `${tr('nav.competitor')} / ${String(item.values.platform ?? '')}` : item.label}</h4><p className="mt-1 break-all text-xs text-slate-500">{item.id}</p><dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">{Object.entries(item.values).map(([key,value]) => <div className="min-w-0" key={key}><dt className="text-slate-500">{displayLabel(key)}</dt><dd className="break-words">{format(value,key)}</dd></div>)}</dl></div>;
}
function format(value: unknown, field?: string): ReactNode {
  if (value === null || value === undefined) return '—';
  if (Array.isArray(value)) return value.length ? value.map((v,i) => <div key={i}>{format(v)}</div>) : tr('common.empty');
  if (typeof value === 'object') return <dl className="space-y-1">{Object.entries(value).map(([k,v]) => <div key={k}><dt className="inline text-slate-500">{displayLabel(k)}: </dt><dd className="inline">{format(v,k)}</dd></div>)}</dl>;
  if (typeof value === 'number') return value.toLocaleString(intlLocale(), { maximumFractionDigits: 4 });
  return typeof value === 'string' && ['classification','role','denominator_type','trend_direction'].includes(field ?? '') ? displayLabel(value) : String(value);
}

