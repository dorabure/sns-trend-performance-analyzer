# Ver2.0 Phase 7 — Instagram API End-to-End implementation report

確認日: 2026-10-05 JST。**Incomplete / USER_ACTION_REQUIRED / Phase 8 NO-GO**。

この報告は初回Phase 7の検証記録です。後続のCapability修正と公式仕様再確認、最新検証結果は [Phase 7 Completion継続報告](v2_phase7_instagram_api_completion.md)を参照してください。

## 1. Executive Summary

Instagram Loginの認証、暗号化Token管理、Credential Manager Router、Profile取得を実装した。Backendは1554 passed / 0 failed / 0 skipped、Frontendは32 passed / 0 failed / 0 skipped、型検査とProduction Buildは成功した。

投稿・Media Insights・Initial/Incremental Syncは未実装である。取得した公式Media資料で `caption` と `media_product_type` がFacebook Loginのみと記載され、Instagram Loginで必要な契約を確認できないため、同期はHTTP通信前に `INSTAGRAM_SPEC_UNVERIFIED` で停止する。Mockの成功を実Insightsの完成とは扱わない。

InstagramのPrivate Validate、Sync、Insights、Refreshは全てNOT EXECUTED。Live Media件数もNOT EXECUTEDであり、取得0件という意味ではない。レビューZIPは未完了の成果物として作成する。

## 2. Git Baseline

Branch: master。HEAD: `e2ad3848105687fb1b48c872e48d15d9315b3b97`。
Phase 2–6の変更は既にWorktreeに存在していた。比較基準は `SNS_Analyzer_V2_Phase6_Verified.zip`、SHA256 `dfc756aba0801f34f8b5c63c4bf6d27358c148b25465a0a5a2b89e93d1bfb9f7`。既存未コミット変更を保持した。コミット、Push、Tag、公開、Phase 8作業は行っていない。

## 3. Changed Files

Phase 6 Verified ZIPとの差分は、本報告書を含め23ファイル。

- OAuth API: `backend/app/api/v1/instagram_oauth.py`、`backend/app/main.py`
- Provider / Credential: `backend/app/providers/instagram_api_provider.py`、`instagram_oauth.py`、`credential_manager.py`、`core.py`、`http_client.py`、`secret_store.py`
- Integration / Logging: `backend/app/services/provider_service.py`、`provider_sync_handler.py`、`backend/app/core/oauth_log_filter.py`
- 新規テスト: `backend/tests/instagram_api/__init__.py`、`conftest.py`、`test_oauth.py`、`test_provider.py`
- 既存テストの進化対応: `backend/tests/provider_core/test_api_migration.py`、`backend/tests/x_api/test_provider.py`
- 設定・資料: `.env.example`、`docker-compose.yml`、`README.md`、`README_EN.md`、`docs/portfolio/instagram_api_private_setup.md`、本報告書

既存X OAuthとX Providerの実装ファイルは比較基準とバイト一致。Frontend実装、CSV、DB MigrationをPhase 7では変更していない。

## 4. Meta Official Spec Verification

結果: **Partial**。公式資料だけを判断根拠とした。旧 `/docs/` URLではログイン表示や429が発生し、新 `/documentation/` URLをブラウザで確認した後、同ページのMarkdownを参照した。取得内容の全文は成果物に転載しない。

| 公式資料 | 確認内容 / 限界 |
| --- | --- |
| [Instagram Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login) | Business / Creator、Facebook Page連携不要 |
| [Business Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login) | Code交換、長期化、Refresh、24時間以上の経過条件 |
| [Get Started](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started) | Professional canonical IDはuser_id。idはApp-scoped |
| [Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) | caption / media_product_typeにFacebook Loginのみの記載。Instagram Loginへの適用は未確認 |
| [Media Insights](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media/insights) | Product Typeで指標が異なる。取得資料は最新v25.0との記載 |
| [Insights](https://developers.facebook.com/documentation/instagram-platform/insights) | 不明値、指標の提供条件、権限 |
| [Migration Guide](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/migration-guide) | Instagram Login用permission名 |
| [Meta SDK API config](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/apiconfig.py) | v26.0のpinを確認。各Instagram endpointの契約確認を代替しない |

利用者から、未確認フィールドの最新版公式資料は保有していないとの回答を受領した。Facebook Login仕様を転用せず保留する。

## 5. Graph API Version

`.env.example` の候補pinは **v26.0**。SDKの版と、取得したMedia/Insights資料のv25.0表記が一致しない。v26.0での全対象endpoint契約は未検証であり、Verifiedとしない。設定は `vN.0` の明示版のみ許可し、版省略、latest、URL挿入を拒否する。

## 6. Permission Contract

要求する権限は `instagram_business_basic` と `instagram_business_manage_insights` の2つ。Short Token交換レスポンスで両権限の付与を確認する。投稿、コメント管理、メッセージ権限は要求しない。Standard / Advanced Access、App Review、Business Verification、アカウント役割の実設定は利用者側で確認する必要がある。

## 7. Instagram Login / OAuth

Mock / DBテスト: PASS。実Login: NOT EXECUTED。
追加APIは `/api/v1/projects/{project_id}/providers/INSTAGRAM_API/oauth/start` (POST) と `/api/v1/providers/INSTAGRAM_API/oauth/callback` (GET) の2パス。既存42パスから44パスになり、全て `/api/v1/`。

StateはCSPRNG生成、TTL600秒、Project / Provider / Redirect URIに結合、暗号化保存、一回使用。期限切れ、Future timestamp、違うProject、Provider、Redirect、DEMO、Replayを拒否する。Redirectは登録と完全一致させるHTTPS URIのみ。Loopback HTTPを公式に許可されたものと推測しない。PKCEは取得した公式手順に記載がなく、実装・サポート可否の断定をしていない。認証は利用者自身のブラウザで行う。

## 8. Token Exchange

Code交換は固定 `https://api.instagram.com/oauth/access_token` へのmultipart POST。公式のdata envelope、App-scoped user_id、付与権限を検証する。Code再送による副作用を防ぐためTimeout / Network / 5xxでも自動再試行しない。レスポンスのTokenをAPI応答、DB、ログ、チャットへ出力しない。

## 9. Long-lived Token

長期化は固定 `https://graph.instagram.com/access_token` へのGET。公式grant、Client Secret、Short Tokenのみを固定の入力契約で渡す。HTTP transportを直接使用し、ClientのURLログ経路を避ける。expires_inを検証し、access_token、expires_at、issued_atを暗号化Runtime Secretとして保存する。架空のInstagram refresh_tokenは生成しない。

## 10. Token Refresh

Mock / DBテスト: PASS。実Refresh: NOT EXECUTED。
固定 `https://graph.instagram.com/refresh_access_token` へのGET、単一試行。未失効かつ発行から24時間以上経過し、LIVE / Smoke / Refresh gatesが揃った場合のみ実行可能。通常resolveは更新猶予期間に入った場合、明示refresh_connectionは猶予期間外でも24時間条件を守って更新する。期限切れは再認証エラー。時刻改ざんを運用へ導入していない。

Provider行FOR UPDATEとProvider種別・Credential論理参照単位のadvisory lockで並行更新を直列化し、Lock後に最新Credentialを再解決する。暗号ファイルをatomic replaceし、失敗時は旧Tokenを保持する。同じ論理参照を共有する2 Projectで、同時更新が1回になるテストを実施した。

## 11. Credential Manager Router

PASS。X_APIは既存XCredentialManager、INSTAGRAM_APIはInstagramCredentialManagerへ振り分ける。Sessionを転送し、未知のProviderは固定エラー。XのOAuth/Refresh条件をInstagramへコピーしていない。

## 12. SecretStore

IG Runtime Schemaはversion 1、access_token / expires_at / issued_at。IGだけにissued_atを追加し、Xの許容項目は保持した。Unknown overlayは拒否。KeyとCiphertextを別管理し、既存の暗号化・atomic replacementを使用する。Private `.env`、実Client Secret、実Token、既存X Secret Volumeを変更していない。秘密値をチャットへ要求していない。

## 13. Production Instagram Provider

**Partial**。Production RegistryへInstagram Provider / Normalizerを登録し、Profile Validateを実装。宣言されたOWN_POSTS / OWN_METRICSは予定の契約であり、運用可能な同期を意味しない。Market、Competitor、Trend収集は非対応。Live gateを守り、DemoへのFallbackはない。

`ensure_sync_ready()` は公式仕様の保留を検知して同期を拒否する。Media/Insightsまで完成したProduction Providerと評価しない。

## 14. Profile

Mock: PASS。実Profile: NOT EXECUTED。
Bearerで `/me` を取得し、user_id / username / name / account_type / followers_count / follows_count / media_countを検証する。Professional canonical user_idとApp-scoped idを混同しない。Business / Media_Creatorのみ許可。単一objectまたは単一data envelopeを扱い、不明値はNULL、実値0は0を保持。Bool、負数、不正ID、非Professional、複数Accountなどを拒否する。

## 15. Media

**NOT IMPLEMENTED**。caption / media_product_typeのInstagram Login契約が未確認。VIDEOをREELSやSTORYと推測して補完しない。Media同期入口はHTTP前に停止する。

## 16. Media Insights

**NOT IMPLEMENTED / Real NOT EXECUTED**。公式のProduct Type識別がないまま指標を要求しない。Mockによる一般DTO処理は本endpointの完成を示さない。No dataを実値0へ置換しない。

## 17. Metric Matrix

調査結果であり、実装済みmatrixではない。取得した公式資料ではFEED / REELS向けlikes、comments、views、reach、saved、shares等と、STORY向けviews、reach、sharesは異なる。STORYへlikes、comments、savedを混用しない。Carousel childへInsightsを要求しない。impressionsの非推奨化とviewsを区別し、両者へ同値を複製しない。Product Typeの契約解決後、明示matrixと欠損・unsupportedの試験が必要。

## 18. Pagination

**NOT IMPLEMENTED**。Instagram Loginでの時間順序とpaging契約を確認できていない。Facebook Login限定の説明を転用しない。将来実装時は固定Host / Path、next URLを直接追わない、初回上限5件、Incremental上限5ページ、境界重複、Cursor再利用と打切り条件を試験する必要がある。

## 19. Initial Sync

**NOT IMPLEMENTED / NOT EXECUTED**。現状はINSTAGRAM_SPEC_UNVERIFIEDでJob FAILED。上限付きMedia取得、Insights、Importまでの成功試験はない。

## 20. Incremental Sync

**NOT IMPLEMENTED / NOT EXECUTED**。Numeric Media IDの大小を時系列とみなさない。並び順が未保証のまま既存IDで早期終了する実装は行っていない。

## 21. Normalizer

Profile / DTOの正規化とmedia_typeのgeneric IMAGE / VIDEO / CAROUSEL変換を実装しMock検証した。Media Product Typeや本番Insightsの変換契約は未実装。Generic DTOを変換できることと、実API同期の完成は別である。

## 22. Live Import

既存共通Live Importは回帰テスト成功。Instagram MediaからImportまでの成功経路は未接続。保留JobがSNSPostやSyncStateを作成しないことをDBテストで確認した。

## 23. Idempotency

既存共通Importの冪等性回帰テストは成功。IG OAuth Stateは一回使用、並行Credential更新は最新値を再解決。Instagram Initial / Incremental Media再取込の冪等性は未検証。

## 24. Sync State

保留同期ではcheckpointを保存しない。Business transaction後にのみIG checkpointを更新する本番成功経路は未実装。既存Xと共通SyncStateの回帰試験は成功。

## 25. Job Pipeline

共通Job HandlerへProviderの事前条件確認を追加。IGの仕様保留はCredential resolve / Refresh / Profile / Media通信より先に停止し、FAILEDとなる。HTTP呼出0、SNSPost追加0、SyncState追加0を試験した。Scheduleは自動で有効化しない。

## 26. Security

固定Token endpoint、TLS、timeout、単一Token試行、通常Profile GETの既存bounded retry、Secret redactionを検証。OAuth callback / start queryのaccess log除去へIGを追加した。HTTP queryにTokenが必要な公式lifecycle endpointは直接Transport経由とし、URLやレスポンスをログへ残さない。

レビュー対象406ソースファイルについてPrivate環境内で実Secret値5種類を照合し、一致0件。実Token、Client ID / Secret、Runtime暗号鍵はプロセス内でのみ読み、値を外へ出力していない。EAA/IG Token、OpenAI key、Private Keyパターン一致0件。Private環境ファイル、鍵、暗号化Runtime Secret、DB dump、実投稿export、cacheはレビュー対象に含まれない。これは照合した既知Secretと検査パターンについての結果であり、あらゆる未知Secretが存在しない証明ではない。

最終ZIPもCRC、Worktree byte一致、禁制ファイル、パターン、既知Secret照合を検査する。ZIP検査結果は末尾のPackaging verificationに記録する。

## 27. X Regression

PASS (Mock / DB regression)。X OAuth実装とX Provider実装はPhase 6 Verified ZIPとバイト一致。X Registry試験をIG追加に合わせて拡張し、既存X assertionは保持した。Xテストの削除・Skipはない。実X APIの再通信はPhase 7では行っていない。既存Private環境のX設定は保持した。

## 28. Backend Test

最終結果: **1554 passed / 0 failed / 0 skipped、302.61秒 (5:02)**。Phase 6 baseline 1482から新規72件追加。10分未満。

```text
docker run --rm --network sns-trend-performance-analyzer_default --env-file .env
  -e POSTGRES_HOST=db -e POSTGRES_PORT=5432 -e LIVE_MODE_ENABLED=false
  -e X_LIVE_SMOKE_ENABLED=false -e INSTAGRAM_LIVE_SMOKE_ENABLED=false
  -e PGOPTIONS="-c statement_timeout=120000"
  -v "<workspace>/demo_data:/demo_data:ro"
  sns-analyzer-phase7-backend python -m pytest -q -p no:cacheprovider
```

上記は複数行で記した引数一覧であり、PowerShellへのそのままの貼付用ではない。使い捨て `sns_phase2_test_<32-hex>` DBを使用し、終了後の残存DBは0。実HTTPは禁止するテストfixture下で実施。通常DBをリセットしていない。

初回の不完全な検証環境では `/demo_data` 未マウントによるCanonical manifest FileNotFoundが1件発生し、435 passed / 1 failedで中断 (388.77秒)。これはCLI試験の失敗という初期説明を訂正済み。Docker network / fixture mountを修正して上記全件を再実行した。アプリのProduction DB timeoutは変更していない。

## 29. Frontend / Typecheck / Build

`sns-analyzer-phase7-frontend-check` Build stageで `npm test && npm run typecheck && npm run build` を実行。
**32 passed / 0 failed / 0 skipped / 0 cancelled** (7044.985471ms)、Typecheck Success、Next.js 16.3.8 Production Build Success、19 routes。Phase 7でFrontend実装変更なし。

## 30. Docker / Migration

最終ソースでBackend / Worker / Beatを再build / recreateし、Frontendを含む通常Compose 6 services runningを確認。DB / Redis / Backend healthy、Backend health HTTP200、Frontend HTTP200、Worker pingは1 node online / pong。OpenAPI44パスを確認。

既存Private `sns-x-live` 環境と衝突しないよう検証用portは127.0.0.1の15432 / 18000 / 13000。Privateの5432 / 8000 / 3000は保持した。検証用overrideはTEMPに保存し成果物へ含めない。

Alembic head: **0005_v2_provider_core**。0001–0005の5ファイルはPhase 6 Verified ZIPとバイト一致。0006なし。Schema変更なし。

## 31. Canonical Demo

Canonical Project、ALL、UTC 2026-07-07〜2026-10-04で7画面の表示をブラウザDOM / AXで確認した。Pixel / responsive / 全操作試験を行ったという意味ではない。CSV取込や設定保存、AI再生成は行っていない。

| 画面 | 実表示確認 |
| --- | --- |
| 概要 | Reach93,392、Posts180、Impressions136,256、Engagement6,928 |
| 自社アカウント | OWN2件各90投稿、NULLは—、実値0は0 |
| 市場トレンド | AIエージェント14.04 (Instagram) / 4.16 (X)、Term4件 |
| 競合比較 | 3競合選択後OWN2+COMP3=5行、Followers1067/1467/1217/2489/1878、Posts90/90/90/270/180 |
| ギャップ分析 | 12行、算出不可1件は散布座標0にしない、四分類、実値Gap0が2行、先頭88.083 |
| AIインサイト | 保存済みFictional fixture、Reach93392、API Key未設定で再生成disabled |
| 設定 / 取込 | Canonical Projectと2Platform、履歴4件 (180 / 4500 / 180 / 540)、エラー0 |

競合選択のmouse操作が一度timeoutしたため、状態を再確認しkeyboard操作で選択・検索して5行を確認した。Backend再起動中の一時的なAPI接続エラーは再起動後のreloadで解消した。

通常DB19テーブル全てで検証前後の件数および `row_to_json` 全行集約MD5が一致。MD5は内容差分検出用。Provider / Job / Schedule / SyncStateは0、Schedule追加なし。Canonical CSVは変更なし。

## 32. Private Instagram Validate

**NOT EXECUTED**。Presence-only確認でIG Client ID / Secret未設定、IG Smoke / Refresh gates=false。Privateの秘密値を開示しない。Profile Mock成功をPrivate Validate PASSとしない。

## 33. Private Instagram Sync

**NOT EXECUTED**。Credential未準備に加え、Media契約の保留がある。既存Private環境のenabled schedulesは0。UI/APIによる実同期の開始、Credential登録、暗号Token更新は行っていない。

## 34. Real Media Insights

**NOT EXECUTED**。Live Media N、実値0、不明NULL、unsupported、product別metricsの実結果は未取得。個人のcaption、Media JSON、ID、Usernameを成果物へexportしていない。

## 35. Existing Analytics API

全Backend回帰試験とCanonical7画面で既存分析を確認。Demo / LIVE分離、一般Import、Trend、Gap、AIの既存試験は成功。Instagramの実データを既存分析へ反映した証拠はない。

## 36. Real Refresh

**NOT EXECUTED**。発行から24時間以上経過した実IG Tokenを保持していない。86399 / 86400秒の境界はMock clock試験だけで確認した。Production時刻やissued_atを改ざんして実Refresh条件を突破していない。

## 37. USER_ACTION_REQUIRED

1. Instagram Loginでcaption / media_product_typeを利用できる公式資料、または代替の正式なProduct識別契約をMetaへ確認する。利用者は最新版資料を保有していないと回答済みであり、同じ資料提出を繰り返し要求しない。
2. 対象endpointのv26.0対応とInstagram Loginのpaging / order契約を確認する。仕様解決後にMedia・Insights・Initial/Incremental実装を完了させる。
3. Meta App / Professional account / readonly permission / 登録HTTPS redirectを準備し、SecretをPrivate SecretStoreへ本人が設定する。値をチャットやGitへ貼らない。設定ガイドは [Instagram Private Setup](../portfolio/instagram_api_private_setup.md)。
4. 未確認契約を解消してから、手動Private OAuth / Validate / 小量Sync / Analyticsを実検証し、実Token発行24時間以降にRefreshを検証する。現状でSmoke flagを有効にするだけではSyncできない。

## 38. Remaining Gaps

Blocker **3件**。

| ID | 判定 / 未完了範囲 |
| --- | --- |
| B1 | IG Loginのcaption / media_product_type未確認。Media、Insights matrix、Initial / Incremental、Import成功経路が未実装 |
| B2 | Graph endpoint版対応およびIG paging / order保証がPartial / Unverified |
| B3 | IG Private App / Credential未準備。Login / Validate / Sync / Real Insights / Refreshの実検証なし |

Mock OAuth / Profile / Routerの成功、共通回帰テストの成功、既存Demoの維持をもってB1–B3解消とはしない。Loopback HTTPとPKCEの公式適用は未確認。HTTPSのみの保守的なRedirect方針を採用した。

## 39. Phase 8 Go / No-Go

**NO-GO**。Phase 7 End-to-Endは未完了。承認済みのreadonly範囲で実装可能な部分と回帰検証・資料・レビューZIPを仕上げ、公式契約と実通信検証が揃うまで後続Phaseへ進めない。

### Packaging verification

Review ZIP: `SNS_Analyzer_V2_Phase7.zip` (workspaceの親フォルダ)。全Worktree sourceと前Phaseから継承するreview_designs、Phase 7指示書を含める。未コミットのPhase 2–6ソースも含む。

411 entries = Worktree source407件 + 設計参照4件。CRC PASS、重複0、Worktree byte一致PASS、禁制ファイル0、Secret pattern一致0。Python207ファイルの構文検査PASS。Migration5件とCanonical demo_dataはPhase 6 Verified ZIPとバイト一致。既知実Secret5種類との照合も一致0件。最終ZIPのサイズ・SHA256は報告書の自己参照を避けるため別途成果物として確認する。
