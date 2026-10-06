# X API Private / Local Setup — Version 2.0 Interim

公開Portfolioの既定値はLIVE無効です。XはComplete / previously real-verified in private environmentです。Production Provider・PKCE・自動Refresh・手動／定期同期を実装し、過去のPrivate実接続で検証しました。Phase14では実通信を再実行していません。このガイドは別途Private環境を準備する場合の手順で、Public Demo起動には不要です。

## 1. Developer Appと費用の確認

X Developer ConsoleでOAuth 2.0を有効にし、AppのClient typeを確認してください。`X_OAUTH_CLIENT_TYPE`には`PUBLIC`または`CONFIDENTIAL`を明示設定します。Native / SPAとWeb App / Automated Appの区別をコードから推測しません。Confidentialの場合はClient Secretが必要です。

固定Read-only Scopeは`tweet.read users.read offline.access`です。Write Scopeは要求しません。ユーザー認可で3 Scopeを許可する必要があります。

実通信直前にDeveloper ConsoleでCreditと現在の課金単価を確認してください。2026-10-04に確認した公式表示はPost Read $0.005/resource、Owned Read $0.001/resourceですが、現在の請求額を保証しません。Owned Readは認証ユーザー本人のIDに加え、そのユーザーがDeveloper App Ownerである条件があります。本人の投稿だから自動的に低い単価になるとは判断しません。[公式Pricing](https://docs.x.com/x-api/getting-started/pricing)

## 2. CallbackとSecretの準備

Developer Consoleに次のURIを完全一致で登録し、同じ値を`X_OAUTH_REDIRECT_URI`へ設定します。

```text
http://127.0.0.1:8000/api/v1/providers/X_API/oauth/callback
```

Backendの8000番とFrontendの3000番はloopbackにのみ公開します。Callback設定はローカルHTTP、固定path、query / fragmentなしに制限しています。任意redirect_uriをAPIから渡すことはできません。

Client ID / Client Secret / Token / Fernet鍵はRepository外のSecret Fileまたは環境変数から提供します。`X_CLIENT_ID_FILE`、`X_CLIENT_SECRET_FILE`、`X_USER_ACCESS_TOKEN_FILE`、`X_REFRESH_TOKEN_FILE`、`RUNTIME_SECRET_KEY_FILE`を利用できます。コンテナ内のファイルパスを指定し、Repository外のCompose overrideからBackend / Workerにだけreadonly mountしてください。鍵は暗号文Volumeとは別に保管します。Beat / FrontendへCredentialは渡しません。

TokenをREADMEやChatへ貼らないでください。実`.env`をGitへCommitしないでください。Developer Consoleのスクリーンショット・exportにSecretを含めないでください。鍵を出力するコマンドの実行結果も共有しません。

## 3. Private DBとOAuth Bootstrap

通常Canonical Demo DBを流用せず、Repository外のprivate Compose overrideで別PostgreSQL DBと別Redis broker/queueを指定してください。Migrationは`alembic upgrade head`で0005まで適用します。Backend / WorkerのDB指定を一致させ、通常BeatからこのDBへ接続しないでください。Private DBにはLIVE / Xの専用Projectを作成し、Providerはまずdisabled、Scheduleはすべてdisabledの状態で開始します。通常のDEMO ProjectをLIVEへ変更してはいけません。

別Xアカウントを認可するProviderには異なる論理`credential_ref`を割り当てます。既定の参照名はPhase 5互換の`X_PRIMARY`です。同じ論理名を共有すると同じCredentialを参照します。Runtime payloadを使わないBootstrap Tokenにも正確なUTC expiry（`X_TOKEN_EXPIRES_AT`または`X_TOKEN_EXPIRES_AT_FILE`）とRefresh Tokenが必要です。期限不明を推測して通信しません。

OAuth設定・Scope・Creditを確認したユーザー環境でのみ、次のフラグを明示設定します。Codexは実`.env`を変更していません。

```text
LIVE_MODE_ENABLED=true
X_OAUTH_BOOTSTRAP_ENABLED=true
X_LIVE_SMOKE_ENABLED=false
X_LIVE_REFRESH_SMOKE_ENABLED=false
```

Private Backendの`POST /api/v1/projects/{project_id}/providers/X_API/oauth/start`を呼び、返された`authorize_url`を本人のブラウザーで開いて認可してください。このURLには一時stateがあります。共有・保存しません。CallbackはTokenを返さず、成功時に`authorized: true`だけを返します。

PKCEはCSPRNG state / verifier、SHA-256 / S256です。pendingは10分TTLでRuntime SecretStoreに暗号化します。CallbackはProvider行ロック下でpendingを再読込・消費し、一度だけ交換します。交換が失敗した場合も新しいstartから認可をやり直してください。認証Codeは短寿命です。UvicornアクセスログはComposeでは無効、直接起動時もOAuth queryを除去します。別のproxyを置く場合もCallback queryを記録しない設定が必要です。[公式OAuth](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code)

## 4. 少量のPrivate Live Smoke

認可・Scope・Creditを再確認した後で、ユーザー環境の`X_LIVE_SMOKE_ENABLED=true`を明示設定し、Private Backend / Workerを再作成します。`LIVE_MODE_ENABLED=true`との両方が必要です。最初のSmokeは`X_INITIAL_MAX_RESULTS=5`を維持してください。

1. Private DBのScheduleがすべてdisabledであることを再確認します。
2. `POST /api/v1/projects/{project_id}/providers/X_API/validate`を1回実行します。内部は`/2/users/me`だけです。設定済remote IDが違う場合は`PROVIDER_SCOPE_INVALID`で止まり、別アカウントへ切り替えません。
3. 成功後Providerだけenableし、`POST /api/v1/projects/{project_id}/providers/X_API/sync`を1回実行します。202 / PENDINGからWorkerでSUCCESSへ進むことを確認します。
4. 必須2 StepはSUCCESS、Trend / AIはSKIPPEDを確認します。SNSAccount / SNSPost / Metric / ImportHistoryのX_API provenance・Job参照と、POSTS last_remote_id / cursor NULLをPrivate DBで確認します。
5. 既存の`accounts/own/posts` / `accounts/own/analytics`を同じProject・X・取得日を含む期間で確認します。

初回は最新1ページのみのCurrent Snapshot Bootstrapです。next_tokenがあっても古い履歴へ進みません。Historical Backfillではありません。実リクエスト数・返却resource数は値を集計して記録し、実投稿本文・Token・Header全文はレポートへ出しません。ValidateでUser Read、SyncでUser Readと最大5 Post Readが発生し、429等のGET retryも追加リクエストになり得ます。

増分はsince_idで新規投稿を取得し、既定100件 × 最大5ページです。全ページ成功後にImportします。上限到達・途中失敗ならImport / checkpointを行いません。429はreset優先、60秒超の待機は行わずFAILEDとなります。[公式Timeline](https://docs.x.com/x-api/users/get-posts)、[公式Rate Limits](https://docs.x.com/x-api/fundamentals/rate-limits)

Metricはlikes=like_count、comments=reply_count、shares=repost_count+quote_count、saves=bookmark_count、impressions=impression_countです。どちらかのshares構成値が欠落すればsharesはNULLです。reach / viewsはNULL、欠落値を0へ置き換えません。

## 5. Real Refreshの確認

MockでのRefresh成功と実通信の検証は別です。過去のPrivate実Refreshは検証済みですが、新しい環境で再確認する場合はCredit・Scope・Refresh Tokenが使用可能であることを確認し、`X_LIVE_REFRESH_SMOKE_ENABLED=true`を明示設定したPrivate環境でのみ実行してください。Public Demo手順では実行しません。

Tokenが期限前5分以内となったタイミングでPrivate Validateを行うと、Credential ManagerがProvider行をFOR UPDATEでロックし、Secretを再読込してから1回Refreshします。期限判定に使う設定は`X_TOKEN_REFRESH_SKEW_SECONDS=300`、許容0～3600秒です。実expiryを短く偽装して通常DBやSecretを編集しないでください。Tokenが有効なら、残り時間が許容skew内になるまで待ちます。

実Token POST成功、暗号化payloadの置換、次回Resolverが新access / refreshを使用し、そのCredentialで`/2/users/me`が成功することを確認します。Refresh responseに新refresh_tokenがなければ旧値を保持します。外部応答のscopeがあれば必要Scopeを再検証します。失敗時は旧ファイルを削除せず、固定ErrorをProvider / Jobへ記録します。

Refresh / Code交換POSTは単回です。応答不明の通信失敗で使い捨てCredentialを自動再送しません。Refreshが拒否された場合は新しいOAuth startから再認可が必要です。通常のScheduled Syncでも同じ期限判定・自動Refreshが動作します。Phase 6ではRefresh POSTにも`X_LIVE_REFRESH_SMOKE_ENABLED=true`が必要です。falseのままで期限が迫ると`X_LIVE_REFRESH_DISABLED`で停止します。

## 6. 終了と判定

Smoke後はScheduleをdisabledのままにし、一時変更したPrivateフラグは元の設定へ戻します。公開既定値の4フラグはfalseを維持します。Private DB / Secret VolumeはRuntimeとして別管理し、Review ZIPには含めません。保持するか削除するかはユーザーが決めます。

公開既定値はフラグfalseです。実環境の設定と検証結果は[Private Live検証報告](../implementation_reports/v2_phase6_private_live_verification.md)を参照してください。Repositoryの既定値からPrivate RuntimeのCredential有無を判断しないでください。

## 7. 定期Live同期（Version 2 Interim / Phase 9）

定期実行はPostgreSQLのJobScheduleが正本です。Celery Beatには固定の`sns.scheduler_tick`（30秒）だけを登録し、Workerは共通の`sns.execute_job`を実行します。Providerの現在のAdapterと検証済みCapabilityの双方にACCOUNT_PROFILE / OWN_POSTS / OWN_METRICSが必要です。InstagramはDeferredのため、無効Scheduleの作成も同期実行も拒否します。未接続Xは無効Scheduleの作成のみ可能です。

Private検証は既存の暗号化Credentialを再利用します。LIVE_MODE_ENABLED / X_LIVE_SMOKE_ENABLEDをtrueにし、自然に期限が到来した場合のRefreshに備えてX_LIVE_REFRESH_SMOKE_ENABLEDをtrueにします。期限を改ざんしてRefreshを強制しません。再認可はCredential不足時だけ必要です。Runtime Secret Volumeは削除しないでください。`docker compose down -v`を使用しないでください。

1. Settingsで既存のX LIVE Projectを選び、Provider CONNECTEDと投稿・指標Capabilityを確認します。
2. 他の有効Scheduleと実行中Jobがないことを確認します。
3. SchedulesでXのINTERVAL 60秒を**無効**で作成し、Worker / Beatの正常性を確認します。
4. Scheduleを有効にし、最初のSCHEDULED Jobが作られたら直ちに無効化します。既存Jobは継続します。
5. Jobsの詳細でSUCCESS、必須2 Step SUCCESS、Trend / AI SKIPPED、scheduled_for、取込件数を確認します。
6. Schedulesのlast job / last runと無効状態・next runなしを確認し、以後Jobが増えないことを確認します。

新しい投稿がなければ投稿0件でも正常です。Account snapshotは保存され、POSTSの前回last_remote_idは維持します。手動同期を連打したり、確認用投稿・大量Pagination・Historical Backfillを行ったりしないでください。既存Analyticsは取得済みDBを読み、外部X通信を追加しません。

失敗したJobはJobsで固定Error Codeを確認してください。Provider ERRORやCapability消失で次Tickが受付を拒否しても、Schedule自体は自動で無効にはなりません。運用中の状態によっては有効Scheduleが失敗Jobを繰り返し作るため、検証後は必ずScheduleを無効にします。Disable / DeleteはCapabilityがなくなっても利用できます。

実通信の確認結果と残る制約は[Phase 9報告](../implementation_reports/v2_phase9_scheduled_live_sync_integration.md)に記録します。公開`.env.example`の4つのX / LIVEフラグはfalseを維持します。
