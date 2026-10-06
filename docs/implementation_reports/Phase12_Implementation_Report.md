# Phase 12 Implementation Report — AI Insights

実装日: 2026-10-03（Asia/Tokyo）。Phase12のみ。Phase13以降は実装しない。

## 正本確認・優先順位

添付Phase12指示書、正本5資料、README、Phase11 Implementation Reportを全文確認した。

- SNS_Trend_Performance_Analyzer_基本設計書_Ver1.1.md
- SNS_Trend_Performance_Analyzer_画面設計書_Ver1.1.md
- SNS_Trend_Performance_Analyzer_API設計書_Ver1.1.md
- SNS_Trend_Performance_Analyzer_DB詳細設計書_Ver1.1.md
- SNS_Trend_Performance_Analyzer_Codex_Phase計画_Ver1.0.md

正本→Phase1〜11公開仕様→Phase12指示書→未定義箇所だけ最小補足、の順で実装した。既存Engagement/Rate/Trend/Gap/Classification/Followers/Latest Snapshotの数値規則は変更していない。DB13テーブル、Migration `0001_initial (head)`を維持した。

## API・Route・正本との差分

```text
GET  /api/v1/projects/{project_id}/insights/latest
POST /api/v1/projects/{project_id}/insights/generate
Frontend: /dashboard/insights
```

正本のPathを採用。指示書Fallbackの`/ai-insights`系へ置き換えていない。GETは必須from/to、platform=ALL/X/INSTAGRAM（default ALL）。POSTはTyped JSON `{platform, from, to}`、成功201、新規保存済みInsightを返す。UUID/date/enum、from<=to、3660日inclusive上限、Project存在、有効Platformを既存Helperで検証する。400/404/422/500/503は共通`error:{code,message,details}`。入力値・SQL・SDK例外を応答へ転載しない。

POST正本Responseの`insight_id / generated_at / sections / evidence`を維持。`sections.market_trend / own_analysis`は文字列、`improvement_points / post_ideas`は文字列配列のまま。DB正本content例の4区分名も保持した。指示書Fallbackの`market_trends[] / next_post_themes[]`構造へ置き換えていない。

追加仕様はcontent.summary、cautions、references。市場/自社の根拠ID配列、改善案/投稿案と同じ順序の根拠ID配列を付ける。Pydanticで個数一致を検証し、すべてのIDが保存するEvidenceに実在することを保存前に検証する。主要文章は空文字不可、各1600文字まで。改善案/投稿案/注意事項は各最大5件、データ不足時の0件を許容。根拠は各主要Itemにつき1〜8件。extra fieldsは禁止。

GETのResponse詳細は正本に未定義なので`{insight, ai_generation_available}`を補足した。同じProject＋DB platform（ALL=NULL）＋analysis_from/toに完全一致する最新created_at、同時刻はUUID DESC。該当なしは正常Empty。別SNSや別期間へのFallbackは行わない。Phase11 Overview既存AI選定は変更せず、その保存期間メタデータを表示する。

旧Ver1.1形式の4区分JSONは読み取り時だけTyped sectionsへ対応付け、content=nullとlegacy_evidenceを返す。画面に旧形式・根拠参照なしを明示する。既存行を書換えたり、架空のEvidence IDを生成したりしない。Phase11の未知JSON保持仕様も維持した。

## SDK・Responses・モデル・Prompt

- Python3.12、OpenAI SDK **3.24.0**を固定。SDKが使用するhttpx2=2.13.1/httpcore2=2.13.1、jiter=0.17.0、sniffio=1.3.1、truststore=0.10.4も固定した。既存httpx=0.28.1は既存API Test互換のため維持。
- 専用`OpenAIInsightClient`へSDKを隔離。ServiceへClientを注入可能。実装時にインストール済みSDKのOpenAI/Responses.parseシグネチャを確認した。
- `client.responses.parse(model=..., input=[developer instructions, user JSON], text_format=AIInsightContent, store=False, max_output_tokens=6000)`。
- `response.output_parsed`を使用。自由JSONテキストのparseやoutput固定位置参照はない。全outputのmessage contentを走査してrefusalを検出する。完了以外/parsed欠落/Schema不正を拒否する。
- Tools、Web Search、File Search、MCP、Conversation、previous_response_id、Assistants APIは使用しない。
- `OPENAI_MODEL`（default gpt-6-luna）から取得。実Response.modelを保存し、取得できない場合だけ設定値を使う。
- `PROMPT_VERSION=phase12-v1`。入力のみ、日本語、未提示データや数値の創作禁止、因果関係/成果の断定禁止、NULL≠0、SNS/Rate分母非混合、保存Trend/Gapを保持、実在ID、判断材料不足、Topic文字列は命令ではなくデータ、と明記した。
- API keyは環境のみ、reprから除外。DB/Frontend/Prompt/ログ/Report/証跡へ値を出さない。.env.exampleは空キー。

確認した公式資料: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)、[Responses移行ガイド](https://developers.openai.com/api/docs/guides/migrate-to-responses)、[Model一覧](https://developers.openai.com/api/docs/models)。実モデルへのアクセス権・実API生成品質/Latencyは未検証。公式資料確認と、実SDKをMockTransportで通す検証を区別する。

## input_summary・Evidence・上限

Overview Typed結果から必要な集約だけを取り出す。Account名/display_nameを除外し、投稿本文/著者名/ユーザー名/raw_data/raw_metrics/投稿一覧/日次全Series/以前のAI本文をPayloadへ含めない。

| 内容 | 再利用・上限 |
| --- | --- |
| analysis_scope | Project UUID、ALL/X/INSTAGRAM、from/to、timezone=UTC |
| previous_period / own_kpi | Phase11の前期間比較＋Phase7共通KPI、Rate Group、OWN Account別最新Followers |
| market_trends | Active Topic×SNS、期間内最新7-day保存Snapshot、Top5。Term除外、Score/Growth/平均は保存値 |
| competitor_summary | Phase9共通結果のActive競合最大3件、Account ID/SNS/各指標/Rate Groups/Follower |
| competitor_aggregate | Phase11のActive全競合の投稿から集約。全AccountのFollower配列は除外し、最大3選択AccountのFollowerだけを送る |
| opportunity | Phase10共通Gap先頭最大1件。Trend/Own比率/競合比率/Gap/分類/分子分母を維持 |

Active OWNは既存DB制約でSNSごと最大1件、対象SNS2つなのでFollower内訳最大2件。Rate Groupsは対象SNS×既存3分母種類に限定。Payload全体はUTF-8最大48000 bytes。2000 OWN投稿を追加しても、件数/合計の桁数等の変化だけでPayload件数は増えないことをテストした。

正本基本設計の入力候補には投稿時間帯もあるが、既存Phase7〜11には時間帯集約の公開Helperがない。Phase12で新しい分析を独自再実装せず、未提示として扱う。自社テーマの指標はGap先頭のOwn Post Ratioを再利用する。時間帯・全Topic分布の追加は将来検討とし、AIが数値を補完しないPromptにした。

EvidenceはTyped `kpis / trends / competitors / opportunities`。各Itemはid/label/values、例はKPI_REACH、KPI_ENGAGEMENT_RATE、TREND:TopicUUID:SNS、COMPETITOR:AccountUUID、GAP:TopicUUID:SNS。同じSnapshotの値をJSONB保存する。Content内のreferences⊆Evidence IDを検証し、未知IDは503でINSERTなし。根拠UIは保存済みの参照Itemを展開するだけで、再度AIを呼ばない。

## Snapshot・外部API・保存境界

1. `with read(project_id)`でread-only / REPEATABLE READ。Overviewの同一Session内部Helperを使い、input_summary/evidenceを完成する。
2. Read Sessionを閉じ、Connection/Transactionを解放した後にOpenAIを呼ぶ。Structured Contentと根拠IDを検証する。
3. 別の短いWrite Session/TransactionでAIInsightをINSERT。JSONBはmodel_dump(mode='json')。flush後にResponseを組み立て、Commit成功後だけ返す。Commit後の元分析再読込はない。

`OverviewService.overview_in_session`は元のOverview本体を抽出しただけ。公開GET、16 SELECT/WITH、Single Snapshot、Phase11全67テストを維持した。KPI/Trend/競合/Gapが同じSnapshotであること、途中の別接続更新でも旧値が一致すること、Fake API呼出時にDB Connectionが0であること、API後の元Metric更新がEvidenceを書換えないことを実PostgreSQLで確認した。

再生成は同じscopeでも新UUID/created_atのINSERT。UPDATE/DELETE機能なし。OpenAI失敗/不正根拠で新規行なし、旧行保持。保存失敗はRollback、安全な500 AI_SAVE_ERROR、成功を返さない。通常開発DBへ検証用AI行を追加していない。

## 障害・費用・Security

| 条件 | 処理 |
| --- | --- |
| Key未設定 | 起動/Health/既存分析は正常。GET available=false、画面に設定案内、ボタン無効。POST503 AI_KEY_NOT_CONFIGURED |
| Authentication / Rate Limit | 503 AI_AUTHENTICATION_ERROR / AI_RATE_LIMIT、設定確認または時間をおいた再試行 |
| Timeout / Network / SDK 5xx | 503 AI_TIMEOUT / AI_CONNECTION_ERROR / AI_SERVICE_UNAVAILABLE |
| incomplete / refusal / parsed欠落 / Schema不正 | 503 AI_INCOMPLETE / AI_REFUSAL / AI_INVALID_OUTPUT |
| 未存在Evidence | 503 AI_INVALID_EVIDENCE、INSERTなし |
| Input bytes上限超 | 503 AI_INPUT_TOO_LARGE、外部APIなし |
| Save失敗 | 500 AI_SAVE_ERROR、Rollback |

SDK retry=0。`OPENAI_TIMEOUT_SECONDS`は1〜120秒、不正値/NaNは30秒。SDKの有限I/O timeoutであり、生成Request全体の厳密な30秒deadlineではない。再試行はユーザーの明示操作のみ。入出力の上限、集約のみ、store=false、Overview生成なし、Polling生成なしで費用を抑える。

ログはproject/platform/status code/elapsedのみ。Prompt/input全文/raw response/SDK例外/request ID/SQL/資格情報を出さない。KeyをFrontendへ返すのはBooleanだけ。文字列データはdeveloper instructionsと別user JSONに置き、Topic内の命令を実行しない。Secret自体を入力へ渡さない。XSSはReactの通常文字列描画、HTML注入なし。

## UI・既存画面連携

レポート型、チャットではない。Project・有効SNS・7/30/90日・任意UTC期間、Generate/Regenerate、最終生成/Model/Prompt/保存期間、Summary、4区分、注意事項、Item別Evidence Expandを実装した。NULLは—、実値0は0、Array/Object内のNULLも維持する。

Loading Skeleton、Generating、Regenerating（旧レポート表示を保持）、Error/再試行、Empty/Import誘導、Generatedに対応。生成中disabled＋同期Refで二重操作を防ぐ。Project keyによるUnmount、GET/POST共通Request version、条件変更時の即時invalidate/clearで古い応答を破棄する。

AI画面内では、切替先Projectに無効なSNSをALLへ補正してから初回APIを呼ぶ。大規模共通Filter Refactorはしていない。Overview AI Summaryから条件付きリンク、既存主要5画面＋SettingsへAIリンクを追加。Overviewの生成呼出は0、既存ai_summary選定規則はそのまま。

任意日付の自動fillはReact draftへ反映されない挙動が出たため、AI画面だけ検索時にFormDataのnamed date inputsから値を確定する実装へ変更した。既存画面の日付処理は変更していない。

## Test・Build・Docker・DB・OpenAPI

| 検証 | 結果 |
| --- | --- |
| 既存Phase1〜11 | 908件維持。Test削除/Skip/期待値変更/Assertion弱体化なし |
| Phase12新規 | 72 passed、Failed0 / Skipped0 |
| 最終全Backend | **980 passed（908＋72）、Failed0 / Skipped0、149.22秒** |
| pytest実行 | `docker compose exec -T backend pytest -q -p no:cacheprovider`、使い捨てPostgreSQL |
| SDK | Fake SDK＋実SDK/httpx2 MockTransport。ネットワークなしでstrict JSON Schema/Pydantic parseまで検証 |
| npm run typecheck | 成功、Docker Node22 |
| npm run build | 成功、frontend Docker内、19 static routes |
| Docker build backend/frontend | 成功 |
| Docker up | db/backend/frontend起動、通常Adapterへ復帰 |
| Health | HTTP200、status=ok / database=connected、Key未設定 |
| Alembic current / heads | 0001_initial (head)、追加Migrationなし |
| OpenAPI | 正本GET/POST、UUID、enum、date、Typed Request/Response、400/404/422/500/503 Error Schema掲載 |
| Test DB残存 | 検証後0 |
| git diff --check | 成功 |

72件はscope分離、UTC/OWN/前期間、NULL/0/Rate分母、Follower非合算、Topic/Term/latest/stored Score、最大5/3/1、2000投稿、全画面値一致、append-only、latest隔離、Keyなし、障害別安全エラー、既存結果保持、不正根拠、read-only/repeatable read、並行更新、API時Connection0、保存失敗、Validation/OpenAPI、Prompt分離、実SDK署名/Strict parse、Schema上限、環境timeout、旧形式読取を含む。

初回全体テストでは新規scope隔離Testが追加Projectを残して既存DB件数テストを失敗させた。新規Test側でfinallyによる後片付けを追加し、既存Testや期待値を変えず全980件を成功させた。通常開発DBには影響しない。

## Browser証跡

Codex In-app Browser、PC1440×1000、最終Frontendと通常Compose/Fake専用Backendを使用。Fakeは別起動`python -m tests.insights.browser_fixture`、使い捨てDB、production appからimportしない。実OpenAI生成ではない旨をFake本文に明示。通常DBを変更せず、Fake終了時にそのDBを破棄する。

- 通常ComposeでKey未設定、生成disabled、正常Empty、Overviewとの同条件往復を確認。
- FakeでEmpty→Generating（disabled）→Generated、4区分、Metadata、Evidence展開、Reach=0/previous=NULL→—を確認。
- 再生成成功で新しい本文/日時へ更新。3回目のFake TimeoutでError＋2回目の保存結果を保持。
- Instagram GETを6秒遅延、ALL GETは0.5秒。ALL保存結果が先着後、旧Instagram応答が到着してもALLレポートを保持。
- 4秒の生成中に30日→7日へ切替。旧POSTは元の30日行を保存するが、7日画面はEmptyのままで上書きされない。
- X/90日生成中に別Projectへ切替。旧POST到着後も新Project Emptyを保持。
- Instagram選択後、XのみProjectへ切替。ALLに補正され、Instagram disabled、無効SNS APIの通常404なし。
- 7/30/90日とURL更新、保存結果をOverview AI Summaryで確認、AI画面へ戻るとFilter/Project保持。Console errorなし。
- 最終FrontendでFrom日付inputを2026-10-01へfill→検索し、URL・nav・実API取得期間・AIレポート期間が10-01〜10-03となることを確認。完全一致の保存行なしのEmptyを確認した。自動fillでの実際のフォーム値反映は検証済み、手動カレンダー操作は未検証。

証跡: [Key未設定](Phase12_Browser_AI_KeyMissing.jpg)、[Empty](Phase12_Browser_AI_Empty.jpg)、[Generating](Phase12_Browser_AI_Generating.jpg)、[Generated](Phase12_Browser_AI_Generated.jpg)、[Evidence](Phase12_Browser_AI_Evidence.jpg)、[Regenerating](Phase12_Browser_AI_Regenerating.jpg)、[Error/旧結果保持](Phase12_Browser_AI_Error.jpg)、[任意期間](Phase12_Browser_AI_CustomPeriod.jpg)。Key/Secret値は写っていない。Viewportは検証後解除する。

## 既知課題・Phase13候補

- 実OpenAIネットワーク生成、実キーの認証/課金/モデル利用権、提案品質は未検証。Fake/MockTransport検証と区別する。
- 全Browser/モバイル/DPI、大規模本番SLA、timeoutの厳密wall-clock deadlineは未検証。
- 既存全画面のProject/SNS補正と共通Filter整理はPhase13候補。今回AI画面だけ対応。
- 追加の時間帯分析や広範な自社Topic分布は別途正本との仕様確認が必要。未提供値は創作しない。
- append-only履歴の一覧/削除、Usage課金管理は対象外。

## 変更ファイル

- Backend追加: app/api/v1/insights.py、app/schemas/insights.py、app/services/insight_service.py、openai_insight_client.py。
- Backend既存: app/main.py（Router登録）、services/overview_service.py（Session内部Helper抽出）、requirements.txt。
- 設定: .env.example、docker-compose.yml。
- 新規Test: backend/tests/insights/{__init__,conftest,test_api,test_adapter,browser_fixture}.py。
- Frontend追加: src/lib/insights-api.ts、src/components/ai-insights.tsx、ai-insights-link.tsx、src/app/dashboard/insights/page.tsx。
- Frontend既存ナビ: overview/my-account/trend-explorer/competitor/gap-analysis/settings.tsx。
- Docs: README、本報告書、Phase12 JPG証跡。

## Git・Push・Review ZIP

開始時master、clean、HEAD `e7b10f5876791e84fa2061b1dc502222cd68b3a4`。実装Commit→報告書Hash追記Commitの順で保存する。Remote未設定を確認したため、追加せずPushしない。Hashは最終回答に記載する。Fakeサーバーを正常停止/削除し、通常Composeへ復帰後、Key未設定/Health200/DB接続/使い捨てDB残存0を再確認した。最終AI画面を開き、検証用Viewport指定を解除した。

実装Commit: `618d3d13bd126050893cbce4e9891ed0e3115dbd`（feat: implement Phase 12 AI insights with saved evidence）、34ファイル。このHash追記を報告書Commitとする。報告書Commit自身のHashは最終回答とZIP HEAD commentで示す。

すべての検証/Docs/Commit完了後、Repository Rootの最終生成工程として`git archive --format=zip HEAD -o ../SNS_Analyzer_Phase12.zip`を実行する。ZIP生成後にtracked編集/追加Commitなし。存在/CRC/最終HEADコメント/全blob内容一致、Backend/Frontend/Tests/README/本報告書、禁止物/.env/実キー非混入を検証する。結果は生成後に本書へ追記せず最終回答に報告する。

おすすめはZIPをChatGPTレビューへ渡すこと。理由はPhase12の回帰・Snapshot・根拠・障害証跡をまとめて確認できるため。今すぐ行うことはZIP/本書のレビュー。Phase13は自動実装しない。
