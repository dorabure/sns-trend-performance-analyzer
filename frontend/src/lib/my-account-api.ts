import { criteriaQuery } from './analysis-filters';
import { apiFetch, Platform } from "./api";
export type MediaType = "TEXT" | "IMAGE" | "VIDEO" | "CAROUSEL" | "OTHER";
export type RateGroup = { platform: Platform; denominator_type: string; post_count: number; avg_engagement_rate: number | null };
export type Aggregate = { post_count: number; engagement_total: number | null; avg_engagement: number | null; avg_engagement_rate: number | null; rate_groups: RateGroup[] };
export type FollowerValue = { platform: Platform; account_id: string; account_name: string; recorded_date: string | null; followers: number | null };
export type OwnAnalytics = {
  kpis: { posts: number; reach: number | null; impressions: number | null; engagement: number | null; engagement_rate: number | null; followers: number | null; avg_engagement: number | null; followers_by_account: FollowerValue[]; rate_groups: RateGroup[] };
  engagement_trend: (Aggregate & { date: string })[];
  media_type_performance: (Aggregate & { media_type: MediaType | null; posts: number })[];
  timezone: string;
};
export type OwnPost = { post_id: string; account_id: string | null; account_name: string | null; author_name: string | null; platform: Platform; posted_at: string; text: string | null; media_type: MediaType | null; permalink: string | null; hashtags: string[] };
export type OwnMetrics = { recorded_at: string | null; impressions: number | null; reach: number | null; views: number | null; likes: number | null; comments: number | null; shares: number | null; saves: number | null; engagement: number | null; engagement_rate: number | null; denominator_type: string | null; denominator_value: number | null };
export type OwnPostItem = OwnPost & OwnMetrics;
export type OwnPostPage = { items: OwnPostItem[]; total: number; page: number; page_size: number };
export type OwnPostDetail = { post: OwnPost; metrics: OwnMetrics; comparison: { vs_average_rate: number | null; rank: number | null; total_posts: number; comparable_posts: number; basis: string }; topics: { topic_id: string; topic_name: string; is_active: boolean; match_type: string }[] };
export type OwnFilters = { platform: string; from: string; to: string; media_type: string; keyword: string; hashtag: string };
export const ownQuery = (filters: OwnFilters) => criteriaQuery(filters, Object.fromEntries(Object.entries({ media_type: filters.media_type, keyword: filters.keyword, hashtag: filters.hashtag }).filter(([, value]) => value !== "")));
const root = (projectId: string) => `/projects/${encodeURIComponent(projectId)}`;
export const ownApi = {
  analytics: (id: string, query: string) => apiFetch<OwnAnalytics>(`${root(id)}/accounts/own/analytics?${query}`),
  posts: (id: string, query: string, page: number, sort: string, order: string) => apiFetch<OwnPostPage>(`${root(id)}/accounts/own/posts?${query}&${new URLSearchParams({ page: String(page), page_size: "20", sort, order })}`),
  detail: (id: string, postId: string, query: string) => apiFetch<OwnPostDetail>(`${root(id)}/posts/${encodeURIComponent(postId)}?${query}`),
};
