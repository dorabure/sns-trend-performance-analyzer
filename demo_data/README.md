# Phase14 Canonical Demo Data

完全な架空CSVです。実在のSNS投稿・企業・個人から取得していません。Version 1は実SNS API連携を完成条件としていません。

- Version: `phase14-v1`、Seed: `1401`
- UTC期間: **2026-07-07〜2026-10-04（90日、両端含む）**
- OWN_POSTS 180、ACCOUNT_DAILY 180、COMPETITOR_POSTS 540、TREND_POSTS 4500。
- 専用Project: `Phase14 Canonical Demo`。固定ID `14da0000-1401-5140-8140-000000000014`。
- X / Instagram、OWN各1、CompetitorはX2・Instagram1。
- 6Topic（生成AI、業務効率化、AIエージェント、データ分析、動画生成、SNS運用）、各Keyword/Hashtagの2Term。

`manifest.json`には件数、Header順、UTF-8 byte数、SHA256、Anchor/Seed/Version、期待シナリオを保存しています。4CSVは全て20 MiB未満。生成時にHeader・Encoding・行数・Size・Secret patternを自動確認します。

## 起動と投入（Repository Root）

クリーンCloneではまずルートREADMEの環境変数・Docker起動・Migration手順を実行してください。OPENAI_API_KEYは空で構いません。

```powershell
docker compose build backend frontend
docker compose up -d
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend python -m app.demo.loader --anchor-date 2026-10-04 --seed 1401 --directory /demo_data/canonical
```

Composeは`demo_data`をBackendの`/demo_data`へread-only mountします。Loaderは入力CSVを同Anchor/Seedの再生成hashと照合してから、専用Project/Account/Topic/Termを準備します。OWN→COMPETITOR→ACCOUNT_DAILY→MARKETの順に既存ImportServiceを実行し、既存MatchingService / TrendServiceから関連とスコアを生成します。trend_daily、post_topics、post_terms、Gapを直接作りません。

API起動・Migration・通常Seedから自動実行されません。通常Phase2 Seedと既存利用者Projectを変更しません。4成功履歴、PROCESSING 0、保存済みAI Fixture1件が作られます。

## 再実行と明示Reset

通常再実行は既存Demo検出で停止し、投稿・Snapshot・履歴・AIを増やしません。再作成する場合だけ:

```powershell
docker compose exec -T backend python -m app.demo.loader --anchor-date 2026-10-04 --seed 1401 --directory /demo_data/canonical --reset-demo
```

この操作は**固定IDとdescription markerが一致するPhase14専用Projectだけ**を削除・再作成します。他Projectは削除しません。markerが利用者に変更されている場合はResetを拒否します。途中失敗でも通常再実行は停止します。専用Projectの履歴を調べ、必要な場合に限り明示Resetしてください。通常DBのVolume削除・downgradeは不要です。

## 再生成

固定Anchor/Seed/Versionならbyte単位で同一CSV/Manifestです。将来Anchorを変える場合は、先にCSVを再生成し、Loaderにも同じAnchor/Seedを指定します。次のコマンドでは生成時だけdemo_dataを別のwritable出力先/demo_exportへmountします。

```powershell
docker compose run --rm -T --no-deps -v "${PWD}/demo_data:/demo_export" backend python -m app.demo.generator --anchor-date 2026-10-04 --seed 1401 --output /demo_export/canonical
```

Python標準ライブラリと既存依存のみを使います。生成だけではDBを変更しません。Anchor/SeedとCSVが不一致なら、LoaderはProjectに触れる前に停止します。

## 確認する画面

[Overview](http://localhost:3000/dashboard?platform=ALL&from=2026-07-07&to=2026-10-04)で専用Projectを選択してください。同じfrom/toで7画面を確認できます。

- Overview: KPI、90日推移、Top5、Competitor、Opportunity、保存AI Summary。
- My Account: 投稿形式4種、ページ切替、本文/Hashtag検索、10月1日の0と10月2日のNULL、投稿詳細。
- Trend Explorer: Topicごとの位相・強度差、複数Term、90日時系列とランキング。
- Competitor: 高頻度/中Engagement、高Engagement、中低頻度/動画の3Account。FollowersはAccount別。
- Gap: OPPORTUNITY / BALANCED / HIGH_COVERAGE / LOW_PRIORITYの4分類。データ分析は100%自社CoverageでGap 0。動画生成/InstagramのTrendはNULLで、座標0へ置換されません。
- AI Insights: 同じ90日/ALL条件に保存したFixture、4区分、根拠展開。Keyなしでも閲覧でき、生成buttonは無効。
- Settings / Import: 5Account、6Topic/12Term、成功履歴4件。

初期60日の周期差と直近30日の上昇・ピーク・下降・安定・低水準・再上昇の分布を架空本文と市場Engagementで作っています。Trend/Gap計算式や分類境界を調整したものではありません。少数のNULL・0、Hashtagなし、日本語/Unicode/絵文字を含みます。

## AI Fixtureと表示言語

**Phase14 Demo用の固定Fixtureであり、OpenAIが実生成した文章ではありません。実OpenAI API呼出・課金は0です。** CLI専用DemoClientを既存InsightServiceへ注入し、実Overview snapshot、Evidence ID validation、append-only保存を通します。model_nameは`demo-fixture`。Production APIのAdapter・モデル・Prompt契約をFakeへ置き換えません。

Settingsの「表示言語 / Display Language」から日本語 / Englishへ切り替えます。`sns-analyzer.locale`をlocalStorageへ保存し、再読込後も維持。不明・空・破損値はjaへFallbackします。7画面の固定UI、Enum表示、Chart/Tooltip、Evidence Labelを翻訳し、API値とUTC期間は維持します。

Project名・Topic/Term・本文・Hashtag・保存AI Contentは自動翻訳しません。**UI LanguageとAI Content Languageは別**です。Englishでも架空日本語データとFixture本文はそのままです。
