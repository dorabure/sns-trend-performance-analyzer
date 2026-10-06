import { apiFetch, Platform } from './api';

export type Classification = 'OPPORTUNITY' | 'BALANCED' | 'HIGH_COVERAGE' | 'LOW_PRIORITY';
export type GapItem = {
  topic_id: string; topic_name: string; platform: Platform;
  trend_date: string | null; trend_score: number | null;
  own_posts: number; own_total_posts: number; own_post_ratio: number | null;
  competitor_posts: number; competitor_total_posts: number; competitor_post_ratio: number | null;
  gap_score: number | null; classification: Classification | null;
};
export type GapAnalysis = {
  timezone: string; from: string; to: string; score_window_days: number;
  trend_threshold: number; own_ratio_threshold: number; items: GapItem[];
};
export const gapAnalysisApi = (project: string, query: string) =>
  apiFetch<GapAnalysis>(`/projects/${encodeURIComponent(project)}/gap-analysis?${query}`);
