# CSV Input

[README](../../README.md) · [Demo Data](../../demo_data/README.md)

Version 1の入力はCSVです。SettingsでProject / Account / Topic / Termを設定し、ImportでDatasetを明示します。ファイル名で種別を推測しません。

| Dataset | 用途 | 全必須Header（値の空欄は別条件） | 必須値 |
| --- | --- | --- | --- |
| OWN_POSTS | 自社投稿・指標 | platform, post_id, account_name, posted_at, text, media_type, impressions, reach, views, likes, comments, shares, saves, hashtags | platform, post_id, account_name, posted_at |
| ACCOUNT_DAILY | 自社Account日次指標 | platform, account_name, date, followers, following, post_count | platform, account_name, date |
| TREND_POSTS | 市場投稿・Trend材料 | platform, post_id, posted_at, text, keyword, hashtags, views, likes, comments, shares | platform, post_id, posted_at |
| COMPETITOR_POSTS | 競合投稿・Followers | platform, account_name, post_id, posted_at, text, media_type, views, likes, comments, shares, followers | platform, account_name, post_id, posted_at |

UTF-8 / UTF-8 BOM、カンマ区切り、Header必須・列順自由。重複・不足・空Headerを拒否します。引用符内のカンマと改行に対応します。OWN / COMPETITORは登録済みの有効Accountに対応するaccount_nameが必要です。

- 数値空欄・NULLは不明、0は整数0。非負の整数のみ、上限2^63−1。負数・小数・指数・桁区切りを拒否します。
- `posted_at`はTimezone付きISO 8601（Zまたは±HH:MM）。`date`はYYYY-MM-DD。投稿分析 / Trendの日付はUTCです。競合Followersの日付は契約上、元Timezoneのposted_at.date()を使い、同日CSV後勝ちです。
- X / TwitterをX、InstagramをINSTAGRAMへ正規化します。IG / ALLはCSVのPlatformとして受理しません。
- `hashtags`はセミコロン区切り（例 `#生成AI;#分析`）。#付加・重複除去を行い、大小文字は保持します。空欄は空配列。keywordは1件として扱い勝手に分割しません。
- File上限20 MiB、multipart Request全体21 MiBがCompose既定値。RequestはParser前から受信量を制限します。環境変数で変更可能です。
- Token / Secret / Password / API Key等の資格情報列を拒否します。エラーに元の秘密値を含めません。

行エラーは異常行を除いてPARTIAL_ERROR、CSV構造エラーは全体FAILED。業務保存の重大障害は全Rollbackします。詳細なHeader・Normalizer・Transaction仕様は[技術資料](../technical_reference.md)、定義は[CSV Schema](../../backend/app/providers/csv_schema.py)へ。
