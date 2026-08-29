# プロジェクト概要

## 目的

仕事で予定されているAWSベースのデータ変換層を理解するため、個人学習環境としてAzure上に概念的に対応する構成を構築する。

サービス名を機械的に置き換えるのではなく、次の設計概念を実装して検証する。

- オブジェクトストレージへのデータ取り込み
- イベントを起点とした処理開始
- ワークフローのオーケストレーション
- Pythonによる入力検証
- スキーマ検出とスキーマ変化への対応
- ETLによるデータ変換
- 出力ストレージへの配置
- 実行監視、障害検知、メール通知
- TerraformによるIaC
- 冪等性、異常系、再実行を考慮したパイプライン設計

Azureは学習環境であり、最終的な目標は仕事のAWS構成を説明できるようになることである。

## AWS側で把握している構成

```text
共通基盤
   ↓
S3 / input
   ↓ Object Created
EventBridge Ruleなど                 ← 実案件の起動経路は未確認
   ↓ StartExecution
Step Functions                       ← 親オーケストレーター
   ├─ Lambda (Python)
   │    └─ 入力データとファイルの検証
   ├─ Glue Crawler
   │    └─ スキーマの検出
   │         ↓
   │       Glue Data Catalog
   ├─ Glue ETL
   │    └─ データ変換
   └─ S3 / output
          ↓
       後段システム

監視:
CloudWatch → CloudWatch Alarm → SNS → Email

IaC:
Terraform
```

### 確定している前提

- Step Functionsが親として処理全体を制御する。
- Lambdaの実装言語はPythonである。
- SNSは処理失敗時のメール通知に使う。
- Glue Crawlerはデータスキーマを自動検出する。
- Terraformを使用する。

### 未確定事項

- S3のオブジェクト作成からStep Functionsを開始するまでの経路
- 入力形式（CSV、JSON、Parquetなど）
- 1ファイルのサイズと件数
- 入力頻度
- Glue Crawlerの実行タイミング
- スキーマ変更を許容するか、検知時に異常とするか
- Glue ETLの実装方式（Glue Studio、PySpark、Python Shellなど）
- 出力S3から後段システムへの受け渡し方式
- Validation NGを業務エラーと処理失敗のどちらで扱うか
- Retry、Timeout、DLQの要件
- 再処理と冪等性の設計
- CloudWatchとSNSの通知条件

## 学習環境の制約

- 月額1,000円以内を目標とする。厳密なハードリミットにはしない。
- ConsumptionまたはServerlessと、利用可能な最小SKUを優先する。
- Storageは小容量かつLRSとする。
- 不要な定期実行と常時稼働リソースを作らない。
- Mapping Data FlowのDebugは検証中だけ有効化する。
- Azure BudgetとCost Alertを設定する。
- Purview、Databricks、Private Endpointは初期構成に含めない。
- アクセスキーの直書きを避け、Managed IdentityとRBACを使う。

## 完成条件

次の内容を説明し、実演できれば学習環境として完成とする。

- ADLS Gen2にCSVを投入すると、イベントによって処理が始まる。
- Azure Data Factory Pipelineが親として処理順序を制御する。
- Azure FunctionsのPythonコードが入力を検証する。
- 不正データが業務Rejectとして分離される。
- Mapping Data Flowがデータを変換する。
- スキーマ変更を許容する場合と拒否する場合を試せる。
- 出力ファイルがADLS Gen2に生成される。
- システム障害時にAzure Monitorからメール通知される。
- Terraformで主要インフラを再構築できる。
- 同一入力を再実行した場合の挙動を説明できる。
- AWS側のS3、EventBridge、Step Functions、Lambda、Glue Crawler、Glue ETL、CloudWatch、SNSとの対応を説明できる。
