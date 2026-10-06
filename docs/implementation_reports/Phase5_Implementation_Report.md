# Phase 5 Implementation Report

実施日: 2026-10-03（Asia/Tokyo）

## 1. 実装概要

Phase 5のBackend Trend Engine、MARKET限定Topic/Term集計、7日Window、Growth/Acceleration、Score、Import連携を実装した。Phase 6には進まない。通常開発DBはSeed状態を保持し、検証データは専用の破棄可能PostgreSQL DBだけに作成した。

## 2. 作業開始時Git状態

- Repository: `Repository Root`
- Branch: `master`（既存Branchを維持）
- 開始HEAD: `ec7805149adc4a0f205975b453acd97677fe6764`
- 開始Working Tree: Clean
- Git author: 利用者指定のAuthor（個人情報は公開用文書から除去）（利用者指定）
- Remote: 未設定。追加・変更しない。

## 3. Phase 4基準点確認

Phase 4実装Commitは `22c3786d38fd690f0a897c0fae93e938ac686f50`、報告書追記Commitが開始HEAD。変更前にDocker内で既存全386件成功（13.95秒、Warning 1、失敗・Skip 0）を確認した。13テーブル、Alembic `0001_initial`、既存Import/Provider契約を維持した。

## 4. 新規作成ファイル

| ファイル | 役割 |
| --- | --- |
| backend/app/services/trend_calculation.py | 純粋なDecimal計算・NULL・正規化 |
| backend/app/services/trend_service.py | UTC日次・Window集計と再構築の統括 |
| backend/app/repositories/trend_repository.py | 一括読込・Latest Metric・Project限定置換 |
| backend/tests/trends/__init__.py | Test package |
| backend/tests/trends/conftest.py | 既存の独立接続/PostgreSQL fixture再利用 |
| backend/tests/trends/test_calculation.py | 44件 |
| backend/tests/trends/test_normalization.py | 11件 |
| backend/tests/trends/test_repository.py | 3件 |
| backend/tests/trends/test_trend_service.py | 22件 |
| backend/tests/trends/test_import_integration.py | 13件 |
| docs/implementation_reports/Phase5_Implementation_Report.md | 本報告書 |

## 5. 変更ファイル

`backend/app/services/import_service.py` にTrend呼出しとPost ImportのProject排他ロックを追加。既存の位置引数互換を保持して任意のTrendService注入を末尾に追加した。`README.md` に計算・NULL・Transaction・実行手順を追記。`backend/.dockerignore` のPythonキャッシュ除外を再帰指定へ変更し、Windows生成pycがDockerへ混入しないようにした。

Model、Migration、API route/schema、Provider/Normalizer/DTO、Frontend、依存Packageは変更なし。

## 6. Trend Engine構成

`TrendRepository.load → build_trend_rows → TrendRepository.replace` を `TrendService.rebuild_project(session, project_id)` が統括する。計算はDBから分離。Service/RepositoryはCommitしない。再構築件数を返す。Project不存在はValueError。明示Service呼出しにも同Project行の排他ロックをかける。

## 7. MARKET限定仕様

SNSPostのproject_idとsource_type=MARKETで取得する。OWN/COMPETITORは計算に含めない。有効ProjectPlatformだけが出力対象。X/INSTAGRAMのCohortを混ぜない。

## 8. Topic集計

有効WatchTopicと正式post_topics関連を使用。重複する投稿・Topic関連は一意化し、複数Term一致でもTopic投稿数は1。Term関連からTopic集計を推測しない。MANUAL/AIの正式Topic関連も同じ1件として含める。

## 9. Term集計

有効WatchTopicに属する有効WatchTermとpost_termsを使用。EXACT/NORMALIZED/MANUAL/AIは重みなし。同じ投稿が複数Termに正式関連を持てば各Termで1件。関連読込でもProjectを絞り、誤った他Project関連を計算に入れない。

## 10. 日付/UTC仕様

**Version 1 Trend aggregation timezone = UTC**。posted_atをUTCへ変換して日付化。OS/DB Session Timezoneに依存しない。Project全体のMARKET最古日～最新日を両端含め連続出力。未一致投稿・無効Platform投稿も期間の基準には含め、出力は有効Platform/Topic/Termだけとする。0投稿日にも行を作る。

## 11. Latest PostMetric仕様

Postごとに `row_number() over (partition by post_id order by recorded_at desc)` の1件をLEFT JOIN。Snapshot全件の加算・任意の1件選択をしない。Metricなしでも投稿数に含める。既存Unique制約により同じpost_id/recorded_atの重複はない。

## 12. Engagement仕様

likes/comments/shares/savesの既知値を加算。impressions/reach/viewsは対象外。全NULL・Metricなしは不明。明示0は既知の0。不明投稿は平均の分母から除外する。全て不明ならDB NOT NULLのengagement_countは0だが、内部の既知投稿数0で不明を区別し、avg_engagement/engagement_growth_rate/対応ScoreをNULLにする。

## 13. 7日Window

基準日D: Current D−6～D、Previous D−13～D−7、Prior D−20～D−14。両端含む。日次の投稿数・Engagement合計・既知投稿数から累積和を作り、境界の差分で取得する。最古日の20日前まで0で補う。window_daysは常に7。

## 14. Post Growth Rate

`(Current投稿数 − Previous投稿数) / Previous投稿数 × 100`。Previous=0はNULL。Previous>0かつCurrent=0は−100。Decimalで計算しRaw保存は小数4桁。

## 15. Engagement Growth Rate

`(Current合計Engagement − Previous合計Engagement) / Previous合計Engagement × 100`。両Windowに既知投稿があり、Previous合計>0の場合だけ計算する。平均Engagementの増加率は使用しない。

## 16. Acceleration Rate

Current対PreviousのPost GrowthからPrevious対PriorのPost Growthを引く。百分率の差として扱う。いずれかNULLならNULL。

## 17. Score Normalization

CohortはPlatform・UTC日付・window_days=7・粒度TOPIC/TERMの組合せ。Project単位で呼ぶため他Projectを含まない。4成分ごとにNULLを除外して `(値−min)/(max−min)×100`。同値・既知値1件は50。全NULLは全NULL。0～100に制限。Rawの保存丸め前に正規化し、Scoreは2桁。

## 18. Trend Score

`post_growth_score×0.40 + engagement_growth_score×0.30 + engagement_level_score×0.20 + acceleration_score×0.10`。成分Scoreを2桁に丸めた後に加重し、結果も2桁。Decimal精度50、ROUND_HALF_UP。floatを使わず、Rawは4桁。

## 19. NULL/Data Insufficient

前期間0・Engagement不明・Prior不足は該当Raw/ScoreをNULLとする。4成分のどれかがNULLならTrend ScoreもNULL。0/50で補完せず、利用可能成分への重み再配分もしない。DBスキーマへData Insufficient列を追加していない。

## 20. Full Rebuild

対象ProjectのWatchTopicに属するTrendを無効Topic分も含め全削除し、全期間を再INSERT（1000行ごとのバッチ）。他Projectを削除しない。MARKETなしは0件へ置換。再構築で業務値は同じになるがUUID/作成時刻は再生成される。削除・途中INSERT失敗も呼出し側TransactionでRollbackされる。

## 21. ImportService連携

OWN_POSTS/TREND_POSTS/COMPETITOR_POSTSの全正常行保存・Matching完了後、最終履歴更新前に1回実行。0件/部分成功でもPost系では1回。ACCOUNT_DAILYでは呼ばない。MARKET→OWN/COMPETITOR、逆のSource Type更新にも対応。API応答は既存契約のまま。

## 22. 同一Project Import直列化

Post ImportのProject確認でFOR UPDATEを取得しBusiness Transaction終了まで保持。明示再構築でも同ロック。Project行単位のため、別Projectを一括直列化しない。ACCOUNT_DAILYは既存FOR SHAREを保持。

別接続で共有ロックを保持し、同Project Post Importがlock_timeout=250msで失敗する実PostgreSQL検証により排他ロックを確認した。同じ条件で別Project Post ImportとACCOUNT_DAILYは成功。同Projectの2つの成功Importを同時実行する長時間負荷試験は未実施。

## 23. Transaction/Rollback

投稿・PostMetric・Matching・Trend・SUCCESS/PARTIAL_ERROR履歴を同Business Transactionで確定。Trend更新後に例外を注入し、更新前の投稿/Metric/関連/Trend IDが復元されることを確認。別Audit SessionでFAILEDをCommit。別接続からCommit前のTrend非公開・PROCESSING履歴だけ可視も確認した。

## 24. Phase 5 Unit Test

純粋計算/正規化55件と純粋build_trend_rows 3件の計58件。正負Growth、0/NULL、巨大Decimal、Acceleration、50/NULL/負値Cohort、微小差の丸め順、64の加重例、粒度分離、合計と平均の相違、10,000投稿の累積和を確認。新規全93件に含まれる。

## 25. Phase 5 PostgreSQL Integration Test

Repository 3件、Service 19件、Import 13件の計35件。専用PostgreSQL DBでLatest Metric、独立粒度、UTC（Session Honolulu）、有効設定、0日、境界、Project分離、Idempotence、全削除、Query数、Rollback、Commit可視性、ロック、Source Type変更を確認。

最終コマンド: `docker compose exec backend python -m pytest tests/trends -q -p no:cacheprovider`

| Total | Passed | Failed | Skipped | Warning | 秒 |
| --- | --- | --- | --- | --- | --- |
| 93 | 93 | 0 | 0 | 1 | 5.15 |

## 26. Import Regression

`docker compose exec backend python -m pytest tests/imports -q -p no:cacheprovider`

| Total | Passed | Failed | Skipped | Warning | 秒 |
| --- | --- | --- | --- | --- | --- |
| 111 | 111 | 0 | 0 | 1 | 7.79 |

既存テストは変更なし。

## 27. Provider Regression

`docker compose exec backend python -m pytest tests/providers -q -p no:cacheprovider`

| Total | Passed | Failed | Skipped | Warning | 秒 |
| --- | --- | --- | --- | --- | --- |
| 150 | 150 | 0 | 0 | 0 | 0.52 |

Provider/Normalizer/DTO/既存テストは変更なし。

## 28. Full Regression

`docker compose exec backend python -m pytest -q -p no:cacheprovider`

| Total | Passed | Failed | Skipped | Warning | 秒 |
| --- | --- | --- | --- | --- | --- |
| 479 | 479 | 0 | 0 | 1 | 21.71 |

既存386件＋新規93件。新規のファイル別件数は44/11/3/22/13。不要なSkipなし。

## 29. Frontend Build/Typecheck

frontendで `node node_modules/typescript/bin/tsc --noEmit`、`node node_modules/next/dist/bin/next build` ともexit 0。Frontend変更なし。ブラウザでの直接GUI操作/スクリーンショット確認はこのPhaseでは実施していない。

## 30. Docker/Health/Alembic

Docker Desktopが停止状態だったため既存インストールをHiddenで起動。Backendを再BuildしてCompose起動。DB/Backend healthy、Frontend running。HealthはHTTP 200 `{"status":"ok","database":"connected"}`。Python compileall成功。Alembic current/headsは `0001_initial (head)`、head 1系統。追加Migrationなし。OpenAPI pathは `/api/v1/health` と `/api/v1/projects/{project_id}/imports` のみ。

テストDB残存0。通常DB件数: projects=1、project_platforms=2、sns_accounts=5、watch_topics=2、watch_terms=6、その他8業務テーブル=0。通常DBの投稿/指標/Trendへ検証データを保存していない。

## 31. Performance基本確認

Repository.loadは投稿0件/100件でどちらも6 SELECT、Latest MetricはWindow関数で一括取得。日次累積和によりWindowごとの投稿全走査を避ける。10,000投稿・90日を純粋計算テストで確認。1000行INSERTバッチ。DB込みの10,000投稿ベンチマーク、長期間・大量Topicのメモリ負荷試験は未実施。Full Rebuildの計算量/メモリは期間×有効Platform×粒度数に比例するため、将来の大量データでは段階的最適化が必要。

## 32. Warning

API TestClientで既存Starlette/httpx連携のDeprecationWarning 1件（httpx2への移行推奨）。依存更新はPhase 5範囲外のため実施せず、失敗とは区別。GitのLF→CRLF通知は環境設定によるもの。pytest cache書込みは `-p no:cacheprovider` で避け、Skipはしていない。

## 33. 発生した問題と対応

初回新規テストは92成功/1失敗、初回Docker全件は478成功/1失敗。Project分離テストのfixtureが自Projectの有効Term関連も作り、正当なTerm集計まで0と期待していた。両関連を他ProjectのTopic/Termへ変更して目的どおりに修正。ProductionのProject絞込に変更は不要だった。最終93/479件成功。

Windowsのローカルpytest生成pycがDocker contextに混入し、tracebackにWindowsパスが出た。`.dockerignore` を `**/__pycache__` / `**/*.py[cod]` に変更して再Build。最終イメージの `/app/app`・`/app/tests` 配下pycは0。

## 34. 正本との差異/未規定事項の決定

利用者に差異を提示し、明示回答「Phase 5の詳細仕様を採用：全NULLは不明、合計Engagementの増加率」を受けた。正本Ver1.1のCOALESCE合計（全NULLも0）・基本設計評価表のEngagement/投稿増加率に対し、この2点だけPhase 5詳細仕様を優先。DB定義は正本を保持。

決定内容: UTC固定、既知値のみ平均、全未知engagement_count=0と平均NULLの併用、Project全MARKET日付範囲、Topic/Term独立関連、Raw丸め前正規化、成分丸め後加重、Decimal精度50、累積和、直接Service呼出しにも排他ロック。Schema/API/画面は追加しない。

## 35. Phase 5実装Commit/Push結果

実装Commit: `a1d5706844cd83932078165cb966380120f99be3`（`feat: complete Phase 5 trend engine`）。Commit成功、直後Working Tree Clean。報告書追記はamendせず別Commit。Remote未設定のためPush未完了。Remote追加・履歴書換えは行わない。最終HEADはこの後の報告書追記Commitを含むため、最終回答とZIP commentで確認できる。

## 36. Review Zip作成結果

実装・報告書追記Commit後、Repository外へ `git archive --format=zip HEAD -o ../SNS_Analyzer_Phase5.zip` で作成した。

保存先: `../SNS_Analyzer_Phase5.zip`

初回検証: HEAD `d4904c6a3176768816ab8afca9144ef21c83fef7`、94ファイル、187,772 bytes、CRC正常、ZIP commentとHEAD一致。Git管理Source/Test/README/本報告書を含め、.env/.git/node_modules/.next/.venv/キャッシュ・Build生成物の混入なし。全ファイル一覧はGit tracked一覧と一致し、本文もLFへ正規化後Git blobと一致した（core.autocrlf=trueによるZIPのCRLF変換を考慮）。

この作成確認の追記を別Commitした後、同じコマンドで最終HEADからZIPを再生成して再検証する。最終HEAD・サイズ・SHA256は自己参照を避けるため最終回答に記載する。ZIPはGit対象外。

## 37. Phase 6への申し送り

Trend EngineはImport経由および内部Serviceから利用可能。Trend API、Data Insufficient表示、設定CRUD、取込画面、分析画面、実SNS通信、PROCESSING強制終了回復は未実装。次Phaseは利用者側でZIPレビュー後に指示する。大量データ/長期間のFull Rebuild負荷、依存Warningへの対応は別途検討事項。

## 38. Phase 5完了判定

実装・新規/回帰479件・Frontend・Docker/Health/Alembic・README/報告書・実装Commit・報告書追記Commit・ZIP作成/検証が完了し、Phase 5は完了。作成確認追記Commit後の最終ZIP再生成/検証まで行って終了する。Push不可（Remoteなし）は指示書に従い失敗扱いとしない。Phase 6へ進まずレビュー待ちで終了する。
