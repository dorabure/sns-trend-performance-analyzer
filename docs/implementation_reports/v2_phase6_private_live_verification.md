# Phase 6 Private Live Verification

検証日・投稿準備後の追検証日: 2026-10-05 JST。Verification Only。**Phase 6 Verification: Complete / Phase 7: GO**。

## 1. Summary

Real X Validate、Manual Sync、実Refresh、新CredentialでのMeは成功。初回0投稿の後、ユーザーの「投稿済み」回答を受けて追加Syncを1回だけ実行し、実SNSPost / PostMetric各1件の保存とPOSTS checkpointを確認した。投稿保存・非空Analyticsの未確認項目は解消。追加取得後のBackend Fullは1482 passed / 0 failed / 0 skippedで成功し、Exit Gateを満たした。過去の全件実行時のSQL遅延は原因未特定であり、修正済みとは扱わず下記に履歴と再発リスクを残す。Production Source、Migration、既存Phase 1〜6 Report、通常`.env`は変更していない。

## 2. Environment

開始時branch `master`、HEAD `e2ad3848105687fb1b48c872e48d15d9315b3b97`。既存未Commit変更を保持。稼働中の` sns-x-live `Composeを再利用。通常Composeの未設定状態とPrivate Composeの実効設定を区別した。

Private DBは別PostgreSQL / Redis / SecretStore Volumeの` sns_analyzer_xlive `。既存の認可済みSmoke Projectは保持し、新しいLIVE / X検証Projectで初回1ページを確認。Scheduleは開始・終了とも0件、enabled 0。Backend / WorkerのSource111ファイルは前回ZIPとLF正規化後に一致。

通常環境は既存5432 / 8000 / 3000との競合を避け、Repository外の一時Compose overrideで15432 / 18000 / 13000に起動。Canonical検証後は停止・コンテナを削除し、Volumeは保持。Private環境は保持。

## 3. Developer App

ユーザーが対象AppのCredit残高、現在価格、支出上限／自動チャージ設定、OAuth Scopeを確認済みと回答し、実通信を明示承認した。Consoleの数値や設定画面はCodexによる独立確認をしていない。価格・費用額は推測しない。

Client type: CONFIDENTIAL。Client ID / Client Secret / Runtime Key: configured、読み取り可能。local redirectはHTTP loopback、8000、固定callback path、query / fragmentなしを確認。Console登録との一致はユーザー確認に依存。

## 4. Scope

`tweet.read / users.read / offline.access`はユーザー確認済み。実Me、実Timeline、実Refreshの成功を確認。Write / DM / Search / Competitor / Market / Trends APIは呼び出していない。

## 5. OAuth / Credential

既存の暗号化Runtime Credentialを再利用。access / refresh / expiryの存在を値非表示で確認。通常bootstrap環境変数のToken未設定は、Runtime Credential不在を意味しない。

OAuth start / callback / PKCE / TTL / replayの新しい実認可は今回NOT EXECUTED。既存Credentialが有効だったため再認可しなかった。これらの回帰テストと今回の実通信結果を区別する。

Private Backend / WorkerはLIVE、Smoke、Refresh、Bootstrapの4フラグが既にtrue。Codexはフラグを書き換えていない。通常環境の既定値はfalse。

## 6. Real Validate

PASS。Public Validate API HTTP 200、valid true、CONNECTED、Credential configured、既存認可アカウントに一致。ACCOUNT_PROFILE / OWN_POSTS / OWN_METRICS true、MARKET_POSTS / COMPETITOR_POSTS / TREND_DATA false。

## 7. Real Manual Sync

PASS（空Timelineの正常処理）。新規検証Projectで手動1回、HTTP 202 / PENDINGからWorkerによりSUCCESS。初回max_results 5、1ページ、過去履歴取得なし。Fetched Posts 0、Imported Posts 0、Account Metrics 1、error 0。

ユーザーの「投稿済み」回答後、追加Syncを1回だけ実行。HTTP 202 / PENDING → SUCCESS、Fetched Posts 1、Imported Posts 1、PostMetric 1、今回AccountMetric 1、Job record_count 2、error 0。

前回のPOSTS last_remote_idがNULLだったため、追加Syncも初回Snapshot分岐（max_results 5・1ページ）を使用する。since_idを使う増分経路の実通信はNOT EXECUTED。これ以上のSyncを実行しない。ユーザー自身の投稿を取得したものであり、Codexは投稿操作をしていない。

## 8. Job / Steps

初回・追加ともJob SUCCESS、error_count 0。初回record_count 1、追加record_count 2（投稿1 + アカウント指標1）。追加のPROVIDER_SYNC SUCCESS、NORMALIZE_IMPORT SUCCESS、TREND_REBUILD SKIPPED、AI_INSIGHT_GENERATE SKIPPED。必須Stepはattempt_count 1。Worker開始・終了記録を根拠とし、RUNNING状態をAPI pollingで直接観測した証拠とは扱わない。

## 9. DB Verification

Account保存PASS: 1件、OWN / X / X_API、Provider FKとplatform_account_idが認可Providerに一致。AccountMetric 1件、ingest_keyあり、今回Job FKあり。

追検証のPost / PostMetric保存: **PASS**。Post 1件、OWN / X / X_API、Provider FK一致。PostMetric 1件、ingest_keyあり、追加Job FKに一致、reach / views NULL。AccountMetricは累計2件、追加Job参照1件。

初回Historyを保持し、追加OWN_POSTS Historyは1 / 1 / 0でSUCCESS、追加ACCOUNT_DAILY Historyは1 / 1 / 0でSUCCESS。追加両HistoryはX_API、Provider FKあり、追加Jobに一致。実投稿本文・プロフィール・個別Metricの値はReportへ記載しない。

## 10. Sync State

初回はPOSTS last_remote_id NULLだったが、追加Sync後は**PASS**。ACCOUNT / POSTS / METRICSの3行すべてSUCCESS、cursor NULL、last_success_atあり、last_remote_idあり。POSTS last_record_count 1、last_remote_idは保存済み最新Post IDに一致。ACCOUNT last_record_count 1、METRICS last_record_count 2。完了Jobとcommit済みのPost / Metric / Stateを同じDBで確認。Commit前の瞬間を実通信中に直接観測した証拠はなく、rollback / checkpoint順序の一般的性質は回帰テストを根拠とする。

## 11. Existing Analytics API

初回の0件に続き、追加Sync後の非空結果も**PASS**。Own Posts / My Account AnalyticsはHTTP 200。Own Posts total 1がDBと一致し、Post ID集合と各PostMetric値がDBに一致。Analyticsの投稿KPI、Engagement集計、Followers KPIはDBと一致、reach不明、timezone UTCをboolで確認。既存kpis / engagement_trend / media_type_performance / timezone Contractを維持。

## 12. Real Refresh

PASS。現在のCredentialに対して実Token POSTを1回実行しHTTP 200。期限や時計は偽装しなかった。検証用プロセスが既存ProductionのXTokenClient、token_payload、Provider行ロック・論理参照advisory lock、EncryptedFileSecretStoreを使用して明示的にRefreshした。

自動期限判定によるRefresh発火の実時間待機はNOT EXECUTED。この経路は回帰テストの対象。今回の実証範囲は実Refresh交換、Scope検証、新payloadの暗号化・atomic replace、Resolver再読込。

access_changed true、refresh_in_response true、refresh_rotated true、resolver_new_access true、expiry_advanced true、atomic_encrypted_replace true。Secret値・暗号文は記録しない。

## 13. Refresh-after-Me

PASS。新CredentialをResolverから読み込み、Production XApiProviderによるGET MeがHTTP 200。同じremote accountであることをboolで確認。再認可なし。さらに追検証のWorker Syncも、このRefresh後の暗号化Runtime Credentialを使う既存経路で成功し、Post 1件を保存した。

## 14. Cost / Request Count

今回の初回手動Sync受付1回、Validate受付1回、追検証の追加Sync受付1回、Token POST1回。実Refreshと直後Meは観測用TransportでPOST 200 / GET 200各1回を確認。

Validate + 2回のWorker Sync + Refresh後Meは正常経路でMe 4回、Timeline 2回を必要とする。従って今回のX通信は少なくともGET 6回 + Token POST 1回、返却Post resource累計1。Worker内部のHTTP retry回数を直接観測していないため、合計を正確なwire request countとは断言しない。Job attempt_count 1はHTTP retry 0の証拠ではない。課金明細・実際の請求額は未確認。以前のSmokeの通信・費用を今回に含めない。

## 15. Privacy / Secret Scan

Source396ファイル + Private Backend / Worker / Beatログ3件、DB業務テーブル、Redisの現行データを、現行Credential / Client / Keyの実値と内部比較。5値比較、検出0。Frontend配布static 24ファイルも検出0。値は画面・Report・ZIPへ出力していない。

追加取得後もSource397ファイル（本Report含む） + ログ3件、実Postを含むPrivate DB、Redisを再検査して検出0。Schedule enabled 0を再確認。

暗号文ファイル0600 / ディレクトリ0700、Runtime内の平文ファイル0を確認。Scanは現行Secretを対象とする。過去に破棄されたCredentialの全履歴やDeveloper Console全体の漏洩不存在を保証するものではない。Review ZIPには.env類、Runtime Secret、Private DB、実投稿export、Console screenshot、検証用ログを含めない。最終Report / ZIPの検査結果は下記納品検査欄に記録する。

## 16. Regression

実通信前Backend: 1482 passed / 0 failed / 0 skipped、324.92s。最初のLive設定を継承した試行は1481 passed / 1 failed、269.53s。既定Smoke無効の契約をLive環境で実行した設定不一致であり、テストプロセスだけ4フラグをfalseにして再実行した。外部HTTP遮断fixtureと使い捨てDBを使用。

Frontend事前: 32 passed / 0 failed / 0 skipped / 0 canceled、2662.767317ms。Typecheck / Build成功（Next.js 16.3.8、19 routes）。実通信後Frontend: 32 passed / 0 failed / 0 skipped / 0 canceled、4869.445239ms、Typecheck / Build成功。

実通信後Backendの第1試行: 1481 passed / 1 failed / 0 skipped、1253.68s。Overviewの2000投稿・固定query数テストで使い捨てDBのSELECTが長時間停止し、該当SELECTを限定キャンセルしたためANALYTICS_ERRORとして失敗。該当テスト単独再実行は1 passed、11.77s（テスト接続にstatement_timeout 120000ms）。全件再実行も同じテストがSQL上限で失敗し、**1481 passed / 1 failed / 0 skipped、465.06s**。原因は未確定であり、Source bug / DB query plan / 一時的な実行環境問題のどれかを断定しない。

終了後の全件コマンド: `docker compose -p sns-x-live exec -T -e LIVE_MODE_ENABLED=false -e X_LIVE_SMOKE_ENABLED=false -e X_LIVE_REFRESH_SMOKE_ENABLED=false -e X_OAUTH_BOOTSTRAP_ENABLED=false -e 'PGOPTIONS=-c statement_timeout=120000' backend pytest -q -p no:cacheprovider`。テスト接続だけにSQL上限を設け、Production Source / 稼働サービスの環境は変更していない。

**投稿準備後の追加Sync終了後、同じ全件コマンドで1482 passed / 0 failed / 0 skipped、291.03s。** 前回失敗したOverview大規模データテストも全件実行内で成功。Source修正は行っていないため、SQL遅延の原因解消を実証した結果ではない。最終Frontendは32 passed / 0 failed / 0 skipped / 0 canceled、4057.610275ms、Typecheck / Build成功（19 routes）。

Docker build成功。Private 6サービス稼働、Backend / DB / Redis healthy、Worker 1 node online、Frontend HTTP 200、Health API HTTP 200、OpenAPI 42 paths。Alembic `0005_v2_provider_core`、0001〜0005保持、0006なし。

Canonical DemoのOverview / My Account / Trend Explorer / Competitor / Gap / AI Insights / Settings Importを実ブラウザーで確認。固定UTC期間2026-07-07〜2026-10-04。180投稿、Reach 93,392、Engagement 6,928、Impressions 136,256。Trend Score14.04 / 4.16、5アカウント比較、Gap 12行・NULL1・0値2・4分類、保存済みDemo AI、CSV4履歴を確認。新しいAI生成・CSV取込・Schedule実行は行わない。通常DBの19テーブル（18業務 + Alembic）の件数と全行内容digestは前後一致。

追加Sync終了後も通常DBの19テーブルを再比較し、検証開始前と全件数・全行digest一致。Source396ファイル・前回Phase6 ZIPのSHA256不変。7画面のブラウザー確認は最初のSmoke後の結果を保持し、追加Sync後は画面操作を繰り返さずDB内容とSourceの不変性を確認した。Private Workerは再確認時も1 node online、Migration 0005 head、通常環境の検査用DBコンテナは停止・削除しVolumeを保持。

## 17. Remaining Gaps

投稿準備のUSER_ACTION_REQUIREDは解消。実SNSPost / PostMetricの保存・provenance・非空Analytics・POSTS非NULL checkpointを確認済み。

1. 再発リスク: Overviewの大規模データテストは過去の全件実行で長時間停止・失敗した。単独実行と最終全件実行は成功したが、以前の停止原因は未確定。今後の全件実行で再発する場合は、DB実行計画・統計情報・実行環境とSourceを切り分けて調査する。実X Providerの障害や原因修正済みとは断定しない。
2. Workerの正確なHTTP wire request countと実請求額は未計測。since_id増分の実通信は省略。課金最小化のため、追加Syncは許容された1回で終了。

実X Providerの実装バグを示す再現結果はない。指示書のVerification Only / Production Source変更制限に従い、今回のOverviewテスト停止を理由に対象外のAnalytics Sourceを書き換えない。0件の正常取得をコード修正で隠したり、Mock PostをLIVEへ挿入したりしない。

## 18. Phase 7 Decision / Deliverables

**GO**。Real Validate / Manual Sync / Job / Live DB Import / X provenance / Sync State / Analytics / Refresh / Refresh-after-Me、最終Backend Full / Frontend / Typecheck / Build、Docker / Migration / Secret検査 / Canonical Demo不変性を確認。最終検証では全必須GateがPASS。以前のNO-GOをこの追検証結果で更新する。Production Source変更0。これはPhase 7へ進める判定であり、今回Phase 7実装は開始していない。

Review ZIP: `SNS_Analyzer_V2_Phase6_Verified.zip`。以前のNO-GO版を、本Reportの追検証結果を含む最終版へ更新。前回Phase6 ZIP / Reportは変更せず、今回のReportを追加する。

納品検査: 400 entries（397 Worktree Source + 3 instruction references）、CRC PASS、全Source byte一致PASS。前回Source396ファイルのSHA256はすべて不変。Migration0001〜0005不変、0006なし。Phase 1〜6 Report / README / Tests / X Guide / 本Reportあり。禁止ファイル0、現行SecretとZIP全entryを内部比較して検出0。Report最終更新後にZIPを再作成・再検査済み。
