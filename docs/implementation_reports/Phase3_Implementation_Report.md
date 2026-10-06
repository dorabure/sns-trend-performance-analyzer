# Phase 3 実装報告書

検証日: 2026-10-03。対象はData Provider / CSVProvider / Normalized DTO / Normalizer / CSV Validationのみ。

## 1. 実装概要

4CSVをDBに依存しない共通DTOへ変換する層を追加した。正常行と行Validation Errorを同時に返す。ファイル単位の重大エラーは専用Exceptionで中止する。DB登録・実SNS通信・Phase 4以降の機能は未実装。

## 2. 作業開始時Git状態

- `git status --short`: 出力なし、Clean。
- Branch: master（維持）。Remote: なし。
- HEAD: `979cd7025aa4d3168f586087adec0fb8afbc7a0e` / docs: record Phase 2 completion commit。
- Phase 2完了Commit: `4749cacfea7e3eda2ab47edd27f7b1ce7d436d13`。
- Phase 1基準点: `2838b4c07f1aa2c2b48fe444e73c7afbfa7303dc`。
- `git ls-files`で.env・依存フォルダー・生成物が追跡されていないことを確認。履歴書換え・Branch切替なし。

## 3. Phase 2基準点確認

Phase 2報告書・13モデル・Initial Migration・Seed・Health・Docker Compose・Frontendが存在。実装前のDocker実行は125 Passed / 0 Failed / 0 Skipped / Warnings 1（5.51秒）。Alembic currentは0001_initial (head)。

正本は添付指示書と同じフォルダーのVer1.1基本・画面・API・DB詳細設計書、およびPhase計画Ver1.0。Repositoryにはこれらの設計書のコピーはないため、元ファイルを参照した。共通CSV列・Provider構成・DTO・NULL方針とPhase分割を確認した。

## 4. 新規作成ファイル

- backend/app/dto/__init__.py、normalized.py
- backend/app/normalizers/__init__.py、common.py
- backend/app/providers/__init__.py、base.py、csv_schema.py、csv_provider.py
- backend/tests/providers/__init__.py、helpers.py、test_normalizer.py、test_csv_provider.py、test_csv_validation.py
- backend/tests/fixtures/csv/own_posts.csv、account_daily.csv、trend_posts.csv、competitor_posts.csv
- docs/implementation_reports/Phase3_Implementation_Report.md

## 5. 変更ファイル

README.mdのみ既存ファイルを変更した。Phase 3概要、Architecture、CSV Header・値仕様、DTO・Result・Error、Unit Test手順を追記。

13業務テーブル・Migration・Seed・Health API・Frontend・Docker Compose・依存定義は変更なし。git diffでPhase 2基準点からの差分がないことを確認した。新規依存は追加していない。

## 6. DataProvider構成

DataProviderはABCでread(path, dataset_type)を定義。CsvDatasetTypeはOWN_POSTS / ACCOUNT_DAILY / TREND_POSTS / COMPETITOR_POSTSのStrEnum。ファイル名から推測せず呼出側が明示する。

返却型はProviderResult[NormalizedRecord]。Application層はこの契約を使用でき、SQLAlchemy Model・DB Sessionを渡さない。将来のAPI adapterも共通フィールド名の文字列MappingをNormalizerへ渡せる。

## 7. CSVProvider構成

標準csv.reader(strict=True)、UTF-8-sig、newline=''を使用。Header名とセルの辞書でアクセスし、列順には依存しない。CSV固有名post_id/dateはplatform_post_id/recorded_dateへ対応付け、共通Normalizerへ渡す。read_textは既にdecodeされた文字列を読む補助API。

物理空行を無視し、空セル行はValidation対象。Headerのみは0件として正常。行Errorがあっても他の正常行を保持し、構造破損時は途中の結果も返さない。

## 8. Normalized DTO

dataclassでSQLAlchemyから分離。Platform / SourceType / MediaTypeは共通Enum。

| DTO | 内容 |
| --- | --- |
| NormalizedPost | source_type/platform/platform_post_id/account_name/posted_at/text/media_type/permalink、7Metrics、hashtags/keywords/raw_data/row_number |
| NormalizedAccountMetric | platform/account_name/recorded_date、followers/following/post_count、raw_metrics/row_number |
| NormalizedTrendData | MARKETのNormalizedPost、keywordsはpost.keywordsを参照 |
| NormalizedCompetitorData | COMPETITORのNormalizedPostとAccount指標followersを分離保持 |
| ProviderResult[T] | records/errors/total_rows、valid_rows/invalid_rowsは計算プロパティ |

post側にaccount_id・followersは追加していない。DB Account検索・Project解決もない。

## 9. Normalizer

CSV Parserと分離し、CSV名ではなく共通フィールド名を受け取る。SQLAlchemy・DB・HTTP Clientに依存しない。

- Platform: X/x/Twitter/twitter→X、Instagram大小文字差→INSTAGRAM。空欄・未知値・IG・ALLは拒否。
- Media: canonical値を大小文字不問で処理、PHOTO→IMAGE / REEL→VIDEO / ALBUM→CAROUSEL。空欄・NULLはNone。未知値は拒否。
- 日時: YYYY-MM-DDTHH:MM[:SS[.ffffff]]にZまたは±HH:MMを必須とし、Timezone保持。Timezoneなし・不正日付・不正Offsetは拒否。DateはYYYY-MM-DD。
- 数値: 空欄/NULL/null→None、0→0、非負整数→int。負数・小数・指数・桁区切り・非数値を拒否。DBのBIGINT上限2^63−1も確認。
- Text: 前後空白除去のみ。内部改行・全角・絵文字・URLを保持。account_nameは100文字、platform_post_idは255文字まで。
- Hashtag: セミコロン区切り、空要素除去、#付加、順序を保った重複除去。大小文字・Unicode維持。曖昧な区切りや#だけの要素は拒否。
- Keyword: Trim後の単一値を0～1件のリストへ。勝手な分割・一般Term正規化はしない。
- Raw: 元セルをコピー。Token/Secret/Password/API Key等の資格情報名のフィールドを拒否する。

## 10. CSV Validation

各CSVの確定列は全Header必須。任意値の列でもHeader省略は不可とした。Header前後空白を除去し、重複・空Header・不足を拒否。未知の通常追加列はrawに保持し、Typoは自動補正しない。資格情報名の追加列は拒否。

必須値をTrim後に確認し、数値・日付・Platform・Media・Hashtag等を行単位で検証。1行に複数Field Errorを保持する。エラーに生値やPython内部例外を露出しない。

## 11. 4CSV対応状況

| CSV | 必須値 | 対応 |
| --- | --- | --- |
| own_posts.csv | platform/post_id/account_name/posted_at | OWN / 7Metrics / media / hashtags |
| account_daily.csv | platform/account_name/date | Date / followers/following/post_count |
| trend_posts.csv | platform/post_id/posted_at | MARKET / Account不要 / keyword / hashtags / Metrics |
| competitor_posts.csv | platform/account_name/post_id/posted_at | COMPETITOR / followers別保持 / media / Metrics |

全Header一覧と入力例はREADMEに記載。サンプルは架空のdummy_demoのみ。

## 12. Structured Error仕様

ValidationError: row_number / field / code / message。row_numberはHeaderを1としたレコード開始物理行。複数行セルに対応し、正常DTOにもrow_numberを保持する。

File-levelはProviderFileError.errorで返す。FILE_NOT_FOUND、FILE_UNREADABLE、INVALID_ENCODING、MISSING_HEADER、EMPTY_HEADER、DUPLICATE_HEADER、SENSITIVE_HEADER、MALFORMED_CSV。列数不一致・引用符破損・Parserのセル長制限超過はMALFORMED_CSVとして全体を停止。

Row-levelはerrorsへ蓄積。REQUIRED_VALUE、VALUE_TOO_LONG、INVALID_PLATFORM、INVALID_MEDIA_TYPE、INVALID_INTEGER、INTEGER_OUT_OF_RANGE、INVALID_DATETIME、INVALID_DATE、INVALID_HASHTAGS。CSV名のpost_id/dateへfieldを戻す。1行複数Errorでもinvalid_rowsは1件。

## 13. Unit Test結果

backendで:

```powershell
.venv/Scripts/python -m pytest tests/providers -q -p no:cacheprovider
```

Total 150 / Passed 150 / Failed 0 / Skipped 0 / Warnings 0（Windows、0.49秒）。最終Docker全体実行でも同じ150件を成功確認。

4CSV・UTF-8/BOM・列順・Trim・追加列・Header異常・必須値・Nullable/0・数値境界・Timezone・Date・Media/Platform Alias・Hashtag・Keyword・followers分離・引用符/複数行・Mixed 7 Valid/3 Invalid・File Error・Raw資格情報ガードを検証。

Provider importをPOSTGRES環境変数なしの別Pythonプロセスで実行し、app.dbをimportしないことを確認した。新規Unit TestはPostgreSQL接続fixtureを使用しない。

## 14. 既存Phase 1/2 Test結果

```powershell
docker compose exec -T backend python -m pytest -q -p no:cacheprovider
```

| 範囲 | Total | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: | ---: |
| 既存Phase 1/2 | 125 | 125 | 0 | 0 |
| 新規Phase 3 | 150 | 150 | 0 | 0 |
| 合計 | 275 | 275 | 0 | 0 |

最終実行6.16秒、Warnings 1。実PostgreSQLで既存Migration roundtrip・制約・Seedを再検証し、通常開発DBをdowngradeしていない。残存テストDBは0。開発DBの設定件数はprojects=1、platforms=2、accounts=5、topics=2、terms=6、残り8テーブル=0を維持。

## 15. Frontend Build / Typecheck

frontendで `node node_modules/typescript/bin/tsc --noEmit`、`node node_modules/next/dist/bin/next build` が双方Exit 0。Production Build・静的生成成功。Frontend変更なし。

Backendは `docker compose exec -T backend python -m compileall -q app` がExit 0。Provider importも新規Unit Testで検証済み。

## 16. Docker / Health Check回帰確認

`docker compose build backend`、`docker compose up -d` 成功。backend/dbはhealthy、frontend稼働。更新イメージに新規app・tests・fixturesを同梱。既存Dockerfile・Composeの変更は不要だった。

Invoke-WebRequest http://localhost:8000/api/v1/health はHTTP 200、`{"status":"ok","database":"connected"}`。Alembic current / headsは両方0001_initial (head)、1系統。API・Schemaの既存仕様を維持した。

Frontend http://localhost:3000 もInvoke-WebRequestでHTTP 200を確認した。

## 17. Warning

全テストで既存StarletteDeprecationWarning 1件（httpxを使うTestClientの非推奨通知）。新規Unit Test単独はWarning 0。既存依存を本Phaseで移行していない。

## 18. 発生した問題と対応

初回は149 Passed / 1 Failed。サンプル生成コマンドのcwdがbackendなのにbackend/.venvを指定していたため、生成処理が実行されずサンプル読込テストが失敗した。backend基準のパスで4CSVを作成し、150件成功。テストHelperも未知追加列の上書き値を保持するよう修正し、最終全275件が成功。

## 19. 設計書との差異

Ver1.1の4CSV列・共通投稿モデル・Provider方針・NULLと0の区別に差異なし。未規定事項は次のとおり明確化した。

- Hashtagセルはセミコロン区切り。Delimiter自動推測なし。
- 日時のTimezoneなしはValidation Error。
- 全確定列のHeaderを必須、値が任意のセルは空欄可。
- Row番号はレコード開始物理行。資格情報名の列はraw保持せず拒否。
- CSV構造破損は全体中止、Headerのみの0件は正常。
- DB互換のBIGINT・ID/Account文字数境界を行Validationへ反映。
- 基本設計のpandas指定はData Analysis用でありCSV Parser必須指定ではないため、標準csvを使用。

ファイル全体のサイズ制限・Upload APIは後続Phaseの範囲。Phase 2 Seedのnormalized_term固定値を一般Normalizerの仕様に流用していない。

## 20. Phase 3完了Commit / Push結果

Commit成功: `a747058156926ab7c4b8f4992e7d17678abf09d5`。
Message: `feat: complete Phase 3 provider normalization foundation`。
19ファイル / 1005追加行 / 1削除行。Stage後のstat・全差分・diff --checkを確認済み。実.env秘密値・資格情報形式・巨大生成物の検査は成功した。

完了Commit直後のgit status --shortは出力なし（Clean）。Branchはmaster。Push未完了の理由はRemote未設定。新Remote追加・変更・履歴書換えはない。

本節の実績追記だけを `docs: record Phase 3 completion commit` の追加Commitで保存する。自身のhashを同じCommitに含めることはできないため、amendせず報告書追記を別Commitにする。

## 21. Phase 4への申し送り

後続ImportはCsvDatasetTypeを明示し、ProviderResultの正常DTOとErrorを受け取る。ファイルException時は部分recordsを使用しない。Account ID解決・Transaction・Import History・DB重複/UPSERT・Topic/Term MatchingはPhase 4。

競合followersはNormalizedCompetitorData.followers、投稿日時はpost.posted_atに保持。Date(posted_at)のTimezone方針は後続Import側で統一する。row_numberを利用してDB書込み段階のErrorも元CSVへ対応付けできる。

実SNS API Client・OAuth・集計・Trend Score・業務API/UIは未実装。DTOは永続化Modelから独立している。

## 22. Phase 3完了判定

**Phase 3完了。** Provider・DTO・Normalizer・4CSV Validation・新規150件・全275件・Frontend Build/Typecheck・Docker/Health・README・実装報告書を完成し、完了CommitとCleanを確認済み。Remote未設定によるPush不可は指示書に従い実装失敗としない。Phase 4へ進まずレビューを待つ。
