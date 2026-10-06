const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

// Use the installed compiler and Node test runner; no new test framework.
function load(path) {
  const source = ts.transpileModule(fs.readFileSync(path, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(source, { exports, URLSearchParams, FormData, Date,
    require: name => name === '../i18n' ? { errorText: () => 'safe error' } : name === './api' ? { ApiError: class extends Error {} } : require(name) });
  return exports;
}
const filters = load('src/lib/analysis-filters.ts');
const { RequestVersion } = load('src/lib/use-analysis-read.ts');

test('inclusive UTC default period and preset boundaries', () => {
  assert.equal(filters.period(30, '2026-10-03').from, '2026-09-04');
  assert.equal(filters.period(7, '2026-10-03').from, '2026-09-27');
  assert.equal(filters.period(90, '2026-10-03').from, '2026-07-06');
});
test('URL parse, validation, and encoded query preserve actual conditions', () => {
  const c = filters.parseCriteria(new URLSearchParams('platform=INSTAGRAM&from=2026-10-01&to=2026-10-03'));
  assert.equal(filters.criteriaQuery(c), 'platform=INSTAGRAM&from=2026-10-01&to=2026-10-03');
  assert.equal(filters.validPeriod(c), true);
  for (const from of ['2026-10-04', '2026-02-30', '', 'not-a-date'])
    assert.equal(filters.validPeriod({ ...c, from }), false);
  assert.equal(filters.parseCriteria(new URLSearchParams()).platform, 'ALL');
});
for (const platform of ['ALL', 'X', 'INSTAGRAM', 'INVALID']) {
  test(`project correction before first request: ${platform}`, () => {
    const draft = { platform, from: '2026-10-01', to: '2026-10-03', keyword: 'ＣＨＡＴｇｐｔ' };
    const next = filters.normalized({ platforms: ['X'] }, draft);
    assert.equal(next.platform, ['ALL', 'X'].includes(platform) ? platform : 'ALL');
    assert.equal(next.keyword, draft.keyword);
    assert.equal(draft.platform, platform);
  });
}
test('competitor IDs are limited to the active role/project/platform and deduplicated', () => {
  const accounts = [
    { account_id: 'x', platform: 'X', account_role: 'COMPETITOR', is_active: true },
    { account_id: 'ig', platform: 'INSTAGRAM', account_role: 'COMPETITOR', is_active: true },
    { account_id: 'own', platform: 'X', account_role: 'OWN', is_active: true },
    { account_id: 'inactive', platform: 'X', account_role: 'COMPETITOR', is_active: false },
  ];
  const c = { platform: 'INSTAGRAM', from: '2026-10-01', to: '2026-10-03', ids: ['foreign', 'x', 'x', 'ig', 'own', 'inactive'] };
  const next = filters.competitorCriteria({ platforms: ['X'] }, c, accounts);
  assert.equal(next.platform, 'ALL'); assert.equal(next.ids.join(','), 'x');
  assert.equal(filters.competitorCriteria({ platforms: ['X', 'INSTAGRAM'] }, c, accounts).ids.join(','), 'ig');
});
test('request ordering and unmount invalidation reject old successes/errors/finalizers', async () => {
  const gate = new RequestVersion(); let finishOld; let state;
  const old = gate.next();
  const pending = new Promise(resolve => { finishOld = resolve; }).then(value => {
    if (gate.current(old)) state = value;
  });
  const current = gate.next();
  if (gate.current(current)) state = 'new project/period';
  finishOld('old'); await pending;
  assert.equal(state, 'new project/period');
  gate.next(); assert.equal(gate.current(current), false);
});
