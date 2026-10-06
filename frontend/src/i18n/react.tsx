"use client";
import { ReactNode, useEffect, useSyncExternalStore } from 'react';
import { currentLocale, readLocale, saveLocale, subscribeLocale, t } from './index';
export function useLocale() { return useSyncExternalStore(subscribeLocale,currentLocale,() => 'ja' as const); }
export function LocaleProvider({children}:{children:ReactNode}) {
  const locale=useLocale();
  useEffect(() => { saveLocale(readLocale()); },[]);
  useEffect(() => { document.documentElement.lang=locale; },[locale]);
  return <>{children}</>;
}
export function LanguageSetting() {
  const locale=useLocale();
  return <label className="grid gap-2 text-sm font-medium text-slate-700">{t('settings.language')}
    <select value={locale} onChange={e => saveLocale(e.target.value)}><option value="ja">日本語</option><option value="en">English</option></select>
  </label>;
}
