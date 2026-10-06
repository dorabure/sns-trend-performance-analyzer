import { apiFetch } from './api';
import type { Provider, ProjectContext, ProviderType, CapabilityMap } from './project-context';
export type { Provider } from './project-context';
export type Page<T> = { items: T[]; total: number; page: number; page_size: number };
export type ScheduleFields = { schedule_mode: 'INTERVAL' | 'DAILY'; interval_seconds: number | null; daily_time: string | null; timezone: string | null };
export type Schedule = ScheduleFields & { id: string; provider_connection_id: string; provider_type: string; enabled: boolean; next_run_at: string | null; last_run_at: string | null; last_job: {id:string;status:string} | null };
export type Step = { id: string; sequence_no: number; step_type: string; status: string; attempt_count: number; started_at: string | null; finished_at: string | null; record_count: number; error_count: number; error_code: string | null; error_summary: string | null };
export type Job = { id: string; provider_type: string | null; trigger_type: string; job_type: string; status: string; scheduled_for: string | null; enqueued_at: string | null; started_at: string | null; finished_at: string | null; duration_seconds: number | null; record_count: number; error_count: number; error_code: string | null; error_summary: string | null; created_at: string; steps?: Step[] };
const root = (pid: string) => `/projects/${encodeURIComponent(pid)}`;
const json = (method: string, body: object): RequestInit => ({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
export const operations = {
  context: (pid: string) => apiFetch<ProjectContext>(root(pid)+'/context'),
  providers: (pid: string) => apiFetch<Provider[]>(root(pid)+'/providers'),
  capabilities: (pid: string, type: ProviderType) => apiFetch<{provider_type:ProviderType;capabilities:CapabilityMap}>(root(pid)+'/providers/'+type+'/capabilities'),
  patchProvider: (pid: string, type: ProviderType, enabled: boolean) => apiFetch<Provider>(root(pid)+'/providers/'+type,json('PATCH',{enabled})),
  validate: (pid: string, type: ProviderType) => apiFetch<unknown>(root(pid)+'/providers/'+type+'/validate',{method:'POST'}),
  connect: (pid: string, type: ProviderType) => apiFetch<{authorize_url:string}>(root(pid)+'/providers/'+type+'/oauth/start',{method:'POST'}),
  schedules: (pid: string, query: URLSearchParams) => apiFetch<Page<Schedule>>(root(pid)+'/schedules?'+query),
  create: (pid: string, provider: string, body: ScheduleFields, enabled: boolean) => apiFetch<Schedule>(root(pid)+'/schedules',json('POST',{...body,provider_connection_id:provider,schedule_type:'PROVIDER_SYNC_PIPELINE',enabled})),
  patch: (pid: string, id: string, body: ScheduleFields) => apiFetch<Schedule>(root(pid)+'/schedules/'+id,json('PATCH',body)),
  action: (pid: string, id: string, action: 'enable'|'disable'|'run-now') => apiFetch<unknown>(root(pid)+'/schedules/'+id+'/'+action,{method:'POST'}),
  remove: (pid: string, id: string) => apiFetch<unknown>(root(pid)+'/schedules/'+id,{method:'DELETE'}),
  sync: (pid: string, type: string) => apiFetch<unknown>(root(pid)+'/providers/'+type+'/sync',{method:'POST'}),
  jobs: (pid: string, query: URLSearchParams) => apiFetch<Page<Job>>(root(pid)+'/jobs?'+query),
  job: (pid: string, id: string) => apiFetch<Job>(root(pid)+'/jobs/'+id),
  cancel: (pid: string, id: string) => apiFetch<Job>(root(pid)+'/jobs/'+id+'/cancel',{method:'POST'}),
};
export const jobStatuses = ['PENDING','RUNNING','SUCCESS','PARTIAL_ERROR','FAILED','SKIPPED','CANCELED'];
export function canCancel(status: string) { return status === 'PENDING'; }
export function durationText(seconds: number | null) { return seconds == null ? '—' : `${Math.max(0,seconds).toFixed(1)} s`; }
export function scheduleText(schedule: ScheduleFields) { return schedule.schedule_mode === 'INTERVAL' ? `${schedule.interval_seconds} s` : `${schedule.daily_time?.slice(0,5)} (${schedule.timezone})`; }
