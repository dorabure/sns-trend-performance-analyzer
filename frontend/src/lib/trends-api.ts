import { apiFetch } from "./api";
import { OwnPostItem } from "./my-account-api";

export type TrendMetric = "post_count" | "engagement" | "trend_score";
export type RankingItem = { topic_id: string; topic_name: string; term_id: string; keyword: string; term_type: string; platform: string; trend_date: string; post_count: number; engagement_count: number; avg_engagement: number | null; post_growth_rate: number | null; engagement_growth_rate: number | null; acceleration_rate: number | null; trend_score: number | null; trend_direction: "UP" | "FLAT" | "DOWN" | "UNKNOWN" };
export type Ranking = { score_window_days: number; score_as_of: string | null; items: RankingItem[] };
export type TrendSeries = { term_id: string; term_name: string; platform: string; values: { date: string; value: number | null; row_present: boolean }[] };
export type Timeseries = { metric: TrendMetric; timezone: string; series: TrendSeries[] };
const path = (project: string) => `/projects/${encodeURIComponent(project)}/trends`;
export const trendsApi = {
  ranking: (project: string, topic: string, query: string) => apiFetch<Ranking>(`${path(project)}/ranking?${query}&topic_id=${encodeURIComponent(topic)}`),
  timeseries: (project: string, terms: string[], metric: TrendMetric, query: string) => apiFetch<Timeseries>(`${path(project)}/timeseries?${query}&term_ids=${encodeURIComponent(terms.join(","))}&metric=${metric}`),
  popular: (project: string, topic: string, term: string, query: string) => apiFetch<{ items: OwnPostItem[] }>(`${path(project)}/${encodeURIComponent(topic)}/top-posts?${query}${term ? `&term_id=${encodeURIComponent(term)}` : ""}`),
};
