# Phase 7 My Account 実装報告書

2026-10-03 / Phase 7の自社投稿分析を実装。Phase 8以降へは進んでいない。

## 対象と設計

Phase7実装指示書を作業範囲として使用し、既存の基本設計・詳細設計・API仕様Ver1.1・画面設計・CSV仕様・DB仕様の正本を参照した。Phase1〜6の契約、Provider/Normalizer/Import/Matching/Trend/Settingsを維持。通常DBのDROP/TRUNCATE、Migration変更、外部SNS接続、認証・AI・競合分析を追加していない。

Routeは `/dashboard/my-account`、正本の `/dashboard/account`、互換 `/my-account`。Settingsと接続確認画面からリンクする。Backendへ実接続し、Client側固定値で分析を表示しない。

## ファイル

新規Backend:

- `backend/app/api/v1/my_account.py`: typed query・3 GET API・既存安全なエラー形式。
- `backend/app/schemas/my_account.py`: Response/EnumとNULL許容値。
- `backend/app/repositories/my_account_repository.py`: Project/OWNスコープ・最新指標の一括取得・Followers/Topic・ソート。
- `backend/app/services/my_account_service.py`: 集計・期間・比較・read-only Transaction。
- `backend/tests/my_account/__init__.py`, `conftest.py`, `test_calculation.py`, `test_api.py`: 新規96件。

新規Frontend:

- `frontend/src/lib/my-account-api.ts`: typed API client。
- `frontend/src/components/my-account.tsx`: Filter、KPI、Recharts、一覧、Drawer。
- `frontend/src/app/dashboard/my-account/page.tsx`, `dashboard/account/page.tsx`, `my-account/page.tsx`: 画面とAlias。

変更: `backend/app/main.py` Router登録、`frontend/src/app/page.tsx` と `frontend/src/components/settings.tsx` への導線、`README.md`。報告書と検証画像も追加。DBモデル・Alembicファイルは変更なし。

## API

共通prefix: `/api/v1/projects/{project_id}`。

| Method / Path | 用途 |
| --- | --- |
| GET `/accounts/own/analytics` | kpis / engagement_trend / media_type_performance / timezone |
| GET `/accounts/own/posts` | items / total / page / page_size |
| GET `/posts/{post_id}` | post / metrics / comparison / topics |

Analytics/Listはfrom/to必須。Detailのfrom/toは両方指定または両方省略。省略時は有効Platformの全OWN履歴を比較対象にする。日付なしで他の比較Filterを指定する場合は400。存在しないProject、別Project、非OWN投稿は404。型・Enum・範囲違反は422、期間逆転など意味的エラー400。既存SettingsRouteの `error: {code,message,details}` を使用し、入力・SQL・内部例外は転載しない。

## Filter / スコープ

Project IDとsource_type=OWNで絞り、有効Platformのみ対象。Inactive Account・Inactive Projectの過去投稿を除外しない。Detailは同ProjectのOWNならPlatform無効化後も閲覧可能だが、有効Platformの比較対象に入らない場合は比較NULL。

- platform: ALL / X / INSTAGRAM。ALLはProjectで現在有効なPlatform。
- from/to: UTC日付、両端inclusive。開始00:00:00〜終了23:59:59.999999。
- media_type: TEXT / IMAGE / VIDEO / CAROUSEL / OTHER、省略で全形式。NULLは別カテゴリ。
- keyword: 本文のNFKC・trim・casefold後のリテラル部分一致。%と_はワイルドカードにしない。
- hashtag: 共通Normalizerで先頭#補完・正規化、配列の完全一致。空白のみは指定なし、複数タグ・不正タグは400。

Unicode Filterは保存データを書き換えない。画面検索で全セクション・Drawerへ同じ条件を適用し、pageを1へ戻す。Project切替時に検索条件を維持、前の応答を破棄。過去7/30/90日は端末の当日日付を終点としてUTC日付範囲を作る。

リソース上限の補足: 期間最大3660日、keyword最大1000文字、hashtag最大255文字。正本未指定の入力上限を明示的なValidationとして追加した。

## 指標と比較

PostMetricをpost_id別row_numberでrecorded_at DESCの1件に限定し、一括外部結合。指標なし投稿もPostsへ含め、指標はNULL。複数Snapshotを合算せず、古い非NULLで最新NULLを埋めない。

| 指標 | 定義 |
| --- | --- |
| Posts | 条件に一致するOWN投稿数、空なら0 |
| Reach / Impressions | 投稿ごとの最新値の既知値合計、全不明はNULL |
| Engagement | likes + comments + shares + saves。部分NULLは既知値合計、全NULLはNULL |
| Average Engagement | Engagement既知投稿の算術平均 |
| Engagement Rate | Engagement ÷ 優先分母 × 100 |
| Followers | 有効OWN Account別、To以前の最新AccountMetric。未取得NULL、複数Account非合算 |

ER分母は最初の非NULLをreach→impressions→viewsで選択。0ならNULLで、後順位へフォールバックしない。Engagement不明・全分母NULLもNULL。0 Engagement / 正の分母は0。分母名・値をResponse/Drawerへ返す。Decimal精度50で未丸め値を平均・比較し、返却時にHALF_UPの小数4桁へ丸める。ER平均は有効ER投稿のみ。同じPlatform・分母のcohort別に平均し、混在時は無条件のscalar平均をNULLにしてrate_groupsへ内訳を返す。

Followersのscalarは対象の有効OWN Accountが1件の場合のみ。複数SNSを合算せずfollowers_by_accountへ返す。本文・媒体FilterでFollower履歴を絞る意味はないため、AccountのProject/Platform/Toを使用する。

日次TrendはUTCで全日を生成しpost_count/Engagement/平均/ER内訳を返す。0投稿はpost_count=0・Engagement=NULL、指標不明投稿ありはpost_count>0・Engagement=NULL。グラフはNULLを補間せず、日別表で0投稿と指標不明を区別する。Media Type Performanceは実在形式とNULLカテゴリ別に投稿数・平均Engagement・ER内訳を表示。

一覧はpage=1、page_size=20（最大100）、posted_at DESC既定。sortはposted_at/reach/likes/comments/shares/saves/engagement/engagement_rate、order asc/descのEnum。NULL末尾、同値はpost_id DESCで安定。Drawerは全文、latest metrics、分母、関連Topic（Inactiveも明示）、期間内比較。同条件内・同Platform・同分母でERの高い順、同率同順位。vs_average_rate=(対象ER−同cohort平均ER)÷平均ER×100。ER不明・対象範囲外・平均0では比較NULL。total_postsは検索対象全数、comparable_postsは比較可能数。

## Transaction / 性能

GETはREPEATABLE READ・postgresql_readonly=Trueで一貫したSnapshotを読む。最新指標・Account・Topicは一括QueryでN+1を回避。1000投稿の検証でAnalyticsのSELECT最大4、List最大3、書込みSQLなし、DB設定read-only on/repeatable readを確認。

現状はDBでProject/OWN/Platform/日付/媒体を絞った候補をPythonへ読み、Unicode検索・集計・ソート・ページ分割を行う。大量履歴ではメモリ・応答時間が増えるため、将来の性能PhaseでSQL集計/検索/ページネーション最適化を検討する。固定時間の性能保証・大規模負荷試験は未実施。Index/Migrationは追加していない。

## 検証

| 確認 | 実測結果 |
| --- | --- |
| 作業前既存Test | 556 passed、Failed 0 / Skipped 0、32.63秒 |
| 新規 `tests/my_account` | 96 passed、Failed 0 / Skipped 0、10.43秒 |
| 全Backend Test | 652 passed、Failed 0 / Skipped 0、143.72秒 |
| Frontend `npm run typecheck` | 成功（最終UTC表示変更後も再実行） |
| Frontend `npm run build` | Docker build内で成功、8静的ページ生成 |
| Backend Docker build | 成功 |
| Compose | db/backend healthy、frontend稼働 |
| Health | HTTP200、database connected |
| Alembic current / heads | 両方0001_initial (head) |
| OpenAPI | 新規3 GET path・Response Schemaを掲載 |
| 残存使い捨てTest DB | 0 |

テストは専用 `sns_phase2_test_<UUID>` DBを作成/破棄する既存仕組みを再利用。通常開発DBを削除しない。NULL/0/部分NULL/指標なし/複数Snapshot/分母優先/異なるER基準/丸め/UTC境界/Inactive/Platform解除/Keyword/Hashtag/Media/複合条件/ページ/8種ソート両方向/同順位/Followers日付/Project分離/入力エラー/SQL秘匿/1000件Query数を検証。既存Provider/Import/Matching/Trend/Settingsを含む556件にも回帰なし。

既存のStarlette TestClient/httpx DeprecationWarningが1件。npm更新案内・Git改行警告は失敗ではない。

## Browser確認

最終Docker環境のIn-app Browserで実API接続を確認。専用架空Project `Phase7 Browser Verification` にOWN_POSTS 28件（X25/Instagram3）、ACCOUNT_DAILY 2件を既存CSV APIで取り込み、どちらもSUCCESS、error_count=0。開発DBに検証Projectを保持している。これは外部SNSの実データではない。

確認した操作: Project切替（検証28件→Phase6の期間内0件）、3日UTC範囲、KPI Posts28/Reach24000/Impressions56000/Engagement864/平均30.8571、複数ER基準の内訳、Followers1200/850別表示、日次Chart・媒体別表、20件→2ページ目8件、likes昇順、X+IMAGE+全角Keyword+Hashtag複合検索5件、存在しないKeywordのEmpty、不正HashtagのError/再読込ボタン、Drawer全文・指標・平均比・順位・関連Topic、Close/Escape。

投稿・Recorded AtはUTCを明示。画面証跡を同フォルダへ保存する。全ブラウザ/モバイル/DPI、未取得指標だけのChartの直接GUI、大規模通信競合の直接GUIは未検証（該当計算/APIはBackend Testで確認）。Loading状態を実画面で観測。

## 正本との差異・既知課題

- 正本 `/dashboard/account` とPhase7指示 `/dashboard/my-account` は両方実装して整合。
- ER/Followerの単一数字が不適切になる混在時はNULL+内訳。既存Response項目を維持し、内訳・平均Engagement・比較母数・timezone等を補足した。
- 正本の概略wireframeにある前期比KPIカードは今回のPhase7 API契約・作業対象で定義されていないため追加していない。Drawerの期間内平均比を実装した。
- 詳細の比較基準は正本で細部未定義のため、現在の検索範囲内・同Platform・同分母ERと明記。期間を勝手に推測しない。
- 大量候補のPython集計・入力上限・上記直接GUI未検証が残る。重大な未解決不具合は今回の検証では検出していない。

## Git / Push / Review ZIP

開始HEAD: `54823e10a4be9e5753f13669c51dbed935fe00fe`、master、Working Tree clean。実装Commit: `80ce88f74fa24b208507d20f6b3f94796e768897`（feat: complete Phase 7 my account analytics）。本行を報告書追記Commitとして保存する。Remoteは未設定のため追加せずPush未実施。

すべての追記・Commit後、Repository Rootで最後に `git archive --format=zip HEAD -o ../SNS_Analyzer_Phase7.zip` を実行する。ZIP生成後はtracked fileを変更しない。存在・CRC・Backend/Frontend/Test/README/本報告書・禁止ファイル非混入・ZIP commentと最終HEADの一致を検証し、実測結果と最終HEADは最終回答で報告する（本書への生成後追記は禁止のため）。
