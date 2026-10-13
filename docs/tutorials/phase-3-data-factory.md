# Phase 3: Data FactoryでCSVの受け取りから変換までを自動化する

Phase 2では、CSVを1本渡すと`VALID`か`INVALID`を返すFunctionを作りました。ただし、Functionを呼び出すのはまだ人の操作です。Phase 3では、`landing`にCSVが置かれた時点でAzure Data Factory（ADF）が処理を始め、検証、振り分け、変換までを自動で進める仕組みを作ります。

完成すると、投入したCSVに応じて次の結果になります。

| 投入したCSV | 最終的にできるもの | Pipelineの結果 |
|---|---|---|
| 規則を満たす | `validated`に原本、`output`に変換後のCSV | 成功 |
| 規則を満たさない | `rejected`に原本と検証結果（`<ファイル名>.validation.json`） | 成功 |
| 検証や変換を最後まで実行できない | `output`に変換結果は配置されない | 失敗 |

規則を満たさないCSVでもPipelineが「成功」になる理由は、[3節](#3-失敗には2種類ある)で説明します。正確な仕様は[アーキテクチャ](../architecture.md)、実行手順と承認条件は[学習計画のPhase 3](../learning-plan.md#phase-3-data-factory-pipeline)を正とします。

## 1. 先に押さえるData Factoryの用語

ADF PipelineはAWSのStep Functionsに相当します。自分では重い処理をせず、どの処理をどの順番で実行し、結果に応じてどこへ進むかを管理します。

| 用語 | 役割 | このPhaseでの実体 |
|---|---|---|
| Pipeline | 処理手順の全体。Activityを順に並べたもの | `pl-csv-ingestion` |
| run | Pipelineの1回の実行。runごとに一意のRunIdが割り当てられる | CSV 1本につき1回 |
| Activity | Pipelineの中の1つの手順（コピー、HTTP呼び出し、分岐など） | `ValidateCsv`、`CopyToValidated`など |
| Trigger | Pipelineを起動する条件 | `landing`にCSVが作られたとき |
| Linked Service | 接続先と認証方法の設定 | Storage用の`ls-adls-gen2`（Managed Identity）、Function用の`ls-function-validator`（Functionキー） |
| Dataset | 接続先の中で読み書きするデータの場所 | パスをパラメーターで切り替える`ds_adls_binary`（バイト列）と`ds_adls_csv`（CSV） |
| Mapping Data Flow | 列名の変更や型変換などの変換処理。実行時にSparkクラスターが起動する | `df_transform_orders` |
| Integration Runtime（IR） | Data Flowを実行する計算資源 | japaneast、General 8コア |

Activityどうしの値の受け渡しには、`@activity('ValidateCsv').output.status`のような式を使います。この式は「`ValidateCsv`というActivityの出力の`status`」を指します。Pipeline全体で使い回す値は、Pipeline変数（`relativePath`など）に入れます。

## 2. 1本のCSVがたどる6つの段階

```text
① 起動する      landingにCSVが置かれ、TriggerがPipelineを起動する
② 版を特定する  検証するファイルのETagを調べる
③ 検証する      FunctionがCSVを検証し、VALIDかINVALIDを返す
④ 振り分ける    VALIDはvalidatedへ、INVALIDはrejectedへ原本をコピーする
⑤ 変換する      （VALIDだけ）Data Flowで列名と型を整える
⑥ 配置する      （VALIDだけ）行数を確かめてからoutputへ置く
```

### ① 起動する

Triggerが起動するのは、`landing`に`.csv`で終わるファイルが作られたときだけです。Pipeline自身も`validated`や`output`へ書き込みます。対象を絞らなければ、その書き込みでPipelineが再び起動し、処理が繰り返されます。

DFS（Data Lake）のAPIでアップロードすると、Storageはまず空のファイルを作り、続けて中身を書き込みます。どちらの書き込みでも作成イベントが発生するため、Triggerは空のファイルのイベントを無視するように設定しています。その結果、0バイトのCSVを置いてもPipelineは起動しません。

TriggerからPipelineへ渡されるのは、`folderPath`（例：`landing/practice`）と`fileName`（例：`orders_v1.csv`）の2つです。Pipelineは先頭の`landing`を取り除いて`practice/orders_v1.csv`という相対パスを作り、以降の処理ではこの値を使います。

### ② 版を特定する

ETagは、ファイルの内容が変わるたびにStorageが付け替える値で、ファイルの版番号のように扱えます。Phase 2のFunctionは、検証を依頼されたときにETagも受け取り、現在のETagと一致しなければHTTP 409（`INPUT_CHANGED`）を返します。依頼した後に差し替えられたファイルを検証しないための仕組みです。

ところが、Triggerが渡すのはフォルダーとファイル名だけで、ETagは含まれていません。そのためPipelineは、Functionを呼ぶ前に自分でETagを調べます。まずWeb Activityで、`landing`の該当フォルダーにあるファイルの一覧を取得します（DFSのPath List API）。次にFilter Activityで目的のファイルの行だけを残し、そこから`etag`を取り出します。

ファイル1本の情報だけを返すAPI（`comp=metadata`）もありますが、このAPIはETagを応答ヘッダーで返します。Web Activityは応答ヘッダーを後続のActivityへ確実に渡せないため、ETagを本文のJSONで返す一覧APIを使っています。

この方法でも、ETagを調べてから原本をコピーするまでの間にファイルが上書きされると、検証した版とコピーした版がずれます。Phase 3ではこの制約を受け入れ、Phase 6（冪等性）で扱います。

### ③ 検証する

FunctionはPhase 2で作ったものをそのまま使います。ADFはFunctionキーで認証して`POST /api/validate`を呼び出し、ファイルシステム名、相対パス、ETagを渡します。キーをTerraformで受け渡す方法を選んだ理由は、[ADR-0008](../adr/0008-adf-function-auth-with-host-key.md)に記録しています。

Functionがエラー（4xxや5xx）を返したときやタイムアウトしたとき、Activityは失敗します。失敗した場合は30秒の間隔を空けて2回まで再試行し、それでも失敗すればPipeline全体が失敗します。タイムアウトは2分です。Azure Function ActivityはFunction側の応答に関係なく約230秒で打ち切られるため、それより短い値にしています。

### ④ 振り分ける

Switch Activityが、Functionの応答に含まれる`status`の値で処理を分けます。

- `VALID`：原本を`landing`から`validated`へコピーし、⑤へ進みます。
- `INVALID`：原本を`rejected`へコピーし、Functionが返したエラー一覧を`<ファイル名>.validation.json`として保存します。Pipelineは成功で終わります。
- それ以外：Fail Activity（`UnexpectedStatus`）でPipelineを失敗させます。

どの場合も原本は`landing`に残します。原因の調査と手動での再実行に使うためです。

If Conditionで分岐すると、選べるのは条件が真か偽かの2つだけです。「`VALID`かどうか」で分けた場合、Functionの不具合で契約にない応答（空の値や想定外の文字列）が返ると、それもINVALID側へ流れ、正常なCSVを`rejected`へ送ってしまいます。Switchで`VALID`と`INVALID`を明示し、それ以外を失敗させているのは、この取り違えを防ぐためです。

### ⑤ 変換する

`VALID`のCSVだけを、Mapping Data Flowで次のように変換します。

- 列名をcamelCaseに変える（`order_id` → `orderId`、`customer_id` → `customerId`、`ordered_at` → `orderedAt`）
- `amount`を小数型、`orderedAt`を日時型に変換する
- 税込金額`taxIncludedAmount`（`amount` × 1.1）の列を追加する
- 型変換に失敗した行を除外する（`DropInvalidRows`）

Phase 2の検証規則は、金額の桁数（小数部4桁・整数部14桁まで）と小数秒の桁数（3桁まで）をこの変換に合わせて制限しています。そのため、検証を通った行が型変換に失敗することは想定していません。除外は、検証と変換の規則が食い違ったときにだけ起こります。

Data Flowは実行のたびにSparkクラスターを起動し、起動時間を含めて課金されます。IRを`AutoResolve`（実行場所をAzureが選ぶ設定）にせず、japaneast・General 8コア（最小構成）に固定しているのは、実行場所と課金の単位をplanの時点で確定させるためです。TTLを0にして、実行が終わったクラスターをすぐ停止させます。Pipelineの同時実行数も1にして、複数のクラスターが同時に起動しないようにしています。

### ⑥ 配置する

この構成のData Flowは、`part-*.csv`という名前でファイルを出力します。そこで、まずrunごとの一時フォルダー（`output/_staging/<RunId>`）へ書き出し、行数を確かめてから`output`へ置きます。

確かめるのは、Data Flowが読んだ行数（rowsRead）と書き出した行数（rowsWritten）が一致するかどうかです。Functionで検証済みの行が変換で除外されたなら、検証の規則と変換の規則が食い違っています。その結果を`output`へ置くと、行が欠けたデータが正常な結果に見えてしまいます。そのため、行数が減ったrunは失敗させ、一時フォルダーを調査用に残します。

行数が一致した場合は、`RenameOutput`が自分のrunの一時フォルダーだけを読み、入力と同じファイル名で`output/<相対パス>`へまとめてから、一時フォルダーを削除します。一時フォルダーをrunごとに分けているのは、以前のrunが途中で失敗して残したファイルを取り込まないためです。

行数の判定結果は、Pipeline変数`publishStatus`に`ok`か`dropped`として入り、次のSwitch（`PublishOutput`）がこの値を読みます。INVALIDの経路では`publishStatus`が初期値の`none`のままなので、`PublishOutput`はどの分岐にも入らず、何もせずに終わります。

## 3. 「失敗」には2種類ある

このPipelineは、入力データの問題と、処理を最後まで実行できない障害を区別します。

| 状況 | 分類 | Pipelineの結果 |
|---|---|---|
| CSVが規則を満たさない（HTTP 200・`INVALID`） | 業務Reject | 成功 |
| Functionがエラーを返す、タイムアウトする、停止している | 実行できない障害 | 失敗 |
| 検証中にファイルが差し替えられた（HTTP 409） | 実行できない障害 | 失敗 |
| コピー、Data Flow、検証結果の保存が失敗した | 実行できない障害 | 失敗 |
| Functionが契約にない`status`を返した | 実行できない障害 | 失敗 |
| 変換で行が除外された | 実行できない障害 | 失敗 |

`INVALID`は「データを受け入れられない」という判定を最後まで出せた状態なので、Pipelineとしては成功です。Phase 5では、Pipelineの失敗をメールで通知します。もし`INVALID`を失敗として扱うと、データ提供側の誤りのたびに通知が届き、本当の障害の通知が埋もれます。

## 4. コードと対応づける

この節では、2節の6段階を実際の定義ファイルで1つずつ確かめます。先に定義ファイルの分担とActivityの読み方を押さえてから、段階ごとのコードへ進みます。

### 4-1. どのファイルに何が書いてあるか

ADFの定義は主に2つのファイルに分かれています。`infra/terraform/data_factory.tf`は、1節の用語集に出てきた部品をTerraformのリソースとして定義します。`infra/terraform/adf/csv_ingestion.activities.json`は、Pipelineの中身であるActivityの並びを定義し、`data_factory.tf`のPipelineリソースがこのファイルを読み込みます。

| 用語 | 定義している場所 |
|---|---|
| Pipeline | `data_factory.tf`の`azurerm_data_factory_pipeline.csv_ingestion` |
| Activity | `csv_ingestion.activities.json`（配列の要素1つが1つのActivity） |
| Trigger | `data_factory.tf`の`azurerm_data_factory_trigger_blob_event.landing_csv` |
| Linked Service | `data_factory.tf`の`azurerm_data_factory_linked_service_data_lake_storage_gen2.lab`（Storage）と`azurerm_data_factory_linked_service_azure_function.validator`（Function） |
| Dataset | `data_factory.tf`の`azurerm_data_factory_custom_dataset.binary`と`azurerm_data_factory_dataset_delimited_text.csv` |
| Mapping Data Flow | `data_factory.tf`の`azurerm_data_factory_data_flow.transform_orders`。変換の中身は`infra/terraform/adf/transform_orders.dfsql` |
| IR | `data_factory.tf`の`azurerm_data_factory_integration_runtime_azure.lab` |
| Managed Identityの権限 | `data_factory.tf`の`azurerm_role_assignment.adf_landing_blob_reader`と`azurerm_role_assignment.adf_zone_blob_contributor` |

Terraformのリソース名とADF上の名前は別のものです。たとえばTerraformで`azurerm_data_factory_custom_dataset.binary`と書くリソースは、`name = "ds_adls_binary"`と指定しているため、ADF上では`ds_adls_binary`という名前になります。activities JSONから部品を参照するときは、ADF上の名前を使います。

### 4-2. Activityの読み方

activities JSONの各要素は、どれも同じ形をしています。`ValidateCsv`を例に、各項目の意味を見ます（一部を省略しています）。

```json
{
  "name": "ValidateCsv",
  "type": "AzureFunctionActivity",
  "dependsOn": [{ "activity": "PickInputEntry", "dependencyConditions": ["Succeeded"] }],
  "policy": { "timeout": "0.00:02:00", "retry": 2, "retryIntervalInSeconds": 30 },
  "typeProperties": {
    "functionName": "validate",
    "method": "POST"
  },
  "linkedServiceName": { "referenceName": "ls-function-validator", "type": "LinkedServiceReference" }
}
```

| 項目 | 意味 |
|---|---|
| `name` | Activityの名前。ほかのActivityが`@activity('ValidateCsv')`のように参照するときに使う |
| `type` | Activityの種類。`Copy`、`WebActivity`、`Switch`、`Fail`など |
| `dependsOn` | このActivityより先に終わっている必要があるActivityと、その結果の条件。`Succeeded`なら成功したときだけ実行する |
| `policy` | タイムアウトと再試行の設定。`0.00:02:00`は「0日と2分0秒」を表す |
| `typeProperties` | 種類ごとの設定。Copyならコピー元とコピー先、Functionなら呼び出す関数名と本文 |
| `linkedServiceName` | 接続に使うLinked Service |

実行順を決めるのは、配列の並び順ではなく`dependsOn`です。`dependsOn`のないActivityは、Pipeline（Switchの分岐の中なら、その分岐）の開始と同時に実行されます。同じActivityに依存するActivityが複数あれば、それらは並行して実行されます。たとえば`JudgeRowCounts`と`RecordRowCounts`は、どちらも`TransformOrders`の成功後に同時に実行されます。

値を参照する式は`@`で始まります。このPipelineで使う式は次の5種類です。

| 書き方 | 指すもの |
|---|---|
| `@pipeline().parameters.fileName` | Triggerから受け取ったPipelineのパラメーター |
| `@variables('relativePath')` | Pipeline変数 |
| `@activity('ValidateCsv').output.status` | 実行済みのActivityの出力 |
| `@pipeline().RunId` | このrunに割り当てられたID |
| `@item()` | Filter Activityが一覧から1件ずつ取り出した要素 |

式は、`"value": "@..."`と`"type": "Expression"`を組にしたオブジェクトとして書く場合と、`"path": "@variables('relativePath')"`のように文字列へ直接書く場合があります。どちらもADFが実行時に値へ置き換えます。

`${storage_account_name}`のように`$`で始まる部分は、ADFの式ではありません。Terraformの`templatefile`関数が、ADFへ登録する前に実際の値へ置き換えます。ADF Studioで同じActivityを開くと、この部分はStorageアカウント名に置き換わって表示されます。

### 4-3. 段階ごとにコードを追う

#### ① 起動する：Trigger

Triggerは`data_factory.tf`に定義しています（一部を省略しています）。

```hcl
resource "azurerm_data_factory_trigger_blob_event" "landing_csv" {
  events                = ["Microsoft.Storage.BlobCreated"]
  blob_path_begins_with = "/landing/blobs/"
  blob_path_ends_with   = ".csv"
  ignore_empty_blobs    = true

  pipeline {
    name = azurerm_data_factory_pipeline.csv_ingestion[0].name
    parameters = {
      folderPath = "@triggerBody().folderPath"
      fileName   = "@triggerBody().fileName"
    }
  }
}
```

`blob_path_begins_with`は`/<コンテナー名>/blobs/`という形で書く決まりで、`/landing/blobs/`は「`landing`の中」を表します。`blob_path_ends_with`で拡張子を、`ignore_empty_blobs`で空ファイルの無視を指定しています。

`pipeline`ブロックは、イベントに含まれる`folderPath`と`fileName`を、Pipelineの同じ名前のパラメーターへ渡します。受け取る側のパラメーターと、Pipeline変数の初期値は、Pipelineリソースで宣言しています（一部を省略しています）。

```hcl
resource "azurerm_data_factory_pipeline" "csv_ingestion" {
  concurrency = 1

  parameters = {
    folderPath = ""
    fileName   = ""
  }
  variables = {
    relativeDir   = ""
    relativePath  = ""
    publishStatus = "none"
    rowCounts     = ""
  }

  activities_json = templatefile("${path.module}/adf/csv_ingestion.activities.json", {
    storage_account_name = azurerm_storage_account.lab.name
    ir_name              = local.data_factory_ir_name
  })
}
```

`concurrency = 1`が、⑤で説明した同時実行数の制限です。`activities_json`の`templatefile`が、4-2で説明した`${...}`の置き換えを行っています。

#### ② 版を特定する：`NormalizeLandingFolder` → `BuildRelativePath` → `ListLandingDir` → `PickInputEntry`

最初の2つのActivityは、相対パスを組み立ててPipeline変数に入れます。`NormalizeLandingFolder`の式は次のとおりです（読みやすいように改行しています）。

```text
@if(
  equals(pipeline().parameters.folderPath, 'landing'),
  '',
  concat(
    substring(pipeline().parameters.folderPath, 8, sub(length(pipeline().parameters.folderPath), 8)),
    '/'
  )
)
```

`folderPath`が`landing`だけ（`landing`の直下に置かれた）なら、空文字を返します。それ以外なら、先頭の8文字（`landing/`）を除いた残りの末尾に`/`を付けます。`landing/practice`は`practice/`になり、変数`relativeDir`に入ります。続く`BuildRelativePath`が`relativeDir`と`fileName`をつなぎ、`practice/orders_v1.csv`を変数`relativePath`に入れます。

`ListLandingDir`はWeb Activityで、`landing`のファイル一覧を取得します（一部を省略しています）。

```json
"typeProperties": {
  "method": "GET",
  "url": {
    "value": "@concat('https://${storage_account_name}.dfs.core.windows.net/landing?resource=filesystem&recursive=false', if(equals(variables('relativeDir'), ''), '', concat('&directory=', encodeUriComponent(variables('relativeDir')))))",
    "type": "Expression"
  },
  "authentication": { "type": "MSI", "resource": "https://storage.azure.com", "password": null, "pfx": null }
}
```

URLの末尾には、`relativeDir`が空でなければ`&directory=<フォルダー>`を付けます。`authentication`の`MSI`は、ADFのManaged Identityで認証するという指定です。`password`と`pfx`はADFの保存形式が持つ項目で、MSIでは値を持たないため`null`です。このとき使われるのが、`data_factory.tf`の`adf_landing_blob_reader`で付与した`landing`の読み取り権限です。応答の本文は、次のような形のJSONです（必要な項目だけを示しています）。

```json
{
  "paths": [
    { "name": "practice/orders_v1.csv", "etag": "0x8DB000000000000" }
  ]
}
```

`PickInputEntry`はFilter Activityで、この`paths`から目的のファイルだけを残します。

```json
"typeProperties": {
  "items": { "value": "@activity('ListLandingDir').output.paths", "type": "Expression" },
  "condition": { "value": "@equals(item().name, variables('relativePath'))", "type": "Expression" }
}
```

`items`が絞り込む対象の一覧、`condition`が残す条件です。`item()`は一覧の要素を1件ずつ指し、`name`が`relativePath`と等しい要素だけが残ります。結果は`output.Value`という配列に入るので、次の`ValidateCsv`は`output.Value[0].etag`で先頭の要素のETagを読みます。目的のファイルが一覧になければ`Value`は空になり、`Value[0]`を読めずにPipelineが失敗します。

#### ③ 検証する：`ValidateCsv`

`ValidateCsv`は、Functionへ送る本文を次のように組み立てます。

```json
"body": {
  "filesystem": "landing",
  "path": "@variables('relativePath')",
  "etag": "@concat('\"', activity('PickInputEntry').output.Value[0].etag, '\"')"
}
```

Phase 2のFunctionは、`"0x8DB000000000000"`のように引用符で囲まれたETagを要求します。Path Listが返す`etag`には引用符が付いていないため、`concat`で前後に`"`を付けています（JSONの中なので`\"`と書きます）。

接続先のFunctionと認証キーは、`linkedServiceName`が指す`ls-function-validator`に設定されています。`data_factory.tf`では、`azurerm_function_app_host_keys`データソースで取得したキーを、このLinked Serviceの`key`に設定しています。

Functionが返したJSONは、そのまま`activity('ValidateCsv').output`になります。後続のActivityは`output.status`や`output.errors`で、検証結果の中身を参照できます。

#### ④ 振り分ける：`RouteByStatus`

`RouteByStatus`はSwitch Activityで、分岐の中にActivityを入れ子にして持っています。JSONでは深い位置に書かれているため、まず骨組みだけを示します。

```text
RouteByStatus（Switch）
  on: @activity('ValidateCsv').output.status
  cases:
    "VALID"   → CopyToValidated → TransformOrders → JudgeRowCounts と RecordRowCounts
    "INVALID" → CopyToRejected  → SaveValidationResult
  defaultActivities（どのcaseにも当たらない場合）:
    UnexpectedStatus（Fail）
```

`on`の値と同じ`value`を持つcaseの`activities`が実行されます。JSONを読むときは、`"value": "VALID"`、`"value": "INVALID"`、`"defaultActivities"`の3か所を探すと、分岐の区切りがわかります。

`CopyToValidated`は、同じDataset `ds_adls_binary`を、コピー元とコピー先で異なるパラメーターを付けて使います。

```json
"inputs": [{
  "referenceName": "ds_adls_binary",
  "parameters": { "fileSystem": "landing", "folderPath": "@variables('relativeDir')", "fileName": "@pipeline().parameters.fileName" }
}],
"outputs": [{
  "referenceName": "ds_adls_binary",
  "parameters": { "fileSystem": "validated", "folderPath": "@variables('relativeDir')", "fileName": "@pipeline().parameters.fileName" }
}]
```

`data_factory.tf`のDatasetは、場所を`@dataset().fileSystem`のような式で定義しています。Copy Activityが`parameters`で値を渡すと、その値がDatasetの場所になります。こうして1つのDatasetで、どのファイルシステムのどのパスでも読み書きできます。Binary形式のDatasetは中身を解釈せずにバイト列のままコピーするため、原本がそのまま残ります。`CopyToRejected`も同じ形で、コピー先が`rejected`である点だけが違います。

`SaveValidationResult`はWeb Activityで、`rejected/<相対パス>.validation.json`へ`PUT`でファイルを書き込みます。本文には`activity('ValidateCsv').output`の`status`、`errorCount`、`errors`を入れます。認証は`ListLandingDir`と同じManaged Identityで、`adf_zone_blob_contributor`で付与した`rejected`の書き込み権限を使います。

`UnexpectedStatus`はFail Activityで、エラーコード`UNEXPECTED_VALIDATION_STATUS`と、Functionの応答を含むメッセージを出してPipelineを失敗させます。

#### ⑤ 変換する：`TransformOrders`と`transform_orders.dfsql`

`TransformOrders`は、Data Flowの入力と出力の場所、計算資源を指定します（一部を省略しています）。

```json
"dataFlow": {
  "referenceName": "df_transform_orders",
  "datasetParameters": {
    "source1": { "fileSystem": "validated", "folderPath": "@variables('relativeDir')", "fileName": "@pipeline().parameters.fileName" },
    "sink1": { "fileSystem": "output", "folderPath": "@concat('_staging/', pipeline().RunId)", "fileName": "" }
  }
},
"compute": { "coreCount": 8, "computeType": "General" },
"integrationRuntime": { "referenceName": "${ir_name}", "type": "IntegrationRuntimeReference" }
```

`source1`と`sink1`は、Data Flowの中で入力と出力に付けた名前です。入力は`validated`にコピーした原本で、出力先は`output/_staging/<RunId>`です。`sink1`の`fileName`を空にしているため、ファイル名はData Flowが`part-*.csv`の形で決めます。

変換の中身は`transform_orders.dfsql`に書かれています。このファイルは、`入力名 変換の種類(設定) ~> 出力名`という形の文を並べたもので、前の文の出力名が次の文の入力名になります。設定の中身を省くと、次の5つの文がつながっています。

```text
source(...)                ~> source1          validatedのCSVを読む
source1 select(...)        ~> RenameColumns    列名を変える
RenameColumns derive(...)  ~> ConvertTypes     型を変換し、税込金額の列を足す
ConvertTypes filter(...)   ~> DropInvalidRows  変換に失敗した行を除く
DropInvalidRows sink(...)  ~> sink1            書き出す
```

`derive`の中の`toDecimal`や`toTimestamp`は、変換できない値に対してnullを返します。`toTimestamp`は`coalesce`で4つの日時形式を順に試し、どれにも当てはまらなければnullになります。`filter`は、必須の列がnullになった行を除きます。⑥で比べる行数が減るのは、この`filter`で行が除かれたときです。

`data_factory.tf`のData Flowリソースは、`script = file(...)`でこのファイルを読み込みます。同じリソースの`transformation`ブロックには、dfsqlの中間の変換名（`RenameColumns`、`ConvertTypes`、`DropInvalidRows`）を宣言しています。宣言がないとsinkまで実行されないため、変換を追加するときは両方のファイルを変更します。

#### ⑥ 配置する：`JudgeRowCounts` → `PublishOutput`

`JudgeRowCounts`は、`TransformOrders`の出力から2つの行数を取り出して比べ、結果を変数`publishStatus`に入れます（読みやすいように改行しています）。

```text
@if(
  equals(
    activity('TransformOrders').output.runStatus.metrics.sink1.rowsWritten,
    activity('TransformOrders').output.runStatus.metrics.sink1.sources.source1.rowsRead
  ),
  'ok',
  'dropped'
)
```

`metrics.sink1.rowsWritten`がsinkへ書いた行数、`metrics.sink1.sources.source1.rowsRead`がそのsinkへ流れたsourceの読込行数です。同時に実行される`RecordRowCounts`は、この2つの値を`rowsRead=…, rowsWritten=…`という文字列にして変数`rowCounts`に入れます。この文字列は、失敗時のメッセージに使います。

`PublishOutput`は、`RouteByStatus`の外にある2つ目のSwitchです。`dependsOn`で`RouteByStatus`の成功を待つため、VALIDでもINVALIDでも実行されます。

```text
PublishOutput（Switch）
  on: @variables('publishStatus')
  cases:
    "ok"      → RenameOutput → DeleteStaging
    "dropped" → RowsDroppedInTransform（Fail）
  defaultActivities: なし
```

INVALIDの経路では`publishStatus`が初期値の`none`のままです。`none`に当たるcaseがなく、`defaultActivities`もないため、何も実行されずにPipelineは成功します。

`RenameOutput`はCopy Activityで、コピー元の設定に`"wildcardFileName": "part-*.csv"`を指定して、`output/_staging/<RunId>`にある出力ファイルを読みます。コピー先は`output/<relativeDir>`の`fileName`です。続く`DeleteStaging`は、Delete Activityで一時フォルダーを中身ごと削除します。`RowsDroppedInTransform`は、エラーコード`ROWS_DROPPED_IN_TRANSFORM`と`rowCounts`の値を含むメッセージを出してPipelineを失敗させます。このとき一時フォルダーは削除されず、調査に使えます。

### 4-4. テストで固定している設定

`infra/terraform/tests/data_factory.tftest.hcl`は、Azureへ接続せずにplanを作り、設定値が意図どおりかを確かめるテストです。次の設定を固定しています。

- Data Factoryを無効にしたとき、ADFのリソースを作らず、Functionキーも読まないこと
- Triggerが`landing`の`.csv`作成だけを対象にし、空ファイルのイベントを無視すること（①）
- ADFのManaged Identityの権限が、`landing`の読み取りと、`validated`・`rejected`・`output`の書き込みだけであること
- IRがjapaneast・General 8コア・TTL 0であり、Pipelineの同時実行数が1であること（⑤）
- Function用のLinked Serviceが、検証FunctionのURLを指していること（③）

どれも、変わると費用や権限の範囲に影響する設定です。

## 5. Terraformで管理する範囲とplan

Pipeline、Dataset、Data Flow、Triggerは、すべてTerraformで管理しています。ADF Studioは閲覧に使い、Git連携は有効にしません。理由は[ADR-0009](../adr/0009-manage-adf-definitions-in-terraform.md)に記録しています。

`activities_json`の中にあるLinked Service、Dataset、Data Flowへの参照は名前の文字列だけなので、Terraformはこれらの依存関係を自動では把握できません。そのため`data_factory.tf`では、Pipelineリソースの`depends_on`で作成順序を明示しています。

planでは、[学習計画の手順](../learning-plan.md#2-data-factory基盤をplanで確認する)に沿って、対象のSubscription、Data Factory、IR、権限の範囲、Triggerの対象範囲、費用を確認します。費用の大部分はData Flowの実行で、クラスターの起動を含めて1回あたり数十円程度を見込みます。正確な金額はplanを提示するときに公式料金から計算します。予算に近づいたことをメールで知らせるBudgetはPhase 5で作るため、この段階ではまだありません。Budgetは通知するだけで、リソースを自動では停止しません。

## 理解度チェック

1. Triggerの対象を`landing`の`.csv`に絞らないと、何が起きるか。（①）
2. FunctionがETagを要求するのはなぜか。また、PipelineはETagをどこから取得しているか。（②、4-3）
3. If Conditionではなく、Switchで分岐するのはなぜか。（④）
4. Data FlowのIRを`AutoResolve`にせず、リージョンと構成を固定するのはなぜか。（⑤）
5. Data Flowの出力を一時フォルダーへ書き、行数を確かめてから`output`へ置くのはなぜか。（⑥）
6. 規則を満たさないCSVで、Pipelineが成功になるのはなぜか。また、そのとき`PublishOutput`は何をするか。（3節、4-3）
7. ADF定義をGit連携ではなく、Terraformで管理するのはなぜか。（5節）

答えを書いたら、該当する節と[アーキテクチャ](../architecture.md)を読み直し、実際の定義と一致しているかを確認します。
