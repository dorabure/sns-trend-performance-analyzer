import { apiFetch, Platform } from './api';
import { FollowerValue, RateGroup } from './my-account-api';
import { GapItem } from './gap-analysis-api';
import { AccountAnalytics } from './competitors-api';

export type CountKPI = { value: number | null; previous_value: number | null; change: number | null; change_rate: number | null };
export type Summary = { posts: number; avg_engagement: number | null; avg_engagement_rate: number | null; rate_groups: RateGroup[]; followers_by_account: FollowerValue[]; account_count: number };
export type FollowerSeries = { account_id: string; account_name: string; platform: Platform; values: { date: string; followers: number | null; row_present: boolean }[] };
export type Overview = {
  timezone: string; period: { from: string; to: string }; previous_period: { from: string; to: string } | null;
  kpis: { reach: CountKPI; posts: CountKPI; followers: CountKPI; impressions: CountKPI; engagement: CountKPI;
    engagement_rate: { value: number | null; previous_value: number | null; change_point: number | null; rate_groups: RateGroup[]; previous_rate_groups: RateGroup[] };
    followers_by_account: FollowerValue[] };
  performance_trend: { daily: { date: string; posts: number; reach: number | null; engagement: number | null }[]; follower_series: FollowerSeries[] };
  top_trends: { topic_id: string; topic_name: string; platform: Platform; trend_date: string; trend_score: number; post_growth_rate: number | null; engagement_growth_rate: number | null; avg_engagement: number | null; trend_direction: string }[];
  competitor_summary: AccountAnalytics[]; own_summary: Summary; competitor_aggregate: Summary; top_opportunity: GapItem | null;
  ai_summary: { insight_id: string; platform: Platform | null; analysis_from: string; analysis_to: string; created_at: string; content: unknown; model_name: string | null; prompt_version: string | null } | null;
};
export const overviewApi = (project: string, query: string) => apiFetch<Overview>(`/projects/${encodeURIComponent(project)}/dashboard/overview?${query}`);
