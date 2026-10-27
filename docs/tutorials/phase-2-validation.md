# Phase 2: CSVを検証するAzure Functionsを作る

Phase 1では、`landing`にCSVを置けるようになりました。Phase 2では、置かれたCSVが注文データとして受け入れられるかを判定するFunctionを作ります。Functionは、ファイルの場所と版（ETag）を受け取ってCSVを読み、判定結果をHTTPで返します。

完成すると、呼び出し方とCSVの中身に応じて次の応答が返ります。

| 状況 | HTTP | 返すもの |
|---|---:|---|
| CSVが規則を満たす | 200 | `status: VALID` |
| CSVが規則を満たさない | 200 | `status: INVALID`とエラーの一覧 |
| 依頼した後にファイルが差し替えられた | 409 | `INPUT_CHANGED` |
| Storageを読めない、タイムアウトした、予期しない例外が起きた | 5xx | エラーコード |

規則を満たさないCSVでもHTTP 200を返す理由は、[3節](#3-業務rejectとシステム障害を分ける)で説明します。HTTP契約とCSV規則の正は[アーキテクチャのAzure Functions節](../architecture.md#azure-functionsの責務)、実行手順と承認条件は[学習計画のPhase 2](../learning-plan.md#phase-2-azure-functionsによる入力検証)です。

## 1. 1回の呼び出しで起きること

Functionの中では、3つのファイルが順に処理を受け持ちます。

```text
呼び出し元（Phase 3ではADF、ローカルではcurl）
  │  POST /api/validate  {filesystem, path, etag}
  ▼
Functionホスト ─ Function keyを確認する（Azure上だけ）
  ▼
function_app.py ─ リクエストの形を確認する
  ├─ storage.py ─ ETagを条件にして、landingからCSVを読む
  └─ validation.py ─ 読んだバイト列とファイル名を判定する
  ▼
HTTP応答（判定結果、またはエラーコード）
```

| ファイル | 受け持つこと | 依存するもの |
|---|---|---|
| `functions/validator/validation.py` | CSVのバイト列を規則に照らして判定する | Python標準ライブラリだけ |
| `functions/validator/storage.py` | Blobを読み取り、ETagを照合する | Azure SDK（認証とBlob） |
| `functions/validator/function_app.py` | HTTPの入出力と、2つの処理の結果をHTTP応答へ変換する | Azure Functionsのライブラリ |

たとえば、`amount`が負の数であると判定するのは`validation.py`、ファイルが差し替えられたことを検出するのは`storage.py`、そのときにHTTP 409を選ぶのは`function_app.py`です。

コードは`validation.py`から読みます。`function_app.py`から読み始めると、HTTP、認証、Storage、CSVの検証が一度に登場して、どの処理が何の責任を持つのかを追いにくくなるためです。振る舞いの確認には、`tests/validator/test_validation.py`のテストが役立ちます。

## 2. `validation.py`が判定すること

検証処理の入口は、次の関数1つです。

```python
validate_csv(content: bytes, filename: str) -> dict
```

この関数はAzureと通信しません。受け取ったバイト列とファイル名だけで判定するので、手元のテストとAzure上のFunctionで、同じ入力に対して同じ結果が得られます。Storageの権限やネットワークの状態に左右されずに、CSVの規則だけを確かめられるのが、この分離の利点です。

判定の対象は、ファイル全体（サイズ、文字コード、CSVとしての構文）、ヘッダー（必須の5列がそろっているか）、各セルの値（`amount`が数値か、`currency`が`JPY`かなど）の3段階です。規則の一覧は[アーキテクチャのCSV検証規則](../architecture.md#csv検証規則)にあります。

不正なサンプル[`orders_invalid.csv`](../../samples/invalid/orders_invalid.csv)を判定すると、次の結果になります（5件のうち3件だけを示しています）。

```json
{
  "status": "INVALID",
  "errorCount": 5,
  "errors": [
    { "row": 2, "column": "amount", "message": "amount must be >= 0" },
    { "row": 3, "column": "customer_id", "message": "customer_id must not be blank" },
    { "row": 4, "column": "currency", "message": "currency must be JPY" }
  ]
}
```

`row`はヘッダーを1行目として数えた行番号で、最初のデータ行が2行目です。エラーは1つのセルにつき1件で、最初のエラーで止まらずに、問題のあるセルをすべて返します。`errorCount`は常に`errors`の要素数と一致します。

`amount`の桁数（整数部14桁・小数部4桁まで）と、`ordered_at`の小数秒（3桁まで）の制限は、Phase 3の変換に合わせたものです。Mapping Data Flowは`amount`を`decimal(18,4)`へ、`ordered_at`をミリ秒までの日時へ変換します。検証の段階でこの範囲を超える値を拒否しておけば、検証を通った行が変換で失敗したり、値が丸められたりすることはありません（[Phase 3の解説](phase-3-data-factory.md)の⑤）。

## 3. 業務Rejectとシステム障害を分ける

このFunctionは、「CSVを判定できた」場合と「判定を最後まで実行できなかった」場合を、HTTPの状態コードで分けます。

`INVALID`は、CSVを読み、規則に照らし、受け入れられないという結論まで出せた状態です。Functionとしては仕事を終えているので、HTTP 200で返します。これを業務Rejectと呼びます。一方、Storageを読めなかったりタイムアウトしたりした場合は、CSVが正しいかどうかがまだわかっていません。これはシステム障害なので、5xxで返します。

この区別は、Phase 3でFunctionを呼び出すADFの動きに対応しています。ADFのActivityは、Functionが4xxや5xxを返すと失敗として扱い、再試行した後にPipelineを失敗させます。もしCSVの不備を4xxで返すと、データ提供側の誤りのたびにPipelineが失敗し、障害の通知が届きます。HTTP 200で`INVALID`を返せば、PipelineはCSVを`rejected`へ振り分けて正常に終われます。

例外を処理する部分は、SDKの例外の中身を応答に含めません。例外のメッセージにはURLや認証の情報が含まれうるためです。応答には、`STORAGE_READ_FAILED`のような決まったエラーコードと短いメッセージだけを返します。

リクエストの形が不正な場合は、HTTP 400（`INVALID_REQUEST`）を返します。`path`には`..`やURLで意味を持つ文字を使えず、`filesystem`は`landing`に固定されています。Storageのアカウント名もリクエストではなくアプリ設定から読みます。呼び出し元が、学習用Storageの`landing`以外の場所を読ませることはできません。

## 4. ETagで検証する版を固定する

ETagは、Blobの内容が変わるたびにStorageが付け替える値で、ファイルの版番号のように使えます。呼び出し元はファイルの場所と一緒にETagを渡し、`storage.py`は「ETagが変わっていなければ読む」という条件付きでBlobを読み取ります。

```text
呼び出し元がETagを取得する
        ↓
（この間にファイルが上書きされると、ETagが変わる）
        ↓
storage.pyが「ETagが一致する場合だけ」読む
  ├─ 一致：CSVを返す
  └─ 不一致：Storageが412を返す → HTTP 409（INPUT_CHANGED）
```

これにより、検証を依頼した時点のファイルと、実際に検証したファイルが同じ版であることが保証されます。上書きの後に検証すると、呼び出し元が把握していない版の結果を返してしまうためです。

`storage.py`は、Blobを最後まで読みません。読み取るのは、サイズの上限（1 MiB）より1バイト多い量までです。それだけ読めば、上限を超えているかどうかを判定でき、大きなファイルを丸ごとダウンロードせずに済みます。

## 5. Managed IdentityとRBACで読み取る

Functionは、Storageのアカウントキーを使わずにBlobを読み取ります。Storageへ接続するときに必要な判断は、「誰として接続するか」（認証）と「その相手に何を許すか」（認可）の2つで、それぞれ別の仕組みが受け持ちます。

| 判断 | 仕組み | このPhaseでの設定 |
|---|---|---|
| 誰として接続するか | Managed Identity | Functionに割り当てたUser Assigned Managed Identity |
| 何を許すか | RBAC | そのIdentityに、入力用Storageの`landing`を読む権限だけを与える |

`storage.py`は、実行する場所に応じて認証の方法を切り替えます。

| 実行場所 | 認証 | 切り替えの条件 |
|---|---|---|
| Azure | User Assigned Managed Identity | 環境変数`AZURE_CLIENT_ID`にIdentityのClient IDが設定されている |
| ローカル | Azure CLIのログイン | `AZURE_CLIENT_ID`が設定されていない |

ローカルで`AZURE_CLIENT_ID`を設定しないのは、このためです。設定すると、手元には存在しないManaged Identityで接続しようとします。逆にAzure上で`AZURE_CLIENT_ID`が設定されていない場合、`storage.py`は別の認証方法へ切り替えずにエラーにします。

入力用のStorageと、Functionが自分のコードや状態を置くStorage（ホスト・デプロイ用）は、役割が違うので分けています。入力用のStorageに対しては、`landing`を読む権限だけを与えます。この判断の理由は[ADR-0004](../adr/0004-separate-function-host-storage.md)にあります。

Blobを読めないときは、CSVの中身を疑う前に、Identity、対象のアカウント、Filesystemの権限の範囲、ETagの順に確かめます。

## 6. 依存関係を固定し、Azure用のパッケージを作る

Functionの依存関係は、`functions/validator/pyproject.toml`に書かれています。

```toml
[project]
name = "validator"
requires-python = ">=3.14,<3.15"
dependencies = [
  "azure-functions>=1.24,<2",
  "azure-identity>=1.25,<2",
  "azure-storage-blob>=12.27,<13",
]
```

このディレクトリは、リポジトリのルートの`pyproject.toml`が定義するuv workspaceのメンバーです。AWS Lambdaの`functions/aws`もメンバーで、uvは両方の依存関係をまとめて解決し、ルートの`uv.lock`にバージョンとハッシュを固定します。`uv run --locked --package validator`で実行すると、ロックと異なる依存関係では実行されません。

```bash
uv lock
uv run --locked --package validator functions/validator/function_app.py test
```

ただし、Azure Functionsのホストは`pyproject.toml`を読みません。Azure上のFunctionが読み込むのは、発行したパッケージに含まれるコードと、`.python_packages/lib/site-packages`に置かれたライブラリだけです。そこで、ロックどおりのライブラリをAzureと同じLinux x86_64・Python 3.14の環境でインストールし、パッケージに含めて発行します。Macでは固定したLinuxコンテナーの中で生成し、CIも同じLinux用の生成処理を使います。手順は[学習計画の依存関係の生成](../learning-plan.md#4-azure-functions用の依存関係を生成する)にあります。

つまり、依存関係を解決する場所（uvとロック）と、解決済みのライブラリを実行する場所（Azure上のホスト）が分かれています。生成方式を選んだ理由は[ADR-0005](../adr/0005-package-functions-with-pep723-and-uv.md)、workspaceへ移した理由は[ADR-0014](../adr/0014-manage-function-dependencies-with-uv-workspace.md)にあります。

## 7. 手を動かして確かめる

### 正常なCSVと不正なCSVを比べる

リポジトリのルートで、テストと2つのサンプルの判定を実行します。

```bash
uv run --locked --package validator functions/validator/function_app.py test
uv run scripts/validator/test_pure.py
uv run --locked --package validator functions/validator/function_app.py sample samples/valid/orders_v1.csv
uv run --locked --package validator functions/validator/function_app.py sample samples/invalid/orders_invalid.csv
```

`test_pure.py`は、Azure SDKをインストールせずに`validate_csv`を呼び出します。検証処理がAzureに依存していないことを、ここで確かめられます。

続けて、不正なサンプルのコピーを1か所ずつ直し、エラーの一覧がどう変わるかを観察します。元のサンプルは残しておきます。

```bash
mkdir -p .artifacts
cp -n samples/invalid/orders_invalid.csv .artifacts/orders-practice.csv
uv run --locked --package validator functions/validator/function_app.py sample .artifacts/orders-practice.csv
```

最初は5件のエラーが出ます。`amount`の負の数、`customer_id`の空欄、`currency`の値、`ordered_at`の形式を順に直し、直すたびに`sample`を実行して、どのエラーが消え、どのエラーが残るかを記録します。

### HTTPの応答を確かめる

ローカルでFunctionsホストを起動すると、HTTPで呼び出せます。準備と呼び出しのコマンドは[学習計画のローカル実行](../learning-plan.md#2-ローカルで実行する)にあります。学習用Storageの`landing/orders_v1.csv`を実際に読むので、Storageを削除している場合は、再構築してから行います。

正しいETagで呼び出してHTTP 200を確かめたら、リクエストを変えて、3節と4節で説明した応答を確かめます。

| 変えるもの | 期待する応答 |
|---|---|
| `etag`を、引用符付きの別の値（`"0x1"`など）にする | 409（`INPUT_CHANGED`） |
| `path`を、存在しないファイル名にする | 502（`STORAGE_READ_FAILED`） |
| `path`に`../`を含める、キーを1つ減らす | 400（`INVALID_REQUEST`） |

存在しないファイルの場合、`storage.py`はStorageの「見つからない」（404）を502へ変換します（`tests/validator/test_http.py`で固定しています）。ETagの条件付きの読み取りに対して実際のStorageが404と412のどちらを返すかは、この演習で観察して記録します。412が返った場合、応答は409になります。

### Azureへ発行する

Azure上に基盤を作る前に、[学習計画のplan手順](../learning-plan.md#5-azureの基盤をplanで確認する)に沿って、対象、Storageの境界、RBAC、アプリ設定、費用をplanで確かめます。PRの承認やコードのレビューは、Azureリソースの適用承認を兼ねません。適用が承認された後、[発行手順](../learning-plan.md#6-発行して動作を確認する)でFunctionを発行し、ローカルと同じ入力で同じ判定になることを確かめます。

## 理解度チェック

1. CSVの不備を、4xxではなくHTTP 200・`INVALID`で返すのはなぜか。（3節）
2. `validation.py`をAzure SDKから分離すると、何ができるようになるか。（1節、2節）
3. リクエストにETagを含めるのはなぜか。ETagが一致しないとき、Functionは何を返すか。（4節）
4. ローカルで`AZURE_CLIENT_ID`を設定しないのはなぜか。（5節）
5. `uv.lock`があるのに、Linuxでパッケージを生成して発行するのはなぜか。（6節）

答えを書いたら、該当する節と[アーキテクチャ](../architecture.md#azure-functionsの責務)、ADRを読み直し、実際のコードの境界と一致しているかを確かめます。
