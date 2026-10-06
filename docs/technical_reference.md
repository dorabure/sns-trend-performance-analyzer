<!-- Preserved pre-Phase15 README; commands run from repository root. -->
> 本文はPhase14 Fix以前のREADMEを保全した開発履歴・詳細契約です。現在の入口は[README](../README.md)。Phase15の初回投入タイムアウト修正により、TrendRepositoryの最新PostMetric取得はwindow subqueryからindexed LEFT JOIN LATERALへ変更しました。計算式・NULL・Source分離は維持しています。[現行差分・検証](implementation_reports/Phase15_Implementation_Report.md)

# SNS Trend & Performance Analyzer

Phase 14で、固定90日分の架空デモCSV・安全な投入CLI・総合テスト・日本語 / English表示切替を追加しました。実行手順と検証結果は本書末尾のPhase 14節を参照してください。

SNS運用の意思決定を支援するWebアプリです。Phase 1〜11の接続基盤、13テーブル、CSV取込、Trend Engine、Settings / Import、My Account、Trend Explorer、Competitor、Gap Analysis、Overviewに加え、Phase 12でAI Insightsの生成・保存・根拠表示、Phase 13でImport回復・受信サイズ制限・画面条件と応答の整合性・AI Privacyの品質改善を実装しました。SNS実連携は後続Phaseです。

## 前提条件

- Docker Engine と Docker Compose v2以降（WindowsではDocker DesktopのLinuxコンテナ）
- 空きポート: 3000 / 8000 / 5432
- 初回ビルド時にパッケージ・Dockerイメージを取得できるネットワーク

## 環境変数と起動

プロジェクトルートで実行します。

```powershell
Copy-Item .env.example .env
# .env の POSTGRES_PASSWORD を開発用の独自値に変更
docker compose up --build -d
docker compose ps
```

macOS/Linuxではコピーに `cp .env.example .env` を使用します。`.env` はGit対象外です。`.env.example` のパスワードは例示用です。Composeで `$` を含む値を扱う場合、`.env` 内では単一引用符で囲んでください。

| 変数 | 用途 |
| --- | --- |
| POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD | DB初期設定とBackendの接続情報 |
| POSTGRES_HOST / POSTGRES_PORT | Backendから見た接続先。Composeでは `db` / `5432` |
| FRONTEND_ORIGIN | CORSで許可する単一Origin。既定値 `http://localhost:3000` |
| NEXT_PUBLIC_API_BASE_URL | **ブラウザから見た**APIのURL。既定値 `http://localhost:8000` |
| MAX_IMPORT_FILE_SIZE_BYTES | CSV本体の上限。既定値 `20971520`（20 MiB）、正の整数 |
| MAX_IMPORT_REQUEST_SIZE_BYTES | multipart body全体の上限。Compose既定値 `22020096`（21 MiB）、正の整数 |

DB接続URLはSQLAlchemyの `URL.create` で組み立てます。DATABASE_URLの二重管理はしません。Frontendの公開環境変数はビルド時に埋め込まれるため、変更後は `docker compose up --build -d` で再ビルドしてください。Next.jsにDB資格情報は渡していません。

## DB初期化（Phase 2）

Compose起動後、ルートで順に実行します。MigrationとSeedは明示コマンドのみで実行し、API起動時には実行しません。

```powershell
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.db.seed
docker compose exec backend alembic current
docker compose exec backend alembic heads
```

初期Revisionは `0001_initial`、headは1系統です。通常開発DBでは `upgrade head` のみ使用してください。既存データを保護するため、通常DB・永続Volumeに `downgrade base` や `down -v` を使用しないでください。

SeedはDemo Project 1件、対象SNS 2件、架空OWN 2件、架空COMPETITOR 3件、Topic 2件、Term 6件だけを追加します。既存行を更新・削除せず、再実行しても重複しません。名前変更・無効化を保持し、既存Active OWNがある場合は追加しません。SeedのOWNを利用者が無効化した場合、再実行しても自動再有効化しません。投稿・指標・Trend・AI結果は追加しません。

テーブルとSeed件数の確認（DB資格情報はコンテナ環境から参照）:

```powershell
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
docker compose exec backend python -c 'from sqlalchemy import select,func; from app.db.base import Base; import app.db.models; from app.db.session import engine; c=engine.connect(); print({t.name:c.scalar(select(func.count()).select_from(t)) for t in Base.metadata.sorted_tables}); c.close()'
```

定義はDB詳細設計書Ver1.1を優先します。Phase 2指示書との差異は `post_terms.match_method`、`trend_daily.window_days=7` と対応Index、`account_metrics.raw_metrics NOT NULL`、`ai_insights` の期間CHECKです。`updated_at` はSQLAlchemy経由の更新で更新し、DB Triggerは使用しません。テーブル間の業務整合性は後続PhaseのApplication層で扱います。

## CSV Provider / Normalizer（Phase 3）

`DataProvider`（抽象クラス）→ `CSVProvider` → 共通 `Normalizer` → `ProviderResult[NormalizedRecord]` の順に処理します。CSVのpost_id/dateを共通名platform_post_id/recorded_dateへ変換する処理はCSVProviderに置き、NormalizerはCSV Parser・SQLAlchemy・DB Sessionに依存しません。将来のAPI Providerは同じ共通フィールド名へ対応付けてNormalizerを使えます。

| Dataset指定 | 用途 | 返却DTO |
| --- | --- | --- |
| OWN_POSTS | 自社投稿 | NormalizedPost (source_type=OWN) |
| ACCOUNT_DAILY | 自社Account日次指標 | NormalizedAccountMetric |
| TREND_POSTS | 市場投稿 | NormalizedTrendData (post.source_type=MARKET) |
| COMPETITOR_POSTS | 競合投稿 | NormalizedCompetitorData (post.source_type=COMPETITOR / followers別保持) |

ファイル名から種別を推測しません。BackendのPythonから明示指定して読めます。Upload APIはPhase 4のImportServiceを介してこのProviderを利用します。

```python
from app.providers.base import CsvDatasetType, DataProvider, ProviderFileError
from app.providers.csv_provider import CSVProvider

provider: DataProvider = CSVProvider()
try:
    result = provider.read("own_posts.csv", CsvDatasetType.OWN_POSTS)
    print(result.total_rows, result.valid_rows, result.invalid_rows)
    # result.records: 正常なDTO / result.errors: 行単位ValidationError
except ProviderFileError as error:
    print(error.error.code, error.error.message)
```

UTF-8とUTF-8 BOM、カンマ区切り、Header必須、列順自由。以下の**全Headerが必須**ですが、必須値以外のセルは空欄可です。Headerは大小文字を区別し前後空白を除去します。重複・不足・空Header・Typoを拒否します。

| CSV | 全Header | 必須値 |
| --- | --- | --- |
| own_posts.csv | platform,post_id,account_name,posted_at,text,media_type,impressions,reach,views,likes,comments,shares,saves,hashtags | platform/post_id/account_name/posted_at |
| account_daily.csv | platform,account_name,date,followers,following,post_count | platform/account_name/date |
| trend_posts.csv | platform,post_id,posted_at,text,keyword,hashtags,views,likes,comments,shares | platform/post_id/posted_at |
| competitor_posts.csv | platform,account_name,post_id,posted_at,text,media_type,views,likes,comments,shares,followers | platform/account_name/post_id/posted_at |

- 数値の空欄・NULL（大小文字不問）はNone、0は整数0。負数・小数・指数形式・桁区切り・非数値を拒否します。DB互換の上限はBIGINT (2^63−1)。account_nameは100文字、post_idは255文字まで。
- X/x/Twitter/twitter→X、Instagram（大小文字不問）→INSTAGRAM。未知値・IG・ALLは行エラーです。
- media_typeは大小文字差を吸収し、PHOTO→IMAGE、REEL→VIDEO、ALBUM→CAROUSEL。未知値をOTHERへ置換しません。空欄・NULLはNone。
- posted_atは `YYYY-MM-DDTHH:MM[:SS[.ffffff]]Z` または末尾 `±HH:MM` のISO 8601日時。Timezoneを保持し、Timezoneなし・不正日付は拒否します。dateは厳密なYYYY-MM-DD。
- textは前後空白だけを除き、内部改行・全角文字・絵文字・URLを保持します。CSVの引用符で囲まれたカンマ・改行にも対応します。
- hashtagsの複数指定は **セミコロン区切り**（例 `#生成AI;#ChatGPT`）。空要素を除き、#なしには#を付加し、順序を保って重複を除きます。大小文字を変換しません。空欄は[]。空白・カンマでの複数指定や#だけの要素は行エラーです。
- keywordはTrim後0または1件のkeywordsリストになります。カンマ等で勝手に分割せず、Unicode・大小文字を保持します。
- 元行はHeader名だけTrimし、セルの元表現をraw_data/raw_metricsへコピーします。通常の追加列は保持します。Token・Secret・Password・API Key等の資格情報名の列はファイルエラーとして拒否し、エラーに値を含めません。API adapterも資格情報を渡さない契約です。

`ProviderResult`はrecords/errors/total_rowsと、計算プロパティvalid_rows/invalid_rowsを返します。1行の複数Field Errorは保持し、invalid_rowsは行数で数えます。ValidationErrorはrow_number/field/code/message、raw_valueは返しません。row_numberはHeaderを1としてCSVレコードが始まる物理行（複数行セルも対応）、DTOにも保持します。

行エラーは該当行だけ除外し、他の正常行を保持します。ファイルなし・読取不能・不正UTF-8・Header問題・引用符破損・列数不一致は `ProviderFileError` により全体を中止します。途中までの正常行も返しません。Headerだけは0件として正常、物理空行は無視し、空セルだけの行はValidation対象です。csv標準Parserのfield_size_limitを超えるセルもファイルエラーです。ファイル全体のサイズ制限・UploadはPhase 4のAPIで扱います。

**Phase 3のProvider単体ではDB保存しません。** Account ID解決・重複DB確認・Import履歴・Transaction・MatchingはPhase 4のImportServiceが担当します。競合followersはpost.followersに混ぜず、NormalizedCompetitorData.followersからServiceへ渡します。Trend集計はPhase 5のTrendService、実SNS通信は後続Phaseです。

DB不要のPhase 3テスト（backendフォルダー）:

```powershell
.venv/Scripts/python -m pytest tests/providers -q -p no:cacheprovider
```

Docker内では `docker compose exec backend python -m pytest tests/providers -q -p no:cacheprovider`。架空の4CSVサンプルは `backend/tests/fixtures/csv/`、検証結果は [Phase 3実装報告書](implementation_reports/Phase3_Implementation_Report.md) にあります。

## CSV Import（Phase 4）

`POST /api/v1/projects/{project_id}/imports` にmultipart/form-dataで、必須の `file`（UTF-8 CSV）と `import_type` を送ります。ファイル名から種別を推測しません。有効なProject/Platformと、OWN/COMPETITORの取込では該当Accountを事前にDBへ登録してください。照合を行う場合はTopic/Termも登録します。現段階の確認用設定はPhase 2 Seedを利用できます。

| import_type | 保存内容 |
| --- | --- |
| OWN_POSTS | 登録済みの有効なOWN Accountに紐づく投稿・投稿指標・Topic/Term関連 |
| ACCOUNT_DAILY | 登録済みの有効なOWN Accountの日次指標 |
| TREND_POSTS | MARKET投稿・投稿指標・Topic/Term関連。account_idはNULL |
| COMPETITOR_POSTS | 登録済みの有効なCOMPETITOR Accountの投稿・投稿指標・followers・Topic/Term関連 |

処理は `UploadFile → 最大64 KiBずつ一時ファイルへコピー → CSVProvider → Project/Platform/Account確認 → 正常行を一括保存 → Matching → 最終履歴更新` の順です。ファイルは20 MiBが既定上限で、`MAX_IMPORT_FILE_SIZE_BYTES` により変更できます。ちょうど上限までは許可します。一時ファイルは成功・失敗ともfinallyで削除し、DBのfilenameにはWindows/Unixのディレクトリを除いたbasenameのみ保存します。255文字超・空の名前・制御文字は拒否します。

最初に短い別TransactionでPROCESSING履歴をCommitします。**1 CSVの正常行すべてとSUCCESS/PARTIAL_ERROR履歴を1つのBusiness TransactionでCommit**し、DB障害・想定外の制約違反・Programming Error時は業務データを全Rollbackして、別Audit TransactionでFAILED履歴を確定します。重大エラーを行エラーとして処理しません。全DB停止でAuditも不可能な場合は履歴を確定できず、安全な固定ログ `IMPORT_AUDIT_FAILED` を出します。Phase13では起動時に前プロセス由来のPROCESSING履歴をFAILEDへ回復します（下記参照）。

| HTTP / status | 意味 |
| --- | --- |
| 200 / SUCCESS | 全行正常（HeaderだけのCSVは0件成功） |
| 200 / PARTIAL_ERROR | ProviderまたはApplicationの行エラーあり。異常行のみSkip。全行異常でもこのStatus |
| 400 / FAILED | CSV構造・Encoding等のファイルエラー、無効なfilename |
| 404 / FAILED | Project不存在 |
| 409 / FAILED | Project非アクティブ等 |
| 413 / FAILED | CSV本体が上限超過 |
| 422 | import_type/file必須・種別/UUID不正。入力値は応答へ転載しない |
| 500 / FAILED | DB等の重大障害。SQL・資格情報・内部例外は応答へ含めない |

Project/filename/リクエストが不正で履歴作成前に拒否した場合、import_idや履歴はありません。作成後のファイルエラー・サイズ超過・DB障害はFAILED履歴を残します（Audit接続可能な場合）。

応答は `import_id / status / total_count / success_count / error_count / errors`。total_countはCSVのデータ行数、success_countは正常処理した行数、error_countはSkip行数です。1行に複数Field Errorがあってもerror_countは1です。投稿重複を更新した行も成功行に数えます。API/DB設計Ver1.1を優先し、errorsおよび履歴error_detailの行番号は `row`、その他は `field / message / code` とします。ProviderのValidationError.row_number契約は保持しています。

```json
{
  "import_id": "00000000-0000-0000-0000-000000000001",
  "status": "PARTIAL_ERROR",
  "total_count": 10,
  "success_count": 7,
  "error_count": 3,
  "errors": [
    {"row": 3, "field": "likes", "code": "INVALID_INTEGER", "message": "Metric must be a non-negative integer or NULL"},
    {"row": 4, "field": "likes", "code": "INVALID_INTEGER", "message": "Metric must be a non-negative integer or NULL"},
    {"row": 5, "field": "account_name", "code": "ACCOUNT_NOT_FOUND", "message": "Active account was not found"}
  ]
}
```

投稿は `(project_id, platform, platform_post_id)` でINSERT/UPDATEします。異なるSource Typeで同じ投稿IDが来ても同じPostを更新し、post_id・created_atは保持します。updated_atは既存Model仕様と同じCURRENT_TIMESTAMPを明示更新します。

投稿指標7項目はpost_metricsへ分離し、**Import開始時刻を1回だけ取得して全行共通のrecorded_at**にします。別時刻で再取込すると新Snapshot、同じ `(post_id, recorded_at)` は全7項目・raw_metricsをUPSERTします。ClockはServiceへ注入できます。

日次指標は `(account_id, recorded_date)` でfollowers/following/post_count/raw_metricsをUPSERTし、空欄・NULLも最新入力として既存値を置換します。競合followersはNoneなら保存を省き、値があれば元Timezoneのposted_at.date()を使用します。**同日複数行はDB詳細設計Ver1.1 §26に従ってCSV内の後勝ち**です（Phase 4指示書の最新posted_at優先より正本を優先）。既存following/post_countを保持し、raw_metricsのfollowersのみ更新します。

Matchingは有効なProject内の有効Topic/Termだけが対象です。候補をNFKC→Trim→casefoldし、DBのnormalized_termと比較します。Hashtag・明示KeywordはOriginal完全一致ならEXACT、正規化一致ならNORMALIZED（EXACT優先）。本文KeywordはNORMALIZED、ASCII英数字・underscoreのTermは前後のASCII境界、それ以外は部分一致です。match_scoreは100。TopicはHASHTAG優先、なければKEYWORDです。再取込で古い自動Matchを削除して作り直し、MANUAL/AIの関連・スコアを保持します。保持Termの親Topic関連も維持します。設定なし・Matchなしでも取込は成功します。

実行例（架空Project ID・架空ファイル。実際のID/登録Accountに置換してください）:

```powershell
curl.exe -X POST "http://localhost:8000/api/v1/projects/00000000-0000-0000-0000-000000000001/imports" -F "import_type=OWN_POSTS" -F "file=@sample_own_posts.csv"
docker compose exec backend python -m pytest tests/imports -q -p no:cacheprovider
docker compose exec backend python -m pytest tests/providers -q -p no:cacheprovider
docker compose exec backend python -m pytest -q -p no:cacheprovider
```

Phase 4完了時は新規111件、既存275件と合わせて全386件を実PostgreSQLを使って確認しました。Integration/APIテストは通常開発DBとは別の破棄可能DBで、AuditとBusinessを独立Session/接続で実Commit・Rollbackします。Phase 5ではPost系ImportのMatching後・最終履歴更新前にTrendを再構築し、投稿・指標・関連・Trend・最終履歴を同じBusiness TransactionでCommitします。Import履歴一覧GET・設定管理・取込UIはPhase 6で追加しています。詳細は [Phase 4実装報告書](implementation_reports/Phase4_Implementation_Report.md) を参照してください。

## Trend Engine（Phase 5）

`TrendRepository → build_trend_rows / Decimal計算 → TrendService` が、Project内のMARKET投稿だけから `trend_daily` を再構築します。Topicは `post_topics`、Termは `post_terms` の正式関連をそれぞれ独立して集計し、MANUAL/AIも重みなしで含めます。Topicでは複数Termが一致しても同じ投稿を1件と数えます。有効Topic/Termと有効ProjectPlatformだけが出力対象です。

**Version 1 Trend aggregation timezone = UTC**。Project全体のMARKET投稿の最古～最新UTC日付を連続して出力し、投稿がない日・一致がないTopic/Termにも行を作ります。投稿ごとに `recorded_at` が最新のPostMetric 1件を使います。

Engagementは `likes + comments + shares + saves` の既知値の合計です。全項目NULL・Metricなしは不明、明示的な0は既知の0です。不明投稿も投稿数に含め、平均の分母からは除きます。Window内に既知値がなければ、DBのNOT NULL制約に合わせて `engagement_count=0`、平均・Engagement Growth・対応ScoreはNULLです。

| 指標 | 計算 |
| --- | --- |
| Current / Previous / Prior | 基準日Dに対して D−6～D / D−13～D−7 / D−20～D−14（両端含む7日） |
| Post Growth | `(Current投稿数 − Previous投稿数) / Previous投稿数 × 100` |
| Engagement Growth | `(Current合計Engagement − Previous合計Engagement) / Previous合計Engagement × 100` |
| Acceleration | Current対PreviousのPost Growth − Previous対PriorのPost Growth（百分率の差） |
| 平均Engagement | Current合計Engagement / CurrentのEngagement既知投稿数 |

前期間の分母0・計算材料不足はNULLです。Engagement Growthは両Windowに既知値が必要です。**利用者の明示指定により、正本Ver1.1との差異である「全NULLは不明」「合計Engagementの増加率」をPhase 5詳細仕様どおり採用**しています。

4成分を同じPlatform・UTC日付・7日Window・集計粒度の中でMin-Max正規化します。TopicとTermは別Cohortです。`(値−最小値)/(最大値−最小値)×100`、全同値・既知値1件は50、NULLはNULLのままです。Trend Scoreは `Post Growth Score×0.40 + Engagement Growth Score×0.30 + Engagement Level Score×0.20 + Acceleration Score×0.10`。1成分でも不足すればNULLで、重みの再配分はしません。Decimal精度50で計算し、Rawは小数4桁、Scoreは2桁のROUND_HALF_UP。Rawは丸める前に正規化し、成分Scoreを2桁に丸めてから加重します。

対象Projectの既存Trendを無効Topic分も含めて削除し、全期間を再INSERTするFull Rebuildです。他Projectは変更せず、再実行で業務値は同じになります（UUID/作成時刻は再生成）。MARKET投稿なしは既存行を消して0件になります。Service/Repository内部でCommitしません。

OWN_POSTS / TREND_POSTS / COMPETITOR_POSTSの正常行保存・Matching後に1回だけ自動再構築し、ACCOUNT_DAILYでは行いません。Source Type変更によるMARKET除外も反映します。同じProjectのPost ImportはProject行の `FOR UPDATE` で直列化し、別Projectを一括ロックしません。ACCOUNT_DAILYは既存の共有ロックを維持します。Trend失敗時は投稿・指標・Matching・Trendを全Rollbackし、FAILED履歴は別Transactionに残します。

明示的な再構築もBackendのServiceから呼べます（架空UUIDは実在Projectに置換）:

```python
from uuid import UUID
from app.db.session import SessionLocal
from app.services.trend_service import TrendService

with SessionLocal.begin() as session:
    rows = TrendService().rebuild_project(
        session, UUID("00000000-0000-0000-0000-000000000001")
    )
    print(rows)
```

```powershell
docker compose exec backend python -m pytest tests/trends -q -p no:cacheprovider
docker compose exec backend python -m pytest -q -p no:cacheprovider
```

Phase 5新規93件、全479件成功（失敗・Skip 0）。DB Schema・Migration・既存API応答・Frontendは変更していません。Trend API/画面は後続Phaseです。詳細は [Phase 5実装報告書](implementation_reports/Phase5_Implementation_Report.md) を参照してください。

## Settings / Import（Phase 6）

起動は上記と同じ `docker compose up --build -d`。ブラウザで [Settings / Import](http://localhost:3000/dashboard/settings) を開きます。`/settings` も同じ画面です。トップの接続確認画面からも移動できます。

1. **Project**：新規作成、名前・説明の保存、有効/無効の切替。Platformsは専用の保存ボタンで変更します。最低1つ必須です。Inactive Projectも選択・再有効化できます。
2. **Accounts**：OWN / COMPETITORを登録・編集・有効/無効化。Platform/Roleは作成後変更できません。有効OWNはProject×Platformに1件までです。変更する場合は既存を無効化して新規登録します。
3. **Topics**：Topic・KEYWORD / HASHTAG Termを追加・編集・有効/無効化。Hashtagは1件ずつ入力し、#なしは補完します。本文とCSV keyword/hashtagsに照合されます。
4. **Import**：4種のImport Typeを明示し、対応CSVを選択してImport CSV。結果、行エラー、最新20件の履歴、Previous/Next、Status/Typeフィルター、Detailを表示します。OWN/COMPETITOR取込前に該当Accountを登録してください。

Project選択はlocalStorage、TabはURL queryで保持します。保存・取込中は重複送信を禁止し、Loading/Error/Empty、再読み込み、フォーカス表示、aria-liveに対応しています。UIは既存Tailwindのみを利用します。

| Resource | API |
| --- | --- |
| Project | `GET/POST /api/v1/projects`、`GET/PUT/PATCH /api/v1/projects/{project_id}` |
| Platform | `GET/PUT /api/v1/projects/{project_id}/platforms` |
| Account | `GET/POST /api/v1/projects/{project_id}/accounts`、`PUT/PATCH/DELETE /api/v1/projects/{project_id}/accounts/{account_id}` |
| Topic | `GET/POST /api/v1/projects/{project_id}/topics`、`PUT/PATCH/DELETE /api/v1/projects/{project_id}/topics/{topic_id}` |
| Term | `POST /api/v1/projects/{project_id}/topics/{topic_id}/terms`、`PATCH /api/v1/projects/{project_id}/topics/{topic_id}/terms/{term_id}` |
| History | `GET /api/v1/projects/{project_id}/imports`、`GET /api/v1/projects/{project_id}/imports/{import_id}` |

PUTは正本Ver1.1の更新経路、PATCHはPhase6指示書の互換経路です。**Account/TopicのDELETEは正本に従った無効化のみ**で、行を削除しません。Project/TermのDELETEと物理削除UIはありません。Topic作成は `terms: [{term, term_type}]` の一括指定も可能です。

履歴は正本の `page=1&page_size=20`（page_size最大100）を使用します。指示書の `limit/offset` も受け付け、明示時はそれらを優先します。Responseはitems/total/page/page_size/limit/offset、status/import_typeでフィルター、imported_at DESC（同時刻はimport_id DESC）。一覧はerror_detailを省略しDetailに返します。異なるProjectのIDは404です。作成201、更新200。Settings APIのエラーは正本の `error: {code, message, details}`、Request Validation 422、意味的エラー400、不存在404、Unique/OWN競合409、想定外500です。入力値・SQL・内部例外を応答へ転載しません。既存POST Importの応答契約は維持します。

Term追加・文字/Type/Active変更、Topic Active変更では、**Settings保存 → 既存OWN/COMPETITOR/MARKET全投稿をRematch → 既存TrendServiceでFull Rebuild**を同一Transactionで行います。Topicの名前・説明だけなら再照合しません。Platform変更はTrendのみ再構築します。失敗時は設定・関連・TrendをすべてRollback。Platform解除後もAccount/投稿/指標/履歴は保持します。

RematchはActive Termsを1回取得し、投稿を500件ずつ読み、共通ImportRepositoryで自動関連をBatch再構築します。keywordsはraw_data.keywordから復元し、保存済み本文/hashtags/raw_dataは変更しません。EXACT/NORMALIZEDおよびKEYWORD/HASHTAGを再生成し、MANUAL/AIの関連・スコアと親Topicを保持します。TrendのUTC・NULL・7日Window・40/30/20/10・Min-Max契約は変更しません。

Settings変更はProject行の `SELECT ... FOR UPDATE` をTransaction終了まで保持し、同ProjectのPost Importと直列化します。別Projectは同時に処理できます。DB Schema/Migration追加はありません。

```powershell
docker compose exec backend python -m pytest tests/settings -q -p no:cacheprovider
docker compose exec backend python -m pytest -q -p no:cacheprovider
cd frontend
npm run typecheck
npm run build
```

Phase6新規77件、全556件Passed（Failed/Skipped 0）。Frontend型チェック・本番ビルド、ブラウザ登録/編集・PARTIAL_ERROR CSV取込・履歴詳細を確認。詳細と正本との差分は [Phase 6実装報告書](implementation_reports/Phase6_Implementation_Report.md) を参照してください。

## My Account（Phase 7）

自社投稿の成果を確認する画面です。起動後、Settings / ImportでProject・OWN Accountを登録し、OWN_POSTSと必要に応じてACCOUNT_DAILY CSVを取り込み、<http://localhost:3000/dashboard/my-account> を開きます。正本の `/dashboard/account`、短縮の `/my-account` でも同じ画面を表示します。

Project・Platform（ALL/X/INSTAGRAM）・UTC期間（7/30/90日または任意）・Media Type・本文Keyword・Hashtagで検索します。KeywordはNFKC・大小文字を正規化した部分一致、Hashtagは先頭#を補う正規化完全一致です。OWNのみ対象で、有効Platformを使用し、Inactive Account/Projectの過去投稿は保持します。

KPI（Posts、Reach、Impressions、Engagement、平均Engagement、ER、Followers）、UTC日次Engagement Trend、Media Type Performance、20件単位の投稿一覧・ソート・ページ送り、詳細Drawer（全文・最新指標・期間内比較・関連Topic）を表示します。Loading・Empty・Error・再取得に対応します。

| Method | API（共通prefix `/api/v1/projects/{project_id}`） |
| --- | --- |
| GET | `/accounts/own/analytics` |
| GET | `/accounts/own/posts` |
| GET | `/posts/{post_id}` |

Analytics/Listは `from=YYYY-MM-DD&to=YYYY-MM-DD` が必須です。Listは `page=1&page_size=20&sort=posted_at&order=desc` が既定、page_size最大100、NULLは末尾、同値はpost_id DESC。Detailへ同じ検索条件を渡すと同期間内で比較します。別Project・非OWN投稿の詳細は404です。

各投稿は `recorded_at DESC` の最新PostMetricだけを使用します。Engagementはlikes+comments+shares+savesの既知値合計、全NULLはNULLです。ERはEngagement÷分母×100、分母は最初の非NULL値をReach→Impressions→Viewsの順に選択します。分母0・Engagement不明・分母なしはNULL、分母0で別指標へ切り替えません。平均は既知値のみ、未丸め値で計算後4桁へ丸めます。SNS・分母が異なるERは一つに平均せず内訳を返します。FollowersはTo以前の最新AccountMetric、Account別表示で複数Accountを合算しません。NULLは画面で「—」、明示0は0です。

```powershell
docker compose up --build -d
docker compose exec backend python -m pytest tests/my_account -q -p no:cacheprovider
docker compose exec backend python -m pytest -q -p no:cacheprovider
cd frontend
npm run typecheck
npm run build
```

新規96件・全652件Passed、Failed/Skipped 0。DB Schema/Migration変更なし。検証結果・仕様判断・制限は [Phase 7実装報告書](implementation_reports/Phase7_Implementation_Report.md) を参照してください。

## Trend Explorer（Phase 8）

市場のKeyword・Hashtagを比較する画面です。Settings / ImportでTopic・Termを設定してTREND_POSTS CSVを取り込み、<http://localhost:3000/dashboard/trends> を開きます。`/trends` も同じ画面です。My Account・Settings・接続確認から移動できます。

Project・有効Topic・Platform（ALL/X/INSTAGRAM）・UTC期間（7/30/90日/任意、最大3660日）・Keywordで検索します。KeywordはTerm表示文字列のNFKC/trim/casefold後のリテラル部分一致で、%/_をワイルドカードにしません。

| GET API（共通prefix `/api/v1/projects/{project_id}`） | 用途 |
| --- | --- |
| `/trends/ranking?topic_id=...&from=...&to=...` | Term・SNS別ランキング。limit既定20、最大100 |
| `/trends/timeseries?term_ids=id1,id2&from=...&to=...&metric=post_count` | 1〜5個の異なるTerm UUIDをカンマ区切り。metricはpost_count/engagement/trend_score |
| `/trends/{topic_id}/top-posts?from=...&to=...` | MARKET人気投稿。optional term_id、limit既定10、最大50 |

**Trend Score/Growth/AccelerationはPhase5生成済みのtrend_dailyを読むだけ**です。ランキングは指定期間内のTerm・Platformごとの最新Snapshotを使用し、Topic行を混在させず複数日を合算しません。Score降順・NULL末尾。ALLでもSNS別行を維持します。Directionは保存されたpost_growth_rateの符号（UP/FLAT/DOWN/UNKNOWN）です。

比較はRechartsの凡例・Tooltip・UTC日付と日別表を表示します。行なしはNULL、保存済み0は0、Score NULLは算出不能として線を補間しません。最大5Term、ALLでは最大10線になります。Popular Postsは同ProjectのMARKET＋既存Topic/Term Matchを使用し、最新PostMetricだけでEngagementを計算（Phase7と同じNULL仕様）。Keywordは一致したTermのMatchを通じて全セクションへ連動します。

全APIはread-only/repeatable read、Schema/Migration変更なし。Error/Loading/Empty/再取得、古い応答の破棄に対応します。

```powershell
docker compose up --build -d
docker compose exec backend python -m pytest tests/trend_explorer -q -p no:cacheprovider
docker compose exec backend python -m pytest -q -p no:cacheprovider
cd frontend
npm run typecheck
npm run build
```

新規53件・全705件成功、Failed/Skipped 0。Browser証跡・仕様差分は [Phase 8実装報告書](implementation_reports/Phase8_Implementation_Report.md) を参照してください。

## Phase 9: Competitor

画面: <http://localhost:3000/dashboard/competitors>（alias `/competitors`）。Project・Platform・7/30/90日・任意UTC期間で、登録済み有効COMPETITORを1〜3件選択して検索します。同じ条件の有効OWNは自動追加し、ALLでもSNS別Accountのまま比較します。条件変更は検索時に全セクションへ適用します。

| GET API（`/api/v1/projects/{project_id}` 配下） | 内容 |
| --- | --- |
| `/competitors/analytics` | Followers・Posts・投稿頻度・各平均・分母別ER |
| `/competitors/topic-distribution` | Active Topic × AccountのDistinct投稿数・総投稿数・比率 |
| `/competitors/top-posts` | 選択COMPETITOR全体の最新Engagement上位投稿 |

共通Queryは必須`from`/`to`、`platform=ALL/X/INSTAGRAM`、必須`account_ids`（カンマ区切り、重複なし1〜3件のCOMPETITOR UUID）。OWNのUUIDを指定しません。別Project・OWN Role・Inactive・無効Platform・Platform不一致は404、件数/重複は400、UUID形式は422。期間両端をUTCで含め、最大3660日。Top Postsは`limit`既定10/最大50。

FollowersはTo以前の最新AccountMetricで、未来値・古い非NULL値による補完なし。Postsは対象期間内投稿数、投稿頻度はPosts÷期間日数（posts/day）。Views/Likes/Comments/Shares/Engagementの平均は最新PostMetricの既知値のみ。NULLは「—」、実値0は0です。EngagementはPhase5の共通関数、ERはPhase7の計算を再利用し、Reach→Impressions→Viewsの最初の非NULL分母を使います。分母0は算出不能、分母が異なるERは別Groupで表示し、優劣色を付けません。

Theme比率は既存PostTopicのDistinct一致投稿数÷Account総投稿数×100。総投稿0はNULL、投稿あり・Matchなしは0%。複数Topicに含まれる投稿があるため比率合計は100%を超える場合があります。再Matching・Trend再計算は行いません。TopicごとのGrouped Bar・凡例・比率/Match/Total/Account/Role/SNS Tooltipと表を表示します。Top PostsはCOMPETITORのみ、Engagement DESC NULLS LAST→投稿日時 DESC→UUID ASC、HTTP/HTTPSリンクのみ表示します。

APIはread-only/repeatable read、Schema/Migration変更なし。Loading Skeleton・Error/再取得・Empty/Settings導線・古い応答破棄・Project切替時の選択クリアに対応。

```powershell
docker compose up --build -d
docker compose exec backend python -m pytest tests/competitors -q -p no:cacheprovider
docker compose exec backend python -m pytest -q -p no:cacheprovider
cd frontend
npm run typecheck
npm run build
```

新規76件・全781件成功、Failed/Skipped 0。Browser証跡・Fallback・未検証項目・変更ファイルは [Phase 9実装報告書](implementation_reports/Phase9_Implementation_Report.md) を参照してください。検証Projectは架空データです。競合Followersは既存COMPETITOR_POSTS CSVのFollowers列から取り込みます（ACCOUNT_DAILYはOWN専用）。

## Phase 10: Gap Analysis

画面: <http://localhost:3000/dashboard/gap>。基本・画面設計書の正本Routeを主入口とし、指示書の`/dashboard/gap-analysis`と互換入口`/gap-analysis`も同じ画面を表示します。Project・Platform（ALL/X/INSTAGRAM）・7/30/90日・任意UTC期間で検索し、同一Responseを散布図と表に表示します。

`GET /api/v1/projects/{project_id}/gap-analysis?platform=ALL&from=2026-09-04&to=2026-10-03`。必須from/toはUTC日付・両端inclusive、最大3660日。期間不正400、未知Project/無効Platform404、UUID/日付/Platform形式不正422、内部障害は機密を含まない500。Typed Responseはtimezone/from/to/score_window_days/閾値/itemsを返します。

| 指標 | 仕様 |
| --- | --- |
| 粒度 | Active Topic × Project有効Platform。ALLでもSNS間で合算・平均しない |
| Trend Score | `trend_daily`のTopic行（term_id NULL・window_days 7）、期間内最大trend_dateの1 Snapshot。SUM/AVG・再計算なし |
| Own Post Ratio | 期間内TopicにMatchしたDistinct OWN投稿数 ÷ 同Project/SNSのOWN総投稿数 ×100 |
| Competitor Post Ratio | 同条件のActive COMPETITOR全体のDistinct Match投稿数 ÷ 全競合総投稿数 ×100。投稿数加重、Account比率の単純平均なし |
| Gap Score | Trend Score × (1 − Own Post Ratio /100)。競合比率は参考値で式には含めない |
| Sort | Gap Score DESC NULLS LAST → Topic名 ASC → Platform ASC → Topic UUID ASC |

RatioはDB詳細設計書25節の確定式、分類閾値は正本に数値指定がないため指示書FallbackのTrend50 / Own50%です。

| Classification | 条件 |
| --- | --- |
| OPPORTUNITY | Trend≥50、Own<50% |
| BALANCED | Trend≥50、Own≥50% |
| HIGH_COVERAGE | Trend<50、Own≥50% |
| LOW_PRIORITY | Trend<50、Own<50% |

散布図はX=Own Post Ratio（0〜100%）、Y=Trend Score（0〜100）。左上X<50/Y≥50をOpportunity Zoneとして背景・境界線で示します。色は分類、●X/◆InstagramでSNSを表し、TooltipにTopic/SNS/Trend/基準日/Own/競合/Gap/分類を表示。表は分子・分母も表示します。同座標のPointは重なるためSNSフィルターと表でも確認できます。

Trendは期間内最新の7日Rolling Snapshot、Ratioは選択期間全体です。Ratio/Gap/分類/SortはBackend計算。丸め前Decimalで計算・判定・Sortし、既存4桁HALF_UPで表示するため、閾値直近では表示50%でも丸め前値による分類の場合があります。

総投稿0の比率はNULL「—」。投稿がありMatch0は実値0%。TrendまたはOwn比率がNULLならGap/分類もNULL、表で「算出不可」とし散布図の(0,0)へ置きません。Active TopicはTrendなしでも保持します。重複Topicの比率合計は100%を超える場合があります。全PostTopic Match方式を利用し、本文の再Matchingはしません。

Role/source/account/project/platformの一致を検証し、MARKET・不整合行をRatioから除外します。競合はActive全件、OWNはPhase7と同様に整合するInactive Accountの過去投稿も含みます。Read-only / repeatable read、SQL側でDistinct集計、固定6 SELECT/WITH。1000 OWN＋1000 COMPETITOR・100 Topic・2 SNSでQuery数不変を検証しました。Schema/Migration・Trend Engine・Import変更なし。

Loading Skeleton・Error/再読み込み・Empty/Settings導線・version token/Unmountによる旧応答破棄を実装。起動と確認:

```powershell
docker compose build backend
docker compose build frontend
docker compose up -d
docker compose exec backend python -m pytest tests/gap_analysis -q -p no:cacheprovider
docker compose exec backend python -m pytest -q -p no:cacheprovider
cd frontend
npm run typecheck
npm run build
```

新規60件・全841件成功、Failed/Skipped 0。型チェック・本番ビルド・Docker build/up・Health200・Alembic `0001_initial (head)`・OpenAPI確認済み。実Backendの架空CSVで4分類・Tooltip・SNS/期間・NULL/0・Loading/Error/Empty/Project切替を確認。日付inputの自動fillはReact条件反映を確認できず、任意期間はURL条件で検証しました。手動日付入力、通信遅延を伴う競合E2E、大規模負荷は未検証です。詳細・変更ファイル・画面証跡は [Phase 10実装報告書](implementation_reports/Phase10_Implementation_Report.md) を参照してください。Phase11/12は実装していません。

## アクセスと確認

- Frontend: <http://localhost:3000>
- Backend APIドキュメント: <http://localhost:8000/docs>（`/` は未定義のため404）
- Health Check: <http://localhost:8000/api/v1/health>
- PostgreSQL: `localhost:5432`（コンテナ内の接続先は `db:5432`）

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health
docker compose exec backend python -m pytest -q -p no:cacheprovider
```

正常時は HTTP 200 と `{"status":"ok","database":"connected"}` を返します。DB接続障害時は HTTP 503 と `{"status":"error","database":"disconnected"}` を返します。内部例外は公開しません。

画面で Backend API / Database がともに Connected になることを確認してください。DB停止時はAPIがConnected、DBがDisconnectedとなり、API停止時はAPIがDisconnected、DBがUnknownとなります。「接続を再確認」で更新できます。

障害時の確認は `docker compose logs backend` などを使用してください。

Docker導入直後にコマンドや `docker-credential-desktop` が見つからない場合は、ターミナルを開き直してPATHを反映してください。メモリの少ない環境で同時ビルドが失敗する場合は、`docker compose build backend`、`docker compose build frontend` の順にビルドしてから `docker compose up -d` を実行できます。

## 停止

```powershell
docker compose down
```

名前付きVolumeにDBデータを保持します。`down -v` はデータを削除するため、通常の停止には使いません。既存VolumeのDBユーザー・パスワードは `.env` を書き換えるだけでは変更されません。

## ローカル品質確認（任意）

Frontendは Node.js 22 と npm を使用します。

```powershell
cd frontend
npm ci
npm run typecheck
npm run build
npm run dev
```

Backendは Python 3.12 を使用します。リポジトリルートから:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt
cd backend
.venv/Scripts/python -m pytest -q -p no:cacheprovider
```

全テストには稼働中のPostgreSQLが必要です。推奨コマンドはルートで `docker compose exec backend python -m pytest -q -p no:cacheprovider` です。コンテナのDB設定を使用して `sns_phase2_test_<32桁UUID>` の破棄可能なDBを作り、Migration・制約・Seedを検証して削除します。通常開発DBを更新・削除しません。作成用DBロールには `CREATEDB` 権限が必要です（Compose初期ユーザーは対応）。テストDB削除・downgradeは厳密な名前検査と通常DBとの不一致検査で保護しています。

Compose外では、下記の接続環境変数を設定してから全テストを実行してください。既存Phase 1の6件だけなら、DB不要で `python -m pytest tests/test_health.py -q -p no:cacheprovider` を実行できます。`no:cacheprovider` は非rootコンテナ・Windows環境のpytestキャッシュ書込み警告を避けるためで、テストをSkipする指定ではありません。

BackendをCompose外で起動する際は `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_HOST=localhost`、`POSTGRES_PORT=5432` をプロセス環境変数に設定し、backendフォルダーで `python -m uvicorn app.main:app --port 8000` を実行してください。Backend単体ではルート `.env` の自動読み込みはしません。

本構成はローカル開発用です。公開運用の設定は含みません。検証結果は [Phase 1 実装報告書](implementation_reports/Phase1_Implementation_Report.md)、[Phase 2 実装報告書](implementation_reports/Phase2_Implementation_Report.md) を参照してください。

## 参照した公式資料

- [Next.js Installation](https://nextjs.org/docs/app/getting-started/installation)
- [Tailwind CSS with Next.js](https://tailwindcss.com/docs/installation/framework-guides/nextjs)
- [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/)
- [Alembic Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [Alembic Autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
- [SQLAlchemy PostgreSQL](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html)
- [Python 3.12 csv](https://docs.python.org/3.12/library/csv.html)
- [Python 3.12 datetime](https://docs.python.org/3.12/library/datetime.html)
- [FastAPI Request Files](https://fastapi.tiangolo.com/tutorial/request-files/)
- [SQLAlchemy PostgreSQL UPSERT](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert)
- [python-multipart PyPI](https://pypi.org/project/python-multipart/)
# Phase 11 — Overview（統合ダッシュボード）

`http://localhost:3000/dashboard` で、自社KPI・Performance Trend・Trending Topics・Competitor Summary・Opportunity・AI Summaryを一画面で確認できます。互換入口は `/dashboard/overview` と `/overview`。接続確認ページ `/` と既存分析画面は引き続き利用できます。

- API: `GET /api/v1/projects/{project_id}/dashboard/overview?platform=ALL&from=2026-09-04&to=2026-10-03`。Overview本体は1リクエストで全Sectionを取得します。
- 正本Ver1.1に合わせ、`period`、`kpis.*.value` / 前期間比較、`top_trends`、`competitor_summary`、`top_opportunity`、`ai_summary`を返します。日次データの `performance_trend`、自社/競合集約、Rate CohortとAccount別FollowersをTyped Responseとして補足しています。
- 正本の別API `GET /api/v1/projects/{project_id}/dashboard/performance-trend` も実装。共通Queryに `metric=reach|engagement|followers|posts` を指定します。Followersは合計 `series` を作らず `follower_series` を返します。
- KPIはTotal Reach、Engagement Rate、Followers、PostsにImpressions、Engagementを追加。Phase7のOWN全投稿・Latest PostMetric・既知値のみの合計・Rate Cohort・Active OWNのTo以前最新Followersを再利用します。Inactive OWNの過去投稿はKPIに残ります。
- 期間はUTC/from・to inclusive、最大3660日。ALLはProjectの有効SNSのみ。比較期間は直前の同日数期間です。前期間0や不明値から増減率を作りません。ERの前期間差はSNS/分母Cohortが一致する場合だけ返します。日付下限で完全な比較期間を作れない場合は前期間をNULLとします。
- NULLは「—」、実値0は「0」。異なるSNS/分母のERは単一値NULL＋Group別表示。複数AccountのFollowersを合算せず、Account別に表示します。
- Performance TrendはReach/Engagement/Followers/Posts切替。投稿日UTCで日別集計した全日付をBackendが返します。0投稿日はPosts=0、Reach/Engagement=NULL。Followersは日次Snapshotのみ、欠測NULL・`row_present=false`。補間/Carry Forwardを行いません。単独観測も点として表示します。
- Trending TopicsはActive Topic×SNSの期間内最新7日Rolling SnapshotからScore上位5件。Term行/NULL Scoreを除外。最新ScoreがNULLなら過去値に戻しません。Score降順→Topic名→SNS→UUIDの安定順、方向はPhase8共通関数を使用します。
- Competitor SummaryはActive OWN/COMPETITORをPhase9のScope/計算で比較。競合集約は全有効競合投稿の既知Engagementの平均、Account平均の平均ではありません。RateはSNS/分母別、FollowersはAccount別。最大3競合はAccount名の安定順で表示します。詳細はCompetitor画面で選択してください。
- OpportunityはPhase10 Gap Analysisの有効Gap先頭と完全一致。Gap=0も有効、分類はOPPORTUNITYに限定しません。市場/自社データ不足時は正常NULLです。
- AI Summaryは同Projectの既存Insightを読むだけ。対象SNS（ALLはplatform NULL）を優先し、その後created_at最新順。候補はALL/有効な対象SNSに限定します。本文 `summary` が文字列の場合だけ表示し、未知構造はメタデータ表示。Insightなしは「AI Insightsはまだ生成されていません」。OpenAI呼出・生成・再生成・Phase12 Routeは追加していません。
- 全Sectionは1つのREPEATABLE READ / PostgreSQL read-only Transaction。同時更新でもSnapshotが一致します。通常16 SELECT/WITH固定、N+1なし。DB Schema / Migrationの変更なし。
- Projectは `localStorage sns-project`、Platform/期間はURL。Overviewと既存画面間の導線は共通Filterを保持。Loading Skeleton、Error/再試行、Section別Empty/Import導線、Partial Empty、Request version/Unmountによる旧応答破棄を実装しました。

起動・検証（Repository Root）:

```powershell
docker compose build backend frontend
docker compose up -d
docker compose exec -T backend pytest -q -p no:cacheprovider
docker compose exec -T backend alembic current
docker compose exec -T backend alembic heads
docker build --target build -t sns-analyzer-frontend-check ./frontend
docker run --rm sns-analyzer-frontend-check npm run typecheck
```

Frontendの `npm run build` はDocker frontend build内で実行。最終Backend Testは **908 passed（既存841＋Phase11新規67）、Failed 0 / Skipped 0**。typecheck/build成功、Health HTTP200 `ok/connected`、Alembic `0001_initial (head)`。実ブラウザーでX/Instagram/ALL、7/30/90日、URL任意期間、Metric切替、Followers複数Series、NULL/0、Empty、Error復帰、既存画面との数値一致を確認しました。

日付inputへのBrowser自動fillはReact条件更新を確認できなかったため、任意期間はURLで検証しました。手動日付入力・意図的な遅延応答E2E・全Browser/モバイル・大規模本番SLA・既存AI本文の実画面表示は未検証です。Phase12へ自動進行しません。詳細と画面証跡は [Phase11 Implementation Report](implementation_reports/Phase11_Implementation_Report.md) を参照してください。

## Phase 12 — AI Insights

画面は [AI Insights](http://localhost:3000/dashboard/insights)。ProjectはlocalStorage `sns-project`、Platform・UTC期間はURLでOverviewと引き継ぎます。7/30/90日・任意期間、生成/再生成、4区分のレポート、保存された根拠の展開、注意事項を表示します。Overviewは保存結果を読むGETのみで、自動生成しません。

| API（`/api/v1/projects/{project_id}`配下） | 契約 |
| --- | --- |
| GET `/insights/latest` | platform=ALL/X/INSTAGRAM、必須from/to。同じProject・SNS・期間の最新行のみ。`{insight, ai_generation_available}`、該当なしはinsight=null |
| POST `/insights/generate` | JSON `{platform, from, to}`。成功201、保存済みTyped Insightを返す。同条件の再生成も新しい行をINSERT |

正本の`sections.market_trend / own_analysis / improvement_points / post_ideas`を保持し、contentへsummary、cautions、referencesを追加。各改善案/投稿案と同じ順序の根拠ID配列をBackendで検証します。不正ID・不完全/拒否応答は保存しません。旧Ver1.1形式は読み取り時だけ表示し、根拠参照のない旧形式であることを明示します。既存行を書き換えません。

### OpenAI設定

`.env.example`のOpenAIキーは空です。利用する場合、Git対象外のルート`.env`へ利用者自身がキーを設定し、Backendを再作成してください。キーを画面やDBへ入力する機能はありません。

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-6-luna
OPENAI_TIMEOUT_SECONDS=30
```

```powershell
docker compose up -d --force-recreate backend
```

OPENAI_MODELは生成に使用するモデル、TIMEOUTは1〜120秒（不正設定は30秒）です。キー未設定でも全サービス・Health・既存分析は起動します。AI画面は設定案内＋生成ボタン無効、POSTは安全な503 `AI_KEY_NOT_CONFIGURED`。キー値をFrontendへ渡さず、Booleanだけを返します。モデルへの実アクセス権や実APIでの品質/所要時間は利用者の環境で確認してください。

OpenAI Python SDK **3.24.0**、Responses API `responses.parse(text_format=AIInsightContent)`、Pydantic Structured Outputs、`store=false`を使用。Tools・Conversation・previous_response_idは使用しません。SDK retry=0、明示ボタンで再試行する設計です。有限timeoutと最大出力6000 tokenを設定します。モデル名は実Responseのmodelを保存し、取得できない場合だけ環境設定を使用します。

### 入力・根拠・トランザクション

Phase7〜11共通Serviceを再利用し、同じread-only / REPEATABLE READ Snapshotでinput_summary/evidenceを作成します。Read Sessionを閉じてからOpenAIを呼び、Structured Outputと実在するEvidence IDを検証後、短い別Write TransactionでINSERT/COMMITします。外部API待機中はDB接続を保持せず、生成後に元データを読み直して根拠を変更しません。再生成はappend-only、ALLはDB platform=NULL。Migration追加なし。

入力はUTC scope・前期間比較・OWN KPI/Rate Cohort/Account別Followers・最新7-day Topic×SNS Trend最大5件・Active競合最大3件/全体集約・Gap先頭最大1件。Account名/表示名/投稿本文/著者名/raw_dataを送信しません。全競合のFollower配列を送らず、選択最大3件のAccount別Followersを保持します。Active OWNは既存DB制約によりSNS別最大1件、合計最大2件。ERはSNS/分母別、Followersは非合算、NULLと実値0を維持。KPI・Trend・競合・Gapの独自計算はありません。

PayloadはUTF-8最大48000 bytes、Trend5/競合3/Gap1、本文各1600文字・改善案/投稿案/注意事項各最大5件。2000投稿のテストでも投稿数に比例して本文が増えません。投稿時間帯集計の共通APIは未実装のためAIが時間帯の数値を補いません。自社テーマの根拠は既存Gap先頭のOwn Post Ratioです。

Evidenceはkpis/trends/competitors/opportunities、Stable ID（KPI_REACH、TREND:TopicUUID:SNS、COMPETITOR:AccountUUID、GAP:TopicUUID:SNS）と値を保存。「根拠データを見る」は保存済みSnapshotを展開します。AIへ再質問しません。認証/Rate Limit/Timeout/接続/5xx/Refusal/不正形式/不正根拠は安全な503、保存失敗は500。失敗時は旧レポートを保持し、Source/Prompt/SDK例外の内容を通常ログへ出しません。

Browser成功/失敗検証用の`backend/tests/insights/browser_fixture.py`はテスト専用の別起動サーバーです。production appはimportしません。使い捨てPostgreSQL、Fake adapter、生成遅延4秒、Instagram GET遅延6秒、3回目の生成失敗を使い、実OpenAI呼出を行いません。通常Composeは常に本番Adapterを使用します。

詳細・検証結果・既知課題・証跡は [Phase12 Implementation Report](implementation_reports/Phase12_Implementation_Report.md)。[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)、[Responses移行ガイド](https://developers.openai.com/api/docs/guides/migrate-to-responses)、[Model一覧](https://developers.openai.com/api/docs/models)を確認しました。


## Phase 13 — 横断品質改善

分析計算式・公開Route・DB Schema・Migrationは維持します。Phase14のDemo Dataや実SNS連携は追加していません。

Backendのstartupで、既存PROCESSING履歴を1回の原子的UPDATEでFAILEDにし、`IMPORT_INTERRUPTED`の安全なsystem errorを追加します。件数とimported_at、他statusは変更しません。2回目の回復は0件です。**Backend 1 process / uvicorn 1 worker**を前提とし、startup完了前は受付しません。multi-worker / multi-instanceではlease / heartbeatの再設計が必要です。初回導入のMigration前でテーブル自体がなければ回復対象なしとして起動し、従来の明示`alembic upgrade head`を使用します。自動Migrationはしません。DB障害など回復失敗時は安全な固定エラーでstartupを中止します。

Import POST専用の公開ASGI middlewareでContent-Length超過をparser前に413にします。Content-Lengthなし・過少申告・不正値でもreceive実測を行い、上限超のchunkをparserへ渡しません。Starlette 1.7.0の公開HTTPException処理と、解析例外時のspool cleanupを確認しました。private API / monkey patchは使いません。通常経路の64 KiBコピー・CSV本体の厳密な20 MiB上限・finallyでのTemp cleanupも維持します。

- Request上限超: 413 `REQUEST_TOO_LARGE`、Import履歴作成なし、本文/filenameのechoなし。
- Request上限以内・File上限超: 従来の413 `FILE_TOO_LARGE`、FAILED履歴を保存。
- Composeでは21 MiBを既定にします。単独Backend起動でRequest変数を省略した場合はFile上限＋1 MiB。File上限を変更したらRequest上限もoverhead分を含めて調整してください。

6分析画面は小さな共通Utilityを使用します。UTCの過去30日、URL parse、Project有効SNSへの補正、期間validation、query生成、named date inputのFormData確定を揃えました。切替先で無効なPlatformは初回分析request前にALLへ補正し、無効optionをdisabledにします。Competitorは有効Role/Project/PlatformのIDだけを保持します。検索で適用する既存UXとAIの即時Platform/Preset更新は維持します。

5画面の取得Hookは共通のrequest versionで古い成功・失敗・finallyを破棄し、Project unmountでも無効化します。AIのGET/POST共通version方式も維持します。Loadingはstatus/aria-live、Errorはalert、Empty/Partial Emptyはsection別、取得/生成中の重複実行buttonはdisabledです。同条件の再取得・再試行を維持します。

AI POSTはKey未設定なら重いOverview/DB接続の前に503 `AI_KEY_NOT_CONFIGURED`。内部保存SnapshotにはProject UUIDを残し、外部送信用deep copyからanalysis_scope.project_idを除きます。投稿本文・名前・raw data・Secretの除外、保存Evidence、Structured Outputs、SDK3.24.0、gpt-6-luna、Prompt phase12-v1、store=false、retry=0は維持します。

Settings/分析およびImport Routeは予期しないdependency/serialization例外も安全な500へ変換します。既存業務エラーcodeとImport固有のResponse形式を保持します。Phase7/8の無効SNSは従来どおり正常Empty、後続分析は404です。見た目だけを揃える契約変更はしません。

構造的な性能確認は時間閾値を使いません。1500投稿・100TermでもMy Account3、Ranking5、Popular5、Competitor Top4、Gap6、Overview16、AI snapshot16 SELECT/WITHが一定で、ページ/Top N返却とAI Payloadを制限します。候補行のPython sort/sliceとImportの行ごとのMatch SELECTは残ります。NULL順・tie break・Unicode正規化・CSV後勝ちの意味を証明せずSQLへ置換しません。

追加確認:

```powershell
docker compose exec -T backend pytest -q -p no:cacheprovider
docker build --target build -t sns-analyzer-frontend-check ./frontend
docker run --rm sns-analyzer-frontend-check npm test
docker run --rm sns-analyzer-frontend-check npm run typecheck
```

Browser用`python -m tests.quality.browser_fixture`は使い捨てDBと実Serviceを使う明示テスト起動です。Instagram応答を6秒遅延します。production appはimportせず、通常DBへDemo/AIデータを追加せず、実OpenAIを呼びません。通常終了で検証DBを破棄します。

結果と検証範囲は [Phase13 Implementation Report](implementation_reports/Phase13_Implementation_Report.md) を参照してください。Phase14へ自動進行しません。


## Phase 14 — 総合テスト / Demo Data / 表示言語

クリーンCloneからの最短手順（Repository Root）:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# .envのDB passwordを設定。OPENAI_API_KEYは空でDemo閲覧できます。
docker compose build backend frontend
docker compose up -d
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend python -m app.demo.loader --anchor-date 2026-10-04 --seed 1401 --directory /demo_data/canonical
```

[Overview](http://localhost:3000/dashboard?platform=ALL&from=2026-07-07&to=2026-10-04)で`Phase14 Canonical Demo`を選択します。OWN180、Competitor540、Market4500、OWN日次180、3競合、6Topic/12Term、X/Instagramの架空CSVです。90日分を既存Import・Matching・Trend Engineで処理し、7画面で同じ期間の集計を確認できます。

Gap4分類、Gap0、NULL非0化、投稿形式4種、本文/Hashtag・日本語/絵文字の検索、複数TermのTrend、Account別Followersを確認できます。保存済みAIは**固定Demo Fixtureであり、実OpenAI APIは呼んでいません**。実SNS API連携済みという意味ではありません。

通常のLoader再実行は停止して増殖を防ぎます。固定ID/markerに限定した明示`--reset-demo`、Generatorの`--anchor-date` / `--seed`、投入・再生成・期待画面の詳細は[Demo Data説明](../demo_data/README.md)、件数/ファイルhashは[Manifest](../demo_data/manifest.json)を参照してください。自動startup/Seed/Migrationによる投入は行いません。

Settingsの「表示言語 / Display Language」で日本語 / Englishを変更できます。7画面の固定UIだけを切り替え、`sns-analyzer.locale`をlocalStorageへ保存します。再読込後も維持し、不正値はjaへFallback。Project名・投稿本文・Topic/Term・保存AI Contentは自動翻訳されません。UI LanguageとAI Content Languageは別です。

クリーン環境相当のFrontend検証は、ローカルnode_modulesをbindせず、npm ciを行うbuild imageを使います:

```powershell
docker build --target build -t sns-analyzer-frontend-check ./frontend
docker run --rm sns-analyzer-frontend-check npm test
docker run --rm sns-analyzer-frontend-check npm run typecheck
docker compose run --rm -T --no-deps backend pytest -q -p no:cacheprovider
```

Migrationは`0001_initial`、公開26Path/13テーブルを維持。既知のPython候補行保持・CSV全records・行単位Import/Full Rebuildは継続します。Live OpenAI・実SNS・本番同時負荷は未検証。結果と証跡は[Phase14 Implementation Report](implementation_reports/Phase14_Implementation_Report.md)へ記録します。Phase15へは進まずReview待ちです。
