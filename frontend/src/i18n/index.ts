import { ja } from './ja';
import { en } from './en';
import { labelKeys } from './labels';
export type Locale = 'ja' | 'en';
export const STORAGE_KEY = 'sns-analyzer.locale';
export const dictionaries: Record<Locale,Record<string,string>> = {ja,en};
export function normalizeLocale(value: unknown): Locale { return value === 'en' ? 'en' : 'ja'; }
export function readLocale(storage?: Pick<Storage,'getItem'>): Locale {
  try { return normalizeLocale((storage ?? (typeof window === 'undefined' ? undefined : window.localStorage))?.getItem(STORAGE_KEY)); }
  catch { return 'ja'; }
}
let selected: Locale | undefined;
const listeners = new Set<() => void>();
// First client render matches SSR; the provider restores storage after hydration.
export function currentLocale(): Locale { return typeof window === 'undefined' ? 'ja' : selected ?? 'ja'; }
export function saveLocale(value: unknown, storage?: Pick<Storage,'setItem'>) {
  selected=normalizeLocale(value);
  try { (storage ?? (typeof window === 'undefined' ? undefined : window.localStorage))?.setItem(STORAGE_KEY,selected); } catch { /* blocked storage: session choice still works */ }
  listeners.forEach(fn => fn());
  return selected;
}
export function subscribeLocale(listener: () => void) {
  listeners.add(listener);
  const sync = (e: StorageEvent) => { if(e.key === STORAGE_KEY || e.key === null) { selected=readLocale(); listener(); } };
  if(typeof window !== 'undefined') window.addEventListener('storage',sync);
  return () => { listeners.delete(listener); if(typeof window !== 'undefined') window.removeEventListener('storage',sync); };
}
export function translate(key: string, locale: Locale, params: Record<string,string|number> = {}) {
  const value = dictionaries[locale][key] ?? dictionaries.ja[key] ?? key;
  return value.replace(/\{(\w+)\}/g,(_,name) => String(params[name] ?? `{${name}}`));
}
export function t(key: string, params?: Record<string,string|number>) { return translate(key,currentLocale(),params); }
/** Only apply to enum/fixed labels. Never pass user text, Topic names or AI content. */
export function displayLabel(value: string | null | undefined) { return value == null ? '—' : labelKeys[value] ? t(labelKeys[value]) : value; }
export function intlLocale() { return currentLocale() === 'en' ? 'en-US' : 'ja-JP'; }
export function countText(unit: 'items' | 'posts', count: number) {
  return t(`count.${unit}.${count === 1 ? 'one' : 'other'}`, { count: count.toLocaleString(intlLocale()) });
}
export function ratePostCount(count: number) { return t('rate.postCount', { posts: countText('posts', count) }); }
export function errorText(code?: string, status?: number) {
  if(code === 'LIVE_MODE_DISABLED') return t('jobs.liveDisabled');
  if(code === 'SCHEDULE_REQUIRES_LIVE') return t('jobs.liveOnly');
  if(code === 'PROVIDER_NOT_READY') return t('jobs.notReady');
  if(code === 'PROVIDER_CAPABILITY_UNAVAILABLE') return t('jobs.capabilityUnavailable');
  if(code === 'JOB_ALREADY_RUNNING') return t('jobs.alreadyRunning');
  if(code === 'SCHEDULE_ALREADY_EXISTS') return t('jobs.duplicateSchedule');
  if(code === 'JOB_NOT_CANCELABLE') return t('jobs.notCancelable');

  if(code === 'AI_KEY_NOT_CONFIGURED') return t('ai.keyMissing');
  if(code === 'REQUEST_TOO_LARGE' || code === 'FILE_TOO_LARGE' || status===413) return t('error.tooLarge');
  if(code === 'IMPORT_INTERRUPTED') return t('error.interrupted');
  if(status===0) return t('error.network');
  if(status===404) return t('error.notFound');
  if(status===409) return t('error.conflict');
  if(status===400 || status===422 || code === 'VALIDATION_ERROR') return t('error.validation');
  return t('error.unexpected');
}
