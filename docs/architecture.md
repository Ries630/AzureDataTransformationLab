# アーキテクチャ

## AWSとAzureの概念対応

| AWS | Azure学習環境 | 学習する役割 |
|---|---|---|
| S3 | Azure Data Lake Storage Gen2 | 入出力ストレージ |
| EventBridge Rule | ADF Storage Event Triggerが利用するEvent Grid | ストレージイベントの配送 |
| Step Functions | Azure Data Factory Pipeline | 親オーケストレーター |
| Lambda (Python) | Azure Functions (Python) | 入力検証 |
| Glue Crawler | ADFのSchema DiscoveryとMapping Data FlowのSchema Drift | スキーマ推論と変化への対応 |
| Glue Data Catalog | 初期構成では再現しない | 推論結果を永続化するカタログ |
| Glue ETL | ADF Mapping Data Flow | ETLとデータ変換 |
| CloudWatch | Azure Monitor、Application Insights、Log Analytics | 監視とログ |
| CloudWatch AlarmとSNS Email | Azure Monitor AlertとAction Group | 障害通知 |
| Terraform | TerraformとAzureRM Provider | IaC |

Glue Crawlerはスキーマを推論し、そのメタデータをGlue Data Catalogへ保存する。

初期構成で再現するのはスキーマ推論とスキーマ変化への対応であり、カタログの永続化、パーティション管理、組織的なデータガバナンスは対象外とする。

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
       └─ Azure Function Activity
              │  入力検証
              ▼
          If Condition
           ├─ VALID
           │    ├─ Copy: landing → validated
           │    └─ Mapping Data Flow
           │           ├─ rename
           │           ├─ cast
           │           ├─ filter
           │           ├─ derived column
           │           └─ ADLS Gen2 / output
           │
           └─ INVALID
                ├─ Copy: landing → rejected
                └─ 業務RejectとしてPipelineを正常終了

Function例外、アクセス拒否、Timeout、Data Flow失敗
       ↓
Pipeline Failed
       ↓
Azure Monitor Alert → Action Group → Email
```

初期段階では`landing`の入力を削除しない。

原本を残すことで原因調査と手動再実行ができ、少量のサンプルデータでは保存費用も小さいためである。

## ストレージ領域

| Filesystem | 内容 |
|---|---|
| `landing` | 受信した原本 |
| `validated` | 入力検証を通過した原本 |
| `rejected` | 入力検証に失敗した原本と検証結果 |
| `output` | Mapping Data Flowによる変換結果 |

Storage Event Triggerは`landing`だけを対象とし、CSVのパスまたは拡張子で絞り込む。

`validated`、`rejected`、`output`への書き込みによって同じPipelineが再起動しないようにする。

## Azure Functionsの責務

Azure Functionsは重いETLを実行せず、`landing`にある小さなCSVの入力検証を担当する。検証結果を返すだけで、入力CSVのコピーや書き込みは行わない。

### コードの責務

検証処理はAzure Functions固有の処理から分離する。

| ファイル | 責務 |
|---|---|
| `functions/validator/validation.py` | Azure SDKに依存せず、CSVのバイト列とファイル名を検証する |
| `functions/validator/storage.py` | Managed IdentityでBlobを読み取り、ETagを照合する |
| `functions/validator/function_app.py` | HTTPリクエストを検証し、Storage・純粋な検証処理・HTTP応答を接続する |

純粋な検証処理の公開境界は次の形とする。

```python
validate_csv(content: bytes, filename: str) -> dict
```

`validation.py`はAzureへの通信を行わないため、同じ入力に対してローカルテストとAzure上のFunctionで同じ判定を確認できる。

### CSV検証規則

次の規則をPhase 2の正とする。

| 対象 | 規則 |
|---|---|
| ファイル名 | 拡張子が`.csv`であること |
| エンコーディング | UTF-8。UTF-8 BOMは許容し、その他の不正なバイト列は拒否する |
| CSV構文 | CSVとして解析でき、各データ行の列数がヘッダーと一致すること |
| ヘッダー | `order_id`、`customer_id`、`amount`、`currency`、`ordered_at`を必須とする。順序は問わず、重複名は拒否する。追加列は許容する |
| データ行 | ヘッダーを除くデータ行を1,000行までとする。空ファイル、ヘッダーだけのファイル、上限超過は拒否する |
| ファイルサイズ | UTF-8デコード前の入力バイト数を1 MiBまでとする |
| `order_id`、`customer_id` | 空欄および空白だけの値を拒否する文字列 |
| `amount` | 指数表記を含まない通常の十進表記で、有限な`Decimal`かつ0以上であること |
| `currency` | `JPY`であること |
| `ordered_at` | ISO 8601日時。日付と時刻の区切りは`T`とし、タイムゾーンは省略可能とする |

ヘッダーに不備がある場合は必須セルの値検証を行わず、ヘッダーエラーとデータ行の列数エラーだけを返す。入力サイズと行数の上限内では、必須セルの検証エラーを省略しない。1つのセルに対してエラーを1件返し、巨大なヘッダーによる構造エラーは空欄列名を1件、同じ重複列名を名前ごと1件に集約する。セルに対応しないファイル・構造エラーでは`row`または`column`を`null`にできる。行番号はヘッダーを1行目、最初のデータ行を2行目として数え、quoted field内の改行は1つの論理レコードとして扱う。

### 検証結果

Functionは次の構造化された結果を返す。`errorCount`は`errors`の要素数と一致させる。

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

`status`は`VALID`または`INVALID`とする。`errors[].row`と`errors[].column`は、該当する行または列がない場合に`null`を設定する。入力内容の不備は、すべて検証結果として返す。

### HTTP契約

エンドポイントは`POST /api/validate`とする。Azure上ではFunction keyを要求する。

```json
{
  "filesystem": "landing",
  "path": "orders_v1.csv",
  "etag": "\"0x8DB000000000000\""
}
```

リクエストは8 KiB以下のJSONオブジェクトで、キーを`filesystem`、`path`、`etag`の3つに限定する。`filesystem`は`landing`に固定する。`path`は1〜1,024文字の相対パスで、各要素を空、`.`、`..`にできず、先頭の`/`、バックスラッシュ、制御文字、URLに使われる`:`、`?`、`#`、`%`を許可しない。`etag`は必須で、Blobから取得した引用符付きETagと完全一致させる。アカウント名はリクエストから受け取らず、アプリ設定`LAB_STORAGE_ACCOUNT_NAME`で固定する。

認証後のHTTP応答は次のとおりとする。

| 条件 | HTTP | `code`または本文 | 内容 |
|---|---:|---|---|
| CSVが規則を満たす | 200 | `status: VALID`の検証結果 | 入力を受け入れる |
| CSVが規則を満たさない | 200 | `status: INVALID`の検証結果 | 業務Rejectとして扱う |
| JSON、`filesystem`、`path`、`etag`などリクエストが不正 | 400 | `INVALID_REQUEST` | リクエストエラー |
| 指定ETagと現在のBlobのETagが一致しない | 409 | `INPUT_CHANGED` | 入力が更新されたため検証を中止 |
| Blobの読み取り、アクセス、その他のStorage操作に失敗 | 502 | `STORAGE_READ_FAILED` | システム障害 |
| Storage読み取りがタイムアウトした | 504 | `STORAGE_TIMEOUT` | システム障害 |
| 予期しない例外 | 500 | `INTERNAL_ERROR` | システム障害 |

HTTP 200の`INVALID`は入力データを業務上受け入れられない状態であり、Pipelineで`rejected`へ進められる。HTTP 5xxは検証を完了できなかったシステム障害であり、Pipelineを失敗させて監視対象にする。

### Storageと実行環境

`storage.py`は`LAB_STORAGE_ACCOUNT_NAME`の`landing`だけを読み取る。Azure上ではFunctionがSDKで使用するUser Assigned Managed Identityを`AZURE_CLIENT_ID`で指定し、ローカルではAzure CLIのログインを使う。ETagを条件に読み取ることで、リクエストを受けた後に内容が変わったBlobを検証しない。

FunctionはLinuxのFlex Consumption、Azure Functionsランタイムv4、Python 3.14を対象とする。インスタンスメモリは2048 MB、最大インスタンス数は40、HTTPトリガーのインスタンスあたり同時実行数は1、Always Readyは0とする。最大インスタンス数はスケール上限であり、40台を常時起動する設定ではない。Function専用のホスト・デプロイStorageを入力Storageから分離し、Identityベースの接続を使う。Storage構成の判断理由と未検証事項は[ADR-0004](adr/0004-separate-function-host-storage.md)、最大インスタンス数の判断と未検証事項は[ADR-0007](adr/0007-set-flex-max-instance-count.md)を参照する。

## Mapping Data Flowの責務

主なデータ変換はMapping Data Flowへ寄せる。

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

最初の変換は次を対象とする。

- `order_id`から`orderId`への変更
- `customer_id`から`customerId`への変更
- `amount`のdecimalへの変換
- `taxIncludedAmount = amount * 1.1`の追加
- `ordered_at`のtimestampへの変換

Schema Driftでは列追加、列削除、型変更を試し、許容する変更と拒否する変更を区別する。

スキーマの自動検出は、スキーマ変更の自動受け入れを意味しない。

## 業務Rejectとシステム障害

入力内容の不備は業務Rejectとして扱う。

- 必須列の不足
- `amount`の不正
- 許可されていない`currency`
- 入力形式の不正

Functionが正常に判定を返し、`rejected`への配置に成功した場合、Pipelineは正常終了させる。

次はシステム障害としてPipelineを失敗させる。

- Functionの例外
- ADF PipelineまたはMapping Data Flowの失敗
- Storageへのアクセス拒否
- Timeout
- Managed IdentityまたはRBACの設定不備

システム障害だけをAzure Monitor AlertとAction Groupによるメール通知の対象とする。

## 冪等性

Event Gridは同じイベントを複数回配送する可能性があるため、同一入力を複数回処理しても二重出力や不整合を起こさない設計にする。

処理識別子は次を候補とする。

```text
storage account
+ filesystem
+ object path
+ ETag
```

学習環境では、入力パスとファイルハッシュの組み合わせも比較する。

具体的な状態保存、排他制御、再試行時の状態遷移はPhase 6で決定する。

最低限、出力パスと上書き方針を決め、同じ入力の再実行結果を説明できるようにする。
