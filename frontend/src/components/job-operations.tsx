"use client";
import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { t as tr, displayLabel, intlLocale, errorText } from '../i18n';
import { useLocale } from '../i18n/react';
import { canSync } from '../lib/project-context';
import { ApiError, Project } from '../lib/api';
import { operations, Job, Schedule, Provider, Page, ScheduleFields, canCancel, durationText, scheduleText, jobStatuses } from '../lib/job-operations';

const dateText = (value: string | null) => value ? new Date(value).toLocaleString(intlLocale(),{timeZone:'UTC'})+' UTC' : '—';
const message = (error: unknown) => error instanceof ApiError ? error.message : tr('error.unexpected');

export default function JobOperations({project, kind}: {project: Project; kind:'Schedules'|'Jobs'}) {
  useLocale();
  const [providers,setProviders]=useState<Provider[]>([]),[live,setLive]=useState(false);
  const [schedules,setSchedules]=useState<Page<Schedule>|null>(null),[jobs,setJobs]=useState<Page<Job>|null>(null);
  const [page,setPage]=useState(1),[provider,setProvider]=useState(''),[status,setStatus]=useState(''),[trigger,setTrigger]=useState('');
  const [from,setFrom]=useState(''),[to,setTo]=useState(''),[enabled,setEnabled]=useState('');
  const [loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [editing,setEditing]=useState<Schedule|null|undefined>(),[detail,setDetail]=useState<Job|null>(null);
  const version=useRef(0),mounted=useRef(true),sending=useRef(false),detailVersion=useRef(0);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;version.current++;detailVersion.current++;};},[]);
  const refresh=useCallback(async()=>{
    if(project.data_mode!=='LIVE'){setLoading(false);return;}
    const token=++version.current;setLoading(true);setError('');
    detailVersion.current++;setDetail(null);
    const query=new URLSearchParams({page:String(page),page_size:'50',...(provider?{provider_type:provider}:{})});
    if(kind==='Jobs'){
      if(status)query.set('status',status);if(trigger)query.set('trigger_type',trigger);
      if(from)query.set('from',from+'T00:00:00Z');if(to)query.set('to',to+'T23:59:59.999999Z');
    }else if(enabled)query.set('enabled',enabled);
    try{
      const [context,connections,list]=await Promise.all([operations.context(project.project_id),operations.providers(project.project_id),kind==='Schedules'?operations.schedules(project.project_id,query):operations.jobs(project.project_id,query)]);
      if(token!==version.current)return;
      const capabilities = await Promise.all(connections.map(async p => ({...p,available:(await operations.capabilities(project.project_id,p.provider_type)).capabilities})));
      if(token!==version.current)return;
      setLive(context.live_operations_enabled);setProviders(capabilities);
      if(kind==='Schedules')setSchedules(list as Page<Schedule>);else setJobs(list as Page<Job>);
    }catch(e){if(token===version.current)setError(message(e));}
    finally{if(token===version.current)setLoading(false);}
  },[project.project_id,project.data_mode,kind,page,provider,status,trigger,from,to,enabled]);
  useEffect(()=>{void refresh();return()=>{version.current++;};},[refresh]);
  async function run(action:()=>Promise<unknown>, successKey='settings.saved'){
    if(sending.current)return;sending.current=true;setBusy(true);setNotice('');
    try{await action();if(!mounted.current)return;setNotice(tr(successKey));setDetail(null);detailVersion.current++;await refresh();}
    catch(e){if(mounted.current)setNotice(message(e));}
    finally{sending.current=false;if(mounted.current)setBusy(false);}
  }
  async function show(id:string){const token=++detailVersion.current;setDetail(null);try{const row=await operations.job(project.project_id,id);if(mounted.current&&token===detailVersion.current)setDetail(row);}catch(e){if(mounted.current&&token===detailVersion.current)setNotice(message(e));}}
  if(project.data_mode!=='LIVE')return <section className="rounded-xl border bg-white p-6"><h2 className="text-lg font-semibold">{displayLabel(kind)}</h2><p className="mt-3">{tr('jobs.liveOnly')}</p></section>;
  const syncProviders = providers.filter(p => canSync(p,true));
  const data=kind==='Schedules'?schedules:jobs;
  return <section className="space-y-5 rounded-xl border bg-white p-6">
    <h2 className="text-lg font-semibold">{displayLabel(kind)}</h2><p className="text-sm text-slate-600">{tr('jobs.utcNote')}</p>
    {!loading&&!error&&!live&&<p className="rounded-lg bg-amber-50 p-3">{tr('jobs.liveDisabled')}</p>}
    <fieldset disabled={busy} className="flex flex-wrap items-end gap-3">
      <label>{tr('jobs.provider')}<select aria-label={tr('jobs.provider')} value={provider} onChange={e=>{setProvider(e.target.value);setPage(1);}}><option value="">{tr('jobs.all')}</option>{providers.map(p=><option key={p.id} value={p.provider_type}>{displayLabel(p.provider_type)}</option>)}</select></label>
      {kind==='Jobs'?<>
        <label>{tr('common.status')}<select value={status} onChange={e=>{setStatus(e.target.value);setPage(1);}}><option value="">{tr('jobs.all')}</option>{jobStatuses.map(s=><option key={s} value={s}>{displayLabel(s)}</option>)}</select></label>
        <label>{tr('jobs.trigger')}<select value={trigger} onChange={e=>{setTrigger(e.target.value);setPage(1);}}><option value="">{tr('jobs.all')}</option>{['MANUAL','SCHEDULED','SYSTEM'].map(s=><option key={s} value={s}>{displayLabel(s)}</option>)}</select></label>
        <label>{tr('jobs.from')}<input type="date" value={from} onChange={e=>{setFrom(e.target.value);setPage(1);}}/></label>
        <label>{tr('jobs.to')}<input type="date" value={to} onChange={e=>{setTo(e.target.value);setPage(1);}}/></label>
      </>:<label>{tr('jobs.enabled')}<select value={enabled} onChange={e=>{setEnabled(e.target.value);setPage(1);}}><option value="">{tr('jobs.all')}</option><option value="true">{tr('common.active')}</option><option value="false">{tr('common.inactive')}</option></select></label>}
      <button onClick={()=>void refresh()}>{tr('common.retry')}</button>{kind==='Schedules'&&<button disabled={!live || !syncProviders.length} onClick={()=>setEditing(null)}>{tr('jobs.addSchedule')}</button>}
    </fieldset>
    <p role="status" aria-live="polite">{busy?tr('settings.saving'):notice}</p>{error&&<p role="alert">{error}</p>}
    {loading?<p>{tr('common.loading')}</p>:!data?.items.length?<p>{tr('jobs.empty')}</p>:<div className="overflow-x-auto"><table><thead><tr>
      <th>{tr('jobs.provider')}</th><th>{kind==='Schedules'?tr('jobs.mode'):tr('jobs.trigger')}</th><th>{tr('common.status')}</th><th>{kind==='Schedules'?tr('jobs.next'):tr('common.dateUtc')}</th><th>{kind==='Schedules'?tr('jobs.last'):tr('jobs.duration')}</th><th>{tr('common.actions')}</th>
    </tr></thead><tbody>{kind==='Schedules'?schedules?.items.map(s=><tr key={s.id}>
      <td>{displayLabel(s.provider_type)}</td><td>{displayLabel(s.schedule_mode)}<br/>{scheduleText(s)}</td><td>{s.enabled?tr('common.active'):tr('common.inactive')}</td><td>{dateText(s.next_run_at)}</td><td>{dateText(s.last_run_at)}<br/>{s.last_job&&<button onClick={()=>void show(s.last_job!.id)}>{displayLabel(s.last_job.status)}</button>}</td>
      <td className="space-x-2"><button disabled={busy} onClick={()=>setEditing(s)}>{tr('common.edit')}</button><button disabled={busy||(!s.enabled&&(!live || !syncProviders.some(p=>p.id === s.provider_connection_id)))} onClick={()=>void run(()=>operations.action(project.project_id,s.id,s.enabled?'disable':'enable'))}>{s.enabled?tr('jobs.disable'):tr('jobs.enable')}</button><button disabled={busy||!live || !syncProviders.some(p=>p.id === s.provider_connection_id)} onClick={()=>void run(()=>operations.action(project.project_id,s.id,'run-now'),'jobs.manualAccepted')}>{tr('jobs.runNow')}</button><button disabled={busy} onClick={()=>void run(()=>operations.remove(project.project_id,s.id))}>{tr('jobs.delete')}</button></td>
    </tr>):jobs?.items.map(j=><tr key={j.id}>
      <td>{displayLabel(j.provider_type)}</td><td>{displayLabel(j.trigger_type)}</td><td>{displayLabel(j.status)}<br/>{tr('jobs.records')}: {j.record_count} / {tr('jobs.errors')}: {j.error_count}</td><td>{dateText(j.created_at)}<br/>{tr('jobs.started')}: {dateText(j.started_at)}</td><td>{durationText(j.duration_seconds)}</td>
      <td><button onClick={()=>void show(j.id)}>{tr('common.detail')}</button>{canCancel(j.status)&&<button disabled={busy} onClick={()=>void run(()=>operations.cancel(project.project_id,j.id))}>{tr('common.cancel')}</button>}{j.status==='RUNNING'&&<p className="text-xs">{tr('jobs.runningNoCancel')}</p>}</td>
    </tr>)}</tbody></table></div>}
    <div className="flex items-center gap-3"><button disabled={page<=1||loading||busy} onClick={()=>setPage(p=>p-1)}>{tr('common.previous')}</button><span>{page} / {Math.max(1,Math.ceil((data?.total??0)/50))} ({data?.total??0})</span><button disabled={loading||busy||page*50>=(data?.total??0)} onClick={()=>setPage(p=>p+1)}>{tr('common.next')}</button></div>
    {kind==='Schedules'&&providers.map(p=><div key={p.id} className="flex items-center gap-3"><span>{displayLabel(p.provider_type)}: {displayLabel(p.connection_status)} {p.sync_in_progress&&tr('jobs.syncing')}</span><button disabled={busy||!canSync(p,live)} onClick={()=>void run(()=>operations.sync(project.project_id,p.provider_type),'jobs.manualAccepted')}>{tr('jobs.manualSync')}</button></div>)}
    {editing!==undefined&&<ScheduleForm key={editing?.id??'new'} value={editing} providers={editing ? providers.filter(p=>p.id === editing.provider_connection_id) : syncProviders} live={live} busy={busy} cancel={()=>setEditing(undefined)} save={(fields,providerId,on)=>void run(async()=>{if(editing)await operations.patch(project.project_id,editing.id,fields);else await operations.create(project.project_id,providerId,fields,on);if(mounted.current)setEditing(undefined);})}/>}
    {detail&&<section aria-label={tr('jobs.detail')} className="rounded-lg border p-4"><div className="flex justify-between"><h3>{tr('jobs.detail')}: {detail.id}</h3><button onClick={()=>{setDetail(null);detailVersion.current++;}}>{tr('common.close')}</button></div><p>{displayLabel(detail.provider_type)} · {displayLabel(detail.status)} · {displayLabel(detail.trigger_type)} · {durationText(detail.duration_seconds)}</p><p>{tr('jobs.scheduledFor')}: {dateText(detail.scheduled_for)} · {tr('jobs.enqueued')}: {dateText(detail.enqueued_at)}</p><p>{tr('jobs.started')}: {dateText(detail.started_at)} · {tr('jobs.finished')}: {dateText(detail.finished_at)}</p><p>{tr('jobs.records')}: {detail.record_count} · {tr('jobs.errors')}: {detail.error_count}</p>{detail.error_code&&<p role="alert"><code>{detail.error_code}</code> · {displayLabel(detail.error_code)}: {errorText(detail.error_code)}</p>}<ol className="mt-4 space-y-3">{detail.steps?.map(step=><li key={step.id} className="border-l-4 border-teal-600 pl-3">{step.sequence_no}. {displayLabel(step.step_type)} — {displayLabel(step.status)}<p>{tr('jobs.attempts')}: {step.attempt_count} · {tr('jobs.records')}: {step.record_count} · {tr('jobs.errors')}: {step.error_count}</p><p>{dateText(step.started_at)} → {dateText(step.finished_at)}</p>{step.error_code&&<p><code>{step.error_code}</code> · {displayLabel(step.error_code)}: {errorText(step.error_code)}</p>}</li>)}</ol>{canCancel(detail.status)&&<button disabled={busy} onClick={()=>void run(()=>operations.cancel(project.project_id,detail.id))}>{tr('common.cancel')}</button>}{detail.status==='RUNNING'&&<p>{tr('jobs.runningNoCancel')}</p>}</section>}
  </section>;
}

function ScheduleForm({value,providers,live,busy,cancel,save}:{value:Schedule|null;providers:Provider[];live:boolean;busy:boolean;cancel:()=>void;save:(fields:ScheduleFields,provider:string,enabled:boolean)=>void}){
  const [provider,setProvider]=useState(value?.provider_connection_id??providers[0]?.id??'');
  const [mode,setMode]=useState<'INTERVAL'|'DAILY'>(value?.schedule_mode??'INTERVAL'),[interval,setInterval]=useState(value?.interval_seconds??3600);
  const [time,setTime]=useState(value?.daily_time?.slice(0,8)??'09:00'),[zone,setZone]=useState(value?.timezone??'Asia/Tokyo'),[on,setOn]=useState(false);
  const submit=(e:FormEvent)=>{e.preventDefault();save({schedule_mode:mode,interval_seconds:mode==='INTERVAL'?interval:null,daily_time:mode==='DAILY'?time:null,timezone:mode==='DAILY'?zone:null},provider,on);};
  return <form onSubmit={submit} className="grid gap-3 rounded-lg border p-5"><h3>{value?tr('common.edit'):tr('jobs.addSchedule')}</h3><fieldset disabled={busy} className="grid gap-3">
    <label>{tr('jobs.provider')}<select value={provider} disabled={!!value} onChange={e=>setProvider(e.target.value)}>{providers.map(p=><option key={p.id} value={p.id}>{displayLabel(p.provider_type)}</option>)}</select></label>
    <label>{tr('jobs.mode')}<select value={mode} onChange={e=>setMode(e.target.value as 'INTERVAL'|'DAILY')}><option value="INTERVAL">{displayLabel('INTERVAL')}</option><option value="DAILY">{displayLabel('DAILY')}</option></select></label>
    {mode==='INTERVAL'?<label>{tr('jobs.interval')}<input type="number" min={60} required value={interval} onChange={e=>setInterval(Number(e.target.value))}/></label>:<><label>{tr('jobs.dailyTime')}<input type="time" step={1} required value={time} onChange={e=>setTime(e.target.value)}/></label><label>{tr('jobs.timezone')}<input required maxLength={64} value={zone} onChange={e=>setZone(e.target.value)}/></label></>}
    {!value&&<label><input type="checkbox" disabled={!live} checked={on} onChange={e=>setOn(e.target.checked)}/>{tr('jobs.enabled')}</label>}
    <div><button type="submit">{tr('jobs.saveSchedule')}</button><button type="button" onClick={cancel}>{tr('common.cancel')}</button></div>
  </fieldset></form>;
}
