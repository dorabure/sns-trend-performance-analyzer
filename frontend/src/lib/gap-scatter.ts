import type { Classification, GapItem } from './gap-analysis-api';

export const classificationColors: Record<Classification, string> = {
  OPPORTUNITY: '#0f766e', BALANCED: '#2563eb', HIGH_COVERAGE: '#a16207', LOW_PRIORITY: '#64748b',
};

/** Keep API coordinates and tooltip payload intact; unknown coordinates have no symbol. */
export function scatterSeries(items: GapItem[]) {
  const points = items.filter(item => item.own_post_ratio !== null && item.trend_score !== null);
  return (['X', 'INSTAGRAM'] as const).map(platform => ({
    platform,
    shape: platform === 'X' ? 'circle' as const : 'diamond' as const,
    // Entrance animation starts every symbol at area zero. Render immediately on every read.
    isAnimationActive: false as const,
    data: points.filter(point => point.platform === platform),
  }));
}
