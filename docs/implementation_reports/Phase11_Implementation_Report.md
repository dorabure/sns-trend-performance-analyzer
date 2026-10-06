# Phase 11 Implementation Report — Overview

実装日: 2026-10-03（Asia/Tokyo）。対象: Phase11のみ。Phase12 AI Insights生成は実装していない。

## 正本確認

作業開始時に添付Phase11指示書と、同じ資料フォルダーにある以下の全文を確認した。

- SNS_Trend_Performance_Analyzer_基本設計書_Ver1.1.md
- SNS_Trend_Performance_Analyzer_画面設計書_Ver1.1.md
- SNS_Trend_Performance_Analyzer_API設計書_Ver1.1.md
- SNS_Trend_Performance_Analyzer_DB詳細設計書_Ver1.1.md
- SNS_Trend_Performance_Analyzer_Codex_Phase計画_Ver1.0.md

正本のOverview Route `/dashboard`、Overview API、KPI、4種類のPerformance Trend、Top5、競合比較、最大機会1件、最新AI概要を実装。正本APIのResponse例は指示書Fallbackと名称/形が異なるため、正本の `period` / `kpis.reach.value` / `engagement_rate.value` / `followers.value` / `posts.value` / `top_trends` / `competitor_summary` / `top_opportunity` / `ai_summary` を優先した。指示書Fallbackの `trending_topics` / `opportunity` には置き換えていない。

正本の前期間比較も実装した。直前の同日数期間、Reach/Followers等のchange_rate、ERのchange_point、PostsのchangeをBackendで返す。画面設計書の追加可能KPIと基本設計書に合わせImpressions/Engagementも表示する。正本APIにあるPerformance Trend独立GETも追加し、Overview本体への組み込みを主経路とした。Frontendは1 Overview APIで全分析Sectionを取得する。

DB/API設計書のCOALESCE Engagement例は全NULL時の扱いが基本設計書/DB NULL方針/確定済みPhase5〜9と異なり得る。既存共通calculate_engagementと既知値合計をそのまま再利用し、全NULLをNULLとする既存公開仕様を維持した。Schema/Constraints/Migration変更なし。

## API / Frontend Route

```text
GET /api/v1/projects/{project_id}/dashboard/overview
GET /api/v1/projects/{project_id}/dashboard/performance-trend
```

Query: UUID project_id、platform=ALL/X/INSTAGRAM（default ALL）、必須from/to（date）。Performance Trend独立APIのみ必須metric=reach/engagement/followers/postsを追加。

Pydantic `Overview` / `MetricTrend` Typed Response。AI本文は `JsonValue` で将来のJSON構造を保持し、Response全体を自由dictにしていない。Overviewへtimezone=UTC、previous_period、performance_trend、own_summary、competitor_aggregate、Rate Groups、Account別Followersを追加。正本competitor_summaryはArrayのまま最大3 Accountにし、自社/全競合集約を別のTyped Objectで返す。

Route: `/dashboard`（正本）。`/dashboard/overview`、`/overview` は互換入口。既存接続確認 `/` と既存分析Routeを維持。既存各画面へOverview導線を追加、共有フィルターはplatform/from/toだけをURLで持ち込み、画面固有フィルターはOverviewへ渡さない。ProjectはlocalStorage `sns-project`。正本AI画面のRouteはPhase12まで未実装のためリンクを出さない。大規模Layout/Design System整理なし。

## KPI / Performance Trend / Followers

Phase7 `MyAccountService.item` / `kpis` / `aggregate`、既存Latest PostMetric Window Query、Followers最新Queryを再利用。KPIは期間内OWN投稿のみ。COMPETITOR/MARKET除外、Inactive OWNの過去投稿は残す。Project/有効SNS/UTC投稿時刻を適用。Latest PostMetricの時刻自体を選択投稿期間に制限せず、既存Phase7同様、投稿ごとの最新1件を使う。

Reach/Impressions/Engagementは既知値のみ合計、全NULLはNULL、実値0は0。EngagementはLikes+Comments+Shares+Savesの既知値合計。RateはReach→Impressions→Viewsの最初の非NULL分母。選ばれた分母0ならNULLで、次分母へ移らない。Rate GroupはPlatform+Denominator Type単位、単一Cohortだけ単一ERを表示する。異なるSNSも単一ERへ混ぜない。

FollowersはActive OWNごとにrecorded_date<=toの最新値。Latest NULLを過去既知値で置き換えず、未来Snapshotを使わない。複数Accountならfollowers.value=NULL＋followers_by_account。単一Accountだけ値を表示する。

比較期間は直前の同日数期間。Current/Previous投稿を同一Bulk Queryで読み、共通KPI関数に分離して渡す。前期間0/NULLのchange_rateはNULL。ERのchange_pointは両期間の単一SNS/分母Cohortが一致する場合だけ計算。Followersの単一値比較はAccount ID一致を確認する。date.min付近で完全な比較期間を作れない場合はprevious_period/previous_value=NULLとし、期間を勝手に短縮しない。

Performance TrendはBackendで全日付を作る。OWN投稿日UTC別にPosts、Latest Reach、共通Engagementを集計。0投稿日はPosts=0、Reach/Engagement=NULL。投稿あり全指標NULLの日もNULL。Frontendは表示用整形のみで合計/日付補完をしない。

Followers TrendはAccount別Series。AccountMetric recorded_date当日だけ値、欠測はNULL・row_present=false、Snapshot実値NULLはNULL・row_present=true。Carry Forward/0補間なし。Recharts connectNulls=false、単独観測もdotで表示する。Metric切替はReach/Engagement/Followers/Posts。

## Trending Topics / Competitor / Opportunity / AI

Trending TopicsはActive Topic×SNS、term_id NULL、window_days=7、from<=trend_date<=toの最大日Snapshot。ROW_NUMBERで一括取得。NULL Scoreを最新選択後に除外するため、最新NULLから過去有効Scoreへ戻らない。保存Scoreを再計算/SUM/AVGしない。Trend Score DESC→topic_name ASC→platform ASC→topic_id ASCの上位5件。方向はPhase8のdirection関数。Post Growth/Engagement Growth/Avg Engagementを保存値から返す。

Competitorは同Project/対象SNSのActive COMPETITOR全件。Active OWNとともにPhase9 `CompetitorRepository.period_posts` / `account_followers`、`CompetitorService.analytics_from_rows` を再利用。Account/Role/Source/Platform整合性チェックも既存Queryのまま。自社SummaryはPhase9のActive OWN Scope、KPIはPhase7のInactive履歴保持Scopeである点を維持する。複数競合Average Engagementは全競合投稿の既知値平均、Account平均の単純平均ではない。ERは共通SNS/分母Group、FollowersはAccount別で合算しない。最大3競合はname/platform/UUIDの安定順、評価Rankを作らない。

OpportunityはPhase10 `GapAnalysisService.analysis_in_session` から、有効Gap Score先頭をそのまま返す。Raw DecimalによるSort、Gap計算、50/50の分類を変えていない。Gap0は有効、OPPORTUNITY分類限定ではない。Active Topicなし/市場Scoreなし/Own RatioなしならNULL。Gap APIとの完全一致Testを追加。

AI Summaryは既存ai_insightsのReadのみ。同Project/対象Platform（ALLはplatform NULL）を優先、その中でcreated_at DESC、UUID安定順。候補はplatform NULLまたは有効対象SNS。特定SNSで同SNSなしの場合はALLのみをFallbackにし、別SNSを混ぜない。ALLでALL Insightなしの場合は有効SNSの最新を返す。分析from/toに一致するInsightに限定する正本指定がないため、保存Insightの分析期間メタデータをそのまま表示する。

contentのJSON構造を固定しない。content.summaryが文字列なら本文、それ以外は「AI Insightsあり」と分析期間/Platform/作成日/モデル/Prompt Versionを表示。Insightなしは正常「AI Insightsはまだ生成されていません」。OpenAI API、Prompt作成、生成、再生成、Retry、AI専用APIは追加していない。

## 再利用 / Snapshot / Read Only / Query数

My AccountはKPI関数とSession内部Helper、CompetitorはRowからの純粋計算Helper、GapはSession内部Helperのみ最小抽出。既存公開APIのトランザクション開始/結果を維持した。Overviewから公開analytics()/analysis()を直列呼出していない。

`MyAccountService.read` を使用し、Project検証からAI取得まで同一Session/同一Connection、REPEATABLE READ、postgresql_readonly=True。Request内のSnapshotは共通。SELECT/WITHのみ、INSERT/UPDATE/DELETE/明示COMMITなし。Import/Matching/Rematch/RebuildをRead経路から呼ばない。

通常16 SELECT/WITH固定:

| Query | 本数 |
| --- | ---: |
| Project、Enabled Platform | 2 |
| Current+Previous OWN posts / Latest Metric | 1 |
| Current / Previous OWN Followers | 2 |
| OWN AccountMetrics期間履歴 | 1 |
| Active Account一覧、Phase9 period posts、Account latest followers | 3 |
| Phase10 Platform、Topics、Topic latest snapshots、coverage totals、coverage matches | 5 |
| Top5 Topic latest snapshot、既存AI latest row | 2 |
| 合計 | 16 |

比較期間が作れないdate.min境界はPrevious Followers Query不要のため15本。独立Performance Trend APIは通常5本（Project/Platform/OWN posts/OWN latest followers/OWN history）。各QueryをPost/Topic/Accountごとに繰り返さない。

使い捨てPostgreSQLに1000 OWN/1000 COMPETITOR、100 Topic、X/Instagram、複数Account・27 AccountMetric・複数AIInsightsを投入し、小/大データ双方16 SELECT/WITH、Connection1、read_only=on/isolation=repeatable readを確認。検証用SHOW2本は集計Query数に含めない。2000 PostMetric・2000 PostTopic・200 Trend Snapshotを一括読み取り、KPI1000 Posts/Reach10000、競合1000 Posts、Top5/最大3 Accountを確認した。

別接続の書込みTransactionを取得途中でCommitし、PostMetric・TrendDaily・AIInsightを更新/追加する並行更新Testも実施。KPI Reach10、Own Summary Engagement1、Top Trend/Opportunity Score80、AI NULLが更新前Snapshotのままで一致した。Response安全500・Project/Platform分離も確認。

計算量/転送量は期間内投稿/Topic/Account数に依存する。N+1なしを実測したが大規模本番SLAは未検証。キャッシュTable、Index追加Migration、横断SQL最適化は行っていない。

## Test / Build / Docker / DB / OpenAPI

| 検証 | 結果 |
| --- | --- |
| 作業前Backend（Phase1〜10） | 841 passed、Failed0 / Skipped0、76.79秒 |
| Phase11新規 | 67 passed、Failed0 / Skipped0、35.00秒 |
| 最終全Backend | 908 passed（841＋67）、Failed0 / Skipped0、127.63秒 |
| npm run typecheck | 最終Frontendソースで成功、Docker Node22 |
| npm run build | 最終Frontend Docker build内で成功、18静的Route |
| docker compose build backend/frontend | 両方成功 |
| docker compose up -d | db/backend/frontend起動成功 |
| Health | HTTP200、status ok / database connected |
| Alembic current / heads | 0001_initial (head)、Migration追加なし |
| OpenAPI | Overview / Performance Trend GET、UUID、from/to date、Platform enum、Typed Response掲載 |
| Test使い捨てDB | 残存0 |
| git diff --check | 成功 |

67新規TestはKPI全NULL/0/部分NULL、分母優先/0、Latest Metric/UTC境界、OWN/競合/市場/Project/SNS分離、Rate混在・比較Cohort変化、前期間0/NULL/負成長/date.min、Followers最新NULL/0/未来/欠測/Account別、Topic最新/Term除外/Top5/安定順/Inactive、競合全体投稿平均とActive/最大3件、Gap4分類/0/NULL/既存API一致、AI最新/Platform優先/未知JSON保持/隔離、400/404/422/安全500、3660日inclusive、独立Trend API、並行更新Snapshot、2000投稿固定Query/Read Onlyを含む。既存Testの削除/Skip/期待値変更/Assertion弱体化なし。Starlette/httpx既存DeprecationWarning1件は非失敗。初回基準TestはPytest cache権限警告も出たため、最終Testでは既存cacheを変更せず `-p no:cacheprovider` とした。

## Browser確認 / Cross-screen / 証跡

Codex In-app Browserと最終Compose実Backendを使用。PC幅1440×1000と標準幅655のレイアウトを確認し、検証用Viewport指定を終了時に解除。既存Projectのデータを再利用し、Phase11検証用Import/Matching/Rebuildや開発DBへのAI追加は行っていない。

`Phase10 Browser Verification`（4509740f-2a16-49a8-aab2-0b482ea946ce）、ALL、2026-09-04〜10-03で以下を実画面とAPIの両方で確認。

| 指標 | Overview / 既存画面の一致 |
| --- | --- |
| Posts / Reach / Impressions / Engagement | 20 / 2000 / 4000 / 240（My Account一致） |
| Own ER | ALL単一値NULL、Instagram reach12%・X reach12% |
| Competitor | 2 Account、各20 Posts・Avg Engagement12・views ER4%・Followers2000（Phase9画面一致） |
| Competitor aggregate | 40 Posts・Avg Engagement12、SNS/views Rate別 |
| Trending Topics | OpportunityAI Instagram/X Score100、BalancedAI Instagram/X63.79、LowAI Instagram9.05（GapのTopic保存Snapshot一致） |
| Opportunity | OpportunityAI/Instagram、Trend100、Own10%、Comp50%、Gap90、OPPORTUNITY（Gap先頭一致） |
| AI | 正常未生成表示 |

X/Instagram各指定でReach1000/Posts10、Opportunity Platform切替を確認。ALLへ戻すとReach2000/Posts20。7日（09-27〜10-03）、90日（07-06〜10-03）、30日（09-04〜10-03）PresetとURL更新を確認。Reach/Engagement/Posts/Followers全Metric切替を確認。Loadingは初回表示/再取得時のAX状態で確認。Browser console errorなし。

`Phase7 Browser Verification`（a7272f32-a533-44e8-b5b7-d164bf7ccbb0）へProject切替し、Reach24000/Posts28、ER4 Cohort、Followers Instagram850/X1200、単一FollowersNULLとAccount別2 Seriesの実測点/欠測の空白を確認。Trend/競合/GapなしのPartial EmptyでもKPIとFollowersを保持する。

`Phase10 Empty Verification`（fd1abd8c-0d9f-440c-8008-5c4604d45a1e、Xのみ）への切替で旧結果破棄、Posts0・その他NULL、Section別Empty/Import導線、AI正常Empty、Instagram optionのdisabled=trueをDOMで確認。元Project復帰を確認した。

任意期間2026-10-01〜03はURL指定でPosts20/Gap90を確認。2026-10-04〜05はPosts0、Reach NULL、Trend/Opportunityなし、前期間Posts20→差-20/-100%、Reach前期間2000→比較率NULLを確認。3660日超をURLから指定しError/再読み込み、30日Presetで正常復帰を確認した。

Overview→My Account、Overview→Gap、Overview→Competitorのリンクで同じURL Filterを保持し数値を実画面で照合。既存画面→OverviewでもProject/Platform/from/toを保持する。Trend Explorerは既存Phase8のTerm粒度、OverviewはTopic粒度であるためランキングを無条件に同一視せず、Gap画面/既存Topic SnapshotでTrend一致を確認した。

証跡:

- [Overview全体](Phase11_Browser_Overview.jpg)
- [Account別Followers / Partial Empty](Phase11_Browser_Followers.jpg)
- [Empty Project](Phase11_Browser_Empty.jpg)
- [未来期間のNULL/0 / 前期間差](Phase11_Browser_NULL.jpg)
- [期間上限Error](Phase11_Browser_Error.jpg)
- [My Account KPI一致](Phase11_Crosscheck_MyAccount.jpg)
- [Gap / Topic Snapshot / Opportunity一致](Phase11_Crosscheck_Gap.jpg)
- [Competitor一致](Phase11_Crosscheck_Competitor.jpg)

## 正本との差分 / Fallback採用 / 既知課題

- 正本のResponse名称/ネスト/Arrayを優先。追加Typed fieldsの詳細（日次daily、follower_series、Rate Cohort、own_summary、competitor_aggregate）は指示書Fallbackを採用。
- Daily Reach/Engagementの欠測NULL、Followers当日Snapshotのみ/欠測NULLは詳細未定義のFallback。LOCFを導入していない。
- Trending Topicsは正本でTopic/Term両方の表示候補があり選定詳細未定義のため、指示書Topic粒度を採用。最新期間内7-day Topic×SNS、Top5の安定Sort/NULL除外を採用。
- Competitor ScopeはActive全件、最大3件は評価Rankでなくname/platform/UUID安定順。Summary詳細は指示書Fallback＋正本Arrayを保持する補足Object構成。
- OpportunityはPhase10有効Gap先頭、Gap0を保持、分類を正確に表示。AIはLatest existing row / なしNULL、Platform優先を採用。
- 前期間比較の不明/0基準NULL、ERのCohort一致条件、date.minの完全前期間なしNULLは既存NULL/Rate方針を守るための未定義詳細補足。
- 日付inputへの自動fillはDOM/Reactの条件更新を確認できず、検索URLは元の期間のままだった。任意期間API/UI結果はURL指定で検証。手動カレンダー/キーボード日付入力は未検証で、原因を推測して既存共通input実装を変更していない。
- Request version/Unmount invalidationを実装し通常のProject/Filter切替で旧値クリアを確認。意図的に遅延応答順序を逆転するBrowser E2Eは未実施。
- 既存AI本文のBrowser描画は開発DBに既存Insightがないため未検証。保存JSON/選定/メタデータは使い捨てDBのAPI Testで検証。AI未生成画面は実Browser確認済み。
- 全Browser/モバイル/DPI/本番大量データ負荷/固定秒数SLAは未検証。View幅655/1440で表示を確認したが完全レスポンシブ認証ではない。
- Phase12/13、Provider、Normalizer、CSV、Import/Matching/Rematch/Trend/Gap計算式、DB Schema/Constraintsは変更しない。既存公開分析結果も変更しない。

## 変更ファイル

| 分野 | ファイル |
| --- | --- |
| Backend追加 | backend/app/api/v1/overview.py、repositories/overview_repository.py、schemas/overview.py、services/overview_service.py |
| Router登録 | backend/app/main.py |
| 既存共通計算抽出 | backend/app/services/my_account_service.py、competitor_service.py、gap_analysis_service.py |
| Test追加 | backend/tests/overview/__init__.py、conftest.py、test_api.py |
| Frontend追加 | frontend/src/lib/overview-api.ts、components/overview.tsx、components/overview-link.tsx |
| Route追加 | frontend/src/app/dashboard/page.tsx、dashboard/overview/page.tsx、overview/page.tsx |
| 既存ナビ | frontend/src/app/page.tsx、components/my-account.tsx、trend-explorer.tsx、competitor.tsx、gap-analysis.tsx、settings.tsx |
| Docs | README.md、本報告書、上記Phase11 JPG証跡8枚 |

## Git / Push / Review ZIP

開始時master、Working Tree clean、HEAD `7deb2997421e179763a054ecdd176de2771c0f4d`。実装Commit `fbcefe8373ba8a445080237ce2c2d6a9ed0ce006`（feat: complete Phase 11 overview dashboard）に実装/Tests/README/本書/証跡の33ファイルを保存した。このHash追記を報告書Commitとする。実装Commit/報告書Commit/最終HEAD/Push結果は最終回答に記載する。Remote未設定を確認し、勝手にRemoteを追加せずPushしない。

全実装/検証/Docs/Commit後、最後の生成工程としてRepository Rootで `git archive --format=zip HEAD -o ../SNS_Analyzer_Phase11.zip` を実行する。ZIP生成後はtracked Source変更/Commitなし。存在、CRC、必須Backend/Frontend/Tests/README/本報告書、禁止物非混入、ZIP comment=最終HEAD、全格納ファイルとHEAD blobの一致を検証する。ZIP検証結果は生成後に本書へ追記せず最終回答に報告する。既存Phase ZIPは変更しない。ZIPはソース/証跡であり開発DBを含まない。

Phase11完了で停止する。おすすめは、このZIPをChatGPTレビューへ渡してから次Phaseの判断を行うこと。理由は既存分析との一致/NULL/読み取り専用性の証跡がまとまっているため。今すぐ行うことはZIPと本報告書のレビュー。
