# Version 2 Phase 9 — Scheduled Live Sync Integration

検証日: 2026-10-05 JST。X-First Interim / Instagram Deferred。

## 1. Executive Summary

Phase 9: **Complete**。Phase 10: **GO**。Blocking gap: **0**。

BackendのCapability受付GuardとFrontendの同じ判定を追加。既存Private X Projectで、PostgreSQL Schedule → fixed Beat → durable Job → Redis → Worker → Credential Manager Router → 自然な期限到来によるRefresh → production X Provider → Live Import → checkpoint → SUCCESSを1 Job実証した。手動同期・OAuth start・Instagram実通信は0。検証用Scheduleは無効で保持。

Backend全件の最終結果は**1577 passed / 0 failed / 0 skipped、344.19秒**。Frontendは**54 passed / 0 failed / 0 skipped / 0 canceled**。Typecheck / Build成功。通常DBは19テーブルすべて件数・全行digestが前後一致。Migration / Demo bytes不変。既存未Commit変更を保持し、Commit / Push / Tag / Releaseは実施しない。

## 2. X-First / Instagram Deferred Decision

実Live ProviderはX_APIのみ。InstagramはACCOUNT_PROFILE基盤のみで、OWN_POSTS / OWN_METRICS false、DEFERREDのまま。Instagram Media / Insights / Scheduled Sync、AI History / Compare、新Provider / Job Type / 認証 / Cloud / 大規模Performance改善は追加しない。後続AI HistoryはProvider個別APIではなくnormalized DB / analyticsを基準にする。

## 3. Phase 8 Review Carryover

README JA / EN冒頭の「実SNS API未実装」を修正。V1 CSV / Demo、V2 Interim X OAuth / Refresh / Manual / Scheduled Live、Instagram Deferredを明示。Phase 2 / 3説明の古い現在形とMigration headも現在状態へ更新。

## 4. Changed Files

Phase 8 Review ZIPとの比較で次の19ファイルが追加・変更される。Phase 1〜8 Reportは変更しない。

- Backend: `app/providers/readiness.py`、`app/services/job_operations_service.py`。
- Backend tests: `tests/job_operations/conftest.py`、`runtime_probe.py`、`test_capability_readiness.py`、`tests/provider_core/test_api_migration.py`、`tests/x_api/test_pipeline.py`、`test_scheduled_integration.py`。
- Frontend: `src/lib/project-context.ts`、`src/i18n/index.ts` / `ja.ts` / `en.ts`、`tests/job-operations.test.cjs` / `project-context.test.cjs`。
- Docs: README JA / EN、`docs/portfolio/x_api_private_setup.md`、本Report、`evidence/v2_phase9_scheduled_x.png`。

既存のconnected test fixtureを検証済みCapability付きにし、将来ProviderのFake Adapter試験はregistryを明示注入する。ProductionをFake Providerへ切り替えない。

## 5. Capability-aware Backend Guard

`sync_capabilities_available()`はACCOUNT_PROFILE / OWN_POSTS / OWN_METRICSを現在Adapterと保存済みCapabilityの**双方**に要求する。現在Adapterのfalseは古いDBのtrueに優先する。空・重複・未知・不正型のCapability、未知Adapterは受付不可。

Manual Sync、enabled Schedule create / enable / patch、run-now、tickで共通`ready()`を利用。Adapter自身が同期を実装していない場合はdisabled creationも409 PROVIDER_CAPABILITY_UNAVAILABLE。未接続Xのdisabled creationは維持し、enableはPROVIDER_NOT_READY。OAuth startを禁止する処理は追加しない。

Disable / DeleteにはCapability / Live global判定を追加しない。既存enabled ScheduleがCapabilityを失ったTickはJob 0、enabled維持、next_run_atを旧dueから次境界へ進め、同じdueを繰り返さない。Current loss / stored loss / stale InstagramのAPI・service回帰試験で確認。

## 6. Schedule Source of Truth

PostgreSQL JobScheduleを継続。実UIでX / INTERVAL 60秒のdisabled Scheduleを作成し、Backend / Worker / Beat / Frontend再作成後も同じrowを保持。DB・Redis・Runtime Secret Volumeは削除しない。再認可なしで同期成功。

## 7. Beat

Beat entryは1つ、`sns.scheduler_tick`、30秒fixed tick。ユーザーScheduleをBeat registryへ動的登録しない。再作成後のBeat → WorkerのSCHEDULER_TICKとWorker pongを確認。

## 8. Tick

enabled / next_run_at <= now、FOR UPDATE SKIP LOCKED、batch 50を維持。二重Tick / Manualとの競合 / provider disabled / Project inactive / global Live falseの既存回帰は最終全件で成功。Global falseはdueを消費しない。

実Jobのscheduled_forは11:27:06 UTC、受付last_run_atは11:27:14 UTCで、tick時刻とは異なる旧due境界を保存。旧dueからnowを超える次境界への進行はMock統合・既存Interval / DAILY / DST試験で検証。実受付後、無効化前のnext_run_at値は即時安全停止を優先したため直接採録していない。無効化後のNULLはDB / UIで直接確認。

## 9. Redis Dispatch

DB commit後にUUIDだけを既存dispatcherへ送信。実Jobのenqueued_at、Worker実行、terminal resultを確認。TokenをSchedule / Job / Broker payloadへ追加しない。JOB_REDISPATCH_SECONDS=300を維持。

## 10. Worker

既存`sns.execute_job` / JobRunnerを継続。X専用Taskは追加しない。Worker再作成後も1 node online / pong。実Jobの開始・終了と4 StepsをDB / API / UIで確認。

## 11. Credential Manager

Production WorkerはCredentialManagerRouter → XCredentialManager → Resolver / Encrypted Runtime SecretStoreを使用。再作成前後に既存Credentialの存在を値非表示で確認し、Scheduled Jobの実成功でWorkerからの利用を実証。Credentialを手動上書きせず、OAuth start 0。

## 12. Scheduled Refresh Contract

期限・時計・skewを改ざんしない。自然に期限が到来していたため実Scheduled Worker内のRefreshが発生。Job成功、新expiry、Runtime暗号文hash変更、Credential再読込を確認。**Scheduled refresh: PASS**。検証専用のRefreshを別途強制しない。

Mock Scheduled Worker試験ではRefresh due / not due / failureを確認。失敗時はJob FAILED、Provider ERROR、旧Credential暗号文保持、checkpoint不変。Private Refresh Gateを維持。

## 13. X Provider

既存Production XApiProvider / HTTPClient / Normalizer / since_id契約を変更しない。実新規投稿0件でも正常。既存POSTS last_remote_idを保持し、Account snapshotを取得。新規投稿・Backfill・大量Paginationを強制しない。

## 14. Job Pipeline

実Job ID: `a50a8b7a-8da5-4cac-96e0-201834893007`。

| 項目 | 結果 |
| --- | --- |
| Job type / trigger | PROVIDER_SYNC / SCHEDULED |
| job_schedule_id / scheduled_for | 非NULL、該当Schedule / due境界 |
| Job final / record_count / error_count | SUCCESS / 1 / 0 |
| PROVIDER_SYNC | SUCCESS、attempt 1 |
| NORMALIZE_IMPORT | SUCCESS、attempt 1、record_count 1 |
| TREND_REBUILD | SKIPPED |
| AI_INSIGHT_GENERATE | SKIPPED |

予定11:27:06、受付・送信11:27:14、開始11:27:18、終了11:27:21（すべて2026-10-05 UTC）。UI durationは2.5秒。RUNNINGの瞬間をブラウザーで観測したという意味ではなく、DB / APIの開始・終了記録が根拠。

## 15. Provider Sync State

ACCOUNT / POSTS / METRICSの3行がSUCCESS。last_synced_at / last_success_atはjob.scheduled_forに一致。POSTS last_record_count=0、前回last_remote_id保持、checkpoint後退なし。Provider CONNECTED、last_success_at / last_record_count更新。OWN_POSTS / ACCOUNT_DAILY History各1件はX_API / Provider FK / Job FK / SUCCESS。AccountMetricの今回Job参照1件、PostMetric新規0件。

Business Import Commit → checkpoint順序は実コードを維持し、Scheduled LiveImport failureのMockでcursor / last_remote_id不変を検証。実通信中に故意のBusiness failureは注入しない。

## 16. Idempotency

At-least-once前提。Scheduled observationにはscheduled_forを使用。Mock production Provider / Workerの同UUID再配送はNO_OP、HTTP追加0、Business / History / Steps件数不変。既存UTC日AccountMetric UPSERT、Metric ingest_key、active uniqueを維持。Exactly-onceを保証しない。

## 17. Stale Recovery

Scheduled RUNNINGのheartbeatを古くしたMockではWORKER_HEARTBEAT_TIMEOUT、FAILED、再配送NO_OP、HTTP0。JOB_STALE_SECONDSの既定900と300以上3600未満の範囲を変更しない。実X Jobを故意に停止しない。

## 18. Redis Reconciliation

Scheduled JobのDB受付後にpublisherを失敗させるisolated Mockで、enqueued_atなしのPENDINGを保持し、broker復旧後に**同Job ID**を送信、Worker SUCCESS、再配送NO_OPを確認。実X Redis failure injectionは0。正常環境でRedisを停止する試験は実施しない。

## 19. Frontend Schedule UI

既存JobOperations画面を使用。canSyncは現在と保存済みの3必須Capabilityを確認。409 Capability errorはJA / ENの専用安全メッセージへ対応。候補Xのみ、Instagram手動同期無効、60秒disabled作成、enable、成功last jobから詳細表示、last / scheduled / sent / started / finished / records / 4 Stepsを実ブラウザーで確認。受付後の安全停止は監視プロセスから共通serviceを利用し、UIの無効状態・nextなしを確認。UI DisableのCapability喪失後の可用性は実Component render試験で確認。

画面証跡: [無効Scheduleと成功last job](evidence/v2_phase9_scheduled_x.png)。投稿本文・Token・remote account ID・Credential refを含めない。

## 20. Instagram Deferred Enforcement

Production Private APIに直接Manual Sync、disabled / enabled Schedule creationを送信し、すべて409 PROVIDER_CAPABILITY_UNAVAILABLE、Job増加0を確認。Mock API試験でenabled patch / enable / run-now / stale stored true / due tick / Disable / Deleteを検証。実Instagram HTTP0。Instagram Phase 7をCompleteとは扱わない。

## 21. Private X Scheduled Smoke

```text
Private X Scheduled Sync: PASS
Schedule: INTERVAL 60 sec / 1 row
Scheduled Jobs intentionally executed: 1
Manual Sync calls: 0
OAuth start: 0
Instagram real calls: 0
Trigger: SCHEDULED
Job: SUCCESS
PROVIDER_SYNC: SUCCESS
NORMALIZE_IMPORT: SUCCESS
TREND_REBUILD: SKIPPED
AI_INSIGHT_GENERATE: SKIPPED
New X posts: 0
Scheduled refresh: PASS (naturally due)
Schedule disabled after verification: YES
Credential persistence after recreation: PASS
```

Settingsの既存Private Projectを使用。Schedule作成時は無効。他の有効Schedule / active Jobは0。最初のJob受付を200ms間隔で検出し、直ちにScheduleを無効化。監視はtimeout / exceptionでもfinallyで無効化する方式。X本文 / Full account ID / Token / Credential ref / Raw response / DB dumpをReport・ZIPへ書かない。

## 22. Schedule Cleanup

Scheduleはdisabledで保持、next_run_at=NULL、last_job_run_id一致、last_run_at更新。有効test Schedule 0。無効化から複数の30秒Tick・60秒周期を経た再確認でもJob増加は1件のみ。

Private環境のLIVE_MODE_ENABLED / X_LIVE_SMOKE_ENABLED / X_LIVE_REFRESH_SMOKE_ENABLED / X_OAUTH_BOOTSTRAP_ENABLEDはbefore=true / after=true。元の設定を保持し、`.env` / `.env.xlive`を書き換えない。Public `.env.example`は4フラグfalse。Secret Volume・Private DBを保持。途中の重複テストプロセス停止で残った使い捨てDB3件は、正規prefix・fixture名・作成時刻・無接続・test credentialを検証して限定cleanup。最終残存test DB 0。

## 23. Existing Analytics

実Scheduled SUCCESS後、同Project / X / 2026-10-01〜2026-10-05のGET `/accounts/own/posts` / `/accounts/own/analytics`はHTTP200。既存投稿1件はDB件数と一致、kpis / engagement_trend / media_type_performance / timezone Contractを保持、timezone UTC。投稿0件の新規取得によって既存データを失わない。Analytics読取でX APIを追加呼出ししない。

## 24. Security / Secret

最終納品Secret検査: **PASS**。現在の既知Secret 5値をPrivate Runtime内でのみ比較し、値は出力せず件数・boolのみ記録。Report / Source / ZIP 426 entries、compiled static 24 files、Backend / Worker / Beat logs 3 files、Private DB 19 tables、Redis 5 keysの実Secret一致は全て0。Logsのsensitive patternも0。Runtime encrypted file 0600 / directory 0700、平文Runtime file 0を確認。OAuth logging filter・result_summary allowlistを維持。過去に存在した全Secretを保証する検査ではない。

この検査は現行 / Bootstrapの既知Secretとパターンの検出であり、破棄済Credential全履歴やDeveloper Console、実費用を独立監査したものではない。

## 25. Backend Tests

最終**1577 passed / 0 failed / 0 skipped、344.19秒**。Phase 8の1557を維持し20件追加。新規skip / xfailなし。External HTTP禁止fixture、PostgreSQLは`sns_phase2_test_<32-hex>`だけを使う。

```text
docker exec -e FRONTEND_ORIGIN=http://localhost:3000
  -e LIVE_MODE_ENABLED=false -e X_LIVE_SMOKE_ENABLED=false
  -e X_LIVE_REFRESH_SMOKE_ENABLED=false -e X_OAUTH_BOOTSTRAP_ENABLED=false
  -e INSTAGRAM_LIVE_SMOKE_ENABLED=false -e INSTAGRAM_LIVE_REFRESH_SMOKE_ENABLED=false
  -e INSTAGRAM_OAUTH_BOOTSTRAP_ENABLED=false
  -e 'PGOPTIONS=-c statement_timeout=120000'
  sns-trend-performance-analyzer-backend-1 pytest -q -p no:cacheprovider
```

検証履歴を最終PASSと区別する。最初の対象suiteは267 passed / 3 failed、55.66秒。新規TestのPostMetric FK名をjob_run_idから既存ingest_job_run_idへ修正し、新規Scheduled suite 7 passed、16.76秒。

Private設定を継承した全件1回目は1567 passed / 10 failed、1254.23秒。Instagram Refresh skewが空文字の設定不一致8件と、Insights / Overviewの2000投稿SQL timeout2件。次の通常設定全件は1568 passed / 9 failed、420.46秒。全9件は検証ポート13000のFRONTEND_ORIGINとテスト期待3000の不一致。最終はテストプロセスだけ3000へ明示し上記全件PASS。対象外AnalyticsのSource変更で隠さない。別コンテナのInsights 42件もPASS。途中の重複検証プロセスは停止・整理した。

SQL停止原因の修正は行っていない。ビルド終了後の全件で大規模試験も成功したが、以前のSQL遅延の原因解消を証明したものではない。再発時はtest DB統計・実行計画・環境負荷を分けて調査する。

## 26. Frontend Tests

最終**54 passed / 0 failed / 0 skipped / 0 canceled、4920.1712ms**。Phase 8の49を維持し5件追加。Instagram候補除外、current + stored必須Capability、error mapping、Scheduled SUCCESS / last job render、Capability / Live喪失後もDisable操作可能、public endpointを確認。Component renderとutility / API wrapper試験であり、実ブラウザーの全click操作を自動試験したという意味ではない。

## 27. Typecheck / Build

`npm run typecheck`成功（Node 22 Docker、外部networkなし、作業ツリーFrontendをmount）。Hostの同じtsc --noEmitも成功。`npm run build`成功（Private / Canonical用Docker build）、Next.js 16.3.8、19 routes。SecretをFrontendへ渡さない。

## 28. Docker / Health

build成功。Private db / redis / backend / worker / beat / frontendの6サービス稼働。Backend HTTP200 / DB connected、Frontend HTTP200、Worker pong / 1 node online、Beat fixed Tick確認。OpenAPI 44 paths。Canonical検証は通常DBを15432 / Backend18000 / Frontend13000で使用し、検証後は追加した3コンテナを削除、Volume保持。Private6サービスを保持する。

## 29. Migration

head=`0005_v2_provider_core`、0006なし、Schema変更なし。Phase 8 ZIPとの5ファイルbyte一致とPhase 6 Verified prefix一致。実測SHA-256:

| Migration | SHA-256 |
| --- | --- |
| 0001 | `508943d4824451b8faa66df5105198d44002c5143a4520199d0891cb1af8570a` |
| 0002 | `d8666dc8525a59dbb9c1219bb01613afbc92b8de49f732ea21cf48ff91d7a450` |
| 0003 | `d64604a6a62f4c107e251695fe4fe68bbd99a94290f8a310494a6ff5e2d0dece` |
| 0004 | `bbfd2da2c836cc37f47089e1169e885c5a79ac3f56871a4b0beb18fe0bbbc628` |
| 0005 | `bb213e3acb5f10c047b335135fd0ff941b18a0b7341060c3375831329e02db38` |

## 30. Canonical Demo

Overview / My Account / Trend Explorer / Competitor / Gap Analysis / AI Insights / Settingsの7画面を実ブラウザーで読取確認。固定UTC期間2026-07-07〜2026-10-04。Overview / My Account: 180投稿、Reach93,392、Engagement6,928、Impressions136,256。Trend: 14.04 / 4.16、Competitor: 5アカウント、Gap: 12行 / NULL1 / 0値2 / 4分類、AI:保存済demo-fixture、Settings:既存Import履歴を確認。新規AI生成・CSV import・Project変更なし。

Demo dataの6ファイルbytesと通常DB19テーブルのcount / full-row hashが前後一致。Demo / Live選択とreload persistence、Live no fallback / provider-managed CSV・Account、Instagram Deferredは既存Frontend回帰を含めて維持。PrivateのSchedule成功画面は撮影済み。全7画面のスクリーンショットを保存したという意味ではなく、DOM・表示値を確認した。

## 31. External Call Count

意図的に実行した実X Scheduled Job=1、Manual Sync=0、Validate=0、OAuth start=0、Instagram実通信=0、実OpenAI=0。自然なRefreshはこの1 Job内で発生。正常経路はMe GET1 / Tweets GET1 / Token POST1を必要とする。正確なHTTP wire request数・GET retry回数・請求金額は未計測で、3をexact request totalとは断言しない。追加X検証を繰り返さない。

## 32. Remaining Gaps

機能Blocker: **0**。非Blocking制約は、実HTTP retry / 費用未計測、即時Disable直前のnext_run_at値未採録、過去の大規模SQL遅延原因未確定。必要な契約はMock / 最終全件で検証済み。enabled schedule can continue producing failed jobsという運用リスクを維持し、自動停止仕様は追加しない。Private検証では既にdisabled。Instagram end-to-endはDEFERREDのまま。

## 33. Phase 10 Go / No-Go / Deliverables

最終判定: **Phase 9 Complete / Phase 10 GO**。納品対象は本Report、現在Source / Migration0001〜0005 / Tests / README / Portfolio Docs / Phase Reports / 指示書参照を含む`../SNS_Analyzer_V2_Phase9.zip`。426 entries（Source 419 + 指示書参照7）、CRC成功、重複entry 0、禁止path / sensitive pattern 0、現在Sourceとのbyte一致を確認。Python 210 filesの構文検査も成功。Migration5 / Demo6 / 過去Reportのbytesを保持。`.git` / 実.env / Tokens / Key / ciphertext / Private DB / Redis runtime / Raw X response / exports / node_modules / venv / caches / celerybeat-scheduleを含めない。

Phase 10の実装は本作業に含めない。
