# Phase 10 Implementation Report — Gap Analysis

実装日: 2026-10-03 / 対象: Phase10。市場Trendと自社CoverageをTopic × SNSで比較するAPI・散布図・表を実装し、既存781＋新規60＝841 Test成功（Failed 0 / Skipped 0）。Phase11 Overview・Phase12 AI Insightsへ進まない。

## 正本確認

デスクトップ側の同名プロジェクト資料から、実装前に以下5文書を全文確認した。

- SNS_Trend_Performance_Analyzer_基本設計書_Ver1.1.md
- SNS_Trend_Performance_Analyzer_画面設計書_Ver1.1.md
- SNS_Trend_Performance_Analyzer_API設計書_Ver1.1.md
- SNS_Trend_Performance_Analyzer_DB詳細設計書_Ver1.1.md
- SNS_Trend_Performance_Analyzer_Codex_Phase計画_Ver1.0.md

指示書はSNS_Trend_Performance_Analyzer_Codex_Phase10_実装指示書.md。正本優先、詳細未定義部分のみ指示書Fallbackを採用。基本・画面設計の主Route `/dashboard/gap`、APIのGET `/gap-analysis`、DB詳細25節のOwn/Competitor RatioとGap式、4分類、Phase計画の対象を確認。分類の数値閾値は正本に指定なし。

## API / データの粒度

`GET /api/v1/projects/{project_id}/gap-analysis`。必須日付from/to、platform=ALL（既定）/X/INSTAGRAM。UTC両端inclusive、最大3660日。期間逆転/上限超過400、未知Project/Projectで無効なSNS404、UUID/日付/enum形式・必須日付欠落422。SettingsRouteと既存エラー処理を再利用し、内部障害500はANALYTICS_ERROR汎用文言。SQL・DB URL・Secret・Stack Trace・内部Pathを応答へ出さない。

Pydantic GapAnalysis/GapItemによるTyped Response。timezone/from/to/score_window_days=7/trend_threshold/own_ratio_threshold/items。各Itemはtopic_id/name、platform、trend_date/score、OWN/競合のmatched/total/ratio、gap_score、nullable Classification enum。不要な投稿本文・Metric・候補リストは返さない。

Active WatchTopic × ProjectのEnabled Platformが粒度。ALLでもTopic × X / Topic × Instagramを保持し、SNS間の合算・平均なし。Topicが存在すればTrendがなくても応答へ保持。Inactive Topic除外。PostTerms・Term RankingをTopicへ流用しない。

## Trend Snapshot / Ratio / Gap

TrendDailyのTopic行、term_id IS NULL、window_days=7、ProjectのActive Topic、有効SNS、from≤trend_date≤toに限定。ROW_NUMBERのTopic/SNS別trend_date降順で最新1件。保存済みMARKET由来Phase5結果をそのまま使い、期間SUM/AVG・再正規化・古い非NULL補完・Trend再計算なし。

| 指標 | 式・対象 |
| --- | --- |
| Own Post Ratio (%) | TopicにMatchしたDistinct OWN Post ÷ 期間内同Project/SNSの整合するOWN全Post ×100 |
| Competitor Post Ratio (%) | TopicにMatchしたDistinct Active COMPETITOR Post ÷ 期間内同Project/SNSの全Active COMPETITOR Post ×100 |
| Gap Score | Trend Score × (1 − Own Post Ratio /100) |

PostTopicのKEYWORD/HASHTAG/MANUAL/AIすべての既存Relationを使用。COUNT(DISTINCT post_id)で同一Topic複数Match Typeを二重計上しない。本文再Matchingなし。Topic間の重複は許容するためRatio合計は100%超があり得る。分母はMatch有無・PostMetric有無を問わない期間内投稿数。

SNSPost.account_id/project/platform/sourceとSNSAccount.account_id/project/platform/roleの一致を検証し、Accountなし、不整合legacy、別Project、MARKETをRatioから除外。PostTopic.topic_idだけを信用せず、Topic自身のProject/Active条件を検証する。OWNのActive制限は正本・指示書に明示されていないため、Phase7同様、整合するInactive OWN Accountの過去投稿も含める解釈を採用し専用Testを追加。COMPETITORは指示書通りActiveのみ。

正本に競合選択Queryの指定がないため、同Project/SNSのActive COMPETITOR全件を集約。Account別Ratioの単純平均ではなく、全matched / 全postsによるpost-weighted Ratio。競合比率は参考表示で、Gap Score式には影響させない。

Trendは期間内最新7-day Rolling Snapshot、投稿Ratioは指定期間全体というVersion1の比較を画面/READMEへ明記。BackendでDecimal precision50のRatio/Gap計算、丸め前値で分類・Sort、既存number/RAW_QUANTUM 4桁HALF_UPでJSON表示。49.999999%が表示50%に丸まっても分類は丸め前値を使う境界Testあり。Frontendは値の表示とNULL座標除外だけを行う。

## Classification / NULL / Sort

Service定数TREND_THRESHOLD=50、OWN_RATIO_THRESHOLD=50は正本未定義のため指示書Fallback。

| Classification | 条件 |
| --- | --- |
| OPPORTUNITY | Trend≥50 AND Own<50% |
| BALANCED | Trend≥50 AND Own≥50% |
| HIGH_COVERAGE | Trend<50 AND Own≥50% |
| LOW_PRIORITY | Trend<50 AND Own<50% |

総投稿0→Ratio NULL。一致0/総投稿>0→Ratio実値0%。Trend/Own RatioのいずれかNULL→Gap/Classification NULL。競合Ratio NULLだけではGapをNULLにしない。Snapshotなし→trend_dateもNULL、最新SnapshotのScore NULL→その基準日を保持しScore NULL。未知値を0へ補完しない。

SortはGap Score DESC NULLS LAST→topic_name ASC→platform ASC→topic_id ASC。全ItemをBackendで安定Sort。NULL Itemを末尾の表へ保持し「算出不可」、数値NULLは「—」、実値0は0。座標に必要なTrend/Own NULLは散布図から除外し(0,0)へ置かない。

## Frontend / 状態制御

正本の `/dashboard/gap` を主Route。指示書主Route `/dashboard/gap-analysis` と `/gap-analysis` を互換入口とする。既存My Account/Trend Explorer/Competitor/Settings/接続状態へGapナビを追加しただけで共通Layout大規模改修なし。

Project・Platform・7/30/90日・任意UTC日付。PresetはUTC今日からinclusive日数。Platform/Periodは検索でScatterとTableへ同時適用しURLへ保存。Project切替はkeyによるUnmount/新取得。既存sns-project選択記憶を共有。無効SNS選択肢をdisabledにする。各取得でdataをクリア、version tokenとUnmount invalidationで古い応答を破棄。Loading Skeleton、Error/再読み込み・再取得、Empty/Settings Import導線を実装。

Recharts ScatterChart、X=Own Post Ratio 0〜100%、Y=Trend Score 0〜100。ReferenceLine x/y50、ReferenceArea左上X<50/Y≥50のOpportunity Zone、分類色、●X/◆Instagram、4分類凡例。TooltipはTopic/SNS/Trend/Trend Date/Own Ratio/競合Ratio/Gap/Classification。React keyはTopic UUID＋SNS。同座標の別SNS Pointは重なることがあり、SNSフィルター/表で別Itemを確認できる。位置をずらして指標を改変しない。

TableはTopic/SNS/Trendと基準日/Own比率とmatched-total/競合比率とmatched-total/Gap/Classificationを同一Responseで表示。Snapshotなしの基準日は市場Trendデータなし。市場ScoreのみNULLの場合は基準日と「—」を表示。完全Topic Emptyと算出不可Topic保持を分ける。

## Read Only / Query数

MyAccountService.readを再利用。Project検証から全QueryがREPEATABLE READ・postgresql_readonly=Trueの同一Snapshot。Read APIからINSERT/UPDATE/DELETE/COMMIT・Rematch・Trend Rebuildを呼ばない。

固定6 SELECT/WITH: Project、Platform、Topics、最新Topic Snapshot、Platform/Role別Distinct total、Topic/Platform/Role別Distinct matched。スコープ投稿MATERIALIZED CTEとSQL GROUP BYで一括集計、N+1なし。Pythonへ投稿全件を読み込まず、Topic/SNS別Snapshotと集計行だけを読み分類・Sortする。

使い捨てPostgreSQLで1000 OWN＋1000 COMPETITOR、Active競合4 Account、100 Topic、X/Instagram、4000 PostTopic Relation、200 Snapshotを投入。小データ/大データ双方6 Query、不変。Response200 Item、各SNSの各Role総投稿500、matched合計4000、read_only=on/isolation=repeatable read、書込みStatementなしを確認。SHOW2文は検証用でSELECT/WITH件数に含めない。固定秒数SLA・大量本番負荷は未検証。DB/Index/Migration変更なし。

## 正本との差分 / Fallback採用

- Routeは正本 `/dashboard/gap` を優先、指示書Pathをaliasで維持。APIPath・基本項目・Ratio式・Gap式・4分類は正本通り。
- Latest期間内7-day Topic Snapshot、Active Topicの全件保持、Trendなし/NULL分類、ALLのTopic×SNS分離、UTC上限3660日、Distinct分子/全期間分母、0分母NULL、全Match Type、Active競合全体Scopeと投稿数加重、安定Sortは詳細未定義箇所に指示書Fallbackを採用。
- Classification50/50、NULL→分類NULL、Opportunity ZoneはFallback。数値閾値をService定数とResponse/Frontend/README/Testへ明示。
- OWN Inactive履歴保持は既存Phase7と指示書OWN全投稿に合わせた解釈。競合Active制限と混同しない。
- Responseへtrend_date・matched/total・UTC/from/to・score_window_days・閾値を補足。Competitor個別選択・Overview・AI API・新Derived Tableを追加しない。
- 既存ファイルの変更はAPI Router登録とナビのみ。Provider/CSV Import/Matching/Rematch/Trend Engine/Settings/My Account/Trend Explorer/Competitorの既存分析ロジック・DB Schema/Constraints/Migrationは変更していない。既存Testの削除・Skip・Assertion弱体化なし。

## 検証結果

| 確認 | 結果 |
| --- | --- |
| 作業前既存Backend Test | 781 passed、Failed 0 / Skipped 0、67.01秒 |
| Phase10新規Test | 60 passed、Failed 0 / Skipped 0、9.34秒 |
| 最終Backend全Test | 841 passed（既存781＋新規60）、Failed 0 / Skipped 0、92.95秒 |
| npm run typecheck | 成功、Docker Node22で実施 |
| npm run build | 成功、15静的Route生成 |
| Docker backend/frontend build・up | 両方成功、db/backend Healthy、frontend稼働 |
| Health | HTTP200、status ok / database connected |
| Alembic current / heads | 0001_initial (head)、追加Migrationなし |
| OpenAPI | GET Gap API・必須from/to・platform enum・UUID・GapAnalysis Typed Response掲載 |
| 全Test後使い捨てDB | 残存0 |
| git diff --check | 成功 |

TestはTopicのみ/Term除外/期間Latest/NULL/0/Active、X/Instagram/ALL分離、全Match方式/Distinct/重複Topic100%超、OWN履歴、競合Active/投稿数加重、異常Role/Project/Platform/Account隔離、UTC最小/最大日境界、Gap数値例、4分類50境界、丸め前分類、安定Sort/NULL末尾、400/404/422/安全500、2000投稿固定Query/read-onlyを含む。Starlette TestClient/httpx既存DeprecationWarning1件は非失敗。Git LF→CRLF警告は既存Windows改行設定によるもの。

## Browser確認 / 証跡 / 既知の限界

最終Composeの実Backend/APIとIn-app Browserを使用。架空Project `Phase10 Browser Verification`（4509740f-2a16-49a8-aab2-0b482ea946ce）に既存Settings APIでOWN X/Instagram各1件、COMPETITOR X/Instagram各1件、Topic5＋未観測Topicを作成。OWN_POSTS20、COMPETITOR_POSTS40、MARKET_POSTS886を既存CSV Importで投入し、すべてSUCCESS/errors0。市場Snapshotは既存Trend Engineの計算結果で、手動Score固定のMockではない。未観測Topic作成時には既存SettingsのRematch/Trend更新が走り、2026-10-03のNULL Score Snapshotが存在する。Gap Read APIは更新しない。

2026-09-04〜10-03では各SNSで以下の実結果を確認した。

| Topic | Trend | Own% | Competitor% | Gap | Classification |
| --- | ---: | ---: | ---: | ---: | --- |
| OpportunityAI | 100 | 10 | 50 | 90 | OPPORTUNITY |
| BalancedAI | 63.79 | 70 | 25 | 19.137 | BALANCED |
| LowAI | 9.05 | 10 | 0 | 8.145 | LOW_PRIORITY |
| CoverageAI | 0 | 70 | 10 | 0 | HIGH_COVERAGE |
| ZeroAI | 0 | 0 | 0 | 0 | LOW_PRIORITY |
| 未観測Topic | NULL | 0 | 0 | NULL | NULL/算出不可 |

ALL12表行、10有効座標/2算出不可。左右上下4領域と凡例、SNS別Point/行、Gap降順、NULL末尾、0座標を確認。デモではSNSの値が同一なので別Pointの座標が重なる。Xのみ6行、Instagramのみ6行、7日/90日/30日Presetと各UTC from/to、キーボードArrowRightによるBalancedAI/X Tooltipの全項目、Loading、期間上限Error両Section/再読み込み/30日正常復帰を確認した。

任意期間2026-10-01〜03をURL条件で確認。2026-10-04〜05ではSnapshot/投稿なし、12 Item保持、Ratio/Trend/Gap NULL、0/0件数、散布図なし、全表行算出不可を確認。架空Empty Project `Phase10 Empty Verification`（fd1abd8c-0d9f-440c-8008-5c4604d45a1e、Xのみ、Topicなし）へProject切替し、旧結果クリア、Instagram無効、Empty/Settings導線と元Project復帰を確認。

- [4分類・Opportunity Zone・ALL・NULL/0](Phase10_Browser_Gap.jpg)
- [Tooltip](Phase10_Browser_Tooltip.jpg)
- [Snapshot/投稿なしのNULL保持](Phase10_Browser_NULL.jpg)
- [期間上限Error](Phase10_Browser_Error.jpg)
- [Empty Project](Phase10_Browser_Empty.jpg)

日付inputへの自動fillはDOM表示値だけ変わりReact検索条件の更新を確認できなかった。Preset・URL条件で任意期間の実結果を検証し、原因を推測して変更していない。手動カレンダー/キーボード日付入力、全Browser/モバイル/DPI、遅延応答競合を意図的に作るE2E、実SNSデータ、大規模本番負荷は未検証。旧応答破棄はコードで実装し、通常の条件/Project切替を画面で確認。架空Import履歴/デモデータを開発DBに保持する。Review ZIPはソースと証跡でありDBデータを含まない。

## 変更ファイル

| 分野 | ファイル |
| --- | --- |
| Backend新規 | backend/app/api/v1/gap_analysis.py、repositories/gap_analysis_repository.py、schemas/gap_analysis.py、services/gap_analysis_service.py |
| Backend登録 | backend/app/main.py |
| Test新規 | backend/tests/gap_analysis/__init__.py、conftest.py、test_calculation.py、test_api.py |
| Frontend新規 | frontend/src/lib/gap-analysis-api.ts、components/gap-analysis.tsx、app/dashboard/gap/page.tsx、app/dashboard/gap-analysis/page.tsx、app/gap-analysis/page.tsx |
| ナビ追加 | frontend/src/app/page.tsx、components/my-account.tsx、trend-explorer.tsx、competitor.tsx、settings.tsx |
| Docs | README.md、本報告書、Phase10_Browser_Gap/Tooltip/NULL/Error/Empty.jpg |

## Git / Push / Review ZIP

開始master、Working Tree clean、Phase9最終HEAD `ff7a6781043ea364bc1c55f6328f72132f6a3ffc`。実装Commit `7875c0f86c237b49f7a6eb640635ab524ccd4272`（feat: complete Phase 10 gap analysis）に実装・検証・Docs計26ファイルを保存。このHash追記を報告書Commitとする。最初のcommit試行はindex書込みエラーで作成されず、HEAD/Stage/lockなし/空き容量を確認して再試行し成功した。Remote未設定のためRemote追加/Pushなし。報告書Commit自身のHashと最終HEADは最終回答に記載する。

全作業・Test・Docs・Commit完了後の最後の生成工程で、Repository Rootから `git archive --format=zip HEAD -o ../SNS_Analyzer_Phase10.zip` を実行する。生成後trackedファイル変更/Commitをしない。存在/CRC/必須Backend・Frontend・Tests・README・本書/禁止物非混入/ZIP comment最終HEAD/全HEADファイル内容一致を検証し、実測結果を最終回答へ記載する。Windows Git archiveのCRLF変換は既存core.autocrlf設定の範囲で内容比較する。ZIP検証結果を生成後の本書へ追記しない。Phase6〜9の既存ZIPを変更しない。
