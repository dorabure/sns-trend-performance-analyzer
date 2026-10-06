"use client";
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { Project, ApiError } from '../lib/api';
import { Provider, capabilityNames, hasCapability, canSync, canConnect } from '../lib/project-context';
import { operations } from '../lib/job-operations';
import { useProjectScope } from './project-scope';
import { t as tr, intlLocale } from '../i18n';
import { useLocale } from '../i18n/react';
export default function ProviderSettings({project}: {project: Project}) {
 useLocale(); const scope = useProjectScope(); const [busy,setBusy] = useState(false),[notice,setNotice] = useState('');
 const mounted = useRef(true), sending = useRef(false); useEffect(() => { mounted.current=true; return () => {mounted.current=false;}; },[]);
 const live = scope.context?.live_operations_enabled ?? false;
 const date = (value: string | null) => value ? new Date(value).toLocaleString(intlLocale(),{timeZone:'UTC'}) + ' UTC' : '—';
 async function run(action: () => Promise<unknown>, message = 'settings.saved') {
  if (sending.current) return; sending.current=true; setBusy(true); setNotice('');
  try { await action(); if (mounted.current) { await scope.reloadProviders(); if (mounted.current) setNotice(tr(message)); } }
  catch(e) { if (mounted.current) setNotice(e instanceof ApiError ? e.message : tr('error.unexpected')); }
  finally { sending.current=false; if (mounted.current) setBusy(false); }
 }
 async function connect(provider: Provider) { const result = await operations.connect(project.project_id,provider.provider_type);
  if (!mounted.current) return;
  const url = new URL(result.authorize_url); if (url.protocol !== 'https:') throw new Error('Invalid authorization URL');
  window.location.assign(url.href);
 }
 if (project.data_mode === 'DEMO') return <section className="rounded-xl bg-white p-6"><h2>{tr('provider.open')}</h2><p>{tr('provider.demo')}</p></section>;
 return <section className="space-y-5"><h2 className="text-xl font-semibold">{tr('provider.open')}</h2><p>{tr('provider.callback')}</p>
 {scope.context && !scope.providerLoading && !live && <p>{tr('availability.LiveDisabled')}</p>}<button disabled={busy || scope.providerLoading} onClick={() => void scope.reloadProviders()}>{tr('common.refresh')}</button>
 {notice && <p role="status">{notice}</p>}{scope.providerError && <p role="alert">{scope.providerError}</p>}
 {scope.providerLoading ? <p role="status">{tr('common.loading')}</p> : scope.providers.map(p => <article key={p.id} className="space-y-4 rounded-xl border bg-white p-6">
 <h3 className="text-lg font-semibold">{tr('provider.'+p.provider_type)}</h3><p>{tr('provider.status.'+p.connection_status)} · {tr(p.enabled ? 'common.active' : 'common.inactive')} {p.sync_in_progress && tr('jobs.syncing')}</p>
 {hasCapability(p,'ACCOUNT_PROFILE') && !hasCapability(p,'OWN_POSTS') && <p className="rounded bg-amber-50 p-3">{tr('provider.deferred')}</p>}
 <ul>{capabilityNames.map(cap => <li key={cap}>{tr('capability.'+cap)}: {tr(hasCapability(p,cap) ? 'provider.available' : 'provider.unavailable')}</li>)}</ul>
 <dl><dt>{tr('provider.remote')}</dt><dd>{tr(p.remote_account_id ? 'provider.present' : 'provider.absent')}</dd><dt>{tr('provider.attempt')}</dt><dd>{date(p.last_attempt_at)}</dd><dt>{tr('provider.success')}</dt><dd>{date(p.last_success_at)}</dd><dt>{tr('jobs.records')}</dt><dd>{p.last_record_count}</dd></dl>
 <div className="flex flex-wrap gap-3"><button disabled={busy || !live} onClick={() => void run(() => operations.patchProvider(project.project_id,p.provider_type,!p.enabled))}>{tr(p.enabled ? 'jobs.disable' : 'jobs.enable')}</button>
 <button disabled={busy || !canConnect(p,live)} onClick={() => void run(() => connect(p))}>{tr(p.connection_status === 'CONNECTED' ? 'provider.reconnect' : 'provider.connect')}</button>
 <button disabled={busy || !live || !p.enabled} onClick={() => void run(() => operations.validate(project.project_id,p.provider_type))}>{tr('provider.validate')}</button>
 <button disabled={busy || !canSync(p,live)} onClick={() => void run(() => operations.sync(project.project_id,p.provider_type),'jobs.manualAccepted')}>{tr('jobs.manualSync')}</button>
 <Link className="underline" href="/dashboard/settings?tab=jobs">{tr('provider.jobs')}</Link></div>
 </article>)}
 </section>;
}
