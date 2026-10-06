import { Criteria, InsightHistoryItem, InsightHistoryPage, InsightComparePrevious, InsightComparisonMetadata, insightsApi } from './insights-api';

export function historyScopeKey(project: string, criteria: Criteria) {
  return JSON.stringify([project, criteria.platform, criteria.from, criteria.to]);
}
export function mergeHistoryPages(previous: InsightHistoryItem[], incoming: InsightHistoryItem[]) {
  const seen = new Set(previous.map(item => item.insight_id));
  return [...previous, ...incoming.filter(item => { if (seen.has(item.insight_id)) return false; seen.add(item.insight_id); return true; })];
}
export function comparisonLabels(value: InsightComparisonMetadata) {
  if (!value.has_previous) return ['ai.noPrevious'];
  if (value.changed === false) return ['ai.unchanged'];
  const labels = value.changed === true ? ['ai.changed'] : [];
  const fields = {input_changed:'ai.inputChanged', prompt_version_changed:'ai.promptChanged', model_changed:'ai.modelChanged', content_changed:'ai.contentChanged', evidence_changed:'ai.evidenceChanged'} as const;
  for (const field of Object.keys(fields) as (keyof typeof fields)[]) if (value[field] === true) labels.push(fields[field]);
  return labels;
}
export type HistoryState = {
  items: InsightHistoryItem[]; cursor: string | null; selected: string | null; comparison: InsightComparePrevious | null;
  loading: boolean; comparing: boolean; historyError: unknown; compareError: unknown;
};
type HistoryAPI = {
  history: (project: string, criteria: Criteria, cursor?: string | null) => Promise<InsightHistoryPage>;
  comparePrevious: (project: string, insight: string) => Promise<InsightComparePrevious>;
};
export function createHistoryController(project: string, criteria: Criteria, api: HistoryAPI = insightsApi) {
  let state: HistoryState = {items:[],cursor:null,selected:null,comparison:null,loading:true,comparing:false,historyError:null,compareError:null};
  let historyVersion = 0, compareVersion = 0, active = true;
  const listeners = new Set<() => void>();
  const update = (patch: Partial<HistoryState>) => { if (active) { state={...state,...patch}; listeners.forEach(fn => fn()); } };
  const select = async (id: string, retry = false) => {
    if (!active || !state.items.some(item => item.insight_id === id) || (state.selected === id && !retry)) return;
    const token = ++compareVersion;
    update({selected:id,comparison:null,comparing:true,compareError:null});
    try { const comparison = await api.comparePrevious(project,id); if (active && token === compareVersion) update({comparison}); }
    catch (compareError) { if (active && token === compareVersion) update({compareError}); }
    finally { if (active && token === compareVersion) update({comparing:false}); }
  };
  const load = async (cursor: string | null, append: boolean) => {
    const token = ++historyVersion;
    update({loading:true,historyError:null});
    try {
      const page = await api.history(project,criteria,cursor);
      if (!active || token !== historyVersion) return;
      update({items:append ? mergeHistoryPages(state.items,page.items) : page.items,cursor:page.next_cursor});
      if (!append && page.items.length) void select(page.items[0].insight_id);
    } catch (historyError) { if (active && token === historyVersion) update({historyError}); }
    finally { if (active && token === historyVersion) update({loading:false}); }
  };
  return {
    snapshot: () => state,
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    reload: () => {
      active=true; ++compareVersion;
      update({items:[],cursor:null,selected:null,comparison:null,comparing:false,historyError:null,compareError:null});
      return load(null,false);
    },
    loadMore: () => active && !state.loading && state.cursor ? load(state.cursor,true) : Promise.resolve(),
    retryHistory: () => state.loading ? Promise.resolve() : state.items.length && state.cursor ? load(state.cursor,true) : load(null,false),
    select,
    retryCompare: () => state.selected ? select(state.selected,true) : Promise.resolve(),
    // React owns subscription cleanup. Retain listeners when the same controller
    // is disposed/reloaded by a generation or refresh effect.
    dispose: () => { active=false; ++historyVersion; ++compareVersion; },
  };
}
