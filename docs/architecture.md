# アーキテクチャ

この文書は、Azure学習環境のサービス構成、各コンポーネントの責務、異常時の扱いを定める。AWS版に固有の契約は[AWS処理契約](aws-architecture.md)、実装の順序は[学習計画](learning-plan.md)を正とする。

## AWSとAzureの概念対応

| AWS | Azure学習環境 | 学習する役割 |
|---|---|---|
| S3 | Azure Data Lake Storage Gen2 | 入出力ストレージ |
| EventBridge Rule | ADF Storage Event Triggerが利用するEvent Grid | ストレージイベントの配信 |
| Step Functions | Azure Data Factory Pipeline | 親オーケストレーター |
| Lambda (Python) | Azure Functions (Python) | 入力検証 |
| Glue Crawler | ADFのSchema DiscoveryとMapping Data FlowのSchema Drift | スキーマ推論と変化への対応 |
| Glue Data Catalog | 初期構成では再現しない | 推論結果を永続化するカタログ |
| Glue ETL | ADF Mapping Data Flow | ETLとデータ変換 |
| CloudWatch | Azure Monitor、Application Insights、Log Analytics | 監視とログ |
| CloudWatch AlarmとSNS Email | Azure Monitor AlertとAction Group | 障害通知 |
| Terraform | TerraformとAzureRM Provider | IaC |

Glue Crawlerはスキーマを推論し、そのメタデータをGlue Data Catalogへ保存する。Azureの初期構成で再現するのは、このうちスキーマの推論と、スキーマが変化したときの対応である。カタログの永続化、パーティション管理、組織的なデータガバナンスは対象外とする。

外部SQLからの取得（[#28](https://github.com/Ries630/AzureDataTransformationLab/issues/28)）は、Azure・AWSとも当面の対象外とし、[後から追加する機能](aws-learning-plan.md#後から追加する機能)で扱う。AWS版の構成案は[AWS版の計画案](aws-learning-plan.md#aws-2-検証と変換のコードiacを作る)にある。

## Azure側の処理フロー

```text
ADLS Gen2 / landing
       │
       │ BlobCreated
       ▼
ADF Storage Event Trigger
       │  内部でEvent Gridと連携
       ▼
Azure Data Factory Pipeline
       │
       ├─ Web Activity（DFS Path List）+ Filter（対象のETag取得）
       │
       └─ Azure Function Activity
              │  入力検証
              ▼
          Switch
           ├─ VALID
           │    ├─ Copy: landing → validated
           │    ├─ Mapping Data Flow → output/_staging/<RunId>
           │    │      ├─ rename
           │    │      ├─ cast
           │    │      ├─ filter
           │    │      └─ derived column
           │    └─ 読込行数と書込行数を比較
           │           ├─ 一致: Copy _staging → output/<path> → _staging削除
           │           └─ 不一致: Pipeline Failed（_stagingを残す）
           │
           └─ INVALID
                ├─ Copy: landing → rejected
                ├─ Web PUT: rejected/<path>.validation.json
                └─ 業務RejectとしてPipelineを正常終了

Function例外、アクセス拒否、Timeout、Data Flow失敗、変換による行の欠落
       ↓
Pipeline Failed
       ↓
Azure Monitor Alert → Action Group → Email
```

初期段階では、`landing`の入力を処理後も削除しない。原本が残っていれば原因を調べたり手動で再実行したりでき、少量のサンプルデータなら保存費用も小さいためである。

## ストレージ領域

| Filesystem | 内容 |
|---|---|
| `landing` | 受信した原本 |
| `validated` | 入力検証を通過した原本 |
| `rejected` | 入力検証に失敗した原本と検証結果 |
| `output` | Mapping Data Flowによる変換結果 |
| `state` | 入力の世代ごとの処理状態（Phase 6、[冪等性](#冪等性)） |

Storage Event Triggerは`landing`だけを対象とし、CSVのパスまたは拡張子で絞り込む。Pipeline自身が`validated`、`rejected`、`output`へ書き込むので、対象を絞らないとその書き込みで同じPipelineが再び起動してしまう。

DFSのAPIでアップロードすると、Storageは空のファイルを作ってから中身を書き込み（flush）、その両方で`BlobCreated`を発行する。Triggerは空Blobのイベントを無視する設定にし、1回の投入でPipelineが1回だけ起動するようにする。この設定の結果、0バイトのCSVではPipelineが起動しない。

### 検証する版の特定

Functionは、どの版のファイルを検証するかを特定するために`etag`を必須の入力としている（[HTTP契約](#http契約)）。一方、TriggerがPipelineへ渡すのは`folderPath`と`fileName`だけで、ETagは含まれない。

そこでPipelineは、Functionを呼ぶ前に自分でETagを取得する。

1. Web Activityが、Managed IdentityでDFS endpointのPath List（`landing?resource=filesystem&directory=<dir>`）を呼び出す。
2. Filter Activityが、応答JSONの`paths`から対象ファイルの要素を選び、`etag`を取り出す。

ファイル1件の情報を返す`comp=metadata`もあるが、このAPIはETagを応答ヘッダーで返す。Web Activityは応答ヘッダーを後続のActivityへ確実に渡せないため、ETagを応答本文に含むPath Listを使う。

この方法でも、ETagを確認してから原本をコピーするまでの間に入力が上書きされると、検証した版とコピーした版が食い違う。Phase 6では、コピーの後にETagを照合して版を固定する（[版の固定](#版の固定)）。

## Azure Functionsの責務

Azure Functionsは重いETLを実行せず、`landing`にある小さなCSVの入力検証だけを担当する。検証結果を返すだけで、入力CSVのコピーや書き込みは行わない。

### コードの責務

検証処理は、Azure Functions固有の処理から分離する。

| ファイル | 責務 |
|---|---|
| `functions/validator/validation.py` | Azure SDKに依存せず、CSVのバイト列とファイル名を検証する |
| `functions/validator/storage.py` | Managed IdentityでBlobを読み取り、ETagを照合する |
| `functions/validator/function_app.py` | HTTPリクエストを検証し、Storage、純粋な検証処理、HTTP応答をつなぐ |

純粋な検証処理の公開境界は、次の関数とする。

```python
validate_csv(content: bytes, filename: str) -> dict
```

`validation.py`はAzureと通信しないので、同じ入力に対する判定を、ローカルのテストとAzure上のFunctionの両方で同じように確かめられる。

### CSV検証規則

次の規則をPhase 2の正とする。

| 対象 | 規則 |
|---|---|
| ファイル名 | 拡張子が`.csv`であること |
| エンコーディング | UTF-8。UTF-8 BOMは許容し、その他の不正なバイト列は拒否する |
| CSV構文 | CSVとして解析でき、各データ行の列数がヘッダーと一致すること |
| ヘッダー | `order_id`、`customer_id`、`amount`、`currency`、`ordered_at`を必須とする。順序は問わず、重複した列名は拒否する。追加の列は許容する |
| データ行 | ヘッダーを除くデータ行を1,000行までとする。空ファイル、ヘッダーだけのファイル、上限を超えるファイルは拒否する |
| ファイルサイズ | UTF-8でデコードする前の入力バイト数を1 MiBまでとする |
| `order_id`、`customer_id` | 空欄と空白だけの値を拒否する文字列 |
| `amount` | 指数表記を含まない通常の十進表記で、有限な`Decimal`かつ0以上であること。Mapping Data Flowの`decimal(18,4)`へ値を変えずに変換できるよう、小数部は4桁まで、整数部は14桁まで（10の14乗未満）とする |
| `currency` | `JPY`であること |
| `ordered_at` | ISO 8601の日時。日付と時刻の区切りは`T`とし、タイムゾーンは省略できる。小数秒は、Mapping Data Flowが解釈できる3桁（ミリ秒）までとする |

エラーは次の規則で報告する。

- ヘッダーに不備がある場合は、必須セルの値を検証しない。返すのは、ヘッダーのエラーと、データ行の列数のエラーだけである。
- 入力サイズと行数が上限内であれば、必須セルの検証エラーを省略せずにすべて返す。1つのセルについて返すエラーは1件とする。
- 巨大なヘッダーによる構造エラーは集約する。空欄の列名は1件にまとめ、同じ名前の重複は名前ごとに1件にまとめる。
- 特定のセルに対応しないファイルや構造のエラーでは、`row`または`column`を`null`にできる。
- 行番号はヘッダーを1行目、最初のデータ行を2行目として数える。quoted fieldの中の改行は、1つの論理レコードの一部として扱う。

### 検証結果

Functionは、次の構造の結果を返す。

```json
{
  "status": "INVALID",
  "errorCount": 1,
  "errors": [
    {
      "row": 2,
      "column": "amount",
      "message": "amount must be >= 0"
    }
  ]
}
```

`status`は`VALID`か`INVALID`のどちらかである。`errorCount`は`errors`の要素数と一致させる。`errors[].row`と`errors[].column`は、該当する行や列がない場合に`null`とする。入力内容の不備は、例外にせず、すべてこの検証結果として返す。

### HTTP契約

エンドポイントは`POST /api/validate`とする。Azure上ではFunction keyを要求する。

```json
{
  "filesystem": "landing",
  "path": "orders_v1.csv",
  "etag": "\"0x8DB000000000000\""
}
```

リクエストは次の条件を満たさなければならない。

- 8 KiB以下のJSONオブジェクトで、キーは`filesystem`、`path`、`etag`の3つだけである。
- `filesystem`は`landing`に固定する。
- `path`は1〜1,024文字の相対パスである。パスの各要素は空、`.`、`..`にできない。先頭の`/`、バックスラッシュ、制御文字、URLで意味を持つ`:`、`?`、`#`、`%`は使えない。
- `etag`は必須で、Blobから取得した引用符付きのETagと完全に一致しなければならない。

Storageのアカウント名はリクエストから受け取らず、アプリ設定`LAB_STORAGE_ACCOUNT_NAME`で固定する。

認証を通過した後のHTTP応答は、次のとおりとする。

| 条件 | HTTP | `code`または本文 | 内容 |
|---|---:|---|---|
| CSVが規則を満たす | 200 | `status: VALID`の検証結果 | 入力を受け入れる |
| CSVが規則を満たさない | 200 | `status: INVALID`の検証結果 | 業務Rejectとして扱う |
| JSON、`filesystem`、`path`、`etag`などリクエストが不正 | 400 | `INVALID_REQUEST` | リクエストエラー |
| 指定したETagが現在のBlobのETagと一致しない | 409 | `INPUT_CHANGED` | 入力が更新されたため検証を中止 |
| Blobの読み取り、アクセス、その他のStorage操作に失敗 | 502 | `STORAGE_READ_FAILED` | システム障害 |
| Storageの読み取りがタイムアウトした | 504 | `STORAGE_TIMEOUT` | システム障害 |
| 予期しない例外 | 500 | `INTERNAL_ERROR` | システム障害 |

HTTP 200の`INVALID`は、入力データを業務上受け入れられないという判定であり、Pipelineは`rejected`へ進む。HTTP 5xxは検証を最後まで実行できなかったシステム障害であり、Pipelineを失敗させて監視の対象にする。

### Storageと実行環境

`storage.py`は、`LAB_STORAGE_ACCOUNT_NAME`が指すStorageの`landing`だけを読み取る。ETagを条件にして読み取るので、リクエストを受けた後に内容が変わったBlobは検証しない。

認証の方法は、実行する場所で異なる。

| 実行場所 | 認証 |
|---|---|
| Azure | User Assigned Managed Identity。SDKが使うIdentityを`AZURE_CLIENT_ID`で指定する |
| ローカル | Azure CLIのログイン |

Functionの実行環境は次のとおりとする。

| 項目 | 設定 |
|---|---|
| ホスティング | LinuxのFlex Consumption |
| ランタイム | Azure Functionsランタイムv4、Python 3.14 |
| インスタンスメモリ | 2048 MB |
| 最大インスタンス数 | 40（スケールの上限であり、40台を常に起動しておく設定ではない） |
| HTTPトリガーのインスタンスあたり同時実行数 | 1 |
| Always Ready | 0 |
| ホスト・デプロイ用Storage | 入力用Storageから分離し、Identityベースの接続を使う |

Storage構成の判断理由と未検証事項は[ADR-0004](adr/0004-separate-function-host-storage.md)、最大インスタンス数の判断理由と未検証事項は[ADR-0007](adr/0007-set-flex-max-instance-count.md)にある。

## Mapping Data Flowの責務

主なデータ変換は、Mapping Data Flowに集める。

```text
Source
  ↓
Select
  ↓
Derived Column
  ↓
Filter
  ↓
Aggregate（必要な場合）
  ↓
Sink
```

最初の変換は、次を対象とする。

- `order_id`を`orderId`に、`customer_id`を`customerId`に改名する
- `amount`をdecimalに変換する
- `ordered_at`をtimestampに変換し、`orderedAt`とする
- `taxIncludedAmount = amount * 1.1`の列を追加する

Schema Driftでは、列の追加、列の削除、型の変更を試し、受け入れる変更と拒否する変更を区別する。スキーマを自動で検出できても、その変更を自動で受け入れてよいことにはならない。

## 比較基準

Azure Phase 3・4とAWS版の結果は、[固定入力と派生期待値](../samples/expected/README.md)を基準に比較する。派生期待値は仕様から導いたデータであり、実環境から採取した出力ではない。実Azureで確認した挙動は、[Phase 3の解説](tutorials/phase-3-data-factory.md)と[Phase 4の比較結果](tutorials/phase-4-schema-evolution.md#3-比較結果)で確認できる。

### 一致条件

| 比較対象 | 一致させるもの | 一致条件に含めないもの |
|---|---|---|
| 検証結果 | `status`、`errorCount`、`errors`の`row`・`column`・`message` | |
| 変換CSV | 列名と、行の多重集合（同じ行が複数ある場合も件数を保つ） | CSVの行順、partファイル名、サービスの実行ID |
| 行数 | 入力の論理レコード数と、最終出力の行数 | |

### 金額と日時

金額は、浮動小数点を経由せずDecimalとして比較する。

- `amount`は、decimal(18,4)へ値を変えずにcastする。
- `taxIncludedAmount`は、正確な十進数1.1との積を小数5桁まで保持する。
- 許容誤差は設けず、CSV上の末尾ゼロの表記の違いは無視する。
- 上限を超える桁は検証で拒否し、丸めて受け入れることはしない。

日時は、入力のタイムゾーンの有無で扱いを分ける。

- タイムゾーン付きの入力は、UTCへ正規化し、同じ瞬間かどうかをミリ秒の精度で比較する。
- タイムゾーンを省略した入力は、壁時計の時刻のまま比較し、実行環境のローカルタイムゾーンを補わない。

ただし、タイムゾーン付きの入力をこの正規化どおりに扱えることは、Azure実機ではまだ確かめていない。固定入力の比較が成功しても、その確認にはならない。

### 未知列とAWS版の範囲

標準の変換では明示した列だけを、Drift変換では追加の列の値も照合する。AWS版の初期構築はDrift相当の変換を選び、未知の列を入力時の文字列のまま保持する。Crawlerが推論した型が一致するかどうかは、CSVの値の比較では保証できない。

小数の境界、日時のタイムゾーン、castによる欠落、重複配信、再実行は、固定入力では網羅できていない。これらはAWS 2のテストとAWS 4の実機確認で補う。AWS固有の契約は[AWS処理契約](aws-architecture.md)にある。

## 業務Rejectとシステム障害

入力内容の不備は、業務Rejectとして扱う。

- 必須列の不足
- `amount`の不正
- 許可されていない`currency`
- 入力形式の不正

Functionが判定を正常に返し、`rejected`への配置にも成功した場合、Pipelineは正常終了とする。

次の事象はシステム障害とし、Pipelineを失敗させる。

- Functionの例外
- Functionが契約にない`status`を返した
- ADF PipelineまたはMapping Data Flowの失敗
- Mapping Data Flowの変換による行の欠落（読込行数と書込行数の不一致）
- Storageへのアクセス拒否
- Timeout
- Managed IdentityやRBACの設定不備

Azure Monitor AlertとAction Groupによるメール通知の対象は、システム障害だけである（[監視と通知](#監視と通知)）。業務Rejectのたびに通知すると、データ提供側の誤りの通知に、本当の障害の通知が埋もれるためである。

## 監視と通知

監視の構成要素は、Terraformの`monitoring_enabled`と`budget_enabled`で作成する。手順は[学習計画のPhase 5](learning-plan.md#phase-5-monitoring)にある。

| 対象 | 仕組み | 記録・通知する内容 |
|---|---|---|
| Function | Application Insights（Log Analytics workspaceへ保存） | HTTP応答ごとの構造化ログ |
| Pipeline | ADFの診断設定 | `PipelineRuns`、`ActivityRuns`、`TriggerRuns`のログ |
| システム障害 | Metric AlertとAction Group | `pl-csv-ingestion`の`PipelineFailedRuns`が1件以上でメール |
| 費用 | Subscriptionの月次Budget | `Personal-Sandbox`全体の実績が1,000円の80%・100%に達したらメール |

Functionは応答ごとに、次の項目だけを持つJSONを1行記録する。HTTP 5xxはError、それ以外はInformationのレベルで記録する。ログの記録に失敗しても、検証の応答は変えない。

| 項目 | 内容 |
|---|---|
| `event` | `csv_validation`に固定 |
| `http_status` | 応答のHTTPステータス |
| `outcome` | 検証結果の`status`（`VALID`・`INVALID`）、またはエラーの`code` |
| `pipeline_run_id` | ADFが`x-adf-pipeline-run-id`ヘッダーで渡したPipelineの実行ID。UUIDの形式に合わない場合は記録しない |

入力のパス、CSVの値、例外の本文はログに含めない。パスやCSVの値は業務データであり、SDKの例外本文にはURLや認証情報が含まれ得るためである。ADFのログとの関連付けには`pipeline_run_id`を使う。

FunctionからApplication Insightsへの送信はEntra ID認証とし、Log AnalyticsとApplication Insightsのローカル認証は無効にする。送信には、FunctionのUser Assigned Managed Identityに付与した`Monitoring Metrics Publisher`を使う。

障害通知は、Pipelineの失敗を数えるメトリックで判定する。業務RejectではPipelineが正常終了するため、[業務Rejectとシステム障害](#業務rejectとシステム障害)の区別がそのまま通知の有無になる。Functionが呼ばれる前に失敗した場合も、Pipelineが失敗すれば通知される。

Budgetは超過を通知するだけで、リソースを停止しない。費用データの反映には遅れがあるため、Budgetは急な費用増加をすぐに止める手段にはならない。

## 冪等性

Event Gridは、同じイベントを複数回配信することがある。手動の再実行もある。同じ入力を複数回処理しても、二重出力や不整合が起きないようにする。この節はPhase 6の設計であり、判断の理由は[ADR-0013](adr/0013-track-input-generations-in-blob-state.md)にある。

### 入力の世代

入力は、`landing`の相対パスとETagの組で識別する。これを入力の世代と呼ぶ。Storageのアカウントとfilesystemは固定なので、識別子に含めない。同じパスに置き直すと、内容が同じでもETagが変わり、別の世代になる。

Pipelineの1回の実行をattemptと呼び、ADFの`RunId`で区別する。

### 状態ファイル

世代ごとの処理状態は、filesystem`state`の`<相対パス>/<ETag>.json`に置く。ETagは外側の引用符を除く。

| 項目 | 内容 |
|---|---|
| `path`、`etag` | 世代の識別子 |
| `status` | `RUNNING`、`SUCCEEDED`、`REJECTED`のいずれか |
| `runId` | 状態を最後に書いた実行の`RunId` |
| `attempts` | この世代を処理した実行の回数 |
| `updatedAt` | 最後に書いた時刻（UTC） |
| `outputPath` | `SUCCEEDED`のとき、公開した出力のパス |
| `contentMd5` | ADLSが返した`Content-MD5`。比較の観察用で、識別には使わない |

失敗を表す`FAILED`は持たない。Pipelineの失敗やキャンセルでは状態を確実に更新できないため、終了した実行の`RUNNING`を、失敗した処理として扱う。

### 排他と状態遷移

Pipelineは`concurrency = 1`なので、同時に起動した実行は順番待ちになり、実行中の他のattemptはない。この前提で、実行の開始時に状態ファイルを読み、次のように決める。

| 現在の状態 | 実行のきっかけ | 結果 |
|---|---|---|
| ファイルがない | イベントまたは手動 | `If-None-Match: *`で`RUNNING`を作り、処理する |
| `RUNNING` | イベントまたは手動 | 前の実行は終了しているので引き継ぎ、`runId`を更新して処理する |
| `SUCCEEDED` / `REJECTED` | イベント、または`force`なしの手動 | 何も書かずに正常終了する |
| `SUCCEEDED` / `REJECTED` | `force = true`の手動 | `RUNNING`に戻して処理し直す |

`force`はPipelineのパラメーターで、Triggerからは渡さない。初回作成の条件付き書き込みが失敗した場合は、排他の前提が崩れているので、Pipelineを失敗させる。

### 出力の配置と公開

各領域の出力は、世代ごとのディレクトリ`<相対パス>/<ETag>/`に置く。

| 領域 | パス |
|---|---|
| `validated` | `<相対パス>/<ETag>/<ファイル名>` |
| `rejected` | `<相対パス>/<ETag>/<ファイル名>`と`validation.json` |
| `output` | `<相対パス>/<ETag>/<ファイル名>`。途中の結果は従来どおり`_staging/<RunId>` |

公開の正は、状態ファイルの`SUCCEEDED`と`outputPath`である。行数の照合が一致して出力を配置した後に、状態を`SUCCEEDED`にする。配置の途中で失敗した世代は`RUNNING`のまま残り、公開済みにはならない。同じ世代の再実行は同じパスを上書きし、変換は決定的なので同じ内容になる。

別の世代の結果は上書きしない。同じパスで前の世代がVALID、次の世代がINVALIDなら、両方の結果が世代ごとに残り、それぞれの状態ファイルで区別できる。

### 版の固定

`landing`から`validated`または`rejected`へコピーした後に、もう一度Path ListでETagを取得し、検証したETagと比べる。一致すれば、コピーした原本は検証した版である。一致しなければ`INPUT_CHANGED`としてPipelineを失敗させる。新しい版には別のイベントが届き、別の世代として処理される。以後の処理は`landing`ではなく、コピーした原本を読む。

### Retry

ActivityのRetryは、同じ結果を書き直すだけの操作（状態の読み取り、Path List、世代ディレクトリへのCopy）に限る。Data Flowは費用がかかるのでRetryを設定せず、失敗した世代は手動で再実行する。再実行すると、`RUNNING`のまま残った状態を引き継ぐ。
