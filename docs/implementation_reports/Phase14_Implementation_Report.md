# Phase 14 Implementation Report

実装日: 2026-10-04 (Asia/Tokyo)。開始HEAD: `0a0130675808c175dba451c74b9bf37c24b96d3c`。

## 結果と範囲

Canonical Demo、通常Import経由の投入CLI、保存済みDemo AI、総合Contractテスト、日本語 / English表示切替を実装した。既存の計算式、NULL / 0、Followers非合算、Source Type分離、DB Schema、API契約は維持した。Backend 1090 passed / 0 failed / 0 skipped、Frontend 17 passed / 0 failed / 0 skipped。Phase15は実装せず、Review待ちとする。

変更範囲: `backend/app/demo/{generator,loader,fixture_ai,audit}.py` とパッケージ、`backend/tests/demo/`、`demo_data/`、`.gitattributes`、Composeの読み取り専用Demo mount、Frontendのi18nモジュール・7画面と共通リンク・安全なエラー表示・テスト、README、本報告書・実測JSON・ブラウザー証跡。ProductionのProvider / Repository / Service / Migration / OpenAI Adapterには変更なし。新しいDependencyは追加していない。

## 再現可能な架空CSV

Anchor Date `2026-10-04`、開始日 `2026-07-07`、UTCの両端を含む90日。Random Seed `1401`、Generator Version `phase14-v1`。Python標準ライブラリで生成し、既存CSV SchemaのHeaderを使用する。UTF-8 / LF、固定Post ID、固定配列順、明示Seed。ManifestにはHeader・件数・Byte数・SHA256・期間・シナリオを保存した。同じ条件の生成結果は全Byte一致するテストを通過した。別Anchor / Seedも検証した。

| CSV | Dataset | 行数 | Byte数 |
|---|---|---:|---:|
| own_posts.csv | OWN_POSTS | 180 | 30060 |
| account_daily.csv | ACCOUNT_DAILY | 180 | 7893 |
| competitor_posts.csv | COMPETITOR_POSTS | 540 | 64967 |
| trend_posts.csv | TREND_POSTS | 4500 | 566574 |

いずれも20 MiB未満。個人情報・実SNS投稿・実Secretを含まず、本文・アカウントは架空と明示。日本語、絵文字、Hashtagなしを含む。`.gitattributes`でCanonical CSVとManifestをLFに固定し、Windowsの改行変換によるLoaderのHash不一致を防ぐ。

専用Project `14da0000-1401-5140-8140-000000000014` / `Phase14 Canonical Demo`。OWNはX / Instagramの2アカウント各90投稿。COMPETITORはXの270 / 180投稿とInstagramの90投稿の3アカウント。投稿頻度、平均Engagement、動画主体などの差を設定した。各SNSのFollowersはアカウント別に保存し、合算しない。

Topicは生成AI、業務効率化、AIエージェント、データ分析、動画生成、SNS運用の6件。各TopicにKeyword / Hashtagの2Term、計12Term。OWNはデータ分析100%、業務効率化74.4444%、生成AI10%のCoverage。Media TypeはTEXT / IMAGE / VIDEO / CAROUSELの4種類。10月1日のOWN2投稿は実値0、10月2日の2投稿は全Metric NULL。本文・TermのUnicodeと重複Topic一致を通常Matching経由で検証した。

## Loaderと安全性

手順の完全版はルートREADMEと`demo_data/README.md`。起動後に明示的なCLIで実行する。API起動時に自動投入しない。

```powershell
docker compose run --rm -T --no-deps backend python -m app.demo.loader --directory /demo_data/canonical --anchor-date 2026-10-04 --seed 1401
```

全CSVを一時生成してHash検証した後、専用Project / Account / Topic / Termを準備する。既存ImportServiceをOWN → COMPETITOR → ACCOUNT_DAILY → TRENDの順で実行し、既存PostMatching / TrendServiceによるFull Rebuildを使用する。sns_posts / post_topics / post_terms / trend_dailyやスコアを手書きで挿入しない。

通常再実行は既存専用Projectを検知して停止し、投稿、Metric、履歴、AIを増殖させない。`--reset-demo`は固定UUIDと専用Description Markerが一致する場合のみ、専用Projectのデータを再構築する。Marker不一致は拒否。Disposable DBで再実行・専用Reset・別Project保持を検証し、通常開発DBでは初回投入だけを行った。既存Demo / Browser Verification Projectを削除・更新していない。

GeneratorのDocker実行も実検証済み。Composeの同一Mount先を上書きする初回試行はread-onlyで失敗したため、READMEは異なる書き込み先を使用するコマンドに修正し、Canonical再生成の一致を確認した。

```powershell
docker compose run --rm -T --no-deps -v "${PWD}/demo_data:/demo_export" backend python -m app.demo.generator --anchor-date 2026-10-04 --seed 1401 --output /demo_export/canonical
```

## 通常ComposeでのImport・DB結果

| Dataset | Status | Success | Error | 秒 |
|---|---|---:|---:|---:|
| OWN_POSTS | SUCCESS | 180 | 0 | 2.742802 |
| COMPETITOR_POSTS | SUCCESS | 540 | 0 | 9.901964 |
| ACCOUNT_DAILY | SUCCESS | 180 | 0 | 0.565015 |
| TREND_POSTS | SUCCESS | 4500 | 0 | 52.967109 |

Import History 4件。全DBのPROCESSING残留0。検証後のDisposable Test Database残留0。

専用ProjectのDB件数: sns_posts 5220、post_metrics 5220、post_topics 5372、post_terms 10124、trend_daily 3240、account_metrics 450、import_histories 4、ai_insights 1、watch_topics 6、watch_terms 12、sns_accounts 5。Source TypeはOWN 180 / COMPETITOR 540 / MARKET 4500。ACCOUNT_DAILYはOWN180行であり、account_metricsにはCOMPETITOR投稿からの通常Followers snapshotも含む。

## Trend / Gapシナリオ・画面間Contract

既存計算式のまま上昇 / 下降と異なるスコアを確認した。生成AIのInstagram 97.87 / X 91.77、業務効率化X 92.12 / Instagram 90.09。AIエージェントはPost GrowthがInstagram -70.5882% / X -57.1429%、Trend Score 14.04 / 4.16で下降を示す。90日系列はTopic別に異なる山と最新期間の変化を持つ。

GapはOPPORTUNITY / BALANCED / HIGH_COVERAGE / LOW_PRIORITYの4分類が同時成立。生成AIInstagramはTrend 97.87、Own 10%、Gap 88.083。業務効率化はBalanced、データ分析はHigh coverageで実値Gap 0が2件、AIエージェントはLow priority。動画生成InstagramはTrend / Gap不明が1件。NULLを0座標に置かず、表で「—」と表示する。

BackendのMatrixはALL / X / INSTAGRAM × 7日 / 30日 / 90日 / カスタム17日の12組合せ。実APIのOverview / My Account / Gap / Trend / Competitorと実Evidence生成入力について値、ID、期間、SNS、並び順を比較した。OWN優先など既存Repositoryの順序契約を維持する。初回の新規テストはOWN優先順を考慮せず、またNULL分類を4分類集合に含めた誤った期待値で失敗した。既存実装・既存Assertionは変更せず、新規期待値を既存契約に合わせ、NULLを別の明示Assertionで確認した。その後、新規28件・全体1090件を通過した。

90日ALLのOverview / My Account: 投稿180、Reach 93392、Impressions 136256、Engagement 6928。X / Instagramは各90投稿、Followers各1467 / 1067、ALLのFollowers / ERを単純合算しない。Keyword「効率化実験」で134件、Hashtag「#分析ノート」で144件を実画面で確認。ページ送り・戻り・投稿詳細・Metric NULL / 0・分母0のER不明も確認した。期間前 / データなしのNULLと0はBackend Contractで確認した。

## Demo AI

専用CLIからだけDemoClientをInsightServiceに注入し、通常の集計・Evidence Validation・Append-only保存を通して1件生成した。model_name `demo-fixture`。Production prompt_version `phase12-v1`は保持し、実OpenAI Adapterを切り替えていない。固定Fixtureの内容、画面Banner、READMEで架空の参考レポートと明示。Fixture呼出1 / Live OpenAI呼出0、課金なし。

Market Trend / Own Analysis / Improvement Points / Next Post Ideasの4セクションを表示。実データのEvidence IDを使い、Reach 93392、Trend 97.87、Gap 88.083を画面間照合した。Keyなしでも保存済みレポートは閲覧でき、通常APIの新規生成は503で拒否されて追加保存されない。FrontendのRegenerateは無効。保存日時は実時計UTC、分析期間は固定Anchorである。

## i18n

`src/i18n/ja.ts` / `en.ts`の474個の意味ベースTranslation Keyを共有し、軽量な翻訳関数とReact Providerを追加した。対応Localeはja / en。Settingsの表示言語Selectで即時切替し、`sns-analyzer.locale`をlocalStorageへ保存する。ブラウザー再読込後もEnglishが復元され、jaへの戻りを確認する。SSRと初回Hydrationはjaを一致させ、その後保存Localeを復元するため、再読込直後に一瞬jaが見える場合がある。`html.lang`も同期する。

7画面の見出し、説明、固定ラベル、ボタン、Filter、表、Chart、Tooltip、Empty / Loading / Error、Navigation、enum表示を翻訳。API enum値・Filter値・内部型・DB値は維持。Role / Media Type / Import Status / Gap Classification / Direction / Term Typeは表示だけ変換する。Topic名、投稿本文、Hashtag、アカウント名、保存済みAI本文は翻訳しない。AI Contentは英語UIでも元の日本語のままである。

初期Locale未設定、未知値、空値、破損値、Storageアクセス拒否はja fallback。辞書Missing Keyはja → key fallback。Parityと画面で参照するLiteral Keyの存在をTestで検知する。エラーはAPIのCode / HTTP Statusを安全な翻訳文へ対応させ、未知のBackend例外メッセージやSecretを表示しない。

Frontend新規9 Testは初期ja、ja→en→ja通知、保存Locale復元、不正値 / Storage拒否Fallback、474 Key parity / 7画面Nav、Enum表示と内部値分離、Loading / Empty / Error、安全なMissing Key補間、画面Key存在を検証した。既存8 TestのAssertionは維持し、VMの依存Stubだけi18nに対応した。

## Performance / Memory実測

数値は通常Composeでの一回の観測であり、SLAや合否閾値ではない。同時にDocker build / Testが動いた環境でのLoader全体66.849698秒、生成・検証0.270435秒。Trend Full Rebuildの計測は0.033887 / 0.022285 / 1.206233秒。

| Operation | SELECT / WITH数 | 秒 |
|---|---:|---:|
| own_list | 3 | 0.049221 |
| trend_ranking | 5 | 0.021151 |
| popular_posts | 5 | 0.078983 |
| competitor_top | 4 | 0.087998 |
| gap | 6 | 0.038367 |
| overview | 16 | 0.224587 |

SQL本文や接続情報は記録せずQuery数のみ計測。AI外部向けPayload 10241 bytes、Project IDを除外。AuditプロセスのPeak RSS 95784 KiB (約93.54 MiB)。これはAuditの値でありImport全体のPeak Memoryを測定した結果ではない。CSV Providerの全行保持、Python側Candidate処理、通常row単位Import、Full Rebuildは維持しており、より大量データ・高並行負荷・Importピークメモリは未検証。詳細は`Phase14_Measurements.json`。

## Test・Build・Runtime

| 検証 | 結果 |
|---|---|
| 既存Backend | 1062 passed |
| 新規Backend | 28 passed (新規対象の単独実行76.97秒) |
| Backend全体 | 1090 passed / 0 failed / 0 skipped、239.81秒 |
| 既存Frontend | 8 passed |
| 新規Frontend | 9 passed |
| Frontend全体 | 17 passed / 0 failed / 0 skipped、最終Docker実行2641.72 ms |
| typecheck | `tsc --noEmit`成功 (Docker build stage / host) |
| build | Backend / Frontend Compose build成功、Next production build 19 routes |
| Runtime | DB healthy / Backend healthy / Frontend running |
| Health | HTTP 200、status ok / database connected |
| Alembic | current / heads `0001_initial (head)` |
| Schema / API | アプリ13テーブル、OpenAPI26 paths、変更なし |
| Recovery / Security / Privacy / Query契約 | 既存Phase13 Test含め全成功 |

```powershell
docker compose run --rm -T --no-deps backend pytest -q -p no:cacheprovider
docker build --target build -t sns-analyzer-frontend-check ./frontend
docker run --rm sns-analyzer-frontend-check npm test
docker run --rm sns-analyzer-frontend-check npm run typecheck
```

Frontend TestのREADME例は、NodeのみのSource bind mountでTypeScriptが欠ける例から、依存を`npm ci`するDocker build stage imageへ修正した。Host node_modulesを含めないDocker build contextから上記commandを実行して成功。独立PCでのcloneは行っていないが、Test imageはHost依存を使わずビルドした。Backend総合TestはDisposable DBを使用し、通常開発DBへの破壊的Testを行わなかった。

## Browser証跡

実Frontend / Backend / PostgreSQL、1440 × 1000 PC viewport。分析画面は同じProjectと固定90日期間 `2026-07-07` ～ `2026-10-04`、ALLを基本に比較。Settingsは期間Filterのない画面。Englishで全7画面のLayout、固定ラベル、表・フォームを確認した。日本語 / English切替・再読込保持・元のデータ文字列保持を確認した。ブラウザーで全Matrixは実施していない。

| 画面 / 検証 | ファイル |
|---|---|
| Overview 日本語 | [Phase14_Browser_Overview_JA.jpg](Phase14_Browser_Overview_JA.jpg)、[Overview](Phase14_Browser_Overview.jpg) |
| Overview English | [Phase14_Browser_Overview_EN.jpg](Phase14_Browser_Overview_EN.jpg) |
| My Account English | [Phase14_Browser_MyAccount.jpg](Phase14_Browser_MyAccount.jpg) |
| 投稿詳細 / NULL / 0 | [Detail](Phase14_Browser_Post_Detail_EN.jpg)、[NULL](Phase14_Browser_Post_NULL_EN.jpg)、[Zero](Phase14_Browser_Post_Zero_EN.jpg) |
| Trend Explorer English | [Phase14_Browser_Trends.jpg](Phase14_Browser_Trends.jpg)、[下降](Phase14_Browser_Trends_Down_EN.jpg) |
| Competitor English | [Phase14_Browser_Competitor.jpg](Phase14_Browser_Competitor.jpg) |
| Gap English | [Phase14_Browser_Gap.jpg](Phase14_Browser_Gap.jpg) |
| AI English / Evidence | [Phase14_Browser_AI.jpg](Phase14_Browser_AI.jpg)、[Evidence](Phase14_Browser_AI_Evidence.jpg) |
| Settings / Import English | [Phase14_Browser_Settings.jpg](Phase14_Browser_Settings.jpg) |
| Language / Form | [Language](Phase14_Browser_Settings_Language.jpg)、[Account](Phase14_Browser_Account_Edit_EN.jpg)、[Term](Phase14_Browser_Term_Edit_EN.jpg) |

Console error / warnを最大100件で取得し、0件を確認した。Gapのhtml.lang=en、body scrollWidth=viewport width=1440でページ全体の横方向はみ出しなし。散布図の有効11点とNULLの表内表示を確認。ScreenshotはChart animation途中の初回画像を描画完了後に再取得した。編集フォームは表示・Cancelのみであり、設定データを変更していない。

## 既知課題と停止点

実SNS API、Live OpenAI、Production deploy、認証、AI履歴一覧 / 削除、モバイル / DPI網羅、独立PC smokeは未実施。保存済みAIの内容をLocaleで翻訳しない。英語の長いラベルは必要に応じて改行・表内スクロールを利用する。大規模データ・高並行負荷・Importピークメモリは将来検証事項。

Phase15のPortfolio向けREADME最終美装、Architecture図、Screenshot選定・トリミング、職務経歴書説明、GitHub公開整理は行っていない。Review ZIP → ChatGPT Review → 承認 → Phase15指示書の順で進める。

## Git / Review ZIP

実装Commit: `d606040d2ffb97164c455acbaef13de5ae32cf3e` (`feat: add Phase 14 canonical demo and bilingual UI`)。56ファイルを変更し、変更差分の空白チェックと実Secret pattern確認を通過した。全17枚のPhase14 Browser証跡を追跡対象に含めた。最終Browser確認では日本語Overviewの固定90日デモデータ表示とConsole error / warn 0件を確認し、PC viewport overrideを解除してデモ画面を残した。

このHashを記録する報告書Commitを最終HEADとする。報告書Commit自身のHashは循環参照を避けて本文に埋め込まず、ZIP commentと最終回答で報告する。PushはRemote未設定のため未実施。ZIPのCRC / 最終HEAD / Canonical Hash / 禁止物チェックは、生成後にRepository外の検証スクリプトで行う。

実装Commitと、実装Hashを記録する報告書Commitを作成する。Remote未設定のためPushしない。全実装・Test・Browser確認・報告書・Commit後、最後に`git archive --format=zip HEAD -o ../SNS_Analyzer_Phase14.zip`で生成する。ZIP生成後はtracked Sourceの編集・追加Commitを行わない。

最終ZIPはCRC、HEAD comment、全tracked file / Git blob一致（通常SourceのCRLFはLF正規化比較）、Canonical CSVのManifest SHA256一致、必須成果物、禁止生成物・実Secret非包含を検証する。Archive外の検証結果は最終回答で報告する。
