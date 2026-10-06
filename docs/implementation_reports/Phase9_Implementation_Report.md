# Phase 9 Implementation Report

2026-10-03 JST。Competitorの実装・検証を完了。Phase1〜8の契約・既存処理を維持し、Phase10 Gap Analysisへは進まない。DB Schema/Index/Migration・CSV Provider/Normalizer/Import・Matching・Trend計算・既存分析契約の変更なし。

## 参照・優先順位

添付`SNS_Trend_Performance_Analyzer_Codex_Phase9_実装指示書.md`と、同じ設計資料フォルダのAPI設計書Ver1.1、基本設計書、画面設計書Ver1.1、DB詳細設計書、Phase計画を確認。正本で明確な部分を維持し、詳細未定義箇所はPhase9指示書のFallbackを採用した。実装開始前の既存705 Testを実行して全成功、Failed/Skipped 0を確認した。

## API / 選択・比較スコープ

| GET（`/api/v1/projects/{project_id}` 配下） | Response |
| --- | --- |
| `/competitors/analytics` | `accounts`にAccount別指標・Role・SNS・Followers基準日・ER Groups、UTC/unit |
| `/competitors/topic-distribution` | `topics`にActive Topic別Account比率・matched_posts・total_posts・Role/SNS、UTC/overlap説明 |
| `/competitors/top-posts` | `items`に最新PostMetricからの投稿指標・account_id/name/display_name・SNS・本文・permalink |

必須from/toはUTC日付両端を含み最大3660日。PlatformはALL/X/INSTAGRAM、ALLはProjectの有効Platformのみ。必須account_idsはカンマ区切り1〜3件の異なるUUID、同ProjectのActive COMPETITORだけを指定する。Active OWNは選択Platform条件に合わせて自動追加し、ALLではX/InstagramのOWNがそれぞれ表示される。Account同士を合算しない。OWN Role・別Project・Inactive・無効Platform・指定Platform不一致は404、空/重複/4件以上は400、UUID不正/欠落は422。最大1000文字の入力上限。未知Projectは404。

投稿はAccountとのaccount_id/project_id/platform/account_role=source_type一致を検証。OWN/COMPETITORだけを許可しMARKET・Role不整合・Project不整合・Platform不整合の行を除外する。Top Postsは選択COMPETITORだけを残す。既存データを修復・変更しない。

## 指標・計算

| 指標 | 採用仕様 |
| --- | --- |
| Followers | Accountごとにrecorded_date≤toの最新AccountMetric。未来除外。最新NULLを古い非NULLで埋めない。未取得NULL。基準日も返す。期間前の最新値は使用可 |
| Posts | 範囲内の整合する投稿数。PostMetric未取得でも投稿数へ含める |
| Posting Frequency | Posts / (to-from+1)のUTC日数、posts/day。0投稿は0 |
| Average Views/Likes/Comments/Shares | 各投稿の最新PostMetricの既知値だけを平均。0を含み、全不明はNULL |
| Engagement | Phase5 calculate_engagementの既知likes+comments+shares+saves合計。全部NULL→NULL、部分NULL→既知値合計、実値0→0 |
| Average Engagement | 最新Engagementの既知値平均。Snapshot合算・古い値補完なし |
| ER | Phase7 item/raw_rate/aggregate/numberを再利用。Reach→Impressions→Viewsの最初の非NULL分母を使用し、0ならNULLで停止。後順位の非0へ代替しない |
| Average ER | 投稿ごとの丸め前ERを単純平均、Platform+分母別Group。有効Groupが1つのときだけScalar平均、複数/なしはNULL。投稿数も返す。4桁HALF_UP表示 |

比較表にAccount名・表示名・Role・Platformを表示。Average EngagementをAccount別Barで表示し、ERは分母別表と説明で表示する。異なる分母のERを同条件の優劣として色付け・ランキングしない。NULL「—」と実値0を区別する。

## Theme Distribution / Top Posts

ThemeはActive Topicの既存PostTopic（KEYWORD/HASHTAG/MANUAL/AIすべて）だけを使う。本文から再Matchingしない。Account/TopicごとのCOUNT DISTINCT post_idを対象期間Account総投稿数で割って×100。0投稿→NULL、投稿ありで一致0→0%。複数Topicに含まれる投稿により比率合計100%超があり得ることを画面・READMEに説明した。TopicなしはEmpty。Account順はMetric表とそろえ、SNS間で合算しない。

Recharts Grouped Bar、Topic軸、%軸、Account/Role/SNS凡例、比率・Match・Total・Account/Role/SNS Tooltip、比率と分子/分母の表。Frontendは表示のみ、比率はBackendが計算する。

Top Postsは選択Active COMPETITOR全体で最新Engagement DESC NULLS LAST→posted_at DESC→post_id ASC。既定10/最大50。指標不明投稿もNULLとして保持。最新recorded_atの1 Snapshotのみ、OWN/MARKET・未選択競合を含めない。UTC日時・Account・SNS・本文・Media/Views/Engagement/各反応を表示。本文はReact文字表示、長文省略とtitle全文、HTTP/HTTPS permalinkのみ外部リンク。

## Frontend / 状態制御

Route `/dashboard/competitors`、alias `/competitors`。Metric Comparison / Engagement Comparison / Theme Distribution / Competitor Top Postsの4セクション。Project・Platform・7/30/90日・任意UTC日付・競合1〜3件。4件目Checkboxを無効にし、APIでも同じ上限を検証。Keyword/Hashtagフィルターは追加していない。

検索で条件を全Sectionへ適用し、URLへ保存。Project切替ではAccount選択とURL account_idsをクリアする。各取得でデータを一旦クリアし、version tokenとUnmount時の無効化により古い応答が新条件を上書きしない。Loading Skeleton、Error/再読み込み、再取得、Empty/Settings Import導線を実装。登録済み競合がない場合・未選択は分析APIを呼ばない。

## Read Only / 性能

既存MyAccountService.readを再利用し、Project検証から全QueryをREPEATABLE READ・postgresql_readonly=Trueの一貫したSnapshotで読む。INSERT/UPDATE/DELETE/COMMITなし。スコープ投稿・最新MetricはMATERIALIZED CTEとWindow Functionで一括取得、FollowersもAccount別Window、Themeも一括GROUP BYで処理。N+1なし。

使い捨てPostgreSQLに競合3 Account合計1000投稿・1000 Metric・2 Topic計2000 Matchを投入して、Analytics SELECT/WITH最大5、Distribution最大5、Top Posts最大4とread_only=on/isolation=repeatable readを確認した。取得結果1000投稿・各Topic100%・上位50を確認。投稿数/Account数に比例したQuery増加なし。

Analytics/Top Postsは対象投稿を一括取得後にPythonで平均・ソートするため、非常に多い投稿ではメモリ/時間が増える。1,000投稿のQuery数確認は大量本番データの性能保証ではない。秒数SLAや大規模負荷試験は未実施。Schema/Index変更は行わない。

## 正本との差分 / Fallback

- API正本の3 GET Route・基本Response項目を維持。account_idsの形式・選択Role・上限・OWN自動追加は詳細未定義なので指示書Fallbackを採用し、OpenAPI/Frontend/Test/READMEへ明記。
- 画面正本の「自社1件＋競合最大3件程度」に対し、DBのActive OWNはSNSごとに1件。単一PlatformではOWN1件、ALLでは有効OWN最大2件を各SNS別に表示するPhase9詳細仕様を採用。異なるSNSのFollowers/ER合算を避ける。
- Followers基準日、Frequency単位、NULL/0、平均の既知値範囲はFallback。最新PostMetric/Engagement/ERは既存Phase5/7仕様を再利用。
- Themeは基本設計のテーマ比較をPostTopic粒度で実現。Distinct分子、全投稿分母、総0→NULL、重複Topicの100%超、全Match方式・Active TopicはFallback。Keyword/Hashtagの別フィルター・再Matchingを追加しない。
- Topの安定Sort、limit上限、エラー、UTC期間上限、Activeスコープは指示書Fallback。Responseにはdisplay_name/role/platform、followers_as_of、投稿頻度単位、分母Groups、matched/total等を補足した。
- Phase1〜8既存ファイル変更はRoute登録とナビリンクだけで、既存分析ロジック・Import契約・Migrationを変更していない。

## 検証結果

| 確認 | 結果 |
| --- | --- |
| 作業前既存Test | 705 passed、Failed 0 / Skipped 0、54.13秒 |
| Phase9新規Test | 76 passed、Failed 0 / Skipped 0、12.77秒 |
| 最終Backend全Test | 781 passed（既存705＋新規76）、Failed 0 / Skipped 0、71.65秒 |
| npm run typecheck | 成功（Docker Node22使用） |
| npm run build | 成功、12静的Route生成 |
| Docker backend/frontend build・up | 両方成功、db/backend Healthy・frontend稼働 |
| Health | HTTP200、status ok / database connected |
| Alembic current / heads | 0001_initial (head)、変更なし |
| OpenAPI | 競合3 GET・Query・Typed Response掲載確認 |
| 残存使い捨てTest DB | 全Test後0 |

Testは空データ、3競合/複数OWN/ALL/SNS分離、最新Snapshot NULL非補完、NULL/0/平均/投稿頻度、Followers as-of/未来/NULL、ER分母優先/0停止/分母Groups/非加重平均、UTC境界/3660日、Topic全Match方式/Active/Distinct/100%超/別Project、Top Role/選択/NULL/Sort/limit、400/404/422、汎用Errorの内部情報秘匿、1000投稿Query数/read-onlyを含む。初回新規Testの引数重複ヘルパーを修正後、全781件を再実行して成功。既存Starlette TestClient/httpx DeprecationWarning1件、npm更新案内、Git改行警告は非失敗。

## Browser確認 / 限界

最終Composeの実BackendとIn-app Browserを使用。架空Project `Phase9 Browser Verification`（b105c145-1cae-4846-9a93-f94184fb0efa）を既存Settings APIで作成。OWN X/Instagram各30投稿、競合X2件・Instagram1件各30投稿、投稿なし競合X1件、Topic ChatGPT/生成AI/AIエージェント。OWN_POSTS 60件・COMPETITOR_POSTS 90件SUCCESS。競合Followersを既存COMPETITOR_POSTS列から再取込90件SUCCESS、元投稿を重複させず最新Snapshotを追加した。既存ACCOUNT_DAILYはOWN専用であり、最初の5行投入はOWN2行SUCCESS/競合3行Role不一致PARTIAL_ERROR。この既存契約を変更せず、競合Followersの正しい投入方法へ切り替えた。Import履歴と架空データは開発DBに保持（ZIPはソースのみでDBデータを含まない）。

競合選択1→3件・4件目無効、ALLでOWN2＋COMP3の5行、Xのみ3行、Instagramのみ2行、7日各7投稿/1 posts/day、90日各30投稿/0.3333 posts/day、30日各30投稿/1 posts/dayを実画面で確認。任意期間2026-10-01〜03はURL条件で各3投稿を確認。OWN Reach based/COMP Views based表示、平均指標、Topic Grouped Bar/凡例、キーボードによるTooltip（比率・Match・Total・Role/SNS）、既存Matchの100%超、Top Engagement104→100→100等の降順、競合だけの表示を確認した。

投稿なし競合はFollowers/平均/ER「—」・Posts/Frequency 0・Topic 0/0比率「—」・Top Empty。Project切替時の選択クリアと競合なしProjectのSettings導線、Loading Skeleton、期間上限Error4 Section/再読み込み、正常条件への復帰を確認。Browser証跡:

- [通常比較](Phase9_Browser_Competitor.jpg)
- [NULLと0](Phase9_Browser_NULL.jpg)
- [期間Error](Phase9_Browser_Error.jpg)

日付inputへのBrowser自動fillでは表示値のみ変わり、Reactの検索条件更新を確認できなかった。PresetとURL条件では期間変更・実結果を確認した。手動カレンダー/キーボード入力は未検証で、原因を推測して修正していない。全Browser/モバイル/DPI、通信競合の大規模E2E、実SNSデータ、大規模負荷、外部permalink実リンク遷移は未検証。古い応答破棄はコードで実装し、Project/条件の通常切替をGUIで確認している。

## 変更ファイル

| 分野 | ファイル |
| --- | --- |
| Backend新規 | app/api/v1/competitors.py、app/repositories/competitor_repository.py、app/schemas/competitors.py、app/services/competitor_service.py |
| Backend登録 | app/main.py |
| Test新規 | tests/competitors/__init__.py、conftest.py、test_api.py |
| Frontend新規 | src/lib/competitors-api.ts、src/components/competitor.tsx、src/app/dashboard/competitors/page.tsx、src/app/competitors/page.tsx |
| ナビ追加 | src/app/page.tsx、src/components/my-account.tsx、settings.tsx、trend-explorer.tsx |
| Docs | README.md、本報告書、Phase9_Browser_Competitor/NULL/Error.jpg |

## Git / Push / Review ZIP

開始master、HEAD `1826329cbfe522aff0a7ceaf136084acf2a25d9c`、Working Tree clean。実装Commit `f7349e8f447151003491366066738db95b53363c`（feat: complete Phase 9 competitor comparison）に実装・検証・Docs計21ファイルを保存。このHash追記を報告書Commitとする。Remote未設定のためRemote追加/Pushは行わない。報告書Commit自身のHashと最終HEADは最終回答に記載する。

全作業・検証・Commit完了後の最後の生成工程でRepository Rootから `git archive --format=zip HEAD -o ../SNS_Analyzer_Phase9.zip` を実行する。生成後trackedファイルを変更・Commitしない。存在/CRC/必須Backend・Frontend・Tests・README・本報告書/禁止物非混入/ZIP comment最終HEAD一致を検証し、実測結果を最終回答へ記載する。ZIP生成後の本書追記はしない。Phase7/8 ZIPを変更しない。
