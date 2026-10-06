import { apiFetch, Platform } from "./api";
import { OwnPostItem, RateGroup } from "./my-account-api";

export type ComparisonAccount = { account_id: string; account_name: string; display_name: string | null; platform: Platform; role: "OWN" | "COMPETITOR" };
export type AccountAnalytics = ComparisonAccount & { followers: number | null; followers_as_of: string | null; posts: number; posting_frequency: number; avg_views: number | null; avg_likes: number | null; avg_comments: number | null; avg_shares: number | null; avg_engagement: number | null; avg_engagement_rate: number | null; engagement_rate_groups: RateGroup[] };
export type Analytics = { accounts: AccountAnalytics[]; timezone: string; posting_frequency_unit: string };
export type TopicAccount = ComparisonAccount & { matched_posts: number; total_posts: number; ratio: number | null };
export type Distribution = { topics: { topic_id: string; topic_name: string; accounts: TopicAccount[] }[]; timezone: string; overlapping_topics: boolean };
export type CompetitorPost = OwnPostItem & { display_name: string | null };
const path = (project: string) => `/projects/${encodeURIComponent(project)}/competitors`;
export const competitorsApi = {
  analytics: (project: string, query: string) => apiFetch<Analytics>(`${path(project)}/analytics?${query}`),
  distribution: (project: string, query: string) => apiFetch<Distribution>(`${path(project)}/topic-distribution?${query}`),
  top: (project: string, query: string) => apiFetch<{ items: CompetitorPost[] }>(`${path(project)}/top-posts?${query}`),
};
