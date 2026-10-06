# Phase 6 実装報告書

作業日：2026-10-03（Asia/Tokyo）。対象：Settings / Importのみ。

## 1. 実装概要

Project/Platform/Account/Topic/Term管理API、Import履歴API、Settings4タブ、CSV取込・結果・履歴詳細を実装。再照合とTrend再構築を既存基盤へ統合。Phase7以降の分析・認証・外部APIは対象外。

## 2. 作業開始時Git状態

`git status --short`：出力なし、Working Tree Clean。
`git branch --show-current`：master。
`git log --oneline --decorate -15`：HEAD fe704ad（docs: record Phase 5 archive verification）、d4904c6、a1d5706（feat: complete Phase 5 trend engine）、ec78051、22c3786、4288942、a747058、979cd70、4749cac、2838b4c。
`git remote -v`：出力なし（Remote未設定）。.env/node_modules/.next/.venvは未追跡・ignore対象。

## 3. Phase 5基準点

実装Commit `a1d5706844cd83932078165cb966380120f99be3` が履歴に存在。開始時全479 Passed、Failed 0、Skipped 0。Alembic 0001_initialを維持。

## 4. 新規作成ファイル

- backend/app/api/v1/settings.py
- backend/app/repositories/settings_repository.py
- backend/app/schemas/__init__.py、settings.py
- backend/app/services/settings_service.py、rematch_service.py
- backend/tests/settings/__init__.py、conftest.py、test_api.py、test_refresh.py
- frontend/src/lib/api.ts
- frontend/src/components/settings.tsx
- frontend/src/app/dashboard/settings/page.tsx、frontend/src/app/settings/page.tsx
- docs/implementation_reports/Phase6_Implementation_Report.md
- docs/implementation_reports/Phase6_Import_Verification.jpg、Phase6_Validation_Error.jpg

## 5. 変更ファイル

backend/app/main.py（Router/CORS）、backend/app/repositories/import_repository.py（共通Batch Matching）、frontend/src/app/globals.css（Tailwind）、frontend/src/app/page.tsx（Settingsリンク）、README.md。

## 6. Project API

GET/POST一覧、GET詳細、PUT/PATCH更新。Trim後1～100文字、Platform重複禁止・最低1。作成201、更新200。ProjectとPlatformsを同Transactionで作成。Inactiveも取得・再Activate可能。物理DELETEなし。

## 7. Platform API

GET/PUT。差分だけproject_platformsへ反映し、変更時Trend Full Rebuild。最低1、X/INSTAGRAMのみ。解除してもAccount/Post/Metric/Historyは保持。再有効化で既存MARKETを再集計。

## 8. Account API

一覧（platform/role/name安定順）、作成、PUT/PATCH編集。Role/Platform/ID等の未知項目は422。Active AccountのPlatform確認、OWN競合409をApplicationと既存Partial Uniqueで保護。DELETEは正本に従いis_active=falseだけ。再有効化にも同じValidation。

## 9. Topic API

一覧にTerms、作成（Terms同時登録も対応）、PUT/PATCH更新、DELETE無効化。Project内同名409、異Project/不存在404。名前・説明だけならRematch不要。

## 10. Term API

POST/PATCH、Type enum、Backend normalize_termでnormalized_term生成。Client指定不可。Type/文字変更時再計算。Unique409、Topic/Project scope404。物理DELETEなし。

## 11. Import History API

GET一覧/詳細。正本page/page_size（既定1/20、最大100）、互換limit/offset（既定20/0、最大100）。明示limit/offset優先。status/import_typeフィルター、imported_at DESC/import_id DESC。Responseには両ページ形式を返す。詳細error_detail、他Project404。既存POST Importは変更しない。

## 12. Settings Service

Request単位のTransactionとProject Lock。明示Pydantic Request/Response。extra forbid、部分更新のexplicit nullはnullable項目だけ許可。意味的400、404、409、422、500を安全な正本error形式で応答。

## 13. Rematch Service

Active Termsを1回取得、Project内投稿をyield_per=500でBatch取得。保存済みtext/hashtagsとraw_data.keywordを使って最小DTOを復元。CSV Validationは通さず保存値を変更しない。

## 14. Matching再構築

ImportRepository.rebuild_matchesはBatch共通処理に委譲。自動PostTerm EXACT/NORMALIZEDとPostTopic KEYWORD/HASHTAGだけを削除。MANUAL/AIとスコアを保持し、保持Termの親Topicも維持。保持関連のSELECTはBatch単位、INSERTは最大1000行のChunk。1001投稿でSELECT30未満を検証。

## 15. Trend再構築

既存TrendService.rebuild_projectを再利用。Topic Active、Term追加/文字/Type/Active、Platform変更に反映。Phase5のUTC・全NULL不明・合計Engagement Growth・7日・40/30/20/10・Min-Max・Full Rebuildを維持。

## 16. Transaction

Settings変更・Rematch・Trendを同Transaction。Trendが途中で行を削除して例外を出す故障注入により、設定/Matching/TrendのRollbackを検証。Service/Repository中の独立Commitなし。

## 17. Project Lock

変更時SELECT Project FOR UPDATE、終了まで保持。同Project Importと同じ行Lockを使用。実PostgreSQLの共有/排他Lock競合、同Project Import待機、別Project処理成功を検証。

## 18. Frontend構成

既存Next.js/React/TypeScript/Tailwindを使用。新規Libraryなし。api.tsにtyped fetchと各Resource操作。URL末尾Slash共通処理、NEXT_PUBLIC_API_BASE_URL、FormData Upload。未知エラーは安全な固定文言。

## 19. Project Tab

Project選択localStorage、Tab query。新規/編集、Active切替、Platform専用保存。保存応答でstate更新。Project0件Empty→新規導線。保存中選択・Tab・Formをdisable。

## 20. Accounts Tab

Table、Add/Edit/Activate/Deactivate。編集時Platform/RoleはReadonly。Optional項目のNULLクリア、名前必須、OWN競合はBackendメッセージを表示。

## 21. Topics Tab

CardとTerm Table、Topic/Term追加・編集・有効/無効化。normalized_termは主表示しない。Refresh中Saving表示、二重送信防止。

## 22. Import Tab

4種のType、CSVファイル選択、multipart送信、Uploading/Importing、結果とRow/Field/Code/Message。FAILED HTTP応答も結果として表示。Inactive Projectは送信不可・再Activate案内。

## 23. Loading / Error / Empty

各取得のLoading、Error+再読み込み、Project/Account/Topic/Term/履歴Empty。aria-live、label、button、focus。古い非同期取得結果はversionで破棄。保存はrefとdisabledで二重送信防止。

## 24. Import History UI

初期20件、Date/Type/Filename/Status/Total/Success/Error、Previous/Next、Status/Type filters、Inline Detail。横幅が狭い場合Tableを横スクロール。

## 25. Phase 6 Backend Test

Command：`docker compose exec backend python -m pytest tests/settings -q -p no:cacheprovider`
Total 77 / Passed 77 / Failed 0 / Skipped 0 / Warnings 1、10.11s。
Project/Platform/Account/Topic/Term/Hashtag、Unique、Scope、History、CORS、安全なエラー、全Source Rematch、保護関連、Platform OFF/ON、Rollback、Batch query、Project Lock/Import待機を検証。

## 26. Import Regression

Command：`docker compose exec backend python -m pytest tests/imports -q -p no:cacheprovider`
Total 111 / Passed 111 / Failed 0 / Skipped 0 / Warnings 1、7.97s。

## 27. Trend Regression

Command：`docker compose exec backend python -m pytest tests/trends -q -p no:cacheprovider`
Total 93 / Passed 93 / Failed 0 / Skipped 0 / Warnings 1、6.55s。

## 28. Provider Regression

Command：`docker compose exec backend python -m pytest tests/providers -q -p no:cacheprovider`
Total 150 / Passed 150 / Failed 0 / Skipped 0 / Warnings 0、0.67s。

## 29. Full Backend Regression

Command：`docker compose exec backend python -m pytest -q -p no:cacheprovider`
基準点：Total 479 / Passed 479 / Failed 0 / Skipped 0 / Warnings 1、19.36s。
最終：Total 556 / Passed 556 / Failed 0 / Skipped 0 / Warnings 1、32.46s（479既存+77新規）。

## 30. Frontend Typecheck

`npm run typecheck`：成功（exit 0）。HostにnpmがPATH登録されていないため、Node22コンテナにfrontendをbind mountして実行。補助的にbundle Node経由のtsc --noEmitも成功。npm更新noticeのみ。

## 31. Frontend Production Build

`docker compose build frontend`内の`npm run build`成功。Compiled successfully、TypeScript成功、5 static pages生成。/、/dashboard/settings、/settingsを出力。Backend imageもbuild成功。

## 32. Browser確認

Codex In-app Browserで実アプリを操作。検証用の架空Project「Phase6 Browser Verification Edited」を追加し、通常Seedデータは変更しない。
確認：画面表示、Project作成/名前編集、Account追加/Display Name編集（Platform/Role固定）、Topic追加/説明編集、Term追加/文字編集、Account/Topic/Term/履歴Empty、Saving/Uploading/Loading、CSV選択→TREND_POSTS実行、PARTIAL_ERROR（Total2/Success1/Error1）、履歴とDetail（row3/likes/INVALID_INTEGER）、不正Hashtag #のBackend Error表示。
証跡：Phase6_Import_Verification.jpg、Phase6_Validation_Error.jpg。
Project0件の実ブラウザ確認、全4種CSVのGUI取込、Next/Previousの20件超GUI、通信障害からの再読込、全幅/DPI/全Browserは未確認（API/Backendテストと実装確認は別）。認証/E2E導入は対象外。架空検証データは確認可能な状態で開発DBに保持。

## 33. Docker / Health

`docker compose up -d`で更新imageへ再作成。db healthy / backend healthy / frontend running。GET /api/v1/health 200。開発DBのDROP/TRUNCATE/downgrade/down -vは未実行。

## 34. OpenAPI

GET /openapi.jsonで12 paths、指示書の全18操作（Healthを含む）を確認。正本のProject/Account/Topic PUTとAccount/Topic soft DELETEも追加。全Request/Response Modelが記載される。

## 35. Alembic

`docker compose exec backend alembic current`：0001_initial (head)。`alembic heads`：0001_initial (head)、1 head。DB Model/Schema/Migration変更なし。

## 36. Test DB残存確認

pg_databaseのsns_phase2_test_%をread-only count：0。全Integrationは既存Disposable PostgreSQL fixture。通常開発DBへ破壊的テストなし。

## 37. Warning

既存StarletteDeprecationWarning：httpxとstarlette.testclientの組合せ。開始時も同じ1件、Test成功に影響なし。依存更新は本Phaseで行わない。npmのmajor更新notice、GitのLF→CRLF noticeはエラーではない。

## 38. 発生した問題と対応

Host npm未検出→既存Docker Node22環境で品質確認。初回の新規テスト7失敗はテスト側の既存Seed Term重複、Competitor CSVにhashtags Headerなし、TrendDaily PK属性名の誤り。テストを正しい契約/保存済み投稿値に合わせて修正し、77件全成功。最終確認では故障注入のTrend削除scopeをtopic_id経由のProject条件に修正し、実削除rowcount>0を追加検証後、77件/全556件を再実行成功。Docker cpはディレクトリの内容（末尾/.）でコピー後、最終imageを再buildし検証。ブラウザselect label locatorはRole comboboxに切替。

## 39. 正本との差異 / 未規定事項

最初に基本/画面/API/DB Ver1.1とPhase計画を参照。具体Phase6差分は正本優先：

| 項目 | 正本 | Phase6指示書 | 実装 |
| --- | --- | --- | --- |
| 更新Method | PUT | PATCH | PUT正本、PATCH互換 |
| Account/Topic無効化 | DELETE（論理無効化） | PATCH、物理DELETE禁止 | DELETEはis_active=falseのみ、物理削除なし |
| Topic作成 | Terms同時指定 | 名前/説明 | 両方対応・同Transaction、TermsありはRefresh |
| History Pagination | page/page_size | limit/offset | UIは正本、互換指定も受付・両方Response |
| Settings Path | /dashboard/settings | /settings推奨 | 両入口 |
| Settings Error | error/code/message/details | statusの分類 | 正本の安全なerror形式、Import POST維持 |

Phase5確定済みの全NULL/合計Engagement Growthは変更しない。未規定の一覧は小規模SettingsなのでProject/Account/TopicにPaginationを追加しない。Platformは完全置換の業務契約でDBは差分更新。Timestamp/enum/UUIDは明示Model。正本の将来分析API・共通Platform/Periodヘッダー・Sidebar全分析機能は本Phaseで実装しない。

## 40. Phase 6実装Commit / Push

実装Commit：`fbc0a5f0a1c3a5570e220f7f655f2f1749773dc7`（feat: complete Phase 6 settings and import UI）、22 files changed。最終HEAD：報告書追記Commitとして別途最終回答に記載（自身のhashを自ファイルへ記載する循環を避ける）。Push：Remote未設定のため未実施。Remote追加/変更なし。実装Commit後git status --shortは出力なし、Clean。

## 41. Review Zip

報告書追記Commit `95fc0860888c93ae66a48dd9b7320f1326648f28` 後、Repository Rootで `git archive --format=zip HEAD -o ../SNS_Analyzer_Phase6.zip` を実行。初回検証：342,300 bytes、143 entries、全CRC正常、禁止物0、Backend/Frontend/Tests/README/本報告書存在、ZIP commentのCommitがHEADと一致。この検証追記Commit後、同コマンドで最終HEADから再生成し再検証する（最終Hash/サイズは最終回答で報告）。保存先：`../SNS_Analyzer_Phase6.zip`。生成ZipはRepository外・Commit対象外。

## 42. Phase 7への申し送り

ユーザーによるPhase6 Zipレビューを待つ。Settings CRUDとImportを使って分析対象を用意できる。分析API/UIは未実装。Phase7へ自動移行しない。同期Full Rebuild/10,000件規模の性能改善はPhase13、認証/外部APIは後続対象。既存PROCESSING履歴の強制終了回復は引き続き未実装。

## 43. Phase 6完了判定

機能・77新規/556全Test・Typecheck/Build・Docker/Health/OpenAPI/Alembic・TestDB残存0・README・本報告書を確認。Browserの未実施範囲は32節のとおり。実装Commit成功。Phase6機能・品質条件を満たす。Review Zip生成・検証成功。Phase6完了。検証追記後の最終HEADから再archive・CRC/内容/Commit一致を最終確認して終了する。PushのみRemote未設定の制約。
