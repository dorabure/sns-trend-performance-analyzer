"use client";
import Link from 'next/link';
import { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { api, Project, ApiError } from '../lib/api';
import { operations } from '../lib/job-operations';
import { DataMode, Provider, ProjectContext, Feature, chooseProject, restoreScope, persist, read, modeKey, featureAvailability, availablePlatformsForFeature } from '../lib/project-context';
import { t as tr } from '../i18n';
import { useLocale } from '../i18n/react';
import { useRead } from '../lib/use-analysis-read';

type Scope = { projects: Project[]; selectedProject?: Project; selectedProjectId: string; selectedMode: DataMode; loading: boolean; error: string; reload: () => Promise<void>; selectMode: (mode: DataMode) => void; selectProject: (id: string) => void; saveProject: (p: Project) => void; context: ProjectContext | null; providers: Provider[]; providerLoading: boolean; providerError: string; reloadProviders: () => Promise<void> };
const Context = createContext<Scope | null>(null);
export function useProjectScope() { const value = useContext(Context); if (!value) throw new Error('Missing project scope'); return value; }
export function ProjectScopeProvider({ children }: { children: ReactNode }) {
 useLocale(); const path = usePathname();
 const enabled = path !== '/';
 const [projects,setProjects] = useState<Project[]>([]), [mode,setMode] = useState<DataMode>('DEMO'), [id,setId] = useState('');
 const initialized = useRef(false), version = useRef(0);
 const [loading,setLoading] = useState(true), [error,setError] = useState('');
 const reload = useCallback(async () => {
  const token = ++version.current; setLoading(true); setError('');
  if (!initialized.current) { const savedMode = read(window.localStorage,'sns-mode'); if (savedMode === 'DEMO' || savedMode === 'LIVE') setMode(savedMode); }
  try { const list = await api.projects(); if (token !== version.current) return; setProjects(list);
   const restored = restoreScope(list,window.localStorage); setMode(restored.mode); setId(restored.id); initialized.current = true;
  } catch(e) { if (token === version.current) setError(e instanceof ApiError ? e.message : tr('error.unexpected')); }
  finally { if (token === version.current) setLoading(false); }
 },[]);
 useEffect(() => { if (enabled && !initialized.current) void reload(); return () => { version.current++; }; },[enabled,reload]);
 const selectedProject = projects.find(p => p.project_id === id && p.data_mode === mode);
 const liveProject = selectedProject?.data_mode === 'LIVE' ? selectedProject.project_id : '';
 const providerRead = useRead(useCallback(async () => {
  const [context, connections] = await Promise.all([operations.context(liveProject),operations.providers(liveProject)]);
  const providers = await Promise.all(connections.map(async p => ({...p,available:(await operations.capabilities(liveProject,p.provider_type)).capabilities})));
  return {context,providers,projectId:liveProject};
 },[liveProject]),!!liveProject);
 const providerCurrent = providerRead.data?.projectId === liveProject ? providerRead.data : null;
 const selectMode = (value: DataMode) => { const project = chooseProject(projects,value,read(window.localStorage,modeKey(value))); setMode(value); setId(project?.project_id ?? ''); persist(window.localStorage,value,project?.project_id ?? ''); };
 const selectProject = (value: string) => { const project = projects.find(p => p.project_id === value && p.data_mode === mode); if (project) { setId(value); persist(window.localStorage,mode,value); } };
 const saveProject = (project: Project) => { setProjects(old => old.some(p => p.project_id === project.project_id) ? old.map(p => p.project_id === project.project_id ? project : p) : [...old,project]); setId(project.project_id); setMode(project.data_mode); persist(window.localStorage,project.data_mode,project.project_id); };
 const value: Scope = { projects, selectedProject, selectedProjectId:id, selectedMode:mode, loading, error, reload, selectMode, selectProject, saveProject, context:providerCurrent?.context ?? null, providers:providerCurrent?.providers ?? [], providerLoading:providerRead.loading, providerError:providerRead.error, reloadProviders:providerRead.reload };
 return <Context.Provider value={value}>{enabled && <ProjectScope/>}<div key={mode+':'+id}>{children}</div></Context.Provider>;
}
export function ProjectScope() {
 useLocale(); const s = useProjectScope();
 return <section aria-label={tr('scope.title')} className="mx-auto mt-5 max-w-7xl rounded-xl border bg-white p-5">
 <div className="flex flex-wrap items-end gap-5"><div><p className="mb-2 text-sm font-semibold">{tr('scope.mode')}</p><div role="group" aria-label={tr('scope.mode')}>{(['DEMO','LIVE'] as DataMode[]).map(mode => <button key={mode} aria-pressed={s.selectedMode === mode} className={s.selectedMode === mode ? 'primary' : ''} disabled={s.loading} onClick={() => s.selectMode(mode)}>{tr(mode === 'DEMO' ? 'scope.demo' : 'scope.live')}</button>)}</div></div>
 <label>{tr('common.project')}<select value={s.selectedProjectId} disabled={s.loading || !!s.error} onChange={e => s.selectProject(e.target.value)}><option value="" disabled>{tr('common.selectProject')}</option>{s.projects.filter(p => p.data_mode === s.selectedMode).map(p => <option key={p.project_id} value={p.project_id}>{p.name}{p.is_active ? '' : tr('common.inactiveSuffix')}</option>)}</select></label>
 <span>{tr(s.selectedMode === 'DEMO' ? 'scope.demo' : 'scope.live')} · {s.selectedProject && tr(s.selectedProject.is_active ? 'common.active' : 'common.inactive')}</span></div>
 {s.loading ? <p role="status">{tr('common.loadingProjects')}</p> : s.error ? <p role="alert">{s.error} <button onClick={() => void s.reload()}>{tr('common.retry')}</button></p> : !s.selectedProject && <p>{tr('scope.empty')} <Link href="/dashboard/settings">{tr('settings.newProject')}</Link></p>}
 </section>;
}
export function FeatureGate({feature,children}: { feature: Feature; children: ReactNode }) {
 useLocale(); const s = useProjectScope(); const project = s.selectedProject;
 if (!project || project.data_mode === 'DEMO') return <>{children}</>;
 if (s.providerLoading || !s.context && !s.providerError) return <p role="status">{tr('common.loading')}</p>;
 if (s.providerError) return <p role="alert">{s.providerError} <button onClick={() => void s.reloadProviders()}>{tr('common.retry')}</button></p>;
 const status = featureAvailability(project,s.providers,feature,s.context?.live_operations_enabled ?? false);
 return status === 'Supported' ? <>{children}</> : <section className="rounded-xl bg-white p-6" role="status"><h2>{tr('availability.'+status)}</h2><p>{tr('scope.noFallback')}</p><Link href="/dashboard/settings?tab=providers">{tr('provider.open')}</Link></section>;
}
export function useFeatureProject(feature: Feature) { const s = useProjectScope(); const project = s.selectedProject; return project ? {...project,platforms:availablePlatformsForFeature(project,s.providers,feature)} : undefined; }
