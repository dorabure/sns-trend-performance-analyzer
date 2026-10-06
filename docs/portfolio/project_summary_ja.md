# Project Summary / JA — Version 2.0 Interim

[README](../../README.md) · [Architecture](architecture.md)

## 1行説明

CSVとX LiveからSNS実績・市場・競合・Gapを分析し、根拠付きAI提案と履歴比較まで確認できる意思決定ダッシュボード。

## 短い説明

FastAPI・PostgreSQL・Next.jsで7画面、日本語／英語、X OAuth・Refresh・手動／定期同期、AIの保存根拠とHistory / Compareを実装しました。InstagramはDeferred・OAuth / Profile foundation onlyです。個人のポートフォリオ制作であり、実顧客の導入・本番運用実績ではありません。

## 詳細・実装範囲

CSV / X Providerから共通Normalizerへ接続し、投稿・最新指標・Matching・TrendをTransactionで確定してから、共通分析とAIの集計根拠につなぎます。Demo / LiveはProject作成後に変更できず、Liveの未対応機能をDemoへ置き換えません。NULLと実値0を分離し、UTCのRolling Cohortで固定WeightのTrend Scoreを計算します。Gapは市場Scoreと自社の投稿Coverageを組み合わせます。

JobはAt-least-once配送にIdempotencyとCheckpointを組み合わせます。PostgreSQLのScheduleを正本とし、固定Beat TickとCelery / Redis Workerで処理します。ProviderのCapabilityは直接同期と定期同期の双方に適用します。TokenはDB・Frontend・Job Payloadから分離した暗号化Runtime Storageに保存します。AI集計は1つのSnapshotから読み、外部API待機前にDB接続を閉じます。生成ごとにSnapshotを追記し、履歴読取と直前比較では外部APIを呼びません。

担当範囲：要件・契約整理、DB設計、API / Service / Repository、UI・グラフ、ProviderとSecretの境界、Background Job、自動テスト、Docker、架空Demo、Portfolio資料。データの欠損値や再配送・保存根拠を明確に扱い、動作結果を再現できる構成を重視しました。

## Stack

| Area | Technology |
| --- | --- |
| UI | Next.js / React / TypeScript / Tailwind CSS / Recharts |
| API | Python / FastAPI / SQLAlchemy / Pydantic |
| Storage | PostgreSQL / Alembic |
| Jobs | Celery / Redis / fixed Celery Beat tick |
| Provider security | OAuth / PKCE / encrypted runtime SecretStore |
| AI | OpenAI Responses API / Structured Outputs |
| Delivery / test | Docker Compose / pytest / Node built-in test |

## Quality / Performance

Backend **1631 passed / 0 failed / 0 skipped**, **351.52 s** (controlled run ≤600 s). Frontend **84 passed / 0 failed / 0 skipped / 0 cancelled**, 13,753.04691 ms. Typecheck / production build PASS; 19 static routes. OpenAPI **47 paths**; Alembic **0005_v2_provider_core**, five migrations unchanged. Real X / Instagram / OpenAI **0 / 0 / 0**.Phase12のローカルWarm条件の代表値はOverview 約142 ms、Gap 約43 ms、Trend Ranking 約33 ms、Competitor 約131 ms、Trend再構築 約1.57秒。本番SLAではありません。[最終検証報告](../implementation_reports/v2_phase14_portfolio_finish_interim_release_candidate.md)。

## Live status / limitations

X Complete / previously real-verified in private environment. Instagram Deferred / OAuth and Profile foundation only.

Instagramの投稿・指標・Media・Insights・ページング・初回／増分同期はDeferredです。複数ユーザー認証、クラウド本番配備、SLA、24時間運用の実証は対象外です。Phase14では実X・Instagram・OpenAIを呼びません。Xは過去のPrivate実接続で検証済みです。Demo AIは固定Fake Fixtureで、実モデルの品質評価ではありません。投稿や保存AI本文は自動翻訳しません。OWN取込の既存Match保持では投稿ごとのSELECTが残ります。ローカル計測値は本番SLAではありません。スクリーンリーダー音声の全件確認は未実施です。
