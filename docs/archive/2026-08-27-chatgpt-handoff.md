> [!NOTE]
> この文書はプロジェクト開始時の引き継ぎ記録です。
> 現在の要件は [`docs/project-brief.md`](../project-brief.md)、設計は [`docs/architecture.md`](../architecture.md)、実装順序は [`docs/learning-plan.md`](../learning-plan.md) を参照してください。

# Azure Data Transformation Lab — Codex Handoff

## 1. このプロジェクトの目的

仕事で予定されている **AWSベースのデータ変換層**を理解するため、個人学習環境として **Azure上に概念的に同等の構成を構築する**。

目的はAWSサービス名をAzureサービス名へ機械的に置き換えることではなく、以下の設計概念を実際に構築・検証して理解すること。

- オブジェクトストレージへのデータ取り込み
- イベント起点の処理開始
- ワークフローのオーケストレーション
- Pythonによる入力検証
- スキーマの自動検出 / スキーマ変化への対応
- ETLによるデータ変換
- 出力ストレージへの配置
- 実行監視、障害検知、メール通知
- TerraformによるIaC
- 冪等性、異常系、再実行を考慮したデータパイプライン設計

Azureが学習環境だが、最終的には仕事のAWS構成を理解しやすくすることが目的。

---

## 2. 仕事側で想定されているAWS構成

現時点で把握している構成は以下。

```text
共通基盤
   ↓
S3 / input
   ↓
Step Functions                    ← 親オーケストレーター
   ├─ Lambda (Python)
   │    └─ 入力データ / ファイル検証
   │
   ├─ Glue Crawler
   │    └─ データスキーマの自動検出
   │       ↓
   │     Glue Data Catalog
   │
   ├─ Glue ETL
   │    └─ データ変換
   │
   └─ S3 / output
          ↓
       後段システム

監視:
CloudWatch
   ↓
CloudWatch Alarm
   ↓
SNS
   ↓
Email

IaC:
Terraform
```

### 確定している前提

- **Step Functions は親**として処理全体を制御する想定。
- Lambdaの実装言語は **Python**。
- SNSの用途は **処理失敗時のメール通知**。
- Glue Crawlerの説明には **「データスキーマの自動検出」** とある。
- 入力スキーマが完全固定とは限らない可能性がある。
- Terraformを使用する。

### 現時点では不明なこと

実案件について以下はまだ聞いていないため、推測で決めないこと。

- 入力データ形式（CSV / JSON / Parquet等）
- 1ファイルあたりのサイズ / 件数
- 入力頻度
- Glue Crawlerの実行タイミング
- スキーマ変更を許容するのか、検知したら異常とするのか
- Glue ETLの実装方式（Glue Studio / PySpark / Python Shell 等）
- 出力S3から後段システムへの受け渡し方式
- Validation NGを業務エラーとして扱うのか処理失敗として扱うのか
- Retry / Timeout / DLQ等の具体要件

---

## 3. Azure学習環境の基本方針

AWS構成の役割をAzure上で再現する。

### 概念対応

| AWS | Azure学習環境 | 備考 |
|---|---|---|
| S3 | Azure Data Lake Storage Gen2 (ADLS Gen2) | 入出力ストレージ |
| Step Functions | Azure Data Factory Pipeline | 親オーケストレーター |
| Lambda (Python) | Azure Functions (Python) | 入力検証 |
| Glue Crawler | ADFのSchema Discovery / Mapping Data FlowのSchema Driftを中心に学習 | Purviewを無理に1:1対応させない |
| Glue Data Catalog | 必要に応じて検討 | 初期段階では省略可 |
| Glue ETL | ADF Mapping Data Flow | ETL / データ変換 |
| CloudWatch | Azure Monitor + Application Insights + Log Analytics | 監視 |
| CloudWatch Alarm + SNS Email | Azure Monitor Alert + Action Group (Email) | 障害通知 |
| Terraform | Terraform + AzureRM Provider | IaC |

### 補足: Glue Crawlerの再現方針

Glue Crawlerは単なる「固定スキーマ読み込み」ではなく、データを走査してスキーマを推論・更新する役割がある。

Azure学習環境では、最初からMicrosoft Purviewを入れて1:1対応させる必要はない。

まずは以下を重点的に試す。

- ADF SourceのSchema Discovery
- Mapping Data Flowの `Allow schema drift`
- `Infer drifted column types`
- 列追加
- 列削除
- 型変更
- 想定外スキーマを許容する場合 / 拒否する場合

Purviewは、Data Catalog / Governance自体を学習したくなった段階で追加検討する。

---

## 4. Azure側の目標アーキテクチャ

```text
                     Azure

ADLS Gen2 / landing
       │
       │ BlobCreated
       ▼
Storage Event Trigger / Event Grid
       │
       ▼
Azure Data Factory Pipeline             ← 親オーケストレーター
       │
       ├─ Azure Function (Python)
       │    └─ 入力検証
       │
       ├─ If Condition
       │    ├─ VALID
       │    │    ↓
       │    │  ADLS / validated
       │    │
       │    └─ INVALID
       │         ↓
       │       ADLS / rejected
       │
       ├─ Mapping Data Flow
       │    ├─ Schema Drift
       │    ├─ rename
       │    ├─ cast
       │    ├─ filter
       │    ├─ derived column
       │    └─ mapping
       │
       └─ ADLS / output
              ↓
         後段システム相当

監視:
Azure Monitor
   ├─ Application Insights
   ├─ Log Analytics
   └─ Alert Rule
         ↓
      Action Group
         ↓
        Email
```

### Event起点について

学習環境では以下のいずれかを使用する。

1. **ADF Storage Event Trigger**
2. Event Grid → ADF / Function

AWSの `S3 ObjectCreated → Step Functions` に近いイベント駆動を理解できることを優先する。

不要な「起動専用Function」は作らない。

---

## 5. 処理責務

### Azure Function (Python)

Functionでは重いETLを行わない。

主に軽量な入力検証を担当させる。

例:

- ファイル名
- 拡張子
- CSVとして読み込めるか
- 必須カラム
- 基本的な型
- null可否
- 値範囲
- 許可コード
- ヘッダチェック

例:

```text
orders_20260827.csv

required columns:
- order_id
- customer_id
- amount
- currency
- ordered_at
```

検証結果は構造化データとして返せるようにする。

例:

```json
{
  "status": "INVALID",
  "file": "orders_20260827.csv",
  "errors": [
    {
      "row": 12,
      "column": "amount",
      "message": "amount must be >= 0"
    }
  ]
}
```

### Mapping Data Flow

主なデータ変換はADF Mapping Data Flowに寄せる。

例:

```text
Source
  ↓
Select
  ↓
Derived Column
  ↓
Filter
  ↓
Aggregate（必要なら）
  ↓
Sink
```

変換例:

- `order_id` → `orderId`
- `customer_id` → `customerId`
- `amount` → decimal
- `taxIncludedAmount = amount * 1.1`
- `ordered_at` → timestamp

---

## 6. 業務エラーとシステム障害を分離する

重要。

### 業務的なReject

例:

- 必須列不足
- amountが不正
- 許可されていないcurrency
- 入力フォーマット不正

この場合、Function自体は正常に処理を完了している。

```text
Function
  ↓
validation result = INVALID
  ↓
ADLS / rejected
```

原則として「Azureサービス障害」と同一視しない。

### システム障害

例:

- Function exception
- ADF Pipeline failure
- Data Flow failure
- Storage access denied
- Timeout
- Managed Identity / RBAC不備

```text
Pipeline Failed
   ↓
Azure Monitor Alert
   ↓
Action Group
   ↓
Email
```

通知設計ではこの区別を維持する。

---

## 7. 冪等性

S3/Event Grid等のイベント駆動では重複イベントが発生しうるため、学習環境でも冪等性を意識する。

目標:

> 同じ入力ファイルの処理が複数回開始されても、不正な二重出力や二重更新が発生しない。

識別キー候補:

```text
storage account
+ container
+ object path
+ ETag / version相当
```

単純な学習環境ではまず以下でもよい。

```text
input file path
+ hash
```

最低限、同じファイルに対する再実行を想定した出力命名 / 上書き戦略を明示する。

---

## 8. 利用ツール

### メイン

- **Codex Desktop**
- Git
- Terraform
- AzureRM Provider
- Azure CLI (`az`)

### Azure Functions

- Python
- Azure Functions Core Tools (`func`)
- 必要に応じてpytest

### GUI / 可視化

- Azure Portal
- Azure Data Factory Studio
- Azure Storage Explorer

### 役割

```text
Codex
  → 実装、変更、テスト、Terraform、README

Terraform
  → AzureリソースのDesired State

Azure CLI
  → 認証、調査、一時的操作、状態確認

Azure Portal
  → 作成されたリソースの理解、IAM、Monitor確認

ADF Studio
  → Pipeline / Data Flowの視覚的設計・デバッグ

Functions Core Tools
  → Functionのローカル実行

Storage Explorer
  → ADLS内の入力・出力ファイル確認
```

### Azure Developer CLI (`azd`)

初期段階では使用しない。

理由:

- Azure CLI + Terraformの理解を優先する。
- 抽象化レイヤーを増やさない。

一通り完成後に追加学習として検討可。

---

## 9. Terraform方針

基本的にAzureリソースはTerraform管理とする。

ただし学習目的なので、

1. Terraformで作成
2. Azure Portalで実物を見る
3. 必要ならADF Studio等で仕組みを理解
4. 最終的にIaCへ戻す

という流れを許容する。

「Portalを使わないこと」が目的ではない。

### Terraform対象候補

- Resource Group
- Storage Account
- ADLS Gen2 filesystem / container
- Function App
- Function関連リソース
- Managed Identity
- Role Assignment
- Data Factory
- Event Trigger関連
- Application Insights
- Log Analytics Workspace
- Azure Monitor Alert
- Action Group
- 必要に応じてData Factory Pipeline / Data Flow

可能な限りアクセスキー直書きを避け、Managed Identity + RBACを使う。

---

## 10. コスト制約

個人学習用なので **月1,000円以内を目標**とする。

厳密なハードリミットではないが、設計判断ではコストを優先する。

### 基本原則

- Consumption / Serverless優先
- 最小SKU
- Storageは小容量
- LRS
- Private Endpointは初期段階では使用しない
- Purviewは初期段階では使用しない
- 不要な常時稼働リソースを作らない
- Azure Budget / Cost Alertを設定する

### 特に注意

**ADF Mapping Data FlowのDebugはSpark computeを起動するため、学習環境の主な課金要因になる。**

対策:

- Debugを使い終えたらOFF
- 小さいサンプルデータを使う
- 不要な長時間Debugを避ける
- Data Flow実行回数を必要以上に増やさない

---

## 11. サンプルデータ

まずCSVで実装する。

### Version 1

```csv
order_id,customer_id,amount,currency,ordered_at
10001,C001,12800,JPY,2026-08-27T10:30:00
10002,C002,4500,JPY,2026-08-27T10:31:00
10003,C003,9800,JPY,2026-08-27T10:32:00
```

### Invalid sample

```csv
order_id,customer_id,amount,currency,ordered_at
10001,C001,-100,JPY,2026-08-27T10:30:00
10002,,4500,JPY,2026-08-27T10:31:00
10003,C003,ABC,XXX,invalid-date
```

### Schema evolution test: 列追加

```csv
order_id,customer_id,amount,currency,ordered_at,source_system
10001,C001,12800,JPY,2026-08-27T10:30:00,SYSTEM_A
```

### Schema evolution test: さらに列追加

```csv
order_id,customer_id,amount,currency,ordered_at,source_system,promotion_code
10001,C001,12800,JPY,2026-08-27T10:30:00,SYSTEM_A,SUMMER2026
```

### 試すこと

- 新しい列をSchema Driftで通す
- 新しい列を無視する
- 新しい列が来たらValidation Errorにする
- 必須列削除時にrejectする
- `amount` の型変更をどう扱うか確認する

これにより、

> スキーマ自動検出 ≠ スキーマ変更の自動受け入れ

を確認する。

---

## 12. 推奨リポジトリ構成

```text
azure-data-transform-lab/
├── README.md
├── CODEX_HANDOFF.md
│
├── infra/
│   ├── providers.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── resource-group.tf
│   ├── storage.tf
│   ├── identity.tf
│   ├── functions.tf
│   ├── data-factory.tf
│   ├── monitor.tf
│   └── budget.tf
│
├── functions/
│   └── validator/
│       ├── function_app.py
│       ├── validation/
│       ├── tests/
│       ├── requirements.txt
│       └── host.json
│
├── data-factory/
│   ├── README.md
│   └── definitions/
│
├── samples/
│   ├── valid/
│   │   └── orders_v1.csv
│   ├── invalid/
│   │   └── orders_invalid.csv
│   └── schema-evolution/
│       ├── orders_v2.csv
│       └── orders_v3.csv
│
├── scripts/
│   ├── upload-sample.sh
│   ├── show-resources.sh
│   └── cleanup.sh
│
└── docs/
    ├── architecture.md
    ├── aws-azure-mapping.md
    ├── schema-evolution.md
    └── operations.md
```

構成は必要に応じて簡略化してよい。

---

## 13. 実装フェーズ

### Phase 0 — ローカル環境

セットアップ:

- Azure CLI
- Terraform
- Azure Functions Core Tools
- Python
- Azure Storage Explorer（任意）

確認:

```bash
az login
az account show
terraform version
func --version
python --version
```

---

### Phase 1 — Storage

Terraformで以下を作る。

```text
Resource Group
   ↓
Storage Account (ADLS Gen2)
   ↓
containers / filesystems
   ├─ landing
   ├─ validated
   ├─ rejected
   └─ output
```

サンプルCSVを手動 / CLIで投入し、Portal / Storage Explorerで確認する。

---

### Phase 2 — Azure Function Validation

Python Functionを実装。

最初はローカルでテスト可能にする。

ValidationロジックはAzure Functions固有コードから可能な限り分離し、pytestでテストできるようにする。

実装後:

```text
landing
  ↓
Function
  ├─ VALID   → validated
  └─ INVALID → rejected
```

まで動作確認。

---

### Phase 3 — Data Factory Pipeline

ADF Pipelineを親として構築。

目標:

```text
Trigger
  ↓
Pipeline
  ↓
Function Validation
  ↓
If Condition
  ↓
Mapping Data Flow
  ↓
output
```

Retry / Timeout / Failure pathも簡単に試す。

---

### Phase 4 — Schema Evolution

Mapping Data FlowでSchema Driftを試す。

- 列追加
- 列削除
- 型変更
- unknown columns
- strict schema vs tolerant schema

AWS Glue Crawlerの存在意義を理解することが目的。

---

### Phase 5 — Monitoring

以下を構築。

- Application Insights
- Log Analytics
- Azure Monitor
- Alert Rule
- Action Group Email

テストとして意図的にPipelineを失敗させ、メール通知まで確認する。

---

### Phase 6 — Idempotency / Retry

意図的に同じファイルを複数回投入 / イベント再実行。

確認:

- 二重出力しない
- overwrite / versioning方針
- Retry可能
- 再実行しても整合性が壊れない

---

### Phase 7 — IaC整理

ADF Studio等で手動作成したものがあれば、可能な範囲でTerraform / Git管理へ戻す。

最終目標:

```bash
terraform apply
```

でAzure側の主要インフラを再構築できること。

FunctionコードのdeployはTerraformと分離してもよい。

---

## 14. Codexへの実装指針

### 優先すること

1. まず小さく動かす。
2. クラウドサービスごとの責務を明確にする。
3. Azure固有の便利機能でAWS構成の本質を隠しすぎない。
4. Managed Identity / RBACを学習する。
5. GUI操作だけで終わらせずGitに残す。
6. ただし理解のためADF Studio / Portalを積極的に利用してよい。
7. 変更前にはTerraform planを確認できる形にする。
8. 高額なSKUを勝手に選択しない。
9. Purview / Databricks / Private Endpoint等を初期段階で追加しない。
10. 未確定の実案件要件を「仮定で確定事項」にしない。

### 避けること

- いきなり完成形を一括構築する
- Azure Portal上だけで設定を完結させる
- Storage Account KeyをコードやTerraform変数へ直書きする
- FunctionにETL全体を詰め込む
- ADF Data Flow Debugを長時間つけっぱなしにする
- Glue Crawler = Purview と機械的に1:1対応させる
- Validation NGをすべてシステム障害としてメール通知する

---

## 15. AWS案件で今後確認したい質問

案件情報が増えたらAzure学習環境にも反映する。

特に以下を確認したい。

1. **入力形式は何か？**
   - CSV / JSON / Parquet / その他

2. **データ量は？**
   - 1ファイルサイズ
   - 1回の件数
   - 1日のファイル数

3. **Crawlerはいつ動くか？**
   - ファイルごと
   - 定期実行
   - 特定タイミングのみ

4. **スキーマ変更ポリシーは？**
   - 自動受け入れ
   - 新列のみ許可
   - 型変更禁止
   - 変更検知時は停止

5. **Glue ETLの実装方式は？**
   - PySpark
   - Glue Studio
   - Python Shell

6. **Lambda Validationの責務はどこまでか？**

7. **Validation NGは処理失敗か業務rejectか？**

8. **S3 outputの後は誰がデータを取得するか？**

9. **再処理 / 冪等性はどう設計するか？**

10. **CloudWatch + SNSの通知条件は何か？**
    - Step Functions Failed
    - Glue Failed
    - Lambda Error
    - Timeout
    - Validation NG

---

## 16. 完成条件

最低限、以下を自分で説明・実演できれば学習環境として成功。

- ADLSにCSVを投入するとイベントで処理が始まる
- ADF Pipelineが親として処理順序を制御する
- Python Functionが入力検証する
- 不正データはrejectされる
- Mapping Data Flowでデータ変換される
- スキーマ変更を許容 / 拒否する挙動を試せる
- 出力ファイルがADLSに生成される
- 障害時にAzure Monitorからメール通知される
- Terraformで主要インフラを再構築できる
- 同一入力の再実行時の挙動を説明できる
- AWS側のS3 / Step Functions / Lambda / Glue Crawler / Glue ETL / CloudWatch / SNSとの対応を説明できる

---

## 17. Codexへの最初の依頼

最初からすべて実装しない。

まず **Phase 0 + Phase 1** のみ進める。

最初のタスク:

```text
このドキュメントを前提として、Azure Data Transformation LabのPhase 0〜1を実装する。

要件:
- Terraform + AzureRMを使用
- Azure CLI認証を利用
- Resource Groupを作成
- Hierarchical Namespace有効のStorage Accountを作成
- landing / validated / rejected / output の領域を作成
- LRSかつ学習用途で安価な構成
- Managed Identity / RBACを今後追加しやすい構造にする
- terraform fmt / validate が通ること
- READMEに実行手順を書く
- 実際に作成する前にterraform planを確認できるようにする
- Purview、Private Endpoint、Databricks等は追加しない
```

Phase 1が理解できたら、Phase 2へ進む。
