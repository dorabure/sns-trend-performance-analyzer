const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const data = JSON.parse(fs.readFileSync('tests/fixtures/phase14-gap.json', 'utf8'));
const exportsObject = {};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/gap-scatter.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, { exports: exportsObject });
const { scatterSeries, classificationColors } = exportsObject;

test('canonical API rows produce eleven point payloads and exclude one unknown coordinate', () => {
  const points = Array.from(scatterSeries(data.items)).flatMap(s => Array.from(s.data));
  assert.equal(data.items.length, 12);
  assert.equal(points.length, 11);
  assert.equal(new Set(points.map(p => `${p.topic_id}:${p.platform}`)).size, 11);
  for (const point of points) {
    assert.ok(data.items.includes(point), 'preserve the original tooltip payload without recalculation');
    assert.notEqual(point.own_post_ratio, null);
    assert.notEqual(point.trend_score, null);
  }
  assert.equal(data.items.filter(p => !points.includes(p)).length, 1);
  assert.equal(points.filter(p => p.gap_score === 0).length, 2);
  assert.ok(points.some(p => p.own_post_ratio === 0));
  const withoutRatio = { ...points[0], own_post_ratio: null };
  assert.equal(scatterSeries([withoutRatio]).flatMap(s => s.data).length, 0);
});

test('platform series keep six circles and five diamonds at full size without entrance animation', () => {
  const [x, instagram] = scatterSeries(data.items);
  assert.equal(x.platform, 'X'); assert.equal(x.shape, 'circle'); assert.equal(x.data.length, 6);
  assert.equal(instagram.platform, 'INSTAGRAM'); assert.equal(instagram.shape, 'diamond'); assert.equal(instagram.data.length, 5);
  for (const series of [x, instagram]) {
    assert.equal(series.isAnimationActive, false);
    assert.ok(series.data.every(p => p.platform === series.platform));
  }
});

test('all four existing classification colors and eight tooltip fields are preserved', () => {
  const points = Array.from(scatterSeries(data.items)).flatMap(s => Array.from(s.data));
  assert.deepEqual([...new Set(points.map(p => p.classification))].sort(), ['BALANCED', 'HIGH_COVERAGE', 'LOW_PRIORITY', 'OPPORTUNITY']);
  assert.equal(classificationColors.OPPORTUNITY, '#0f766e'); assert.equal(classificationColors.BALANCED, '#2563eb');
  assert.equal(classificationColors.HIGH_COVERAGE, '#a16207'); assert.equal(classificationColors.LOW_PRIORITY, '#64748b');
  for (const p of points) for (const field of ['topic_name', 'platform', 'trend_score', 'trend_date', 'own_post_ratio', 'competitor_post_ratio', 'gap_score', 'classification']) assert.ok(field in p);
});

test('real Scatter uses series animation policy, API payload, Cell color and existing tooltip', () => {
  // Source contract only. Real SVG geometry is separately checked in the browser, without a Recharts mock.
  const source = fs.readFileSync('src/components/gap-analysis.tsx', 'utf8');
  assert.match(source, /scatterSeries\(data\.items\)/);
  assert.match(source, /<Scatter[^>]*shape=\{shape\}[^>]*data=\{platformPoints\}[^>]*isAnimationActive=\{isAnimationActive\}/);
  assert.match(source, /fill=\{colors\[p\.classification!\]\}/);
  for (const field of ['topic_name', 'platform', 'trend_score', 'trend_date', 'own_post_ratio', 'competitor_post_ratio', 'gap_score', 'classification']) assert.ok(source.includes('p.' + field));
});
