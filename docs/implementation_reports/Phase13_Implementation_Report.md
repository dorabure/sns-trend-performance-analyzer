# Phase 13 Implementation Report — 横断品質改善

実装・検証日: 2026-10-03〜2026-10-04（Asia/Tokyo）。Phase13のみ。Phase14 / 15は実装しない。
開始Branch: master、clean。開始HEAD: `602b6e02bf91069aba67f54840868d23f63e96f1`。

## 着手前確認・正本との差分

添付Phase13指示書、README、Phase12 Implementation Report、既存980件の構成を確認。Docker Desktop停止を確認して起動し、通常ComposeとAlembic current / headsの`0001_initial (head)`を確認した。

Trend Score・7日Window・Latest PostMetric・NULL/0・Engagement/Rate分母・Rate Cohort・Followers非合算・Gap式/50境界・source/Topic/Term分離・Cross-screen値・AI4区分/Evidence/append-onlyを変更していない。Migration・13テーブル・26公開Pathを維持。Phase13の必要な補足は安全な413 `REQUEST_TOO_LARGE`、予期しないRoute内部障害の固定500、Request上限環境変数。既存Import Responseを分析APIの形式へ置き換えていない。

## PROCESSING startup recovery

FastAPI lifespanのyield前に`recover_interrupted_imports(SessionLocal)`を実行。PostgreSQLの1回の原子的UPDATEでPROCESSINGだけをFAILEDにし、既存error_detailへ安全な1件をJSONB appendする。

```json
{"row":null,"field":"system","code":"IMPORT_INTERRUPTED","message":"Import was interrupted before completion"}
```

total_count / success_count / error_count / imported_atは更新しない。SUCCESS / PARTIAL_ERROR / FAILEDも不変。対象CSV・filename・本文を取得せず、ログは回復件数か固定失敗codeのみ。回復失敗時は受付を開始しない。engine.disposeはfinallyで実行する。

**単一Backend process / uvicorn 1 worker前提**。起動完了後の正常Importとは競合しない。multi-worker / multi-instanceは別processの実行中Importを区別するlease / heartbeat再設計が必要。初回導入でimport_histories自体が存在しない場合だけ対象なしとして起動し、明示Alembicコマンドを維持。自動Schema作成/Migrationなし。

実PostgreSQLで0/1/5件をstartupから回復し、2回目0件、件数/時刻/既存error保持、他status不変を確認。失敗時のstartup中止と安全なログ、未Migrationの新規DBで自動Schema作成がないことも確認。既存正常Importテストを全維持した。

既存TestClientのstartupが通常開発DBを回復しないよう、root test fixtureでstartup呼出のみstubする。回復専用Testは実関数＋使い捨てDBをlifespanへ注入し、実UPDATE/Commitを検証する。Health単体6件のDB不要契約も維持。

## Multipart前の二段階サイズ防御

使用中FastAPI **0.142.2** / Starlette **1.7.0**のRequest.form / MultiPartParser署名、解析失敗時cleanup、FastAPIのHTTPException再送出をインストール済みSourceで確認した。正式なASGI `scope / receive / send`だけを使うImport POST専用middlewareを追加。private APIやproduction monkey patchなし。

| 防御 | 挙動 |
| --- | --- |
| Content-Length | Request上限超ならreceiveもparserもRouteも実行せず413 |
| receive実測 | 全http.request chunkを加算。Lengthなし/過少申告/不正値でも上限超chunkをparserへ渡さずHTTPException413 |
| Request上限 | Compose既定21 MiB `22020096`、正の整数。単独Backendで省略時はFile上限＋1 MiB |
| CSV本体 | 従来の20 MiB `20971520`を維持。Route内64 KiBコピーで厳密確認 |
| parser前拒否 | `REQUEST_TOO_LARGE`、Import履歴なし、本文/filename echoなし |
| File超過 | 従来の`FILE_TOO_LARGE`、FAILED履歴、Temp削除 |
| malformed multipart | 安全な4xx。解析されたファイルとRoute Tempをcleanup |

Starletteが例外時にpartial spoolを閉じることを実ASGIの複数chunk Testで検証した。最初のchunkで1 MiBを超えてdisk spoolした後に次chunkで超過し、未読chunkが残り、全spool closed、Temp残骸0、Route/start未実行、履歴0を確認。時間閾値を使っていない。設定したRequest/Fileの厳密境界、正常CSV、既存File超過、正の整数Validationを確認。通常のFileコピー/finally cleanupは維持。

ブラウザーでは実CSVを正常Importし、22 MiBのFileをmultipart送信してHTTP413を確認。結果は安全なREQUEST_TOO_LARGE、履歴は直前のSUCCESS1件のまま、PROCESSINGなし。Requestはoverhead込みのため、File上限変更時にはRequest上限も調整する。

## 6画面のFilter・Project・日付・Stale Response

`analysis-filters.ts`にUTC過去30日、URL parse、Platform normalize、from<=to/date validation、query生成、FormDataの日付実値確定、Competitor ID scope補正を集約。Zustand/Context/新状態管理ライブラリなし。

6画面ともProjectの有効SNSでinitialを補正してからchild stateと最初の分析requestを作る。ALL/有効SNSは保持、無効SNSはALL。disabled optionも統一。CompetitorはAccount一覧取得後にRole=COMPETITOR・Active・Project内・有効SNS・選択SNSでIDを絞り、重複も除去してから初回requestを行う。Project変更時は既存の選択クリアを維持。

named from/to inputsを使い、検索時に共通FormData helperから実値を確定し、controlled draft・API・URLへ同じ値を渡す。My AccountのKeyword/Hashtag、Trend Keyword等の独自条件は保持。従来の「検索で適用」とAIの即時Platform/Preset更新を維持する。

5画面の取得を`use-analysis-read.ts`へ集約。RequestVersionで成功・error・finallyをtoken比較し、cleanup/unmountでもinvalidateする。AIのGET/POST共通version / generation busy refを維持。Project keyで旧scopeをunmountする。

## Loading / Error / Empty

Loadingはrole=statusまたはaria-live、Errorはrole=alert、Empty/Partial Emptyは各Sectionの正常不足として表示。検索/再取得/生成中は該当buttonをdisabledにする。再取得・再試行は適用済み条件を使用する。UIの大規模改装や全Section共通化は行っていない。

6画面で正常/Empty/Loading、Gapで安全なError→同条件retry→日付修正で復帰を確認。AI Keyなしでも既存分析は正常で、AI生成だけdisabled。CSV取込中は既存Settings全体のdisabledが機能し、413後に入力可能へ復帰する。

## AI Privacy・早期失敗

InsightService.generateでclient.availableをOverview/readより先に判定。Keyなしは503 AI_KEY_NOT_CONFIGURED、Session/Overview呼出0、INSERTなし。UUID/date/enum等のFastAPIと共通期間Validationは通常どおり行う。

内部保存summaryと外部送信用deep copyを分離し、外部analysis_scopeからproject_idだけを除去。内部AuditのProject UUID・保存Evidence・数値・scopeは保持する。Fakeが実際に受け取ったPayloadにProject UUID、投稿本文、著者、Account名/display_name、raw_data/raw_metrics、Secretが含まれないことを検証した。保存値/Evidenceの完全一致も確認。

Responses API、Structured Outputs、responses.parse(text_format=AIInsightContent)、store=false、retry=0、SDK **3.24.0**、モデルdefault **gpt-6-luna**、Prompt **phase12-v1**を変更していない。既存Fake/実SDK MockTransport全件を維持。Live OpenAI・実Key・課金を使った生成は行わない。

## Validation / Error / Logging監査

Settings、Import、My Account、Trend Explorer、Competitor、Gap、Overview、AIについて不正UUID/Enum/date、逆転期間/過大期間、未知Project、無効SNS、DB/unexpected例外を既存＋新規Testで確認。

Service既存のDB例外安全化に加え、Route wrapperでdependency/serialization等の予期しない例外を固定500にする。フレームワークへ未処理例外を渡し、SQL/Secret/input/tracebackをログへ出す経路を防ぐ。Importは固有status/errors形式を保持。multipart解析HTTPExceptionも固定安全応答にする。

Phase7/8の無効SNSは従来の200 Empty、後続分析は404という公開契約を維持した。統一目的で挙動を変えていない。機密sentinel付きRuntimeErrorを8領域のdependencyに注入し、Response/captured logにSQL・password・path・raw response・tracebackがないことを検証。既存DB障害/AI障害/CSV障害Testも維持。

## Performance / Memory監査

SQL計算・NULL順・Tie break・Latest Snapshot・Unicode Keyword/Hashtag・CSV後勝ちの仕様を変更しない。1500投稿（OWN/MARKET/COMPETITOR各500）＋100Termの実DBで、小Fixtureと同じSELECT/WITH数を確認した。

| 対象 | 小/大Fixture SELECT数 | 出力の構造 |
| --- | --- | --- |
| My Account list | 3 / 3 | page2、page_size7、返却7、total500 |
| Trend Ranking | 5 / 5 | limit7、返却7 |
| Popular Posts | 5 / 5 | limit7、返却7 |
| Competitor Top Posts | 4 / 4 | limit7、返却7 |
| Gap Analysis | 6 / 6 | 既存SQL集約・Topic×SNS |
| Overview | 16 / 16 | Trend≤5、競合≤3 |
| AI snapshot | 16 / 16 | 追加1500投稿でもPayload差1500bytes未満、投稿本文なし |
| OWN_POSTS Import10/100行 | 22 / 112 | retained Match SELECTが1行1件残る |
| ACCOUNT_DAILY Import10/100行 | 5 / 5 | 読取件数固定、日次UPSERTは既存行単位 |

Phase10/11/12の既存2000投稿規模・固定query・AI Payload上限Testも全維持。時間(ms)の成功閾値は使わない。

改善した構造はstartup回復の一括UPDATE、Uploadの受信制限、Keyなし集約省略、外部Payload分離、共通取得Hook。Analyticsの候補行Python読込→sort/slice、CSVProviderの全records保持、投稿Importの行単位UPSERT/retained Match読取・全Trend Rebuildは残す。単純SQL LIKE/Top N移動/Batch UPSERTではUnicode・NULL順・重複行後勝ち・MANUAL/AI保持・過去Trend semanticsを壊す可能性があり、数値契約の変更を伴う最適化を実施しない。

## Test・Build・Docker・DB・OpenAPI

| 検証 | 結果 |
| --- | --- |
| 既存Phase1〜12 | 980件成功。削除/Skip/Assertion弱体化なし |
| Phase13 Backend追加 | 82件成功 |
| Backend総数 | **1062 passed、Failed0 / Skipped0** |
| 最終imageでの全体実行 | docker compose run --rm -T --no-deps backend pytest -q -p no:cacheprovider、258.92秒 |
| Compose backendでの全体実行 | 1062 passed、94.41秒（固定413 bodyの最終差分前、応答内容同一） |
| Frontend Node test runner | **8 passed、Failed0 / Skipped0**、新Frameworkなし |
| npm run typecheck | 成功、Docker Node22 |
| npm run build | 成功、Next16.3.8、19 static routes、frontend Docker build内 |
| Docker backend/frontend build | 成功 |
| docker compose up -d | 通常Backendに復帰、db/backend healthy、frontend稼働 |
| Health | HTTP200、status=ok / database=connected |
| Alembic current / heads | `0001_initial (head)`、Migration追加なし |
| OpenAPI | 26公開Path、Import GET/POST、AI POST/Typed Schema、Overview GETを維持 |
| Test DB残存 / PROCESSING | 最終確認とも0 |
| git diff --check | 成功 |

新規82件: recovery5、Upload12、privacy/security56、performance9。Unit/TypeはDefault UTC、URL parse/encode、実在日付/逆転、Platform matrix、Competitor scope/dedup、古い応答/unmount無効化。

全体初回で既存Phase12のALL Cross-screen Testが失敗した。ランダムUUIDをAccount名にするfixtureと、OverviewのAccount名順/CompetitorのSNS順の違いにより、値が一致しても配列順が不定だった。**fixtureのInstagram競合名だけ固定**し、既存期待値・比較式・Assertionを変更していない。新規Testでは逆順になる名前も固定し、双方の既存順序とAccount IDごとの全値一致を明示検証した。分析仕様を変更して失敗を隠していない。

初期新規security Testではdependency overrideのdefault引数へService instanceを置き、FastAPIがquery defaultとして解釈したため500になった。引数なしclosureへ修正し、productionを変更せず新規Testを成功させた。

## Browser検証・証跡

Codex In-app Browser、PC1440×1000、最終Frontend、実Service＋使い捨てPostgreSQL。明示別起動`python -m tests.quality.browser_fixture`、Instagram応答6秒遅延。通常DBは変更せず、fixtureを通常停止した後DBを破棄し、通常Composeに復帰した。通常起動でfixture moduleをimportしない。

| 画面 | 確認 |
| --- | --- |
| Overview | Instagram再取得中にX-only Projectへ変更。最初からALL、IG disabled、旧Reach90が戻らずEmpty、From/To10-01/10-02一致 |
| My Account | IG分析/List遅延中に変更。ALL、IG disabled、旧投稿混入なし。From/To10-01/10-03、List/Analyticsとも一致 |
| Trend Explorer | IG Ranking/Popular遅延中に変更。ALL、IG disabled、Topic切替、旧Ranking混入なし。10-01/10-02一致 |
| Competitor | IG競合選択後の遅延中に変更。旧ID削除、新Project候補unchecked。新X競合だけ選び10-01/10-02で全3API取得。旧IG Account/数値混入なし |
| Gap | IG遅延中に変更。ALL、IG disabled、NULLの表/Partial Empty保持。10-01/10-02一致。逆転URLでalert、同条件retry、日付修正で復帰 |
| AI | 即時IG変更中にX-onlyへ。ALL、IG disabled、09-30/10-03一致、Keyなし生成disabled。識別可能な旧Project架空IGレポートの再取得を遅らせ、旧応答完了後も新Project Emptyを保持 |
| Import | ACCOUNT_DAILY正常1件SUCCESS。22 MiB File→HTTP413、REQUEST_TOO_LARGE、echoなし、履歴はSUCCESS1件のみ |

ブラウザーの日付自動fill→検索、DOM表示値、URL、Backendが実際に受けたqueryを照合した。各X-only Projectの初回分析queryがALLで、無効IG requestがないことを`Phase13_Browser_API_Conditions.json`（96イベント）から確認。API logは架空Project/Account IDと分析条件だけを抽出保存し、SQL/CSV/Secret/response本文を含めない。意図的Errorは400、巨大Uploadは413。Console error取得は空。手動カレンダー操作は未検証。

AI検証で表示した旧レポートはfixtureがDBへ保存した架空Content/Evidenceで、実OpenAI生成ではない。Keyなしの実AdapterでLatestを取得し、生成は実行していない。

証跡: [Overview](Phase13_Browser_Overview.jpg)、[My Account](Phase13_Browser_MyAccount.jpg)、[Trend Explorer](Phase13_Browser_Trends.jpg)、[Competitor](Phase13_Browser_Competitor.jpg)、[Gap](Phase13_Browser_Gap.jpg)、[Error](Phase13_Browser_Error.jpg)、[AI](Phase13_Browser_AI.jpg)、[Import成功](Phase13_Browser_Import_Success.jpg)、[Import413](Phase13_Browser_Import_413.jpg)、[実API条件](Phase13_Browser_API_Conditions.json)。Secret/個人データを含まない。検証Viewportを解除し、通常ComposeのPhase10 Browser Verification / Overview表示へ戻した。

## 既知課題・制限

- single-process recovery。multi-instance/workerはlease再設計が必要。
- 上記候補行のPython保持、Import行単位処理、CSV全records/Trend full rebuildは既存制約。大規模本番SLA/同時Upload負荷を保証する検証ではない。
- 最新Metric追加で過去Trendが変化するVersion1のFull Rebuild仕様を維持。
- Live OpenAI認証/利用権/課金/提案品質/latency、実SNS API、全Browser/モバイル/DPI、手動日付カレンダーは未検証。
- AI履歴一覧/削除、Demo Data整備、Portfolio Finishは追加しない。

## 変更ファイル

- Backend追加: core/import_request_limit.py、services/import_recovery.py。
- Backend変更: main.py、core/config.py、api/v1/imports.py / settings.py、services/insight_service.py。
- Test追加: tests/quality/{conftest,test_recovery,test_upload_limit,test_privacy_security,test_performance,browser_fixture}.py、__init__.py。
- Test変更: tests/conftest.py（startup DB分離）、tests/insights/test_api.py（ランダムfixture名固定のみ）。
- Frontend追加: lib/analysis-filters.ts、use-analysis-read.ts、tests/analysis-filters.test.cjs。
- Frontend変更: 6分析components、lib/my-account-api.ts / insights-api.ts、package.json。
- 設定/Docs: .env.example、docker-compose.yml、README、本報告書、9JPG、実API条件JSON。

## Git・Push・Review ZIP

Remote未設定を確認し、追加/Pushしない。実装Commitは`a1f515c6422ce1085f45d7e14acbec7381645907`（feat: harden Phase 13 reliability privacy and analysis state）。次に本報告書へのHash追記をCommitする。報告書Commit自身のHashは最終回答およびZIP HEAD commentで示す。

全Source・Docs・検証・Commit完了後、Repository Rootの最後の生成工程として以下を実行する。

```powershell
git archive --format=zip HEAD -o ../SNS_Analyzer_Phase13.zip
```

生成後はtracked編集/追加Commitを行わない。ZIPの存在・CRC・HEAD comment・全Git blob内容一致、Backend/Frontend/Tests/README/本報告書、禁止物/.env/実Key非混入を確認し、結果を最終回答へ記載する。

おすすめはZIPをレビューへ渡すこと。理由は数値契約を維持した品質修正と回帰/Browser証跡をまとめて確認できるため。今すぐ行うことはZIPと本報告書のレビュー。Phase14には進まない。
