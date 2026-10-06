# SNS Trend & Performance Analyzer — Version 2.0 Interim

[English README](README_EN.md)

SNS投稿実績、市場トレンド、競合、投稿Gapを同じ条件で読み解き、根拠付きAI提案と履歴比較につなぐ意思決定支援ダッシュボードです。CSVまたはX Liveのデータを共通Normalizerで取り込み、7つの分析・設定画面で扱います。

**X: Complete / previously real-verified. Instagram: Deferred / OAuth and Profile foundation only.**
Dockerで架空Demoを再現でき、X・Instagram・OpenAIの秘密情報は不要です。Version 2.0 InterimはRelease CandidateとしてGitHub上でPublic Pre-release公開済みです。

![Canonical Demo Overview](docs/portfolio/screenshots/v2_01_overview_ja.png)

## 主な機能

| 機能 | 状態 |
| --- | --- |
| CSV Import / Canonical Demo | 実装済み。X / Instagramの架空データ |
| Overview | 実装済み |
| My Account | 実装済み。NULLと実値0を分離 |
| Trend Explorer | 実装済み。UTCの7日Rolling Score |
| Competitor Analysis | 実装済み |
| Gap Analysis | Complete; four classifications |
| AI Generate / saved Evidence | 実装済み。Demoは固定Fake Fixture |
| AI History / Compare Previous | 実装済み。Snapshot追記保存、読取時API呼出なし |
| Demo / Live mode | 実装済み。Project modeは変更不可、Demoへの代替なし |
| X OAuth / Refresh / manual sync | Complete。過去のPrivate実接続で検証済み |
| X Scheduled Sync | Complete。過去に実接続検証済み、PostgreSQL Schedule + 固定Beat Tick |
| Instagram Live | Deferred。OAuth / Profile基盤のみ |
| JA / EN and responsive UI | 実装済み。保存本文は翻訳しない |

## 画面紹介

![Gap Analysis](docs/portfolio/screenshots/v2_05_gap_ja.png)
![Fake AI History and Compare](docs/portfolio/screenshots/v2_07_ai_history_compare_ja.png)

[全12枚の画面とデータの注意点](docs/portfolio/screenshots.md)

## Quick Start

新しくCloneまたはRCを展開したRepository Rootで実行します。Docker DesktopのLinuxコンテナ／Docker Engine、Compose 2.24.4以上、PowerShell、初回の依存取得用ネットワークが必要です。空きポートは13014 / 18014 / 15414。新しいProject名とVolumeを使い、既存環境とは分離します。既存.env.demoは上書きしないでください。

```powershell
Copy-Item .env.example .env.demo
# .env.demoのPOSTGRES_PASSWORDだけを独自のローカル開発用値へ変更。
$demoProject = "sns-demo-" + [guid]::NewGuid().ToString("N")
$demoArgs = @("--env-file", ".env.demo", "-p", $demoProject, "-f", "docker-compose.yml", "-f", "docs/portfolio/docker-compose.demo.yml")
docker compose @demoArgs build backend frontend worker beat
docker compose @demoArgs up -d --wait
docker compose @demoArgs exec -T backend alembic upgrade head
docker compose @demoArgs exec -T backend python -m app.demo.loader --anchor-date 2026-10-04 --seed 1401 --directory /demo_data/canonical
Invoke-RestMethod http://localhost:18014/api/v1/health
```

[Open Overview](http://localhost:13014/dashboard/overview?platform=ALL&from=2026-07-07&to=2026-10-04). プロジェクトでPhase14 Canonical Demoを選択してください。AI Insightsは保存済みレポートを表示します。外部APIキーと暗号化Master Keyは空のままで起動できます。Public DemoではLiveを無効にしています。再投入は通常拒否されます。

停止は同じPowerShellセッションでdocker compose @demoArgs down。通常／Private環境でdown -vやdowngrade baseを実行しないでください。
For macOS/Linux, use `cp .env.example .env.demo` and substitute a unique `-p` project name and the same two `-f` arguments in each Compose command. [Demo loader and limited reset](demo_data/README.md).

## Canonical Demo

Fictional only: UTC 2026-07-07–2026-10-04, anchor 2026-10-04, seed 1401. OWN 180 / COMPETITOR 540 / MARKET 4,500 posts; Account Daily 180; three competitors, six Topics, twelve Terms. Gap has twelve rows, eleven known-coordinate points and one unknown. AI uses a saved fixed Fake fixture. [CSV manifest](demo_data/manifest.json) · [CSV contract](docs/portfolio/csv_spec.md).

## 技術・設計

| Area | Technology |
| --- | --- |
| UI | Next.js / React / TypeScript / Tailwind CSS / Recharts |
| API | Python / FastAPI / SQLAlchemy / Pydantic |
| Storage | PostgreSQL / Alembic |
| Jobs | Celery / Redis / fixed Celery Beat tick |
| Provider security | OAuth / PKCE / encrypted runtime SecretStore |
| AI | OpenAI Responses API / Structured Outputs |
| Delivery / test | Docker Compose / pytest / Node built-in test |

Browser → Next.js → FastAPI Services / Repositories → PostgreSQL。Fetch → Normalize → 業務Transaction → Checkpointの順で確定します。共通Provider RegistryとCapabilityで未対応操作を拒否します。JobはAt-least-once配送とIdempotencyを組み合わせます。Scheduleの正本はPostgreSQLで、固定Beat TickがCelery / Redisへ処理を送ります。

OAuthの認証待ち情報とTokenは暗号化Runtime Storageに保存し、TTL・再利用防止・ログ秘匿を適用します。業務DB、Frontend、Job Payloadに秘密情報を渡しません。AIは1つのRead-only Snapshotから集計根拠を読み、DB接続を閉じてから外部APIを呼び、Structured Outputsを検証して新しいSnapshotを追記します。History / Compareの読取では外部APIを呼びません。

[Architecture / 18 tables + Alembic](docs/portfolio/architecture.md) · [AI boundaries](docs/portfolio/ai_insights.md) · [Analytics / NULL](docs/portfolio/analytics.md)

## 表示言語

Settings → 表示言語 / Display Language → 日本語 / English。固定UIの選択をlocalStorageに保存します。Project名・投稿・Topic / Term・保存AI本文は翻訳しません。

## 品質・性能

Backend **1,631件成功・失敗0・Skip 0、351.52秒**。600秒以内の単独実行条件を通過。 Frontend **84件成功・失敗0・Skip 0・取消0**、13,753.04691 ms。 Typecheck / production build PASS; 19 static routes. OpenAPI **47 paths**; Alembic **0005_v2_provider_core**, five migrations unchanged. Real X / Instagram / OpenAI **0 / 0 / 0**.

Phase12のローカルWarm条件の代表値：Overview 約142 ms、Gap 約43 ms、Trend Ranking 約33 ms、Competitor 約131 ms、Trend再構築 約1.57秒。ローカル実測例であり、本番SLAや応答時間を保証しません。Phase13のBackend全件は375.85 / 323.42秒でした。常に5分以内とは主張しません。

## 制約

Instagramの投稿・指標・Media・Insights・ページング・初回／増分同期はDeferredです。複数ユーザー認証、クラウド本番配備、SLA、24時間運用の実証は対象外です。Phase14では実X・Instagram・OpenAIを呼びません。Xは過去のPrivate実接続で検証済みです。Demo AIは固定Fake Fixtureで、実モデルの品質評価ではありません。投稿や保存AI本文は自動翻訳しません。OWN取込の既存Match保持では投稿ごとのSELECTが残ります。ローカル計測値は本番SLAではありません。スクリーンリーダー音声の全件確認は未実施です。

## 公開候補・Portfolio

[日本語Summary](docs/portfolio/project_summary_ja.md) · [Release notes](docs/portfolio/release_notes_v2_interim.md) · [Release checklist](docs/portfolio/public_release_checklist.md) · [Current status](docs/portfolio/version2_interim_status.md)

Private環境を別途準備する手順： [X](docs/portfolio/x_api_private_setup.md) / [Instagram foundation and Deferred scope](docs/portfolio/instagram_api_private_setup.md). Public Quick Startにはどちらも不要です。

## 開発履歴

[V1 historical release](docs/portfolio/release_notes_v1.md) · [Phase13 validation](docs/implementation_reports/v2_phase13_cross_cutting_quality_release_validation.md) · [Phase14 delivery](docs/implementation_reports/v2_phase14_portfolio_finish_interim_release_candidate.md). 過去の報告は当時の範囲と件数を保持しています。
