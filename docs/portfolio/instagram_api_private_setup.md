# Instagram Login Private Setup — Version 2.0 Interim / Deferred

仕様調査の確認日: 2026-10-05。Version 2.0 Interimでは **Deferred / OAuth and Profile foundation only**。X中心のInterim Release Candidateは進行可能ですが、Instagram E2Eの完了を意味しません。
投稿・Insights同期は、未確認の公式契約を使用しないため通信前に停止します。
このガイドの設定だけではPhase 7は完了しません。
Completion修正後のCapabilityは `ACCOUNT_PROFILE` のみです。`OWN_POSTS` / `OWN_METRICS` は未対応として表示し、ProfileのみのValidateは可能です。保存済みの古いCapabilityもAPI表示時に利用可能機能へ制限します。

## 1. 公式仕様を確認する

以下はMeta公式資料です。第三者の記事やFacebook Login向けの契約で置き換えないでください。

- [Instagram Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login): Professional Business / Creatorを対象とし、Facebook Page連携は不要。
- [Business Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login): 認証コードの交換、長期Tokenの取得、更新条件。
- [Get Started](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started): `user_id` がInstagram Professional Accountの正規ID。`id` はApp-scoped ID。
- [Media reference](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media): 現在取得できた資料では `caption` と `media_product_type` はFacebook Loginのみとの記載があります。Instagram Loginでの利用可否について、更新された公式資料またはMetaの回答が必要です。
- [Media Insights](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights): FEED / REELS / STORYによって利用できる指標が異なります。Media Product Typeを推測してリクエストしません。

`INSTAGRAM_GRAPH_API_VERSION=v26.0` は明示pinの候補です。
[Meta SDK設定](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/apiconfig.py)と再確認したMediaページ表示はv26.0を示しますが、公式Media / Insights Markdownはv25.0を最新と記載しています。対象endpoint全体の版対応は未確認です。確認してから実通信を行ってください。`latest` と版省略は使用しません。

## 2. 人が準備するもの

1. Meta Developer登録済みのAppとInstagram製品を準備します。
2. 自分が管理するBusiness / CreatorアカウントをAppへ追加し、役割・テスター承認を確認します。Personal Accountは使用しません。
3. 要求する権限は `instagram_business_basic` と `instagram_business_manage_insights` の2つだけです。投稿・メッセージ・コメント管理権限は要求しません。
4. 自分が所有・管理しAppへ追加したアカウントはStandard Accessを確認します。他者のアカウントへ提供する場合はAdvanced Access、App Review、必要なBusiness Verificationを確認します。
5. 実Insightsを検証できる自分の投稿を最低1件用意します。指標反映に遅れがある場合は不明値を0に置き換えません。
6. 全JobScheduleを無効のままにし、手動検証だけを実施します。

## 3. 設定とSecretStore

公開 `.env.example` の3つのInstagramフラグはfalseです。CodexはPrivate `.env` や既存X Secret Volumeを変更していません。

| 設定 | 用途 |
| --- | --- |
| `LIVE_MODE_ENABLED` + `INSTAGRAM_OAUTH_BOOTSTRAP_ENABLED` | OAuth開始・Callback |
| `LIVE_MODE_ENABLED` + `INSTAGRAM_LIVE_SMOKE_ENABLED` | Profile通信・Credential解決 |
| 上記 + `INSTAGRAM_LIVE_REFRESH_SMOKE_ENABLED` | Token更新 |
| `INSTAGRAM_GRAPH_API_VERSION` | 明示Graph版。現在の候補v26.0 |
| `INSTAGRAM_OAUTH_REDIRECT_URI` | Meta登録と完全一致するHTTPS Callback |
| `INSTAGRAM_CLIENT_ID_FILE` / `INSTAGRAM_CLIENT_SECRET_FILE` | Instagram App ID / Secretのローカルファイル参照 |
| `RUNTIME_SECRET_KEY_FILE` | Runtime SecretStore用暗号鍵。SecretStoreディレクトリ外に配置 |
| `INSTAGRAM_TOKEN_REFRESH_SKEW_SECONDS` | 自動更新の開始余裕。既定604800秒（7日）、最大30日 |

BackendとWorkerが必要な設定を共有し、BeatにはInstagram Secretを渡しません。
通常のOAuthは、長期TokenをRuntime SecretStoreへ暗号化して保存します。
Token bootstrapを行う場合も、正しい発行日時と有効期限が必要です。
`issued_at` / `expires_at` は実際の値を使用し、更新可能に見せるための改変は禁止です。
Instagramは別の `refresh_token` を必要としません。既存の同名環境変数はInstagram更新処理に使用しません。

## 4. HTTPS CallbackとOAuth

Callbackは `/api/v1/providers/INSTAGRAM_API/oauth/callback` です。
現在の実装はHTTPS URIのみを受け入れます。HTTP loopbackがMetaで許可されることは今回の資料では確認できていません。
利用者が管理するHTTPS到達経路とMetaのValid OAuth Redirect URIの完全一致を確認してください。
Agentが認証情報を入力したり、公開トンネルを自動で作成したりすることはありません。

開始APIは `POST /api/v1/projects/{project_id}/providers/INSTAGRAM_API/oauth/start`。
対象は有効なLIVE ProjectのInstagram Providerです。返された認証URLを利用者自身が開き、2つの権限を確認して認可します。
認証URL・OAuth state・codeをChat、ログ、スクリーンショットへ貼らないでください。
暗号化stateは10分有効・一度限りで、Project、Provider、Redirectと照合されます。
MetaのInstagram Login契約にPKCEの指定がないため、X用PKCEパラメーターは送信しません。

Callbackは認証コードをMetaの固定POST endpointで一度だけ交換し、続いて固定GET endpointで長期Tokenを取得します。
両方成功した場合だけ既存Credentialを原子的に置き換えます。途中失敗時に既存Credentialを削除しません。
Callback応答は認可結果のみでTokenを返しません。Providerを自動でEnableしたりJobを起動したりしません。

## 5. Validate / Syncの現状

ValidateはProfileだけを取得し、`user_id`、Professional種別、usernameとAccount指標を確認します。
Meta権限やSecretの未設定は固定Error Codeで失敗し、DEMOへFallbackしません。

**手動Syncは現在実行不可**です。`INSTAGRAM_SPEC_UNVERIFIED` でProfile、Media、Insights通信の前にJobをFAILEDにします。
未確認のMedia Product Typeに基づく指標選択、投稿Import、Checkpoint更新は行いません。
仕様確認後、最大5件の初期同期、上限5ページの増分同期、Insights全取得後の業務CommitとCheckpoint、再実行の冪等性を実装・検証する必要があります。

## 6. 実Refresh

Metaの長期Tokenは最大60日です。更新には、実際に24時間以上経過し、Tokenが未失効であることが必要です。
新規Token発行直後は実RefreshをPASS扱いにせず、NOT EXECUTED / USER_ACTION_REQUIREDとして残します。

通常のCredential解決は有効期限の7日前から更新を試みます。
Private確認用の `InstagramCredentialManager.refresh_connection()` は、期限接近を待たずに明示更新できますが、24時間条件、未失効条件、LiveとRefreshフラグ、行Lockと論理Credential Lockは同じです。
更新GETは副作用があるため自動再試行しません。失敗時に既存暗号化Credentialを保持します。
更新後はRuntime SecretStoreを再読込し、Profile取得で同一 `user_id` を確認してください。

## 7. 秘密情報と終了条件

Token、App Secret、Runtime Secret Key、OAuth code/stateをGit・README・Chatへ貼らないでください。
Meta ConsoleのスクリーンショットにSecretを含めず、Runtime暗号化ファイルやPrivate DB、実投稿Caption、Media／Insights dumpをレビューZIPへ入れないでください。
レポートには件数、成功／失敗、固定Error Codeだけを記載します。

将来Instagram E2Eを完了するには、公式契約確認、投稿・Insights実装とMock検証、最低1件の実投稿取込、Analytics照合、実Refresh、X回帰、全体Gateの成功が必要です。Version 2.0 Interimの完了とは別の判断です。
現在はこれらのLive条件を満たしていません。詳細は[Phase 7報告](../implementation_reports/v2_phase7_instagram_api_end_to_end.md)と[Completion継続報告](../implementation_reports/v2_phase7_instagram_api_completion.md)を参照してください。
