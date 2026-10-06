# Phase 7 Completion — 継続・修正報告

確認日: 2026-10-05 JST。**USER_ACTION_REQUIRED / Meta Spec PARTIAL / Phase 8 NO-GO**。
Phase 7 Completion指示書に基づく継続作業であり、Phase 8は開始していない。

Gitはmaster、HEAD e2ad3848105687fb1b48c872e48d15d9315b3b97を維持。前回Phase7 ZIPとの差分は8ファイル: Instagram Provider、ProviderService、IG Provider tests、README日本語/英語、Setup Guide、初回報告への継続リンク、本Completion報告。既存未コミット変更を保持し、commit / push / tag / 公開は行っていない。

## 1. 結果と実装変更

未完成のInstagram投稿・Insightsを利用可能と表示していたCapabilityを修正した。

| Capability | 現在のProduction Provider |
| --- | --- |
| ACCOUNT_PROFILE | true |
| OWN_POSTS | false |
| OWN_METRICS | false |

`InstagramApiProvider.capabilities()` はProfileのみを返す。ProviderServiceのValidateはInstagramの場合にProfileだけを必須とし、Profile HTTP取得・Professional検証が成功すればCONNECTED / valid=trueを返せる。実Validateは未実施であり、ここでいう成功はMock / DB / APIテストによる証明である。

Capabilities APIは現行Providerの利用可能機能を返し、Credential解決や外部HTTPを行わない。List / Detail / Patchの応答は保存済みCapabilityを現行機能へ制限するため、旧DBにOWN_POSTS / OWN_METRICSが残っていても誤表示しない。GETはDBを変更しない。Validate成功時は実際のCapabilityを保存する。Xの必須3機能条件とX固有Sourceは変更していない。

Instagram Media / Insights、Pagination、Initial / Incremental Sync、IG Live Import成功経路、成功checkpointは未実装。手動同期は従来どおり通信前にINSTAGRAM_SPEC_UNVERIFIEDで安全停止する。Fake Contractを追加していない。

## 2. 公式仕様の再確認

Web検索ツールは対象公式URLを取得できなかったが、ブラウザと `Accept: text/markdown` を指定した直接取得で公式資料を確認した。新たな秘密値は送信していない。日本語ページはAI翻訳と注記されていたため、英語の公式Markdownを判断根拠として再取得した。

| 公式Source | 今回の確認結果 |
| --- | --- |
| [Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) | captionとmedia_product_typeはFacebook Loginのみとの記載が継続。id、timestamp、media_type、permalink等は掲載されているが、完全な必要契約は未確定 |
| [Get Started](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started) | graph.instagram.comのIG_ID/media GETと、ID一覧・paging.cursorsの例を確認。IG_IDのProfile正規IDとApp-scoped IDは区別する |
| [User Media](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media) | 読取部の権限・HostはFacebook Login向け。時間pagingをInstagram Loginへ転用しない |
| [Media Insights](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights) | Instagram LoginのHost、basic / manage_insights権限とProduct別Metricを確認。Product識別の未確認は解消しない |
| [Business Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login) | Short→Long Token交換と60日更新の既存方針を再確認 |
| [Refresh Access Token](https://developers.facebook.com/documentation/instagram-platform/reference/refresh_access_token) | 発行後24時間以上、未失効の長期Tokenだけを更新可能。更新後60日。既存条件を維持 |
| [Changelog](https://developers.facebook.com/documentation/instagram-platform/changelog) | B1を解消する正式Product識別契約は今回の確認では得られなかった |

公式Markdown取得7件はHTTP200。全文はTEMPだけに保存し、ZIPへ転載しない。Media MarkdownのSHA256は73f31adb15ff2a64623cb90c4eae555080738c47eec9839feba11b0bd1b69342、Insightsは2b107174883548fb75ed7ec6952aee05e0bcda4565540a2826dbe5dd5b5f6dfd。公式Meta Postmanを対象にした追加検索からもProduct Type契約を解消する結果は得られなかった。SDKや非公式記事、検索snippetをendpoint契約の代替にしていない。

## 3. Graph Version / Permission / OAuth

Graph pinは引き続き候補 **v26.0**。今回のMediaページ表示はv26.0だったが、同Sourceの英語MarkdownとInsights Markdownは最新v25.0表記。全endpointの同Version対応はPARTIALであり、解決したとしない。Token lifecycleの公式URLはversionを含まない固定endpointであり、Graphのversionを挿入しない。

要求権限は引き続きinstagram_business_basic / instagram_business_manage_insightsのみ。Facebook Loginへの切替、Publish / Message / Comment管理権限の追加はない。既存State CSPRNG、TTL600秒、暗号pending、Replay防止、Project / Provider結合、HTTPS Exact Redirect、固定Token endpoint、単一Token試行、query log scrubbingを維持した。

## 4. Media / Product / Insightsと安全な設計範囲

B1が残るためMedia HTTP実装とMetric Matrixは追加していない。VIDEO、数値ID、permalinkからFEED / REELS / STORYを推測しない。

Completion指示書はcaption取得不能時のNULLを許容している。既存NormalizedPost.textも `str | None` なので、将来の正式Media実装では取得不能captionをNULLにできる。ただしこれは設計上の選択肢であり、未実装のMedia同期を実装済みに変えるものではない。本文やHashtagを推測生成しない。

公式Metricを使う場合もmissing / unsupportedはNULL、実値0は0、viewsをimpressionsへ複製しない、total_interactionsを既存Engagementへ直接加算しない。Auth / Permission Errorをunsupportedと混同しない。現状はProduct契約が未確定であり、実InsightsやMatrix PASSを主張しない。

## 5. Paging / Initial / Incremental / Checkpoint

IG Login Media GETとcursor envelopeの例は確認できたが、limit境界、同版coverage、cursor継続・終了条件とordering保証は未確定。順序保証がなければearly stopしないというCompletion指示書の方針を採用する必要がある。Facebook Loginのsince / until、X since_id、max(media_id)を流用しない。

将来の実装は初回最大5 Media、bounded pages、固定Host / Path、next URLの直接追跡禁止、全Fetch / Insights完了後のImport、上限で完全性を保証できない場合の無Commit・無checkpointを必要とする。ACCOUNT / POSTS / METRICS StateはBusiness Commit成功後のみ更新する。これらのIG成功経路は未実装。

既存LiveImportService、Provenance、共通Scope分離、Business KeyによるPost upsert / Metric observation冪等性は保持。IG MediaからDB・Analyticsまでの実証は未完了である。

## 6. Private E2E / USER_ACTION_REQUIRED

既存Private Composeをpresence-onlyで確認した。Instagram Client ID / Secretは未設定、INSTAGRAM_OAUTH_BOOTSTRAP_ENABLED / INSTAGRAM_LIVE_SMOKE_ENABLED / INSTAGRAM_LIVE_REFRESH_SMOKE_ENABLEDは全てfalse、enabled schedules=0。

| Private Gate | 結果 |
| --- | --- |
| OAuth / Profile Validate | NOT EXECUTED |
| Manual Initial / Incremental Sync | NOT EXECUTED |
| Real Media / Insights | NOT EXECUTED |
| Live DB / Existing Analytics | NOT EXECUTED |
| Real Refresh / Refresh後Profile | NOT EXECUTED |

Secret値をチャットへ要求しない。Private .env、既存X Token、暗号鍵、Runtime Secret Volumeを変更しない。Scheduleを有効化しない。利用者の代わりに投稿しない。実Tokenがなく、24時間条件を時刻改ざんで突破しない。

利用者は先に最新版資料を持っていないと回答済み。次に必要なのはMetaへの正式Product識別契約の確認であり、同じ資料提出質問は繰り返さない。B1/B2解決後に残実装を完成させ、[Privateセットアップ](../portfolio/instagram_api_private_setup.md)に沿ってApp / Professional account / readonly権限 / HTTPS Redirect / Private Credentialを本人が準備し、手動E2Eと24時間以降の実Refreshを行う。

## 7. Regression / Capability Tests

Production Provider、未検証row、旧3機能row、Capabilities API、List / Detail応答、Profile-only Validate / CONNECTED、Validate後DB保存、GETの無書込・無HTTP、Profile欠落拒否を3件の新規DB/APIテストで追加確認する。既存のIG仕様保留HTTP0件・無SNSPost・無SyncState試験も維持する。

Backend最終fullは **1557 passed / 0 failed / 0 skipped (293.95秒 / 4:53)**。1554 baselineを減らさず、新規3件を追加。実HTTP禁止fixtureと使い捨てsns_phase2_test_<32-hex> DBを使用し、通常DBをリセットしていない。Real X / Instagram callは0。

```text
docker run --rm --network sns-trend-performance-analyzer_default --env-file .env -e POSTGRES_HOST=db -e POSTGRES_PORT=5432 -e LIVE_MODE_ENABLED=false -e X_LIVE_SMOKE_ENABLED=false -e INSTAGRAM_LIVE_SMOKE_ENABLED=false -e PGOPTIONS="-c statement_timeout=120000" -v "<workspace>/demo_data:/demo_data:ro" sns-analyzer-phase7-completion-backend python -m pytest -q -p no:cacheprovider
```

Frontend再検証は **32 passed / 0 failed / 0 skipped / 0 cancelled (4568.839204ms)**、Typecheck Success、Next.js16.3.8 Production Build Success、19 routes。Frontend Sourceは変更なし。X Mock / OAuth / Provider / Router / Pipelineの全回帰試験もPASS。Capability ContractはProduction Provider / API / DBを含めPASS。

初回fullは **1556 passed / 1 failed / 0 skipped (541.71秒)**。失敗は既存 `tests/my_account/test_api.py::test_read_only_database_transaction_and_n_plus_one` のAnalytics HTTP500で、追加Capability試験ではない。DB状態確認時はtest DBのINSERT後ClientRead / idle in transactionで、長時間Overview SELECTやDB Lock待機は観測されなかった。失敗原因は未確定であり、Timeoutと断定しない。

同試験を変更せず診断付きで単独再実行し **1 passed (2.30秒)**、さらに使い捨てDBのQuery plan確認付き再実行で **1 passed (2.43秒)**。EXPLAIN ANALYZEは1000行、Nested Loop、Planning1.01ms / Execution442.557ms。この再実行時の計画は初回失敗の原因を証明しない。Production code、Production timeout、テストtimeoutを延長せず、前回と同じtest用PGOPTIONS120秒で全件を再実行した。

## 8. Docker / Migration / Canonical

通常Composeを既存Privateと衝突しない127.0.0.1の15432 / 18000 / 13000で起動。Backend / Worker / Beatを現行Sourceでbuildし、6 services running、DB / Redis / Backend healthy、FrontendとBackend health HTTP200、Worker pong / 1 node onlineを確認した。OpenAPIは44パス、全て/api/v1。Schema変更なし、head0005_v2_provider_coreを維持する。

Canonical7画面のDOM / AX表示を再確認した。Overview / My AccountはPosts180、Reach93392、Impressions136256、Engagement6928。Trendは14.04 / 4.16の4行、CompetitorはOWN2+COMP3の5行、Gapは12行・NULL1・実値0が2行、AIは保存済みDemo fixture、Settings / Importは履歴4件 (180 / 4500 / 180 / 540)、エラー0。Pixel / responsive / 全操作試験とは区別する。

通常DB19テーブルは前後の件数・全行集約MD5が一致、head0005_v2_provider_core。0001–0005の5 Migration、X OAuth / X Provider固有Source、Canonical demo_dataはPhase 6 Verified ZIPとバイト一致。0006なし。DBやCSVへの書込、設定保存、AI再生成は行っていない。前回Phase7 ZIPのSHA256はd41879d70c8fdec019b2c07adafa8f7754db8a91fbc5a4bde4d5f2b131a18b92のまま保持した。

## 9. Blocker / Phase 8

| ID | 残るBlocker |
| --- | --- |
| B1 | Instagram Login用Product Type識別の正式契約。captionはNULL許容で回避できるがProductは未解決。Media / Insightsと同期成功経路は未実装 |
| B2 | 全対象Graph版対応、IG paging詳細、安全なIncremental / checkpoint契約の確認と実装 |
| B3 | Private App / Credential / Professional accountの準備と実OAuth→Media→Insights→DB→Analytics→Refreshの実証 |

Capabilityの誤表示指摘は修正した。B1–B3は残る。Completion指示書9・109の「公式仕様が不足する場合は推測実装せずUSER_ACTION_REQUIREDで停止」に従い、**Phase 8 NO-GO**。追加確認の全件テストで成功した場合も、初回の既存Analytics一過性失敗の原因が確定したことにはならない。

## 10. Review Artifact / Security

未完了なのでCompletedの名称で完成成果物を作らない。継続レビュー用 `SNS_Analyzer_V2_Phase7_Completion_Review.zip` をworkspaceの親へ作成する。Current Worktree Source、全Phase Reports、Tests、0001–0005、README、Setup Guide、指示書参照を含める。旧Phase 7 ZIPは保存する。

最終ZIPは413 entries (Worktree source408 + 設計参照5)、CRC PASS、重複0、Worktree byte一致PASS、Migration / demo_data一致PASS、Python207ファイルの構文PASS、禁制ファイル0、Secretパターン一致0。Private環境内で実Secret5種類を照合し一致0件。値は照合プロセス内だけで読み、出力しない。Credential / .env / Token / Runtime Ciphertext / Key / Private DB / Media / Raw Insights / cacheは含めない。

最終テスト結果の追記後にZIPを再生成して検査。最終サイズ / SHA256は自己参照を避け報告書外で確認する。Secret Scanは既知Secretと検査パターンについての結果であり、全ての未知Secretが存在しない証明とは区別する。
