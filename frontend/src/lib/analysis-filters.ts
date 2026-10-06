export type AnalysisCriteria = { platform: string; from: string; to: string };

export function period(days = 30, today = new Date().toISOString().slice(0, 10)) {
  const start = new Date(`${today}T00:00:00Z`);
  start.setUTCDate(start.getUTCDate() - days + 1);
  return { from: start.toISOString().slice(0, 10), to: today };
}

export function parseCriteria(params: URLSearchParams): AnalysisCriteria {
  const dates = period();
  return { platform: params.get('platform') || 'ALL', from: params.get('from') || dates.from,
    to: params.get('to') || dates.to };
}

export function normalized<T extends AnalysisCriteria>(project: { platforms: string[] }, criteria: T): T {
  return { ...criteria, platform: criteria.platform === 'ALL' || project.platforms.includes(criteria.platform)
    ? criteria.platform : 'ALL' };
}

export function formCriteria<T extends AnalysisCriteria>(form: HTMLFormElement, draft: T): T {
  const values = new FormData(form);
  return { ...draft, from: String(values.get('from') ?? ''), to: String(values.get('to') ?? '') };
}

export function validPeriod(criteria: AnalysisCriteria) {
  const date = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
  return date(criteria.from) && date(criteria.to) && criteria.from <= criteria.to;
}

export function criteriaQuery(criteria: AnalysisCriteria, extra: Record<string, string> = {}) {
  return new URLSearchParams({ platform: criteria.platform, from: criteria.from, to: criteria.to, ...extra }).toString();
}

export function replaceQuery(query: string) {
  const url = new URL(window.location.href); url.search = query;
  window.history.replaceState(null, '', url);
}

export function competitorCriteria<T extends AnalysisCriteria & { ids: string[] }>(
  project: { platforms: string[] }, criteria: T,
  accounts: { account_id: string; platform: string; account_role: string; is_active: boolean }[]): T {
  const next = normalized(project, criteria);
  return { ...next, ids: [...new Set(next.ids)].filter(id => accounts.some(a => a.account_id === id &&
    a.account_role === 'COMPETITOR' && a.is_active && project.platforms.includes(a.platform) &&
    (next.platform === 'ALL' || a.platform === next.platform))) };
}

export function scopedCriteria<T extends AnalysisCriteria>(project: { data_mode: string; platforms: string[] }, criteria: T): T {
 return project.data_mode === 'LIVE' && criteria.platform === 'ALL' && project.platforms.length === 1 ? {...criteria,platform:project.platforms[0]} : criteria;
}
