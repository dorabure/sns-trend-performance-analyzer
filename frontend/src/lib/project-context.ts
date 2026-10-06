import type { Project, Platform } from './api';
export type DataMode = 'DEMO' | 'LIVE';
export type Storage = Pick<globalThis.Storage, 'getItem' | 'setItem' | 'removeItem'>;
export const modeKey = (mode: DataMode) => 'sns-project-' + mode.toLowerCase();
export function read(storage: Storage, key: string) { try { return storage.getItem(key); } catch { return null; } }
export function persist(storage: Storage, mode: DataMode, id: string) { try { storage.setItem('sns-mode', mode); if (id) storage.setItem(modeKey(mode), id); } catch { /* Storage may be blocked. Keep the in-memory selection. */ } }
export function chooseProject(projects: Project[], mode: DataMode, saved: string | null) {
 const group = projects.filter(p => p.data_mode === mode);
 return group.find(p => p.project_id === saved) ?? group.find(p => p.is_active) ?? group[0];
}
export function restoreScope(projects: Project[], storage: Storage) {
 const legacy = projects.find(p => p.project_id === read(storage, 'sns-project'));
 if (legacy && !read(storage, modeKey(legacy.data_mode))) { try { storage.setItem(modeKey(legacy.data_mode), legacy.project_id); } catch {} }
 try { storage.removeItem('sns-project'); } catch {}
 const saved = read(storage, 'sns-mode');
 const mode: DataMode = saved === 'DEMO' || saved === 'LIVE' ? saved : legacy?.data_mode ?? (projects.find(p => p.project_id === read(storage, modeKey('LIVE')))?.data_mode) ?? 'DEMO';
 const project = chooseProject(projects, mode, read(storage, modeKey(mode)));
 persist(storage, mode, project?.project_id ?? '');
 return { mode, id: project?.project_id ?? '' };
}
export type ProviderType = 'X_API' | 'INSTAGRAM_API';
export type ProviderCapability = 'ACCOUNT_PROFILE' | 'OWN_POSTS' | 'OWN_METRICS' | 'MARKET_POSTS' | 'COMPETITOR_POSTS' | 'TREND_DATA';
export const capabilityNames: ProviderCapability[] = ['ACCOUNT_PROFILE','OWN_POSTS','OWN_METRICS','MARKET_POSTS','COMPETITOR_POSTS','TREND_DATA'];
export type CapabilityMap = Record<ProviderCapability, boolean>;
export type Provider = { id: string; provider_type: ProviderType; enabled: boolean; connection_status: 'NOT_CONFIGURED'|'CONNECTED'|'ERROR'|'DISABLED'; sync_in_progress: boolean; remote_account_id: string | null; capabilities: ProviderCapability[]; available?: CapabilityMap; last_attempt_at: string | null; last_success_at: string | null; last_record_count: number };
export type ProjectContext = { project_id: string; project_name: string; data_mode: DataMode; platforms: Platform[]; providers: Pick<Provider,'provider_type'|'enabled'|'connection_status'>[]; live_operations_enabled: boolean };
export const providerPlatform: Record<ProviderType, Platform> = { X_API: 'X', INSTAGRAM_API: 'INSTAGRAM' };
export function hasCapability(provider: Provider, cap: ProviderCapability) { return provider.available?.[cap] ?? provider.capabilities.includes(cap); }
export function canSync(provider: Provider, live: boolean) {
 return live && provider.enabled && provider.connection_status === 'CONNECTED' && !provider.sync_in_progress &&
  (['ACCOUNT_PROFILE','OWN_POSTS','OWN_METRICS'] as ProviderCapability[]).every(cap => hasCapability(provider,cap) && provider.capabilities.includes(cap));
}
export function canConnect(provider: Provider, live: boolean) { return live && provider.enabled && (!hasCapability(provider,'ACCOUNT_PROFILE') || hasCapability(provider,'OWN_POSTS')); }
export type Feature = 'overview'|'account'|'trends'|'competitor'|'gap'|'insights';
function supports(p: Provider, feature: Feature) {
 const has = (c: ProviderCapability) => hasCapability(p,c);
 if (feature === 'trends') return has('TREND_DATA') || has('MARKET_POSTS');
 if (feature === 'competitor') return has('COMPETITOR_POSTS');
 if (feature === 'gap') return has('OWN_POSTS') && (has('TREND_DATA') || has('MARKET_POSTS'));
 if (feature === 'account') return has('ACCOUNT_PROFILE') && (has('OWN_POSTS') || has('OWN_METRICS'));
 return has('OWN_POSTS') || has('OWN_METRICS');
}
export function availablePlatformsForFeature(project: Project, providers: Provider[], feature: Feature) {
 if (project.data_mode === 'DEMO') return project.platforms;
 return project.platforms.filter(platform => providers.some(p => providerPlatform[p.provider_type] === platform && p.enabled && p.connection_status === 'CONNECTED' && supports(p,feature)));
}
export type Availability = 'Supported'|'Unsupported'|'NoData'|'ProviderError'|'NotConfigured'|'LiveDisabled';
export function featureAvailability(project: Project, providers: Provider[], feature: Feature, live: boolean): Availability {
 if (project.data_mode === 'DEMO') return 'Supported';
 if (!live) return 'LiveDisabled';
 if (availablePlatformsForFeature(project,providers,feature).length) return 'Supported';
 const candidates = providers.filter(p => project.platforms.includes(providerPlatform[p.provider_type]) && supports(p,feature));
 if (!candidates.length) {
 const unknown = providers.filter(p => project.platforms.includes(providerPlatform[p.provider_type]) && !capabilityNames.some(cap => hasCapability(p,cap)));
 if (unknown.some(p => p.connection_status === 'ERROR')) return 'ProviderError';
 return unknown.length ? 'NotConfigured' : 'Unsupported';
 }
 if (candidates.some(p => p.connection_status === 'ERROR')) return 'ProviderError';
 return 'NotConfigured';
}
