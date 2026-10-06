import { criteriaQuery } from './analysis-filters';
import { apiFetch } from './api';

export type Criteria = { platform: string; from: string; to: string };
export type EvidenceItem = { id: string; label: string; values: Record<string, unknown> };
export type Sections = { market_trend: string; own_analysis: string; improvement_points: string[]; post_ideas: string[] };
export type Insight = {
  insight_id: string; project_id: string; platform: string; analysis_from: string; analysis_to: string;
  generated_at: string; model_name: string | null; prompt_version: string | null;
  sections: Sections; content: Sections & { summary: string; cautions: string[];
    references: { market_trend: string[]; own_analysis: string[]; improvement_points: string[][]; post_ideas: string[][] } } | null;
  evidence: { kpis: EvidenceItem[]; trends: EvidenceItem[]; competitors: EvidenceItem[]; opportunities: EvidenceItem[] };
};
export type Latest = { insight: Insight | null; ai_generation_available: boolean };
export type InsightHistoryItem = Pick<Insight, 'insight_id' | 'project_id' | 'platform' | 'analysis_from' | 'analysis_to' | 'generated_at' | 'model_name' | 'prompt_version'> & {
  data_mode: 'DEMO' | 'LIVE'; input_summary_hash: string; is_legacy: boolean;
};
export type InsightHistoryPage = { items: InsightHistoryItem[]; next_cursor: string | null };
export type InsightHistoryDetail = Insight & { data_mode: 'DEMO' | 'LIVE'; input_summary_hash: string; is_legacy: boolean };
export type InsightComparisonMetadata = {
  has_previous: boolean; changed: boolean | null; input_changed: boolean | null;
  prompt_version_changed: boolean | null; model_changed: boolean | null;
  content_changed: boolean | null; evidence_changed: boolean | null; generated_at_delta_seconds: number | null;
};
export type InsightComparePrevious = { current: InsightHistoryDetail; previous: InsightHistoryDetail | null; comparison: InsightComparisonMetadata };
export function historyQuery(criteria: Criteria, cursor?: string | null) {
  const query = new URLSearchParams(criteriaQuery(criteria)); query.set('limit', '10');
  if (cursor) query.set('cursor', cursor);
  return query.toString();
}
const path = (project: string) => `/projects/${encodeURIComponent(project)}/insights`;
export const insightsApi = {
  history: (project: string, criteria: Criteria, cursor?: string | null) => apiFetch<InsightHistoryPage>(`${path(project)}/history?${historyQuery(criteria, cursor)}`),
  comparePrevious: (project: string, insight: string) => apiFetch<InsightComparePrevious>(`${path(project)}/history/${encodeURIComponent(insight)}/compare-previous`),
  latest: (project: string, criteria: Criteria) => apiFetch<Latest>(`${path(project)}/latest?${criteriaQuery(criteria)}`),
  generate: (project: string, criteria: Criteria) => apiFetch<Insight>(`${path(project)}/generate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(criteria) }),
};
