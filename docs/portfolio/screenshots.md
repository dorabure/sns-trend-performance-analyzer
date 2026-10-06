# Screenshots — Version 2.0 Interim

[日本語 README](../../README.md) · [English README](../../README_EN.md)

Canonical分析画面はすべて架空データ、ALL・2026-07-07〜2026-10-04（UTC）、Phase14の新規Disposable環境です。AI Latestは固定Fake Fixtureで、保存表示にAPIキーは不要です。History / CompareとProviderは別のDisposable Fake Fixtureです。ProviderのConnected表示は実アカウント接続の証拠ではありません。Xの実接続は過去のPrivate検証で確認し、Phase14では実通信しません。

| Screenshot | 読み取れる機能 / Data |
| --- | --- |
| [01 Overview JA](screenshots/v2_01_overview_ja.png) | KPIと分析への導線。Canonical Demo |
| [02 My Account JA](screenshots/v2_02_my_account_ja.png) | 投稿・最新指標とSNS別の分母。Canonical Demo |
| [03 Trend JA](screenshots/v2_03_trend_ja.png) | Topic / TermとSNSのRolling Trend。Canonical Demo |
| [04 Competitor JA](screenshots/v2_04_competitor_ja.png) | 自社と3競合の頻度・指標比較。Canonical Demo |
| [05 Gap JA](screenshots/v2_05_gap_ja.png) | 4分類、Opportunity、NULLと0。Canonical Demo |
| [06 AI Latest JA](screenshots/v2_06_ai_latest_ja.png) | 保存Fake Report、根拠、Previous None。Canonical Demo |
| [07 AI History / Compare JA](screenshots/v2_07_ai_history_compare_ja.png) | 選択Snapshotと同条件の直前Snapshot。Phase13 Disposable Fake、原画像を再利用 |
| [08 Settings / Import JA](screenshots/v2_08_settings_import_ja.png) | CSV取込履歴とDataset。Canonical Demo |
| [09 X capabilities / status](screenshots/v2_09_provider_x_capabilities_status.png) | Profile / OWN Posts / OWN Metrics対応。Disposable Fictional LIVE Provider |
| [10 Instagram Deferred](screenshots/v2_10_instagram_deferred.png) | OAuth / Profile基盤のみ、投稿・指標同期未対応。Disposable Fictional LIVE Provider |
| [11 Overview EN](screenshots/v2_11_overview_en.png) | 英語固定UIと翻訳しないデータ。Canonical Demo |
| [12 AI Compare Mobile](screenshots/v2_12_ai_compare_mobile.png) | 1列の比較。Phase13 Disposable Fake、原画像を再利用 |

新規Desktop撮影は1440×1000の検証Viewportです。通常の実画像は1425×990、05と08はページ全体を撮影しています。再利用した07は1521×680、12は375×811の実画像です。全画像の寸法は[画像検査](../implementation_reports/evidence/v2_phase14_documentation_checks.json)に記録しています。07 / 12はProduction UIがPhase13から不変であることを確認して再利用しました。加工は形式変換のみで、値・文言・状態は変更していません。保存AI本文はUI言語変更時にも翻訳されません。

旧V1画像は旧ファイル名のまま残しています。[Phase14検証報告](../implementation_reports/v2_phase14_portfolio_finish_interim_release_candidate.md)にブラウザー確認範囲と画像検査を記録します。
