# Phase 4 実装報告書

実施日: 2026-10-03（JST）。対象: CSV Import / Import History / Transaction / Duplicate・UPSERT / Topic・Term Matching。

## 1. 実装概要

4CSVのmultipart POST API、ImportService、PostgreSQL Persistence、Topic/Term Matching、履歴とTransaction管理、新規111テスト、READMEを実装した。既存13テーブル・Migration・Phase 3 DTO/Providerを変更していない。業務Frontend、履歴一覧GET、設定CRUD、Trend集計、Score計算、SNS/OAuthは対象外。

正本として基本設計書・画面設計書・API設計書・DB詳細設計書のVer1.1、Codex Phase計画Ver1.0を確認した。優先順位は正本設計→現行DB Schema/Tests→Phase 3 Contract→Phase 4指示書。特にDB §26/28/29、API §16を適用した。

## 2. 作業開始時Git状態

Branch: master。開始HEAD: `4288942ab6d85c5b107d6c17f65155a1170553c0`（Phase 3報告追記）。Remoteなし。Authorは既承認の利用者指定のAuthor（個人情報は公開用文書から除去）。

開始時statusは `?? docs_2.zip` のみ。Phase 4外のため未読・未編集・未Stageとした。作業中の再確認ではファイルが存在せず、statusからも消えていた。本作業ではこのZIPの削除・移動・Git追加を行っていない。消失理由は確認していない。

`.env`は未追跡・ignore対象。依存・Build生成物もignore対象。履歴書換え、Remote追加、Branch変更を行っていない。

## 3. Phase 3基準点確認

Phase 3完了Commit `a747058156926ab7c4b8f4992e7d17678abf09d5` が履歴に存在する。開始時Docker全Testは **275 Passed / 0 Failed / 0 Skipped / Warning 1**（6.17秒）。基準点として既存のProvider 150件を含む。

## 4. 新規作成ファイル

- `backend/app/api/v1/imports.py`
- `backend/app/services/__init__.py`
- `backend/app/services/import_service.py`
- `backend/app/services/matching_service.py`
- `backend/app/repositories/__init__.py`
- `backend/app/repositories/import_repository.py`
- `backend/tests/imports/__init__.py`
- `backend/tests/imports/conftest.py`
- `backend/tests/imports/test_matching.py`
- `backend/tests/imports/test_pipeline.py`
- `backend/tests/imports/test_api.py`
- 本実装報告書。

## 5. 変更ファイル

`.env.example`、`docker-compose.yml`（Upload上限環境変数）、`backend/requirements.txt`（multipart追加）、`backend/app/core/config.py`（設定・正整数検証）、`backend/app/main.py`（Router/CORS）、`README.md`。Frontend Source・DB Model・Alembic・Provider・Normalizer・DTO・既存Testは変更していない。

## 6. Import API

`POST /api/v1/projects/{project_id}/imports`。multipart必須項目: file、import_type。種別はOWN_POSTS / ACCOUNT_DAILY / TREND_POSTS / COMPETITOR_POSTS、project_idはUUID。

応答はimport_id/status/total_count/success_count/error_count/errors。正本のAPI/DB設計例に合わせ、エラーはrow/field/messageへ安全なcodeを追加する。内部DTOのrow_numberからrowへ変換し、DTOは変更しない。

HTTP: 正常/行エラー200、ファイル不正400、不存在Project404、Inactive409、サイズ超過413、必須/Enum/UUID不正422、Server障害500。履歴作成前の拒否ではimport_id/履歴なし。作成後の失敗はFAILED結果を返す。

ImportRouteだけでRequestValidationErrorを安全なloc/type/msgへ変換し、FastAPI既定のinput/ctx転載を避ける。既存Healthの挙動は保持する。OpenAPIからmultipart契約も確認した。

## 7. ImportService構成

`start()`でProject確認・Clock取得・PROCESSING履歴、`run()`でProvider読込→Application Validation→Prepared Records→Persistence→Matching→最終履歴更新、`fail()`で別Audit保存を行う。SessionFactory・Provider・Repository・Clockを注入可能。同期SQLAlchemyを継続し、同期RouteはFastAPIのworker thread上で処理する。RepositoryはCommitしない。

## 8. Upload / Temporary File

UploadFile.fileを最大64 KiBのchunkでNamedTemporaryFileへコピーし、CSVProvider.read(path, type)を使用。全文bytes/stringへの一括読込はしない。成功・File/DB障害・サイズ超過時ともfinallyでclose/unlinkする。

WindowsのbackslashとUnixのslashを共に扱い、basenameのみ保存する。255文字超・空・`.`/`..`・制御文字は切詰めず拒否する。`../evil.csv`と`C:\temp\evil.csv`はevil.csvとして保存することをAPI Testで確認した。

上限既定値20 MiB（20971520）は正本未規定のためPhase 4で追加した運用上のDefault。`.env.example`・Compose・Settingsへ配線済み。正整数のみ許可し、Testは小さい上限を注入してちょうど上限/超過を確認した。これはCSV本体のコピー時制限であり、HTTP multipart parserの事前spoolingや全リクエストサイズ制限とは別である。

## 9. Project / Platform Validation

開始時に存在/activeを確認し、不正ProjectではProviderを実行しない。Business Transaction内でもProjectをshared row lockで再確認する。Project Platformにない行はPLATFORM_NOT_ENABLEDとしてSkip。Projectを自動Activateしない。

## 10. Account Resolution

Project/platform/exact account_name/role/activeで解決。OWN_POSTSとACCOUNT_DAILYはOWN、COMPETITOR_POSTSはCOMPETITOR。不存在・inactiveはACCOUNT_NOT_FOUND、誤RoleはACCOUNT_ROLE_MISMATCH、想定外の複数AccountはFatal。大小文字を勝手に同一視しない。MARKETはaccount_id/author_nameがNULL。Accountは自動生成しない。

## 11. Business Transaction

正常行のSNSPost/PostMetric/AccountMetric/PostTerm/PostTopicと最終SUCCESS/PARTIAL_ERROR履歴を、1つのsession.begin()で確定する。Provider/Application Validation後に書込対象を準備し、行単位Commitをしない。

途中Repository障害、実CHECK制約違反、履歴最終更新障害、before_commit障害を実PostgreSQLで発生させた。投稿・指標・followers・関連の増分が全0で、FAILED履歴が独立接続から読めることを確認した。既存投稿/指標/関連を更新してから失敗した場合も、取込前の値へ復元される。

## 12. Import History Transaction

開始AuditでPROCESSINGを独立Commit。Business成功ではデータと履歴が同時Commit。Business失敗ではRollback後、独立AuditでFAILEDをCommit。独立Session/接続からPROCESSINGの可視性、成功前のデータ非可視性、成功後の同時可視性、FAILEDの永続性を検証した。

通常の失敗経路はPROCESSINGからFAILEDへ移行する。全DB停止でAuditも失敗する場合は更新不能であり、固定ログIMPORT_AUDIT_FAILEDのみ記録する。内部例外はログへ転載しない。この不可避なケースおよびプロセス強制終了のPROCESSING回復は後続運用課題であり、自動Recovery Jobは今回実装していない。

## 13. sns_posts INSERT / UPDATE

既存Unique(project_id, platform, platform_post_id)でON CONFLICT DO UPDATE。account/source/author/posted_at/text/media/permalink/hashtags/raw_dataを最新入力へ更新。post_id/created_atを維持し、updated_atは既存Timestampsと同じCURRENT_TIMESTAMPを明示更新する。別Source Typeによる同一自然キーの再取込も同じPostを更新する。

## 14. post_metrics Snapshot / UPSERT

7指標は専用PostMetricへ保存。Import開始時にtimezone-aware UTC Clockを1回取得し、全行共通のrecorded_atとする。同Import内の重複行はUnique(post_id, recorded_at)のUPSERTで最新入力へ更新。T1/T2で再取込すると2 Snapshot、同じT1で再取込するとそのSnapshotを更新することを確認した。

raw_metricsは7項目の正規化値だけを保存し、raw_data全体を転載しない。NULLと0を区別する。

## 15. account_metrics UPSERT

Unique(account_id, recorded_date)でON CONFLICT DO UPDATE。ACCOUNT_DAILYはfollowers/following/post_count/raw_metricsを全置換し、NULLでも旧値を保持しない。再取込と同ファイル内重複、空欄/NULL/0/正数を確認した。

## 16. Competitor Followers処理

followersがNoneなら更新しない。値があれば元Timezoneのposted_at.date()で保存し、UTC変換による日付ずれを起こさない。followersのみ変更し、既存following/post_countおよびraw_metricsの他キーを保持する。

**正本DB Ver1.1 §26がCSV内の後勝ちを明記**しているため、Phase 4 §36の最新posted_at優先は採用しない。日時が逆順/同時刻の2ケースでも後行の値を採用し、成功行として扱う。CONFLICTING_ACCOUNT_METRICは今回生成しない。

## 17. Topic / Term Normalization

候補はNFKC→Trim→casefold。DB normalized_termを比較の正として使用し、Seed/設定の一括書換えをしない。全角・大小文字・空白・日本語混在の規則をUnit Testで確認した。

## 18. post_terms Matching

有効なTopic/Termで、Hashtagと明示Keywordは完全比較。TrimしたOriginalがtermと同じならEXACT、それ以外の正規化一致はNORMALIZED。本文KeywordはNORMALIZED。ASCII英数字/underscoreのみのキーは同種文字の前後境界を考慮し、paid/mail/railway/xAI/AI2/AI_works内部を除外する。日本語・混在キーは部分一致。score=100、EXACT優先。同Termの複数経路を1件へまとめる。

## 19. post_topics Matching

一致Termの親Topicごとに1件。HASHTAG優先、なければKEYWORD、score=100。MANUAL/AIは新規自動生成しない。Match 0/設定なしは正常取込。ACCOUNT_DAILYはMatchingしない。

## 20. Duplicate再Matching

既存PostTermのEXACT/NORMALIZED、PostTopicのKEYWORD/HASHTAGだけを削除して再構築する。MANUAL/AIは同一PKへのDO NOTHINGで内容・スコアを維持する。DO NOTHINGは保護対象との競合にだけ使用し、投稿・指標の重複更新を無視していない。

保持されたMANUAL/AI Termの親Topic関連も欠けないよう補完する。既存MANUALとAI両方のPostTopic、両方のPostTermが再取込後も保持されることを検証した。

## 21. Error Handling

ProviderFileErrorは安全な構造化ErrorをFAILED履歴へ保存し、部分recordsを使用しない。Unexpected SQL/Integrity/Session/Programming/Commit ErrorはFatalとして全Rollback。Errorはrow/field/code/messageのみ、入力値・SQL・接続文字列・Tracebackを保存/公開しない。API 422でもinputを返さない。Phase 3のSENSITIVE_HEADER拒否を維持する。

DB FatalはIMPORT_DATABASE_ERROR / Import could not be completedの固定内容。Upload一時ファイル作成/読取障害はFILE_UNREADABLE。全DB停止時は履歴なしの安全な500応答となることも確認した。

## 22. Import Count / Status仕様

total_count=Provider.total_rows、success_count=正常処理CSV行数、error_count=Skip行数。複数Field Errorを行数と混同しない。10行中Provider不正2、Account不存在1、正常7の結果は10/7/3、Field Error5件でPARTIAL_ERROR。全行異常もPARTIAL_ERROR。Headerのみは0/0/0 SUCCESS。

Fatalではsuccess_count=0。Provider正常終了後は判明したtotalとSkip数を保存。Provider File Fatalでは0/0/0 FAILED。success+error<=totalを保証する。

## 23. CORS変更

単一FRONTEND_ORIGINを維持し、GET/POST、Accept/Content-Typeを許可。Wildcardを導入しない。Allowed OriginのPOST preflight成功、Unknown Origin拒否、および既存Healthテストの回帰を確認した。

## 24. Dependency変更

python-multipart==0.0.32のみ追加。PyPIの公開versionとFastAPI公式Upload説明を確認した。無関係な更新/psycopg重複整理を行っていない。Docker内pip check: No broken requirements found。

公式資料: [FastAPI Request Files](https://fastapi.tiangolo.com/tutorial/request-files/)、[SQLAlchemy PostgreSQL UPSERT](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert)、[python-multipart](https://pypi.org/project/python-multipart/)。

## 25. Phase 4新規Test結果

`docker compose exec backend python -m pytest tests/imports -q -p no:cacheprovider`

**111 Passed / 0 Failed / 0 Skipped / Warning 1**（11.34秒）。内訳: Matching Unit 30、PostgreSQL Pipeline Integration 49、API/設定 32。matching単独も30 Passed（0.09秒）を確認した。

Integration/APIは既存の名前検査付きdisposable_database・Migration fixtureを再利用する。独立Session/接続で実Commitし、各Testは生成DB内の自分のProjectをCASCADE削除する。生成DBはセッション終了時に削除される。通常開発DBへの破壊操作は行わない。

## 26. Provider 150 Test回帰結果

`docker compose exec backend python -m pytest tests/providers -q -p no:cacheprovider`

**150 Passed / 0 Failed / 0 Skipped**（0.49秒）。Phase 3 Contractを維持した。

## 27. 全Regression Test結果

最終Source/Testを含むDocker Imageを再Buildしてから実行:

`docker compose exec backend python -m pytest -q -p no:cacheprovider`

**386 Total / 386 Passed / 0 Failed / 0 Skipped / Warning 1**（21.28秒）。既存275+Phase 4新規111。最初の新規102件検証後、Commit失敗・既存データ復元・Source契約・入力非転載・MANUAL/AI保持等を補強した最終結果。

## 28. Frontend Build / Typecheck

frontend内で `node node_modules/typescript/bin/tsc --noEmit` と `node node_modules/next/dist/bin/next build` 成功（npm scriptsと同じ入口）。Next.js 16.3.8の本番Build、TypeScript、ページ生成成功。Frontend Source変更なし。Phase 4業務UIは作成しておらず、GUI操作の検証も今回の対象ではない。

## 29. Docker / Health / Alembic確認

`docker compose build backend` / `docker compose up -d` 成功。最終Imageに変更Source/Testが含まれる。

DB healthy / Backend healthy / Frontend running。GET `/api/v1/health`: HTTP 200、`{"status":"ok","database":"connected"}`。OpenAPIにImport POST/multipartを確認。API取込の書込検証は破棄可能DBを使うTestClientで実施し、通常開発DBには架空データを入れていない。

`docker compose exec backend alembic current` = 0001_initial (head)、`alembic heads` = 0001_initial (head) の1件。追加Migrationなし。

Backend static: ローカル `python -m compileall -q app` 成功。Dockerでも `docker compose exec -e PYTHONPYCACHEPREFIX=/tmp/sns_import_compile backend python -m compileall -q app` 成功（非root用cache出力先を指定）。

全Test終了後のTest DB残存0を確認した。通常開発DBはprojects=1、project_platforms=2、sns_accounts=5、watch_topics=2、watch_terms=6、その他8テーブル=0でSeedのみ。

## 30. Warning

既存StarletteDeprecationWarning 1件: TestClientのhttpx利用がdeprecated、httpx2推奨。今回の依存更新範囲外として維持し、Test失敗ではない。Provider単独はWarningなし。

初回Docker Buildには既存Dockerfileのroot pip実行Warningとpip更新Noticeが出た。Runtimeは従来どおりappuser。Git core.autocrlfによるLF→CRLF Warningは空白検査エラーではない。Frontend Build/型チェックはWarningなし。

## 31. 発生した問題と対応

実装開始時の既存Test 275、新規初回102件はすべて成功した。設計照合で競合followers優先規則とrow名の差異を発見し、正本優先を実装/Test/READMEに明記した。

レビューでUPSERT時updated_atを既存SQLAlchemy仕様と同じCURRENT_TIMESTAMPへ合わせた。DB障害・Commit失敗・既存データ復元の追加Test、およびFastAPIの不正入力値転載防止を追加した。

開始時のdocs_2.zipは後の読み取り確認で不存在となっていた。本作業の削除操作はなく、原因は未確認。Git対象へ混入していない。

## 32. 設計書との差異・未規定事項の決定

| 項目 | 決定 / 根拠 |
| --- | --- |
| 競合followers同日複数行 | DB Ver1.1 §26のCSV内後勝ちを優先。Phase 4 §36の最新投稿日時/同時刻Conflictは非採用 |
| Error行番号 | API/DB Ver1.1例のrowを採用。Providerのrow_numberは不変で境界で変換。codeを安全に追加 |
| Snapshot時刻 | 専用CSV列がないためImport開始Clockを1回取得し全行共通。後日再取込は新Snapshot |
| Upload上限 | 正本未規定。20 MiBを運用Defaultとして設定可能にした |
| Inactive Project | HTTP 409。未作成Accountは生成せず行Skip |
| ACCOUNT_DAILY | 空欄/NULLも最新行で上書き。競合followers更新では他指標を保持 |
| Matching | NFKC/Trim/casefold、ASCII境界/日本語部分一致、EXACT> NORMALIZED、HASHTAG>KEYWORD |
| 履歴保護 | Businessと独立した開始/失敗Audit。全DB停止/強制終了の自動回復は未実装 |
| MANUAL/AI親Topic | 既存関連を保持し、親Topic関連が欠ければ補完。MANUAL/AIは自動生成しない |
| UI / 集計 | 基本設計の完成形処理フローにある集計・画面はPhase計画の後続範囲として未実装 |

Schema変更を必要とする差異はない。現行match_method/window_days/raw_metrics NOT NULL/期間CHECKを保持した。

## 33. Phase 4完了Commit / Push結果

Commit成功: `22c3786d38fd690f0a897c0fae93e938ac686f50`。
Message: `feat: complete Phase 4 CSV import pipeline`。
18ファイル / 1376追加行 / 6削除行。

Stage後のstat・全差分・diff --checkを確認済み。実.env資格情報、生成物、Phase外Source/Schema変更の非混入検査成功。Test DB残存0、一時Upload CSV残存0。Commit直後のgit status --shortは出力なし（Clean）、Branchはmaster。

本節と完了判定の実績追記を `docs: record Phase 4 completion commit` の追加Commitで保存する。READMEの事前設定説明とエラー例も明確化する。自身のhashを自身のCommitへ含められないため、amend・履歴書換えは行わない。

Remoteは未設定のためPush未完了。Remote追加・変更をせず、指示書に従いPush不可のみをPhase 4失敗理由としない。

## 34. Phase 5への申し送り

Phase 4の正常Post・Metric・Topic/Term関連を入力としてTrend Engineを実装可能。投稿指標にはImport開始時刻でSnapshotが蓄積し、日次Account指標は最新入力に更新される。再取込でPost Sourceが変更される場合がある。競合followers同日値はCSV後勝ちである。

Import履歴一覧GET・設定CRUD・Settings/Import UIは後続管理Phase。PROCESSINGの運用回復、全HTTP request size制限、Import大容量/同時実行の性能・運用検証は今回対象外。変更済み契約を確認し、次Phase指示を受けてから進める。

## 35. Phase 4完了判定

**Phase 4完了。** 実装、111新規/386全Test、Provider150、Frontend Build/型チェック、Backend compileall、Docker/Health/Alembic、開発DB保護、README/本報告書、完了Commit/Cleanを確認した。Remote未設定によるPush不可は指示書に従い実装失敗としない。Phase 5へ進まず成果物レビューを待つ。
