const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm'),ts=require('typescript');
function load(path,dependencies={}){const exports={};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,{exports,URLSearchParams,require:name=>dependencies[name]});return exports;}
const lib=load('src/lib/job-operations.ts',{'./api':{apiFetch(){}}});
test('interval and daily display preserve configured values and timezone',()=>{assert.equal(lib.scheduleText({schedule_mode:'INTERVAL',interval_seconds:3600}),'3600 s');assert.equal(lib.scheduleText({schedule_mode:'DAILY',daily_time:'09:30:00',timezone:'Asia/Tokyo'}),'09:30 (Asia/Tokyo)');});
test('duration formatting keeps unknown distinct from zero',()=>{assert.equal(lib.durationText(null),'—');assert.equal(lib.durationText(0),'0.0 s');assert.equal(lib.durationText(61.25),'61.3 s');});
test('only pending jobs expose cancellation',()=>{for(const status of lib.jobStatuses)assert.equal(lib.canCancel(status),status==='PENDING');assert.equal(lib.canCancel('UNKNOWN'),false);});
function i18n(){return load('src/i18n/index.ts',Object.fromEntries(['ja','en','labels'].map(key=>['./'+key,load('src/i18n/'+key+'.ts')])));}
test('scheduler errors map to specific safe messages in both languages',()=>{const i=i18n();for(const [code,key] of Object.entries({LIVE_MODE_DISABLED:'liveDisabled',SCHEDULE_REQUIRES_LIVE:'liveOnly',PROVIDER_NOT_READY:'notReady',JOB_ALREADY_RUNNING:'alreadyRunning',SCHEDULE_ALREADY_EXISTS:'duplicateSchedule',JOB_NOT_CANCELABLE:'notCancelable'}))assert.equal(i.errorText(code,409),i.t('jobs.'+key));for(const locale of ['ja','en'])for(const key of ['jobs.liveOnly','jobs.empty','jobs.pending','jobs.running','jobs.scheduled'])assert.ok(i.dictionaries[locale][key]);});
test('job and trigger labels include pending running and all terminal states',()=>{const i=i18n();for(const value of ['PENDING','RUNNING','SUCCESS','PARTIAL_ERROR','FAILED','SKIPPED','CANCELED','MANUAL','SCHEDULED','SYSTEM','PROVIDER_SYNC','NORMALIZE_IMPORT','TREND_REBUILD','AI_INSIGHT_GENERATE'])assert.notEqual(i.displayLabel(value),value);});
test('run-now uses scoped public endpoint and never edits next run',async()=>{const calls=[];const {operations}=load('src/lib/job-operations.ts',{'./api':{apiFetch:(...args)=>{calls.push(args);return Promise.resolve({});}}});await operations.action('p','s','run-now');assert.equal(calls[0][0],'/projects/p/schedules/s/run-now');assert.equal(calls[0][1].method,'POST');assert.equal(calls[0][1].body,undefined);});
test('DEMO renders live-only explanation and no schedule execution controls',()=>{
 const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
 const exports={};const i=i18n();const source=ts.transpileModule(fs.readFileSync('src/components/job-operations.tsx','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2020}}).outputText;
 vm.runInNewContext(source,{exports,require:name=>name==='../i18n'?i:name==='../i18n/react'?{useLocale(){}}:name==='../lib/api'?{ApiError:Error}:name==='../lib/job-operations'?lib:name==='../lib/project-context'?load('src/lib/project-context.ts'):require(name)});
 const html=renderToStaticMarkup(React.createElement(exports.default,{project:{project_id:'demo',data_mode:'DEMO'},kind:'Schedules'}));assert.ok(html.includes(i.t('jobs.liveOnly')));assert.ok(!html.includes('<button'));
});

test('capability rejection has a specific safe localized explanation',()=>{
 const i=i18n();assert.equal(i.errorText('PROVIDER_CAPABILITY_UNAVAILABLE',409),i.t('jobs.capabilityUnavailable'));
 for(const locale of ['ja','en'])assert.ok(i.dictionaries[locale]['jobs.capabilityUnavailable']);
 assert.notEqual(i.errorText('PROVIDER_CAPABILITY_UNAVAILABLE',409),i.t('error.conflict'));
});

function renderLive(kind,rows,providers,live=true){
 const React=require('react'),{renderToStaticMarkup}=require('react-dom/server'),i=i18n(),exports={};
 const values=[providers,live,kind==='Schedules'?{items:rows,total:rows.length}:null,kind==='Jobs'?{items:rows,total:rows.length}:null,
  1,'','','','','','',false,false,'','',undefined,null];let index=0;
 const hooks={...React,useState:()=>[values[index++],()=>{}],useEffect(){},useCallback:f=>f,useRef:v=>({current:v})};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/components/job-operations.tsx','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2020}}).outputText,
  {exports,require:name=>name==='react'?hooks:name==='../i18n'?i:name==='../i18n/react'?{useLocale(){}}:name==='../lib/api'?{ApiError:Error}:name==='../lib/job-operations'?lib:name==='../lib/project-context'?load('src/lib/project-context.ts'):require(name)});
 return {html:renderToStaticMarkup(React.createElement(exports.default,{project:{project_id:'p',data_mode:'LIVE'},kind})),i};
}
const xp={id:'x',provider_type:'X_API',enabled:true,connection_status:'CONNECTED',sync_in_progress:false,capabilities:['ACCOUNT_PROFILE','OWN_POSTS','OWN_METRICS']};
const ig={...xp,id:'ig',provider_type:'INSTAGRAM_API',available:{OWN_POSTS:false},capabilities:['ACCOUNT_PROFILE','OWN_POSTS']};
test('profile-only Instagram cannot create schedules while connected X can',()=>{
 const only=renderLive('Schedules',[],[ig]);const mixed=renderLive('Schedules',[],[xp,ig]);
 // Inspect the actual translated button rather than assuming its locale.
 const add=(html,i)=>html.slice(html.lastIndexOf('<button',html.indexOf(i.t('jobs.addSchedule'))),html.indexOf(i.t('jobs.addSchedule')));
 assert.ok(add(only.html,only.i).includes('disabled'));
 assert.ok(!add(mixed.html,mixed.i).includes('disabled'));
});
test('scheduled SUCCESS and last job details render through the real component',()=>{
 const row={id:'j',provider_type:'X_API',trigger_type:'SCHEDULED',status:'SUCCESS',record_count:1,error_count:0,created_at:'2026-10-05T00:00:00Z',started_at:'2026-10-05T00:00:01Z',duration_seconds:1};
 const {html,i}=renderLive('Jobs',[row],[xp]);assert.ok(html.includes(i.displayLabel('SCHEDULED')));assert.ok(html.includes(i.displayLabel('SUCCESS')));
 const result=renderLive('Schedules',[{id:'s',provider_type:'X_API',provider_connection_id:'x',schedule_mode:'INTERVAL',interval_seconds:60,enabled:false,next_run_at:null,last_run_at:'2026-10-05T00:00:00Z',last_job:{id:'j',status:'SUCCESS'}}],[xp]);
 assert.ok(result.html.includes(result.i.displayLabel('SUCCESS')));assert.ok(result.html.includes(result.i.t('common.inactive')));
});
test('an existing schedule remains disableable after capability or live gate loss',async()=>{
 const {html,i}=renderLive('Schedules',[{id:'s',provider_type:'INSTAGRAM_API',provider_connection_id:'ig',schedule_mode:'INTERVAL',interval_seconds:60,enabled:true,next_run_at:null,last_run_at:null,last_job:null}],[ig],false);
 const pos=html.indexOf(i.t('jobs.disable'));assert.ok(pos>=0);assert.ok(!html.slice(html.lastIndexOf('<button',pos),pos).includes('disabled'));
 const calls=[];const {operations}=load('src/lib/job-operations.ts',{'./api':{apiFetch:(...args)=>{calls.push(args);return Promise.resolve({enabled:false,next_run_at:null});}}});
 const result=await operations.action('p','s','disable');assert.equal(calls[0][0],'/projects/p/schedules/s/disable');assert.equal(result.enabled,false);assert.equal(result.next_run_at,null);
});
