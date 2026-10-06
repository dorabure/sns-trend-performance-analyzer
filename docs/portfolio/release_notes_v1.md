# SNS Trend & Performance Analyzer — Portfolio Version 1

Version 1 Portfolio Complete。ローカル環境で動作するCSV入力のSNS分析アプリをRelease Candidateとして固定しました。GitHub公開・本番deploymentは未実施です。

[日本語README](../../README.md) · [English README](../../README_EN.md) · [公開・提出前Checklist](public_release_checklist.md)

## Included

| 機能 | 内容 |
| --- | --- |
| Overview | 自社KPI・市場・競合・Gap・保存AIを共通条件で横断 |
| My Account | 自社投稿、最新指標、SNS別Rate、日次Account指標 |
| Trend Explorer | Topic／Term別のUTC 7日Rolling Trendと比較 |
| Competitor Analysis | 自社と選択競合の投稿・Engagement・Followers・Topic比率 |
| Gap Analysis | 4分類、Opportunity Zone、NULLを残す表、SNS別Scatter |
| AI Insights | 4区分の提案と保存Evidence、実API adapterと固定Demo Fixture |
| Settings / CSV Import | Project／Account／Topic／Term管理、4 Dataset取込・履歴 |
| JA / EN | 固定UIの切替・永続化。保存AI Contentや利用者データは自動翻訳しない |
| Canonical Demo | 固定Anchor 2026-10-04／seed 1401、90日分の架空CSV、固定AI |
| Docker | ComposeによるPostgreSQL／FastAPI／Next.jsのローカル起動 |

## Verified

Version 1の最終検証はBackend 1091 tests、Frontend 25 tests、Failed 0／Skipped 0、typecheck、production build（19 routes）、Docker startup、Health HTTP200 `ok / connected`、Alembic `0001_initial (head)`、OpenAPI 26 paths、業務DB13 tablesです。最終再実行の結果・範囲は[最終化Report](../implementation_reports/Phase16_Implementation_Report.md)を参照してください。

Canonical DemoはOWN 180／ACCOUNT_DAILY 180／COMPETITOR 540／MARKET 4500行。4 CSVのraw SHA256・bytes・headers・行数を[Manifest](../../demo_data/manifest.json)と照合し、Fresh DBへの標準CLI投入を確認しました。Browser smokeはOverview JA／EN、Gap JA、AI JA、Settings Language。Gapは表12行・11可視点・座標不明1行です。8 Portfolio画像とCanonical CSVは前版の内容を保全しています。

## Important design choices

- NULLは不明、0は観測した実値。平均・Score・表／Graphの扱いを分ける。
- Latest PostMetricは投稿ごとにrecorded_at DESCの1件。MARKET／Project限定の相関LATERAL取得と固定6 SQLを維持。
- Cross-screen Contractで期間・SNS等を共有し、古い応答の反映を防ぐ。
- 共通分析Serviceのread-only SnapshotでAI入力とEvidenceを揃え、外部API待機前にDB接続を閉じる。
- Evidence-linked AIはStructured Outputsと根拠IDを検証し、生成時のContent／Evidenceを保存。
- SecretはBackend環境変数のみ。APIキーをDB／Frontendへ保存せず、生投稿本文やAccount名をAI入力から除く。
- Deterministic Demoは固定Seed／Anchor／Manifestと架空データ。Demo AIは実OpenAI生成結果ではない。

[Analytics](analytics.md) · [AI設計とPrivacy](ai_insights.md) · [Architecture](architecture.md) · [CSV仕様](csv_spec.md)

## Limitations

CSV入力のみ。Live OpenAIの品質・料金・実通信、本番同時負荷、公開deploymentは未検証。保存AIの自動翻訳なし。最新指標によるFull Rebuildで過去Trendが変わる可能性があります。大量CSV保持・行単位matching・Full Rebuildの大規模最適化は将来課題。PROCESSING回復は単一process／worker前提。Gap Tooltipはkeyboardで確認、実pointer hoverは操作APIがなく未検証です。

## Not included

Live SNS API Provider、Authentication、Multi-user、Production deployment。Version 2候補はSNS API、認証、Scheduled Import、Background Job、Cloud deployment等ですが、Version 1には追加していません。Portfolio versionとpackage.jsonのversionは別で、内部version fieldやSemantic Versioning、Licenseは追加していません。
