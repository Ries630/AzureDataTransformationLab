# CSV検証から理解するAzure Functionsと依存パッケージ

Phase 2では、`landing`にある注文CSVを読み取り、HTTPリクエスト → Storageからの読み取り → 純粋なPython関数での検証 → `VALID`・`INVALID`またはシステムエラーの返却という順に処理するFunctionを作ります。

正確なHTTP契約とCSVの規則は[アーキテクチャのAzure Functions節](../architecture.md#azure-functionsの責務)、実行順序、Azureのplan、承認条件は[学習計画のPhase 2](../learning-plan.md#phase-2-azure-functionsによる入力検証)に沿って確認します。

## 1. 最初に読むファイル

| ファイル | ここで見ること |
|---|---|
| `docs/architecture.md` | 入力、検証結果、HTTP応答、Storage境界 |
| `functions/validator/validation.py` | Azureを知らなくてもテストできる検証処理 |
| `functions/validator/storage.py` | Blobの読み取りとETag照合 |
| `functions/validator/function_app.py` | HTTPと2つの処理をつなぐ入口 |
| `functions/validator/function_app.py.lock` | uvが固定した依存関係 |
| `tests/validator/test_validation.py` | Pythonから観測できる振る舞い |

`validation.py`から読み、データの判定だけを理解してから、外側の処理へ進みます。`function_app.py`から始めると、HTTP、認証、Storage、CSV検証が一度に登場するためです。

## 2. ローカルで正常系と異常系を比べる

リポジトリルートで実行します。

```bash
uv run --locked functions/validator/function_app.py test
uv run scripts/validator/test_pure.py
uv run --locked functions/validator/function_app.py sample samples/valid/orders_v1.csv
uv run --locked functions/validator/function_app.py sample samples/invalid/orders_invalid.csv
```

正常なサンプルは`VALID`になり、不正なサンプルは`INVALID`とエラー一覧になります。エラー一覧では、どの行のどの列が問題か、`errorCount`と要素数が一致しているかを確認します。

既存のサンプルを残すため、コピーを一つずつ変更します。

```bash
mkdir -p .artifacts
cp -n samples/invalid/orders_invalid.csv .artifacts/orders-practice.csv
uv run --locked functions/validator/function_app.py sample .artifacts/orders-practice.csv
```

コピー直後に既知の5件のエラーを確認し、`.artifacts/orders-practice.csv`の`amount`の負数、`customer_id`の空欄、`currency`の値、`ordered_at`の形式を順番に直します。変更のたびに`sample`を実行して、入力と出力の対応を記録します。

## 3. HTTPの入口を確認する

この実CSVを使う確認は、[学習計画](../learning-plan.md#2-ローカルで実行する)に沿ってStorageとサンプルを復元した後に行います。復元前でも、前節のCSV演習とテストは実行できます。

ローカルサーバーの前に、Azuriteと設定を準備します。コピーした設定の`LAB_STORAGE_ACCOUNT_NAME`を学習用Storage名へ変更し、ローカルでは`AZURE_CLIENT_ID`を設定しません。`storage.py`はこの環境ではAzure CLIのログインを使い、UAIへ切り替えないためです。

```bash
docker compose -f functions/validator/compose.local.yml up -d
cp -n functions/validator/local.settings.json.example functions/validator/local.settings.json
unset AZURE_CLIENT_ID
az account show --subscription Personal-Sandbox --query '{name:name,state:state,userType:user.type}' -o json
```

`userType`が`user`で対象Subscriptionであることを確認し、別のターミナルでホストを起動します。

```bash
uv run --locked functions/validator/function_app.py serve
```

別のターミナルでAzure CLIログインからETagを取得し、ローカルHTTPを呼び出します。Function keyはローカルでは不要です。

```bash
export LAB_STORAGE_ACCOUNT_NAME="$(jq -r '.Values.LAB_STORAGE_ACCOUNT_NAME' functions/validator/local.settings.json)"
export LAB_ETAG="$(az storage fs file show --subscription Personal-Sandbox \
  --account-name "$LAB_STORAGE_ACCOUNT_NAME" \
  --auth-mode login --file-system landing --path orders_v1.csv --query etag -o tsv)"
jq -n --arg etag "$LAB_ETAG" \
  '{filesystem:"landing",path:"orders_v1.csv",etag:$etag}' \
  | curl --fail-with-body -sS -X POST http://127.0.0.1:7071/api/validate \
      -H 'Content-Type: application/json' --data-binary @-
```

応答を読むときは、HTTP 200の`VALID`・`INVALID`（検証完了）、ETag不一致（入力の版が変わった）、5xx（処理を完了できないシステム障害）を区別します。`INVALID`を業務Rejectとして返すことで、Functionを呼べない障害と入力データの拒否を分けられます。正確な状態コードは[アーキテクチャ](../architecture.md#azure-functionsの責務)で確認します。

## 4. 3つの層を追う

```text
Function host
  └─ Function keyを確認
function_app.py
  ├─ JSONの形を確認
  ├─ storage.pyでBlobを読む
  └─ validation.pyへbytesとファイル名を渡す
```

`validation.py`の`validate_csv(content, filename)`はAzure SDKを呼ばず、`storage.py`はBlobの読み取りとETag照合に集中します。この分離により、ネットワークやRBACの状態がなくてもCSV規則をテストでき、`function_app.py`が結果をHTTPの状態へ変換する流れも追えます。

たとえば、`amount`の判定は`validation.py`、Blobの存在確認は`storage.py`、HTTP 409の選択は`function_app.py`です。

## 5. Managed IdentityとStorageを理解する

Functionはアカウントキーをコードへ書かずにBlobを読み取ります。`LAB_STORAGE_ACCOUNT_NAME`は入力Storageの名前、`AZURE_CLIENT_ID`はFunctionが利用するUser Assigned Managed Identityの識別子です。

入力StorageとFunctionのホスト・デプロイStorageは役割が違うため分離し、入力側には`landing`を読む権限だけを与えます。この境界とロール割り当ての理由は[ADR-0004](../adr/0004-separate-function-host-storage.md)に記録されています。

学習ポイントは認証と認可を分けることです。Managed Identityで「誰として接続するか」、RBACで「どのStorageをどの操作まで許可するか」を決めます。Blobを読めないときは、CSVの内容ではなくIdentity、対象アカウント、Filesystemのスコープ、ETagの順に確認します。

## 6. PEP 723と発行パッケージを理解する

`function_app.py`の先頭にあるPEP 723メタデータはuvが依存関係を解決するための入力です。次のコマンドで隣接するロックファイルを更新し、ロックを変えずに実行します。

```bash
uv lock --script functions/validator/function_app.py
uv run --locked functions/validator/function_app.py test
```

Azure Functionsが実行時に読むのは、発行パッケージ内のコードと`.python_packages/lib/site-packages`です。Macでは固定Linux x86_64コンテナー、Linux x86_64ではネイティブ環境で`scripts/validator/package.py`を実行します。

```bash
# Mac
uv run scripts/validator/package.py --docker .artifacts/validator-build-1

# Linux x86_64
uv run scripts/validator/package.py .artifacts/validator-build-1
```

配置先はまだ存在してはいけません。生成後は`package-manifest.json`のlock SHA256と依存名・バージョンを確認します。同じロックで再生成するときは`validator-build-2`のような別名を使い、manifestを比較します。ZIPのバイト列一致までは保証しません。

Azure基盤のplanの適用とFunction発行が明示承認された段階で、[学習計画の発行手順](../learning-plan.md#6-発行して動作を確認する)へ進みます。Terraform outputからApp名とResource Groupを取得し、対象Subscriptionを照合して発行します。

ここで確認することは、「メタデータを読んで依存を解決する場所」と「解決済みパッケージを実行する場所」が違うことです。CIも同じLinux生成処理を使います。この採用理由とAzure上の未検証事項は[ADR-0005](../adr/0005-package-functions-with-pep723-and-uv.md)にあります。

## 7. planを読む

Azureリソースの作成前に、[学習計画のplan手順](../learning-plan.md#5-azureの基盤をplanで確認する)に沿って対象、Storageの境界、RBAC、アプリ設定、費用を確認します。planを理解してから承認手順へ進みます。PRの承認やコードのレビューだけでは、Azureリソースの適用承認にはなりません。

## 学習メモ

1. なぜCSVの不備をHTTP 200・`INVALID`で返すのか。
2. なぜ`validation.py`からAzure SDKを分離するのか。
3. なぜリクエストにETagを含め、Managed IdentityとRBACを分けるのか。
4. なぜPEP 723のロックだけではAzure Functionsで実行できず、Linuxでパッケージを生成するのか。

回答を書いた後にアーキテクチャとADRを読み直し、コードの実際の境界と一致しているかを確認します。
