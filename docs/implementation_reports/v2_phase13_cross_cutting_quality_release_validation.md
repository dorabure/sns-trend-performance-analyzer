# Version 2.0 Phase13 Cross-cutting Quality / Release Validation

検証日: 2026-10-06 JST。指示書Phase13を正式範囲とする。

## 1. Executive Summary

Phase13 Complete。Blocker 0、Phase14 GO。Production変更0、新規回帰test 1。全件 1631 passed / 375.85秒、2回目 1631 passed / 323.42秒。Frontend84 passed、typecheck/build成功。実X/Instagram/OpenAI呼出は0/0/0。Review ZIPまでで停止する。

## 2. Phase12 Baseline

Phase12 ZIP SHA256 `0a6298fc496d04aacdc8432ebb52bccf1d4cb977484a766f342b2105e4dc6c91`を再検証。開始時の既存472 Source filesはすべてbyte一致。Phase12全件1630、347.13/330.24秒、Frontend84、47 paths、0005を引き継いだ。

## 3. Data Safety Before/After

アプリの起動/再作成・コード変更前にNormal/Private各19 tableの全row件数とstable SHA256をホストのbefore JSONへ保存。通常DBは停止状態だったため既存VolumeをDB serviceのみで再接続して捕捉した。Backend/Frontend開始後、全件・Browser・fixture撤去後のafterを比較し、両環境とも19 table一致、想定外変更0。alembic、provider status/capability、sync states、AI件数、Project mode、enabled schedules、active jobs、Private暗号化byte/hash/permissionsも比較した。DB service再接続前からホストに保持されていたPhase12 post-recreation baselineとも19 table一致（normal_retained_baseline.json）。Phase12の失われたpre-recreation区間を遡って証明したとは主張しない。

## 4. Repository Integrity

`evidence/v2_phase13_repository_integrity.json`。既存Source一致、Migration5本のSHAとbyte不変、既存test/demo/過去reports/frontend不変。追加はTest/Validation/Docsのみ。既存未Commit作業を保持。

## 5. Migration

Full内のfresh head、旧V1/V2 rows保持、0004→0005 downgrade/re-upgrade、Job/Scheduler roundtripが通過。破壊操作は検証済み`sns_phase2_test_<32hex>`専用。0006なし。

## 6. Project / Data Mode

`tests/v2_foundation/test_api.py`でDEMO default、DEMO/LIVE creation、data_mode immutable（同値も拒否）、Live CSV/手動Account拒否。FrontendはProject group切替。

## 7. Demo / Live Isolation

BackendのProject scope、History跨ぎ404、LIVE import/provenance境界とFrontend modeごとの選択をFullで回帰。Public Liveが空でもCanonical Demoへ代替しないことを実Chromeで確認。

## 8. No Fallback Matrix

Live Disabled / Not Configured / Unsupported / Provider Error / No DataをFrontend84 testsとBackend gate/failure/zero-post testsで検証。Mock failureの後にもDemo dataを返さない。Live failureからDemoへのfallbackはなし。

## 9. Provider Generic

ProviderRegistry、Provider type + stored/current Capability + connection stateで判定。Instagram routerも独立して回帰。`if LIVE: use X`へ改変なし。Source Type OWN/MARKET/COMPETITORとData Origin DEMO_CSV/X_API/INSTAGRAM_APIを維持。

## 10. Capability Matrix

X ACCOUNT_PROFILE/OWN_POSTS/OWN_METRICS true。Instagramはprofile true、posts/metrics false。DB true/adapter false、DB false/adapter trueは拒否、両trueのみ受付。既存parametrized intersection tests全通過。

## 11. X Regression

Mock OAuth、validate、manual/scheduled受付、refresh/rotation、normalizer、import、sync state、analyticsを通過。X正式claimはComplete / previously real-verified。Phase6/9の実E2Eを保持し、今回は実Xを呼ばない。

## 12. Instagram Deferred

OAuth/Profile foundation only。直接sync 409 PROVIDER_CAPABILITY_UNAVAILABLE、Schedule create/enable/patch/run-now拒否、tick新Job0、disable/delete許可をFullで回帰。UIはDeferred・posts/metrics unsupported・sync disabled。Schedule createの対象選択はXだけ。実Instagram0、完成扱いなし。

## 13. OAuth Security

X/Instagram state必須、TTL、single-use/replay拒否、redirect固定、callback query redaction、response/logへのtoken非露出をMockテスト。

## 14. SecretStore

暗号化at rest、directory0700/cipher0600/plaintext0。atomic save、並列replace、鍵不正/tamper fail closed、refresh failure時に旧credential保持。実Secret値は内部のみで比較。

## 15. Job Durability

At-least-once。PENDING/RUNNING duplicate、Partial Unique DB guard、同時作成、terminal redelivery no-opを回帰。追加testは受付済みX job後にstored Capabilityを縮小し、manual/run-now/enable/tickが新Jobを作らず既存pipeline/step/historyを保持し、disable/delete cleanup可能なことを統合検証。

## 16. Redis Reconciliation / Stale Recovery

Mock broker失敗後に同一Job UUIDをredispatch、新Job0。heartbeat/stale threshold/locked row/正常RUNNINGを誤回復しない既存testsを維持。Private Redis outageを意図的に起こさない。

## 17. Scheduler

PostgreSQL source of truth、enabled/due/batch/FOR UPDATE SKIP LOCKED、並列tick/manual race、固定Beat entry exactly1（30秒）を確認。ユーザーごとのBeat entry0。終了時Normal/Private enabled0、active0。

## 18. Checkpoint

Fetch→Normalize→Business Import Commit→Sync State update。import失敗でcursor/last_remote_idを進めず、checkpoint保存失敗の再配送もbusiness idempotent。0 new postsでもlast_remote_id保持。

## 19. Idempotency / Import

同snapshot redeliveryにSNSPost/Metric ingest_key重複なし。CSVは1 file transaction、重大error rollback、row validation partial error。PROCESSING startup recoveryは実関数・lifespan failureも既存Quality testsで回帰。

## 20. Analytics Cross-screen

Overview=My Account KPI、Opportunity=Gap、TrendとCompetitor contractをFullとCanonical Chromeで確認。180 OWN、Reach93392、Engagement6928、COMP540、Gap12、最高Opportunity88.083。

## 21. Latest Metrics / Cohorts / Pagination

LATERAL latest recorded_at、latest NULLを古いnon-nullへbackfillしない。Reach→Impressions→Views、NULL/0、混合分母平均拒否、複数OWN followers非合算。posted_at page/total/asc/desc/NULL last/UUID tieとUnicode keyword/hashtag経路を既存13 optimized reads testsで回帰。

## 22. Performance Regression

Targeted4 passed /4.98秒。Quality Overview1500 posts/100 terms、My Account1000、AI2000、追加Job境界。callは0.90/1.06/0.78/0.39秒。ANALYTICS_ERROR/timeout0。Phase12 benchmarkを再生成・再改修せず、fixture/timeout/assertionを縮小しない。

## 23. AI Generate

Key未設定startup正常、Latest/History正常、Canonical Regenerate disabled、POST503 AI_KEY_NOT_CONFIGURED。Mock auth/rate/timeout/connection/5xx/refusal/incomplete/schema/evidence failureで既存Snapshot保持。Read-only Repeatable Read→connection close→external→短いwrite transaction。input/evidence bounded、raw大量本文/secretをpromptへ送らない。

## 24. AI History / Compare

Append-only、cursor ordering/UUID、Project/platform/period、cross-project404、Legacy読み込み、read digest不変、compare保存なし、read external call0。Chrome fixtureで12→14 Snapshot（Fake2成功1失敗）、Latest=History先頭、Load More、Enter/Space選択、Previousなし、History/Compare failure isolationとRetry、Empty、EN比較を確認。

## 25. Frontend Shared Context / Stale Response

7画面同じProject Context、LIVE ALL→effective Xを84 testsで回帰。Scope/selected Snapshot変更時の古いresponse無視、Generate refresh、no polling、History errorでLatest保持、Compare errorでHistory保持。

## 26. JA / EN

7画面を両言語で実Chrome巡回、同Canonical Project/UTC期間。Provider/Deferred/History/Compare/Job/Schedule文言とdictionary key parityを検証。Posts/保存AI本文の日本語は翻訳対象外。Normal表示言語を日本語へ復元。

## 27. Accessibility

Semantic buttons、aria-current、role=status/alert、disabled、details/summary、visible focus。ChromeでSnapshot Enter/Space、EN View Evidence summary Enter（open1、focus SUMMARY）。専用スクリーンリーダー音声テストは未実施。

## 28. Responsive

Desktop default、Tablet768x1024、Mobile390x844。AI Compare desktop2列/mobile1列。Provider、Schedule/Jobs、Canonical competitor26 table rowsにdocumentElement horizontal overflowなし。Scrollbarにより実clientWidthは753/375。Mobile empty Schedule/Jobsに実行済み長文Job明細の検証を拡大したとは主張しない。viewport overrideをreset。

## 29. Canonical Demo

Overview/My Account/Trend/Competitor/Gap/AI/Settingsの7画面。2026-07-07〜10-04 ALL、180/93392、Trend4rows/Term chart、Competitor5系列/6themes/10posts、Gap12、AI fixture1/previous noneを確認。保存/取込/再集計なし。DB全table digest不変がDemo accounts/topics/trends/AI保持も含む。

## 30. Browser Smoke / Evidence

`v2_phase13_browser_checks.json`、7 PNGを実Chrome captureから画素編集なしでPNG化し目視確認。Overviewのみ通常Canonical。AI/Provider画像は全て使い捨て架空fixtureで、実Private account/投稿/token画像は保存しない。PrivateはLive表示、X connected、IG Deferred/sync disabled、無効Scheduleを読取確認。captured console.warn/errorはCanonical/Private/fixture全て0。

## 31. Public / Private

Public LIVE_MODE_ENABLED=falseで秘密情報不要のDemo、空Liveにfallbackなし。OAuth開始/実同期はdisabled gateのFull tests。Private LIVE_MODE_ENABLED=trueはstatus読取のみ。Validate/Connect/Sync/Save実行なし。

## 32. OpenAPI / HTTP Error Schema

47 paths、0005_v2_provider_core。共通error.code/message/details、400/404/409/422/500/503とCapability409を維持。新endpoint0、raw SQL/stack/SDK text/secret pathを返さない。

## 33. Backend Full Test

Run A: 1631 passed /0 failed/0 skipped /375.85秒。Run B: 1631 passed /0 failed/0 skipped /323.42秒。両exit0、同じSource/120000ms test PGOPTIONS、build/npm/benchmarkを同時実行しない。新test初稿は1pass1fail（5.97秒、fixture unique collision）、修正途中は1pass1fail（2.83秒、意図的provider type変更とderived response比較）だった。type変更を除いて本来のCapability喪失に絞り、最終Targeted/Full両回で通過。Production bugではない。初稿logを保持。

## 34. Frontend Full Test / Typecheck / Build

84 passed /0 failed/0 skipped/0 cancelled、6932.18977ms。Docker Node22、network noneでnpm test→typecheck→build exit0。Next16.3.8、19 routes。Frontend Source byteはPhase12不変。

## 35. Docker / Health

Private6 services稼働、backend/db/redis healthy、Backend/Frontend HTTP200（normal/private）、worker pong、Beat固定tick1。Volume保持、down -vなし。仮サーバー2 containersをgraceful stop/rmし、使い捨てDB0を確認。Normal検証containersも最後に停止・撤去し、元のPrivate6だけへ戻す。

## 36. Secret Scan

`v2_phase13_secret_scan.json`、normal_secret_scan、private_archive_check、security_sourceを参照。実Secret5値でZIP/Source/Tests/Docs、Private19tables、Normal19tables（生row未保存）、logs3、Redis、Frontend staticを内部比較しmatches0。directory0700/cipher0600/plaintext0、cipher ZIP混入0。Bearer/access_token/refresh_token/client_secret/api_key/app_secret/private key語の参照をtest fixture/reference/docsに分類。暗号鍵/高entropy token pattern scanも0。dangerouslySetInnerHTML0。

## 37. External Call Count

実X0、実Instagram0、実OpenAI0。Full autouse httpx HTTPTransport/AsyncHTTPTransport fail-fast、fixtureも同guard。Fake OpenAIはbrowser2成功1失敗とtests内のみ。Privateには実外部呼出を伴う操作を行わない。

## 38. README / Docs

README JA/ENをPhase13 Quality validation完了・Phase14 Portfolio Finish次へ更新。X previously real-verified、Instagram Deferred、local warm/no universal SLAを維持。過去Phase Report/Evidence不変。Current README/portfolio docsのstale textをscanし、未実装と完成の矛盾を追加していない。

## 39. Why Production Change Was Required

Production変更不要。Blocker再現0。Backend app/frontend/Migration/dependencies/DB schema/timeout/Provider/OAuth/job algorithmsを変更していない。

## 40. Known Limitations

Full <=300秒はstretch未達で非Blocker。OWN import retained-match per-post SELECT、multi-user authなし、cloud deployなし、production SLA/24h/observability保証なし、IG Media/Metrics Deferred、実OpenAI品質/実X可用性の再検証なし。Phase12 normal pre-recreation hashの歴史的制限は残す。Private post>=8charsの実値scan対象0で、投稿本文網羅scan済みとは主張しない。

## 41. Phase14 GO / NO-GO

GO。Before/After両DB/cipher不変、Migration47path0005、全境界・Capability・Job/Scheduler・AI・大規模performance・Full2回600秒以内・Frontend/build・JA/EN/Responsive/Canonical/Public・Secret scanの各gate通過、Blocker0。Phase14は自動実装しない。

## 42. Archive / Manifest / Stop

Review ZIPはCurrent working tree、tests/docs/manifest/instruction refsを含む。CRC/duplicates/forbidden/runtime/secret/migration/source-byteをseal検証。ZIP自身を含むmanifestへfinal digestを埋め込む自己参照を避け、最終SHAは外部companion `SNS_Analyzer_V2_Phase13.sha256`で提供する。最終ZIP hashを持つ解決済みManifest `SNS_Analyzer_V2_Phase13.release_validation.json`もZIP外へ保存し、Source内Manifestのdigestと結び付ける。Git Commit/Tag/Push/GitHub公開/Release/Deployを実行しない。

## Release Matrix

| Feature | Status | Evidence | Release Claim | Known Limitation |
|---|---|---|---|---|
| Demo CSV | Complete | backend/tests/imports; tests/jobs/test_csv_regression.py | Four synchronous CSV datasets; one file transaction | OWN retained-match per-post SELECT remains |
| X OAuth | Complete / previously real-verified | backend/tests/x_api/test_oauth.py; Phase6/9 reports | PKCE/state TTL/single use/replay/redirect/redaction | Real X availability not revalidated in Phase13 |
| X Manual Sync | Complete / previously real-verified | backend/tests/x_api/test_pipeline.py | Capable X acceptance, worker/import/checkpoint | Private verification; not public multi-user service |
| X Scheduled Sync | Complete / previously real-verified | backend/tests/x_api/test_scheduled_integration.py | Scheduler pipeline for capable X | No 24/7 operation claim |
| X Refresh | Complete / previously real-verified | backend/tests/x_api/test_oauth.py | Atomic credential rotation and logical locking | Real refresh not called in Phase13 |
| Instagram OAuth/Profile foundation | Deferred | backend/tests/instagram_api | OAuth/Profile foundation only | No real Instagram call; no Media/Insights implementation |
| Instagram Posts/Metrics | Deferred | tests/job_operations/test_capability_readiness.py; browser_checks.json | Unavailable; sync/schedule admission fail closed | OWN_POSTS=false; OWN_METRICS=false |
| Demo / Live | Complete | tests/v2_foundation; frontend/tests/project-context.test.cjs; browser_checks.json | Immutable creation mode, isolated shared context, no fallback | No multi-user authentication |
| Background Job | Complete | tests/jobs; tests/provider_core/test_live_pipeline.py | At-least-once, DB duplicate guard, checkpoints/idempotency | Not exactly-once execution |
| Scheduler | Complete for capable X | tests/job_operations; private_archive_check.json | PostgreSQL source of truth; one fixed 30s Beat tick | No per-user Beat entries |
| AI Generate | Complete | tests/insights/test_api.py; test_adapter.py; fake_browser_api.json | Append-only bounded evidence, connection closed before external wait | Real OpenAI quality not revalidated; fake browser generation |
| AI History | Complete | tests/insights/test_history.py; browser_checks.json | Project/platform/period cursor reads and Legacy support | No polling or own project context |
| AI Compare UI | Complete | frontend/tests/insight-history.test.cjs; browser_checks.json; ai_history_compare.png | Current versus previous, read-only, isolated failure | No arbitrary pair comparison or semantic diff |
| Performance | Complete local controlled validation | full_backend.txt; full_backend_b.txt; large_targeted.txt; Phase12 report | Large fixtures pass, full runs <=600s | Local measurements; no production SLA; <=300s stretch not met |
| JA / EN | Complete | frontend/tests/i18n.test.cjs; browser_checks.json | Seven screens, Provider/Deferred and History/Compare labels | Raw saved SNS/AI content is not translated |
| Canonical Demo | Complete | tests/demo; http_checks.json; browser_checks.json; data_baseline_compare.json | Seven screens, 180 OWN posts / reach 93392 preserved | Fictional fixed demo; not real AI output |

各Evidence pathは本Reportの`evidence/v2_phase13_` prefix、test pathはbackend/testsまたはfrontend/testsを参照。
