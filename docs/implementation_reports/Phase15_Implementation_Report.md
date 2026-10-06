# Phase15 Implementation Report — Version 1 Portfolio Finish

実装・検証日：2026-10-04（Asia/Tokyo）。開始HEAD：`e033ee8e5877a27a665a577737cb04861354bec9`。添付Phase15指示書を実装範囲とし、新機能Phaseへは進めていません。

## 成果物と変更ファイル

- [README 日本語](../../README.md)・[README English](../../README_EN.md)：課題・価値、8機能、技術、Quick Start、Demo、分析／AI／Language、品質、制約と未実装Roadmap。主要画像は各3枚。
- [Technical Reference](../technical_reference.md)：開始HEADの旧README本文を保全し、移動に伴う相対リンクを修正。冒頭に現行SQLと歴史資料の区別を追記。
- [Architecture](../portfolio/architecture.md)：構成、CSV Data Flow、Service／Repository責務、13テーブルとFK、AI境界。
- [CSV仕様](../portfolio/csv_spec.md)：4 Dataset、Required Header／Value、NULL／0、日時、上限、取込Transaction。
- [Analytics](../portfolio/analytics.md)：Trend固定Weight 40/30/20/10、UTC 7日Window、Cohort、NULL、Gap算式と4分類。
- [AI設計](../portfolio/ai_insights.md)：共通集計、read-only Snapshot、Structured Outputs／Evidence、接続とPrivacy、Fixtureとの区別。
- Project Summary：[日本語](../portfolio/project_summary_ja.md)・[English](../portfolio/project_summary_en.md)。日本語1行100文字／短文292文字／詳細780文字（本文のみ、改行除外）。要件・DB・Backend・Frontend・AI・品質の実装範囲を記載。
- [Screenshot Gallery](../portfolio/screenshots.md)、同階層のscreenshots/*.jpg 8枚、[Browser確認記録](../portfolio/browser_checks.json)、[Runtime確認記録](../portfolio/runtime_checks.json)、[文書・Manifestチェック](../portfolio/check_docs.py)。
- 過去Phase2／4／5／6 Implementation Reportの個人Author／Email・PCの絶対Pathを一般表記へ置換。技術内容・当時の件数・制約・hashは保全。
- 重大起動不具合への限定修正：`backend/app/repositories/trend_repository.py`、`backend/tests/trends/test_repository.py`、新規`backend/tests/demo/test_cli_startup.py`。

## 新規DBで発見した起動不具合と停止判断

Quick Startの独立新規DBで、標準 `python -m app.demo.loader --anchor-date 2026-10-04 --seed 1401` がMARKET 4500行のTrend Rebuild中に失敗しました。PostgreSQLログで `canceling statement due to statement timeout` を確認。OWN／COMPETITOR／DAILYはSUCCESS、MARKETはFAILEDでした。新規環境を作り直し、同時build／testを止めても再現しました。

実Sessionは既存の `statement_timeout=3000`。従来の全体 `row_number()` サブクエリを最新指標取得に使っていました。新規投入直後の統計とJOIN計画によりサブクエリ再走査が増える可能性は推論であり、正確なEXPLAINベンチマークとしては主張しません。確認した事実は標準CLIのtimeoutと修正後の成功です。

指示書の「新しい重大不具合を発見しない限り変更しない」「勝手に大規模修正せず、Phase 15 Reportへ記録して停止判断すること」に基づき、必須Quick Startを妨げる不具合として、DB Schemaやtimeoutを変えず1箇所のSQL取得に限定して修復しました。外側のMARKET投稿ごとに既存Indexを使い `LEFT JOIN LATERAL`／`recorded_at DESC LIMIT 1` で最新PostMetricを取得します。指標なしはNULL、Project／MARKET限定、最新Snapshot、固定6 SQLの契約を維持。計算式・Weight・API・Migration・CSV・Demo Generator・Frontendは変更していません。大規模最適化は実施していません。

診断用の一時DBでは30秒timeoutの独自Sessionで投入成功しましたが、これは標準手順の検証成功とは扱わず、repoのtimeout変更もしていません。PGOPTIONSを使う試行も成功せず、設定が有効だったとは主張しません。

修正前に本物のCLIを子processで新規の破壊可能テストDBに実行する回帰テストを追加し、1 failed（44.48秒）で再現を確認。修正後の初回全testは新規CLIテストが通り、旧SQL形状を要求する既存assertだけが失敗（1090 passed／1 failed、242.57秒）。このassertを相関条件・DESC・LIMIT・LATERAL・6 SQL維持の検証へ更新し、既存最新指標／NULL等の意味テストを残しました。最終全testは下記のとおり成功しています。

## Test / Build / Runtime

| 検証 | 最終結果 |
| --- | --- |
| Backend `docker compose run --rm -T --no-deps backend pytest -q -p no:cacheprovider` | **1091 passed、Failed 0、Skipped 0、203.77秒** |
| Frontend `docker run --rm sns-analyzer-frontend-phase15-check npm test` | **25 passed、Failed 0、Skipped 0、2695.26291 ms** |
| Frontend `npm run typecheck` | 成功 |
| Docker build target build／明示的 `npm run build` | 成功、Next.js 16.3.8、production 19 routes |
| 通常Compose build／up | Backend／DB healthy、Frontend稼働 |
| HTTP `/api/v1/health` | 通常8000／新規18000とも200、`ok / connected` |
| Alembic current／heads | `0001_initial (head)`、追加Migrationなし |
| OpenAPI | 通常／新規とも26 paths |
| DB | 通常／新規とも業務13 tables（alembic_version除外） |
| 終了後残留 | PROCESSING 0、`sns_phase2_test_*` DB 0 |

開始時のBackend 1090件に、標準Sessionによる新規CLI回帰1件を追加しました。Frontendの実装変更はなく、上記test／typecheck／buildをPhase15で再実行済みです。buildにはDocker cacheを利用しています。依存取得をすべてcacheなしで検証したという意味ではありません。

## Quick Start / Demo / Manifest

Git tracked sourceと今回の変更をTEMPの独立checkout相当へコピーし、`.env.example`から作った専用設定、別Compose project `sns-phase15-clean`、別DB volume、localhost ports 13000／18000／15432で再現。通常環境の `.env`、DB、他Projectをresetしていません。Migration→標準Demo CLI→HTTP／Browser確認を実施しました。修正後は標準3000ms timeoutのまま4 importすべてSUCCESS。

| Dataset | 行数 | import所要秒（新規環境の1回測定） |
| --- | ---: | ---: |
| OWN_POSTS | 180 | 2.090521 |
| COMPETITOR_POSTS | 540 | 5.967087 |
| ACCOUNT_DAILY | 180 | 0.265455 |
| TREND_POSTS | 4500 | 54.467741 |

CLI total 63.446662秒、MARKET Trend Rebuild 1.525035秒。性能保証ではありません。Anchor 2026-10-04、seed 1401、2026-07-07から90日。生成Fixture call 1、Live OpenAI call **0**。

通常／新規とも sns_posts 5220、post_metrics 5220、post_topics 5372、post_terms 10124、trend_daily 3240、account_metrics 450、import_histories 4、ai_insights 1、watch_topics 6、watch_terms 12、sns_accounts 5。4分類、Gap 0が2件、NULLが1件。Top Trendは生成AI／Instagram 97.87、業務効率化／X 92.12、生成AI／X 91.77。AI集計payload 10241 bytes。読取SELECTはown_list 3／ranking 5／popular 5／competitor_top 4／gap 6／overview 16。詳細はRuntime記録を参照。

[Canonical Manifest](../../demo_data/manifest.json)と4 CSVのraw SHA256・bytes・行数・headersを照合し一致。Phase14からデータとhashを変更していません。新規検証後は専用Composeを `down -v` し、専用container／network／volumeのみ削除しました。

## Screenshot / Browser

8枚すべて2026-10-04に現行UIから取得。架空Canonical Demo、ALL、UTC 90日、Viewport 1440×1000。Settingsのみ期間機能なし。全ページ画像は幅1424px（scrollbar除外）。Trendは描画完了を確認した比較セクションをnative Screenshot clipで1240×640px保存しました。fullPage取得時のアニメーション再開により途中の線が写った初期画像は差し替え済み。データ加工や描画実装の変更はしていません。

| ファイル | 内容 |
| --- | --- |
| 01_overview_ja.jpg | KPI・Trend・競合・Gap・AI |
| 02_my_account_ja.jpg | 自社分析・投稿とSnapshot |
| 03_trend_explorer_ja.jpg | 複数Term／SNS比較、UTC時系列 |
| 04_competitor_ja.jpg | 自社＋3競合 |
| 05_gap_analysis_ja.jpg | 11点・4分類・表 |
| 06_ai_insights_ja.jpg | Fixture表示、4区分、Evidence展開 |
| 07_settings_language_ja.jpg | Language設定、4 SUCCESS import |
| 08_overview_en.jpg | 英語固定UI |

日本語7画面、英語Overview／Settingsを実Browserで確認。Gap ALLはrefresh後もtable 12行／実表示11点、X circle 6／Instagram diamond 5、各bbox正、4色／4分類、凡例・Opportunity Zone・NULLは表のみ・実値0保持を確認。ブラウザーconsole error／warnは0。詳細DOM／Tooltip文字列はBrowser記録へ保存。

Tooltipは実画面のkeyboard ArrowRightでXとInstagramを表示し、Topic・Platform・Score／UTC日・Own Ratio・Competitor Ratio・Gap・分類を確認。実pointer hoverは操作APIに機能がなく**未検証**。画像だけでhover成功とは扱いません。Inactive表示は独立DBに作成した専用Fixtureを無効化し、JA「（無効）」／EN「(Inactive)」を実際に確認。通常Canonicalを無効化せず、専用DBは削除済み。最終通常UIは日本語へ復元。

## 文書リンク / Secret / Personal Data / Forbidden Files

`backend/.venv/Scripts/python.exe docs/portfolio/check_docs.py` でREADME／English／demo README／docs全Markdownのローカルリンク・HTML画像参照を検査。コードフェンス内の例と外部URL、同一ページanchorは除外。リンク先ファイルの存在を検証し、外部リンクのHTTP到達性とheading anchor一致は検証対象外。最終結果：27 Markdown、160 local links、missing 0。4 CSVのhash／bytes／rows／headers一致。

公開対象317ファイルをOpenAI key形状、秘密鍵header、長いBearer、個人mail、PC Users絶対Path、電話形状で走査。高リスクpattern hit 0、実設定credentialの内容一致0。実 `.env` はignoredで保全、OpenAI keyは未設定、exampleはblank／change_me。test内のdummy_secret・fixture-only等は意図的な架空入力として確認し保全。文書中の個人Author／Email／PC pathのみ除去し、Git履歴のAuthorを書き換えたという意味ではありません。画像8枚も実画面を目視し、架空データ／キー非表示を確認。[公開前確認記録](../portfolio/publication_checks.json)に画像hashと検査範囲を保存。

公開対象に `.env`、credential、DB dump／SQL dump、log、cache、node_modules／.next／.venv、実行形式等の禁止物を含めません。最終Git tracked manifestとZIP全entry、CRC、HEAD comment、blob内容、Canonical hashを外部検証scriptで照合します。ZIP後にtracked source変更・追加commitは行いません。

## 既知制約と将来拡張

CSV入力のみ、実SNS Provider・認証・Multi-user未実装。Demo AIは固定Fixture、Live OpenAIの品質／料金／実通信は未検証、保存Contentの自動翻訳なし。本番同時負荷／公開deployment未検証。最新PostMetricによるFull Rebuildで過去Trendが変わる可能性あり。CSV保持・行単位matching・大量データ／Full Rebuild最適化は将来課題。PROCESSING回復は単一process／worker前提。実mouse hover未検証。

未実装Roadmap：SNS API Provider、認証／Multi-user、Scheduled Import、AI履歴比較、Background Job、Cloud deployment、Observability、大規模Import最適化。Phase番号を追加せず、新機能へ自動進行しません。

## Git / Review ZIP

実装commit：`412f1d214be15b64b59a6551f205b8dd920f0d5e`。本報告書を最終検証の記録として別commitに保存します。Remote未設定のためPushなし。Remote追加・Tag・Release・公開・License追加なし。

最終working tree clean確認後、Repository Rootで最後に `git archive --format=zip HEAD -o ../SNS_Analyzer_Phase15.zip` を実行。最終HEADはGitとZIP commentで照合し、ZIP CRC／全tracked blob／必須資料／Demo／禁止物を検証します。archive SHA256と最終HEADは最終回答で提示します（自己参照hashを文書へ追記するための再commitは行いません）。

Version 1 Portfolio Finish完了・ChatGPT最終レビュー待ち。
