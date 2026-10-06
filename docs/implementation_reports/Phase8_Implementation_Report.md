# Phase 8 Trend Explorer 実装報告書

実装日: 2026-10-03。対象: Phase 8のみ。Phase 9以降は実装しない。

## 実装概要と参照

基本設計・画面設計・API設計・DB詳細設計Ver1.1、Phase計画Ver1.0を確認し、未定義部分をPhase8指示書で補った。Trend Ranking、複数Term Timeseries比較、Popular PostsをBackendへ実接続。Route `/dashboard/trends` / `/trends`。My Account、Settings / Import、接続確認から導線を追加した。大規模Layout変更は行わない。

## 新規・変更ファイル

- Backend新規: `app/api/v1/trends.py`, `app/schemas/trends.py`, `app/repositories/trend_explorer_repository.py`, `app/services/trend_explorer_service.py`。
- Backend新規Test: `tests/trend_explorer/__init__.py`, `conftest.py`, `test_api.py`。
- Frontend新規: `src/lib/trends-api.ts`, `src/components/trend-explorer.tsx`, `src/app/dashboard/trends/page.tsx`, `src/app/trends/page.tsx`。
- 既存変更: `backend/app/main.py` Router登録、Frontendの `src/app/page.tsx`, `src/components/my-account.tsx`, `src/components/settings.tsx` のリンクのみ、README。
- 本報告書とBrowser確認画像を追加。

Provider/Normalizer/Import/Matching/Rematch/Trend Engine/DBモデル/制約/Migrationの変更なし。

## APIとFilter

prefix `/api/v1/projects/{project_id}`。3 APIともGET、Pydantic Response Modelとtyped Queryを定義。

| Path | Query / Response |
| --- | --- |
| `/trends/ranking` | topic_id必須、platform/from/to/keyword/limit。score_window_days=7、score_as_of、items |
| `/trends/timeseries` | term_ids必須（カンマ区切りUUID1〜5件・重複不可）、platform/from/to/metric、補助keyword。metric/timezone/series |
| `/trends/{topic_id}/top-posts` | platform/from/to/limit、optional term_id、補助keyword。items |

from/toは両方必須、UTC両端inclusive、最大3660日。platform ALL/X/INSTAGRAM、ALLは現在のProjectPlatform。Keyword最大1000文字、Term表示値をNFKC/trim/casefoldでリテラル部分一致（%/_は文字）。保存値変更なし。空白KeywordはFilterなし。

有効Topic/TermのみRanking/Timeseriesへ使用。Topic候補は既存Settings APIから同Project・Activeのみ。Inactive Project自体の過去分析は許容。Project不存在・他Project Topic/Term・指定Topic外Term・Inactive指定は404。Validation422、期間逆転/超過400、内部障害500。SettingsRouteの安全なerror/code/message/detailsを再利用し、入力・SQL・Secret・Stack TraceをResponseへ出さない。

## Ranking

trend_dailyのwindow_days=7、term_id非NULLを読む。WatchTerm.term_idとtopic_id双方、WatchTopic.project_idをJoin条件に含め、不整合なTopic/Term関係も除外。期間内の各Term・Platform別row_number(trend_date DESC)=1で一括取得する。複数日のpost_count/Growth/Scoreを合計・平均しない。

並び順: trend_score DESC NULLS LAST → 保存Term文字列 ASC → term_id ASC → Platform ASC（同Termで複数SNSが同値の場合の追加安定順）。limit既定20/最大100。score_as_ofはlimit適用前の対象最新日付、各行にもtrend_dateを返して異なる日付を隠さない。ALLでSNS同士の合算・平均なし。

Directionは正本に厳密式がないため、指示書Fallbackを採用: 保存post_growth_rate>0 UP、=0 FLAT、<0 DOWN、NULL UNKNOWN。表示用派生値のみ。Trend Score/Growth/Acceleration/Component Scoreは保存値をそのまま返し、計算Engine呼出し・保存値書換えなし。

## Timeseries

複数Termを一括取得し、同Project・Active Topic/Termを検証する。post_count→保存post_count、engagement→保存engagement_count、trend_score→保存trend_score。再計算しない。Term・PlatformごとにUTC全日軸を返し、行なしはvalue=NULL/row_present=false、行ありは保存値/row_present=true。行あり0、Score NULL、行なしを区別する。

正本のterm_ids、term_nameを維持。topic_id/topic_name/term/term_type/platform、metric/timezone/row_presentを補足。1〜5Term、ALLの場合は最大10series（各SNS別）となる。Recharts凡例・Tooltip・Metric切替・connectNulls=false、表で欠測/算出不能/実値を表示。全Score NULL時は算出不能メッセージを表示する。

Keywordは比較対象Termにも適用する。指定Term自体のスコープを検証してからKeywordを絞り込むため、他ProjectのTermをKeywordで隠して200にしない。

## Popular Posts

同Project・MARKET・有効Platform・UTC投稿日時範囲・PostTopic一致が必須。optional term_idは選択Topic配下のActive Termを検証してPostTerm一致も必須にする。Keyword使用時は一致TermのPostTermへ絞る。Topic/Term Matchの重複で投稿を重複させないEXISTS Query。

対象投稿とMetricのWindow QueryはMATERIALIZED CTEで一度ずつ確定し、重複評価を避ける。Window Functionで最新recorded_atのPostMetricを一括外部結合。Phase7の投稿指標組立てを再利用し、EngagementはPhase5の共通関数でlikes+comments+shares+savesの既知値合計。全NULL→NULL、部分NULL→既知値合計、実値0→0、指標なし投稿もNULLで保持。古いSnapshot非NULLで最新NULLを補完しない。

Engagement DESC NULLS LAST → posted_at DESC → post_id ASC、limit既定10/最大50。Trend Scoreを投稿順位に転用しない。本文はReactで文字として省略表示・titleに全文、安全なHTTP/HTTPS permalinkのみ外部リンク。Views/反応/Engagement/UTC日時を表示し、Drawerの過剰複製はしない。

## Read Only / Query数 / 性能

MyAccountServiceの既存read Transactionを再利用しREPEATABLE READ・postgresql_readonly=True。読み取りからINSERT/UPDATE/DELETE/COMMITなし。SQLによるProject/Topic/Term/Snapshot検証とWindow Queryを一括化。

使い捨てDBに1000Trend Snapshot（5Term×200日）と1000MARKET Post/Metric/Matchを投入して、Ranking SELECT最大5、Timeseries最大4、Popular Posts最大5を確認。Term数・投稿数に比例するSELECT増加なし。Transaction read_only=on、isolation=repeatable readも確認。

Ranking候補・Popular Postsは候補を一括でPythonへ読み、Unicode Filter/ソート/limitを適用する。候補が大量ならメモリ・時間増加の余地あり。Timeseriesは最大3660日×5Term×2SNSへ制限する。固定秒数保証・大規模負荷試験は未実施、SQL最適化はPhase13候補。Schema/Index/Migration追加なし。

## 正本との差分と判断

- API正本にはRanking「to以下の最新」、画面正本には「指定期間内の最新」と表現差がある。画面正本とPhase8の詳細契約に合わせfrom≤trend_date≤toの最新とした。期間前の古い行へフォールバックしない。
- 正本はTerm分析なのでtopic_idsを導入せずterm_idsへ統一。カンマ区切りをOpenAPI/Frontend/Testで共通化した。
- Direction、Active制御、Ranking安定Sort、Popular Sort、入力上限は詳細未定義のため指示書Fallback。表示・Responseで明記。
- 正本のResponse例の基本項目を維持し、NULL判別・SNS粒度・Snapshot日付等を補足した。ALL時の値は集約せずSNS別に保持。5Termから最大10線になることを画面に明記。
- Popular/Timeseriesにoptional keywordを補い、画面の共通KeywordをTerm Matchへ連動。本文の再MatchingやTrend計算を行わない。
- Loadingは正本に合わせSkeleton＋状態表示。Error/Empty/再取得・古い応答破棄を各Sectionで実装。

## 検証結果

| 確認 | 結果 |
| --- | --- |
| 作業前既存Test | 652 passed、Failed 0 / Skipped 0、46.22秒 |
| Phase8新規Test | 53 passed、Failed 0 / Skipped 0、7.70秒（最終CTE変更後の再実行） |
| 最終全Backend Test | 705 passed（既存652＋新規53）、Failed 0 / Skipped 0、53.36秒 |
| npm run typecheck | 成功（Docker Node22使用） |
| npm run build | 成功、10静的ページ生成 |
| Docker backend/frontend build | 両方成功 |
| Health | HTTP200、database connected |
| Alembic current / heads | 0001_initial (head)、変更なし |
| OpenAPI | 3 GET path・Query/Response掲載確認 |
| Compose | db/backend healthy、frontend稼働 |
| 残存使い捨てTest DB | 0 |

テスト内容: Term粒度/Topic行除外/最新Snapshot/期間/安定Sort/NULL/0/Direction/Keyword/Platform/Inactive/UTC/複数Term/全Metric/最新PostMetric/MARKET限定/Topic・Term Match/Project分離/不整合Trend行/入力400・404・422/Secret秘匿/read-only/1000件Query数。既存652件も全成功。初回全Testで新規Project分離テストの別Project後片付け不足が既存Import Test3件へ影響したため、finallyで専用テストProjectを削除するよう修正し、全件再実行して成功した。通常開発DBへの影響はない。既存Starlette TestClient/httpx DeprecationWarning1件は非失敗。npm更新案内・Git改行警告も非失敗。

## Browser確認

最終Docker環境・In-app Browser・実Backend APIで検証。専用架空Project `Phase8 Browser Verification`、Topic「生成AI市場」配下ChatGPT/Claude/AIエージェント/#生成AI、有効X/Instagram、30日間のMARKET CSV168件。既存Import APIでSUCCESS、success_count168/error_count0。開発DBに検証Projectを保持している（外部SNS実データではない）。

Project/Topic切替、ALL→X→Instagram、7日Preset、30日期間、全角Keyword複合検索、Ranking8行のPlatform分離、ChatGPT Score80/Post Count18/UP、Claude9.69/DOWN、複数Term比較と凡例、Post Count/Engagement/Trend Score切替、Popular Term絞り込み、Popular Engagement降順、Keywordの全Section連動を実画面で確認。Empty・Loading Skeleton・期間上限Errorと各再読込ボタンを確認。未観測Termの保存済み0とScore/Growth NULLを確認。

Browser証跡を本フォルダへ保存。任意日付はURL条件で確認（日付フィールドの直接fill操作は反映せず、PresetとURLで検証）、全ブラウザ/モバイル/DPI・大規模競合通信は直接GUI未検証。入力・UTC・NULL・Project保護はBackend Testで確認。

## Git / Push / Review ZIP

開始: master、HEAD `e6d06276c0118f917a7f3e0aeef918be25f2796c`、Working Tree clean。実装Commit: `e38067fce06538f3eb3d33f47121686e0645463e`（feat: complete Phase 8 trend explorer）。本行を報告書追記Commitとして保存する。Remote未設定のため追加せずPush未実施。報告書Commit自身のHash・最終HEADは最終回答に記載する。

全実装・検証・追記・Commit後にRepository Rootで最後に `git archive --format=zip HEAD -o ../SNS_Analyzer_Phase8.zip` を実行。生成後trackedファイルを変更・Commitしない。ZIP存在/CRC/Backend/Frontend/Tests/README/本報告書/禁止物非混入/comment最終HEAD一致を検証し、実測値・最終HEADは最終回答で報告する（本書への生成後追記は禁止のため）。
