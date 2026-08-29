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

Azure Functionsは重いETLを実行せず、軽量な入力検証を担当する。

検証対象は次を基本とする。

- ファイル名と拡張子
- CSVとして読み込めること
- 必須カラム
- 基本的な型
- nullの許可条件
- 値の範囲
- 許可コード
- ヘッダー

Pipelineからはストレージ上の入力を特定できる情報を渡す。

```json
{
  "filesystem": "landing",
  "path": "orders_20260827.csv",
  "etag": "input-object-etag"
}
```

Functionは構造化した判定結果を返す。

```json
{
  "status": "INVALID",
  "errorCount": 1,
  "errors": [
    {
      "row": 12,
      "column": "amount",
      "message": "amount must be >= 0"
    }
  ]
}
```

大きな入力を扱う要件が判明した場合は、返却するエラー件数を制限し、完全な検証結果を`rejected`へ保存する方式を検討する。

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
