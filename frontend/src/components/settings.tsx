"use client";
import Link from 'next/link';
import { useProjectScope } from './project-scope';
import ProviderSettings from './provider-settings';
import { t as tr, displayLabel, intlLocale, errorText, countText } from '../i18n';
import { useLocale, LanguageSetting } from '../i18n/react';
import OverviewLink from './overview-link';
import AIInsightsLink from './ai-insights-link';
import JobOperations from './job-operations';

import { FormEvent, ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, HistoryPage, ImportHistoryDetail, ImportResult, ImportType, Platform, Project, Role, RowError, SNSAccount, TermType, WatchTerm, WatchTopic } from "../lib/api";

const tabs = ["Project", "Providers", "Accounts", "Topics", "Import", "Schedules", "Jobs"] as const;
type Tab = typeof tabs[number];
type Run = (action: () => Promise<void>) => Promise<void>;
const importTypes: ImportType[] = ["OWN_POSTS", "ACCOUNT_DAILY", "TREND_POSTS", "COMPETITOR_POSTS"];
const messageOf = (error: unknown) => error instanceof ApiError ? error.message : tr('error.unexpected');
function Field({ label, children }: { label: string; children: ReactNode }) {
  useLocale(); return <label className="grid gap-2 text-sm font-medium text-slate-700">{displayLabel(label)}{children}</label>; }
function Badge({ active }: { active: boolean }) {
  useLocale(); return <span className={`rounded-full px-3 py-1 text-xs font-semibold ${active ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-slate-600"}`}>{active ? tr('common.active') : tr('common.inactive')}</span>; }
function Card({ title, children }: { title: string; children: ReactNode }) {
  useLocale(); return <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><h2 className="mb-5 text-lg font-semibold">{title}</h2>{children}</section>; }
function ErrorState({ error, retry }: { error: string; retry: () => void }) {
  useLocale(); return <div role="alert" className="rounded-lg bg-red-50 p-4 text-red-800">{error} <button type="button" onClick={retry}>{tr('common.retry')}</button></div>; }
function useResource<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const version = useRef(0);
  const reload = useCallback(async () => {
    const token = ++version.current;
    setLoading(true); setError("");
    try { const value = await loader(); if (version.current === token) setData(value); }
    catch (e) { if (version.current === token) setError(messageOf(e)); }
    finally { if (version.current === token) setLoading(false); }
  }, [loader]);
  useEffect(() => { void reload(); return () => { ++version.current; }; }, [reload]);
  return { data, loading, error, reload };
}

export default function Settings() {
  useLocale();
  const scope = useProjectScope();
  const projects = scope.projects, selected = scope.selectedProject, loading = scope.loading, error = scope.error, load = scope.reload;
  const [tab, setTab] = useState<Tab>("Project");
  const [busy, setBusy] = useState(false);
  const sending = useRef(false), mounted = useRef(true);
  useEffect(() => { mounted.current=true; return () => { mounted.current=false; }; },[]);
  const [notice, setNotice] = useState("");
  const [create, setCreate] = useState(false);
  useEffect(() => { const value = new URLSearchParams(window.location.search).get('tab'); const found = tabs.find(t => t.toLowerCase() === value); if (found) setTab(found); },[]);
  const run: Run = async action => {
    if (sending.current) return;
    sending.current = true; setBusy(true); setNotice("");
    try { await action(); if (mounted.current) setNotice(tr('settings.saved')); }
    catch (e) { if (mounted.current) setNotice(messageOf(e)); }
    finally { sending.current = false; if (mounted.current) setBusy(false); }
  };
  const updateProject = (p: Project) => { if (mounted.current) scope.saveProject(p); };
  return <main className="mx-auto max-w-6xl px-5 py-10">
    <div className="mb-8 flex flex-wrap items-start justify-between gap-5"><div><p className="text-xs font-bold tracking-widest text-teal-700">SNS TREND &amp; PERFORMANCE ANALYZER</p><h1 className="mt-3 text-3xl font-bold tracking-tight">{tr('nav.settings')}</h1><p className="mt-2 text-slate-600">{tr('settings.descriptionNote')}</p></div><nav className="flex flex-wrap gap-4 text-sm"><OverviewLink/><AIInsightsLink/><Link className="text-teal-800 underline" href="/dashboard/gap">{tr('nav.gap')}</Link><Link className="text-teal-800 underline" href="/dashboard/competitors">{tr('nav.competitor')}</Link><Link className="text-teal-800 underline" href="/dashboard/trends">{tr('nav.trends')}</Link><Link className="text-teal-800 underline" href="/dashboard/my-account">{tr('nav.account')}</Link><Link className="text-teal-800 underline" href="/">{tr('nav.health')}</Link></nav></div>
    <div className="mb-6 flex flex-wrap items-end gap-4"><LanguageSetting/><button disabled={busy || loading} onClick={() => { setCreate(true); setTab("Project"); }}>{tr('settings.newProject')}</button></div>
    <div role="tablist" aria-label={tr('settings.settingsLabel')} className="mb-6 flex flex-wrap gap-2 border-b border-slate-200 pb-3">{tabs.map(t => <button key={t} id={`tab-${t}`} role="tab" aria-selected={tab === t} aria-controls={`panel-${t}`} disabled={busy} onClick={() => { setTab(t); setCreate(false); setNotice(""); const url = new URL(window.location.href); url.searchParams.set("tab", t.toLowerCase()); window.history.replaceState(null, "", url); }} className={tab === t ? "bg-teal-700 text-white" : "bg-white text-slate-700"}>{displayLabel(t)}</button>)}</div>
    <p aria-live="polite" role="status" className="mb-4 min-h-6 text-sm text-slate-700">{busy ? (tab === "Import" ? tr('settings.uploading') : tr('settings.saving')) : notice}</p>
    {loading ? <p aria-live="polite">{tr('common.loadingProjects')}</p> : error ? <ErrorState error={error} retry={() => void load()} /> : <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
      {!selected && !create && <Card title={tr('common.noProject')}><p>{tr('settings.setup')}</p><button className="mt-4" onClick={() => { setCreate(true); setTab("Project"); }}>{tr('settings.newProject')}</button></Card>}
      {(selected || create) && <fieldset disabled={busy} className="min-w-0 space-y-6">
        {tab === "Project" && <ProjectTab key={create ? "new" : selected?.project_id} project={create ? undefined : selected} run={run} onSaved={p => { if (!mounted.current) return; if (create) { const url = new URL(window.location.href); url.searchParams.set('tab',p.data_mode === 'LIVE' ? 'providers' : 'project'); window.history.replaceState(null,'',url); scope.saveProject(p); setCreate(false); } else updateProject(p); }} cancel={create && projects.length > 0 ? () => setCreate(false) : undefined} />}
        {selected && tab === "Providers" && <ProviderSettings key={selected.project_id} project={selected}/> }
        {selected && tab === "Accounts" && <AccountsTab key={selected.project_id} project={selected} run={run} />}
        {selected && tab === "Topics" && <TopicsTab key={selected.project_id} project={selected} run={run} />}
        {selected && tab === "Import" && <ImportTab key={selected.project_id} project={selected} run={run} />}
        {selected && (tab === 'Schedules' || tab === 'Jobs') && <JobOperations key={selected.project_id+tab} project={selected} kind={tab} />}
      </fieldset>}
    </div>}
  </main>;
}

function PlatformPicker({ values, onChange }: { values: Platform[]; onChange: (values: Platform[]) => void }) {
  useLocale(); return <div className="flex gap-6">{(["X", "INSTAGRAM"] as Platform[]).map(p => <label className="flex items-center gap-2" key={p}><input type="checkbox" checked={values.includes(p)} onChange={e => onChange(e.target.checked ? [...values, p] : values.filter(v => v !== p))} />{p === "INSTAGRAM" ? "Instagram" : "X"}</label>)}</div>; }
function ProjectTab({ project, run, onSaved, cancel }: { project?: Project; run: Run; onSaved: (p: Project) => void; cancel?: () => void }) {
  useLocale();
  const [dataMode,setDataMode] = useState<Project["data_mode"]>(project?.data_mode ?? "DEMO");
  const [name, setName] = useState(project?.name ?? ""); const [description, setDescription] = useState(project?.description ?? "");
  const [platforms, setPlatforms] = useState<Platform[]>(project?.platforms ?? ["X"]);
  const save = (e: FormEvent) => { e.preventDefault(); void run(async () => {
    const body = { name: name.trim(), description: description.trim() || null };
    if (!body.name || (!project && !platforms.length)) throw new ApiError(tr('validation.project'), 400);
    onSaved(project ? await api.updateProject(project.project_id, body) : await api.createProject({ ...body, platforms, data_mode: dataMode }));
  }); };
  return <><Card title={project ? tr('settings.projectSettings') : tr('settings.newProject')}><form className="grid gap-5" onSubmit={save}><Field label={tr('settings.projectName')}><input required maxLength={100} value={name} onChange={e => setName(e.target.value)} /></Field><Field label={tr('settings.description')}><textarea rows={3} value={description} onChange={e => setDescription(e.target.value)} /></Field><Field label={tr('scope.mode')}>{project ? <p>{tr(project.data_mode === 'DEMO' ? 'scope.demo' : 'scope.live')} · {tr('scope.immutable')}</p> : <select value={dataMode} onChange={e => setDataMode(e.target.value as Project['data_mode'])}><option value="DEMO">{tr('scope.demo')}</option><option value="LIVE">{tr('scope.live')}</option></select>}</Field>{!project && <PlatformPicker values={platforms} onChange={setPlatforms} />}<div className="flex gap-3"><button className="primary" type="submit">{project ? tr('settings.saveProject') : tr('settings.createProject')}</button>{cancel && <button type="button" onClick={cancel}>{tr('common.cancel')}</button>}</div></form>{project && <div className="mt-6 flex items-center gap-4"><Badge active={project.is_active} /><button onClick={() => void run(async () => onSaved(await api.updateProject(project.project_id, { is_active: !project.is_active })))}>{project.is_active ? tr('settings.deactivateProject') : tr('settings.activateProject')}</button></div>}</Card>
    {project && <Card title={tr('settings.platforms')}><p className="mb-4 text-sm text-slate-600">{tr('settings.platformNote')}</p><PlatformPicker values={platforms} onChange={setPlatforms} /><button className="primary mt-5" disabled={!platforms.length} onClick={() => void run(async () => { const result = await api.platforms(project.project_id, platforms); setPlatforms(result.platforms); onSaved({ ...project, platforms: result.platforms }); })}>{tr('settings.savePlatforms')}</button></Card>}
  </>;
}

function AccountsTab({ project, run }: { project: Project; run: Run }) {
  useLocale();
  const loader = useCallback(() => api.accounts(project.project_id), [project.project_id]); const resource = useResource(loader);
  const [editing, setEditing] = useState<SNSAccount | null | undefined>(undefined);
  return <><Card title={tr('settings.accounts')}>{project.data_mode === 'DEMO' ? <button className="mb-5" onClick={() => setEditing(null)}>{tr('settings.addAccount')}</button> : <p className="mb-5">{tr('scope.providerAccounts')}</p>}{resource.loading ? <p>{tr('common.loadingAccounts')}</p> : resource.error ? <ErrorState error={resource.error} retry={() => void resource.reload()} /> : !resource.data?.length ? <p>{tr('settings.noAccounts')}</p> : <div className="overflow-x-auto"><table><thead><tr>{["Platform", "Role", "Account Name", "Display Name", "Status", tr('common.actions')].map(v => <th key={v}>{displayLabel(v)}</th>)}</tr></thead><tbody>{resource.data.map(a => <tr key={a.account_id}><td>{a.platform}</td><td>{displayLabel(a.account_role)}</td><td>{a.account_name}</td><td>{a.display_name ?? "—"}</td><td><Badge active={a.is_active} /></td><td className="space-x-2">{project.data_mode === 'DEMO' && <><button onClick={() => setEditing(a)}>{tr('common.edit')}</button><button onClick={() => void run(async () => { await api.updateAccount(project.project_id, a.account_id, { is_active: !a.is_active }); await resource.reload(); })}>{a.is_active ? tr('settings.deactivate') : tr('settings.activate')}</button></>}</td></tr>)}</tbody></table></div>}</Card>
    {editing !== undefined && <AccountForm key={editing?.account_id ?? "new"} account={editing} project={project} run={run} cancel={() => setEditing(undefined)} saved={async () => { setEditing(undefined); await resource.reload(); }} />}
  </>;
}
function AccountForm({ account, project, run, cancel, saved }: { account: SNSAccount | null; project: Project; run: Run; cancel: () => void; saved: () => Promise<void> }) {
  useLocale();
  const [platform, setPlatform] = useState<Platform>(account?.platform ?? project.platforms[0] ?? "X"); const [role, setRole] = useState<Role>(account?.account_role ?? "OWN");
  const [name, setName] = useState(account?.account_name ?? ""); const [display, setDisplay] = useState(account?.display_name ?? ""); const [platformId, setPlatformId] = useState(account?.platform_account_id ?? ""); const [url, setUrl] = useState(account?.profile_url ?? "");
  return <Card title={account ? tr('settings.editAccount') : tr('settings.addAccount')}><form className="grid gap-5 md:grid-cols-2" onSubmit={e => { e.preventDefault(); void run(async () => { const body = { account_name: name.trim(), display_name: display.trim() || null, platform_account_id: platformId.trim() || null, profile_url: url.trim() || null }; if (!body.account_name) throw new ApiError(tr('validation.account'), 400); if (account) await api.updateAccount(project.project_id, account.account_id, body); else await api.createAccount(project.project_id, { ...body, platform, account_role: role }); await saved(); }); }}>
    <Field label={tr('common.platform')}>{account ? <p>{platform}{tr('settings.immutable')}</p> : <select value={platform} onChange={e => setPlatform(e.target.value as Platform)}>{project.platforms.map(p => <option key={p}>{p}</option>)}</select>}</Field><Field label={tr('settings.role')}>{account ? <p>{displayLabel(role)}{tr('settings.immutable')}</p> : <select value={role} onChange={e => setRole(e.target.value as Role)}><option value="OWN">{tr('enum.own')}</option><option value="COMPETITOR">{tr('enum.competitor')}</option></select>}</Field>
    <Field label={tr('settings.accountName')}><input required maxLength={100} value={name} onChange={e => setName(e.target.value)} /></Field><Field label={tr('settings.displayName')}><input maxLength={200} value={display} onChange={e => setDisplay(e.target.value)} /></Field><Field label={tr('settings.platformAccount')}><input maxLength={255} value={platformId} onChange={e => setPlatformId(e.target.value)} /></Field><Field label={tr('settings.profileUrl')}><input type="url" value={url} onChange={e => setUrl(e.target.value)} /></Field><div className="flex gap-3"><button className="primary" type="submit">{tr('settings.saveAccount')}</button><button type="button" onClick={cancel}>{tr('common.cancel')}</button></div>
  </form></Card>;
}

function TopicsTab({ project, run }: { project: Project; run: Run }) {
  useLocale();
  const loader = useCallback(() => api.topics(project.project_id), [project.project_id]); const resource = useResource(loader);
  const [editing, setEditing] = useState<WatchTopic | null | undefined>(undefined);
  const [termEdit, setTermEdit] = useState<{ topic: WatchTopic; term: WatchTerm | null } | null>(null);
  return <><Card title={tr('settings.watchTopics')}><p className="mb-4 text-sm text-slate-600">{tr('settings.matchNote')}</p>{project.data_mode === 'LIVE' && <p className="mb-4 text-sm text-slate-600">{tr('scope.topicNote')}</p>}<button onClick={() => setEditing(null)}>{tr('settings.addTopic')}</button></Card>
    {resource.loading ? <p>{tr('common.loadingTopics')}</p> : resource.error ? <ErrorState error={resource.error} retry={() => void resource.reload()} /> : !resource.data?.length ? <p>{tr('settings.noTopics')}</p> : resource.data.map(t => <Card key={t.topic_id} title={t.topic_name}><div className="mb-4 flex flex-wrap items-center gap-3"><Badge active={t.is_active} /><p className="flex-1 text-sm text-slate-600">{t.description}</p><button onClick={() => setEditing(t)}>{tr('settings.editTopic')}</button><button onClick={() => void run(async () => { await api.updateTopic(project.project_id, t.topic_id, { is_active: !t.is_active }); await resource.reload(); })}>{t.is_active ? tr('settings.deactivateTopic') : tr('settings.activateTopic')}</button></div>
      {!t.terms.length ? <p className="mb-4 text-sm text-slate-500">{tr('settings.noTerms')}</p> : <div className="mb-4 overflow-x-auto"><table><thead><tr><th>{tr('settings.term')}</th><th>{tr('common.type')}</th><th>{tr('common.status')}</th><th>{tr('common.actions')}</th></tr></thead><tbody>{t.terms.map(term => <tr key={term.term_id}><td>{term.term}</td><td>{displayLabel(term.term_type)}</td><td><Badge active={term.is_active} /></td><td className="space-x-2"><button onClick={() => setTermEdit({ topic: t, term })}>{tr('settings.editTerm')}</button><button onClick={() => void run(async () => { await api.updateTerm(project.project_id, t.topic_id, term.term_id, { is_active: !term.is_active }); await resource.reload(); })}>{term.is_active ? tr('settings.deactivateTerm') : tr('settings.activateTerm')}</button></td></tr>)}</tbody></table></div>}<button onClick={() => setTermEdit({ topic: t, term: null })}>{tr('settings.addTerm')}</button></Card>)}
    {editing !== undefined && <TopicForm key={editing?.topic_id ?? "new"} topic={editing} project={project} run={run} cancel={() => setEditing(undefined)} saved={async () => { setEditing(undefined); await resource.reload(); }} />}
    {termEdit && <TermForm key={termEdit.term?.term_id ?? termEdit.topic.topic_id} {...termEdit} project={project} run={run} cancel={() => setTermEdit(null)} saved={async () => { setTermEdit(null); await resource.reload(); }} />}
  </>;
}
function TopicForm({ topic, project, run, cancel, saved }: { topic: WatchTopic | null; project: Project; run: Run; cancel: () => void; saved: () => Promise<void> }) {
  useLocale();
  const [name, setName] = useState(topic?.topic_name ?? ""); const [description, setDescription] = useState(topic?.description ?? "");
  return <Card title={topic ? tr('settings.editTopic') : tr('settings.addTopic')}><form className="grid gap-5" onSubmit={e => { e.preventDefault(); void run(async () => { const body = { topic_name: name.trim(), description: description.trim() || null }; if (!body.topic_name) throw new ApiError(tr('validation.topic'), 400); if (topic) await api.updateTopic(project.project_id, topic.topic_id, body); else await api.createTopic(project.project_id, body); await saved(); }); }}><Field label={tr('settings.topicName')}><input required maxLength={100} value={name} onChange={e => setName(e.target.value)} /></Field><Field label={tr('settings.description')}><textarea value={description} onChange={e => setDescription(e.target.value)} /></Field><div className="flex gap-3"><button className="primary" type="submit">{tr('settings.saveTopic')}</button><button type="button" onClick={cancel}>{tr('common.cancel')}</button></div></form></Card>;
}
function TermForm({ topic, term, project, run, cancel, saved }: { topic: WatchTopic; term: WatchTerm | null; project: Project; run: Run; cancel: () => void; saved: () => Promise<void> }) {
  useLocale();
  const [value, setValue] = useState(term?.term ?? ""); const [type, setType] = useState<TermType>(term?.term_type ?? "KEYWORD");
  return <Card title={`${term ? tr('settings.editTerm') : tr('settings.addTerm')} · ${topic.topic_name}`}><form className="grid gap-5" onSubmit={e => { e.preventDefault(); void run(async () => { const body = { term: value.trim(), term_type: type }; if (!body.term) throw new ApiError(tr('validation.term'), 400); if (term) await api.updateTerm(project.project_id, topic.topic_id, term.term_id, body); else await api.createTerm(project.project_id, topic.topic_id, body); await saved(); }); }}><Field label={tr('settings.term')}><input required maxLength={255} value={value} onChange={e => setValue(e.target.value)} /></Field><Field label={tr('common.type')}><select value={type} onChange={e => setType(e.target.value as TermType)}><option value="KEYWORD">{tr('enum.keyword')}</option><option value="HASHTAG">{tr('enum.hashtag')}</option></select></Field><p className="text-sm text-slate-500">{tr('settings.hashtagNote')}</p><div className="flex gap-3"><button className="primary" type="submit">{tr('settings.saveTerm')}</button><button type="button" onClick={cancel}>{tr('common.cancel')}</button></div></form></Card>;
}

function Errors({ errors }: { errors: RowError[] }) {
  useLocale(); return !errors.length ? null : <div className="mt-4 overflow-x-auto"><table><thead><tr>{["Row", "Field", "Code", "Message"].map(v => <th key={v}>{displayLabel(v)}</th>)}</tr></thead><tbody>{errors.map((e, i) => <tr key={i}><td>{e.row ?? "—"}</td><td>{e.field}</td><td>{e.code}</td><td>{errorText(e.code)}</td></tr>)}</tbody></table></div>; }
function ImportTab({ project, run }: { project: Project; run: Run }) {
  useLocale();
  const [type, setType] = useState<ImportType>("OWN_POSTS"); const [file, setFile] = useState<File | null>(null); const [result, setResult] = useState<ImportResult | null>(null);
  const [page, setPage] = useState(1); const [status, setStatus] = useState(""); const [filterType, setFilterType] = useState("");
  const loader = useCallback(() => api.histories(project.project_id, page, status, filterType), [project.project_id, page, status, filterType]); const resource = useResource<HistoryPage>(loader);
  const [detail, setDetail] = useState<ImportHistoryDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false); const [detailError, setDetailError] = useState("");
  const detailVersion = useRef(0); const detailId = useRef("");
  useEffect(() => () => { ++detailVersion.current; }, []);
  const showDetail = async (id: string) => {
    const token = ++detailVersion.current; detailId.current = id; setDetailLoading(true); setDetail(null); setDetailError("");
    try { const value = await api.history(project.project_id, id); if (detailVersion.current === token) setDetail(value); }
    catch (e) { if (detailVersion.current === token) setDetailError(messageOf(e)); }
    finally { if (detailVersion.current === token) setDetailLoading(false); }
  };
  return <>{project.data_mode === 'DEMO' ? <Card title={tr('settings.csvImport')}><form className="grid gap-5" onSubmit={e => { e.preventDefault(); void run(async () => { if (!file) throw new ApiError(tr('validation.file'), 400); setResult(null); try { setResult(await api.importCsv(project.project_id, type, file)); } catch (e) { if (e instanceof ApiError && e.result) setResult(e.result); throw e; } finally { if (page !== 1) setPage(1); else await resource.reload(); } }); }}><Field label={tr('settings.importType')}><select value={type} onChange={e => setType(e.target.value as ImportType)}>{importTypes.map(t => <option key={t} value={t}>{displayLabel(t)}</option>)}</select></Field><Field label={tr('settings.csvFile')}><input type="file" accept=".csv,text/csv" required onChange={e => setFile(e.target.files?.[0] ?? null)} /></Field>{!project.is_active && <p className="text-amber-800">{tr('settings.inactiveImport')}</p>}<button className="primary w-fit" disabled={!project.is_active || !file} type="submit">{tr('settings.importCsv')}</button></form>
    {result && <div aria-live="polite" className="mt-6 rounded-xl bg-slate-50 p-4"><h3 className="font-semibold">{tr('label.importResult')} {displayLabel(result.status)}</h3><p className="mt-2">{tr('label.total')} {result.total_count ?? "—"} {tr('label.success')} {result.success_count ?? "—"} {tr('label.error')} {result.error_count ?? "—"}</p><Errors errors={result.errors} /></div>}</Card> : <Card title={tr('scope.live')}><p>{tr('scope.providerImport')}</p><Link href="/dashboard/settings?tab=providers">{tr('provider.open')}</Link></Card>}
    <Card title={tr('settings.history')}><div className="mb-5 flex flex-wrap gap-4"><Field label={tr('settings.statusFilter')}><select value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="">{tr('settings.allStatus')}</option>{["PROCESSING", "SUCCESS", "PARTIAL_ERROR", "FAILED"].map(v => <option key={v} value={v}>{displayLabel(v)}</option>)}</select></Field><Field label={tr('settings.typeFilter')}><select value={filterType} onChange={e => { setFilterType(e.target.value); setPage(1); }}><option value="">{tr('settings.allTypes')}</option>{importTypes.map(v => <option key={v} value={v}>{displayLabel(v)}</option>)}</select></Field></div>
      {resource.loading ? <p>{tr('common.loadingHistory')}</p> : resource.error ? <ErrorState error={resource.error} retry={() => void resource.reload()} /> : !resource.data?.items.length ? <p>{tr('settings.noHistory')}</p> : <div className="overflow-x-auto"><table><thead><tr>{["Date", "Type", "Filename", "Status", "Total", "Success", "Error", tr('common.actions')].map(v => <th key={v}>{displayLabel(v)}</th>)}</tr></thead><tbody>{resource.data.items.map(h => <tr key={h.import_id}><td className="whitespace-nowrap">{new Date(h.imported_at).toLocaleString(intlLocale())}</td><td>{displayLabel(h.import_type)}</td><td>{project.data_mode === 'LIVE' ? tr('provider.importHistory') : h.filename}</td><td>{displayLabel(h.status)}</td><td>{h.total_count}</td><td>{h.success_count}</td><td>{h.error_count}</td><td><button onClick={() => void showDetail(h.import_id)}>{tr('common.detail')}</button></td></tr>)}</tbody></table></div>}
      <div className="mt-5 flex items-center gap-4"><button disabled={page <= 1 || resource.loading} onClick={() => setPage(p => p - 1)}>{tr('common.previous')}</button><span>{tr('common.page')} {page} · {countText('items', resource.data?.total ?? 0)}</span><button disabled={resource.loading || !resource.data || page * 20 >= resource.data.total} onClick={() => setPage(p => p + 1)}>{tr('common.next')}</button></div>
    </Card>
    {detailLoading ? <p aria-live="polite">{tr('common.loadingDetail')}</p> : detailError ? <ErrorState error={detailError} retry={() => void showDetail(detailId.current)} /> : detail && <Card title={tr('settings.importDetail',{filename:project.data_mode === 'LIVE' ? tr('provider.importHistory') : detail.filename})}><p>{displayLabel(detail.status)} {tr('label.totalSuffix')} {detail.total_count} {tr('label.success')} {detail.success_count} {tr('label.error')} {detail.error_count}</p><Errors errors={detail.error_detail} />{!detail.error_detail.length && <p className="mt-3 text-sm">{tr('settings.noErrors')}</p>}<button className="mt-4" onClick={() => { ++detailVersion.current; setDetail(null); }}>{tr('common.closeJa')}</button></Card>}
  </>;
}
