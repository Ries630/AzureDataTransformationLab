# 学習計画

## 進め方

各Phaseを順番に実装し、完了条件を確認してから次へ進む。

一度に完成形を構築せず、Azure PortalとADF Studioで実物を確認した結果をTerraformとGit管理へ戻す。

GitHubリポジトリを作成した後は、現在の作業Phaseと進捗をIssueで管理する。

## 利用ツール

### コマンドライン

- Git
- Azure CLI（`az`）
- Terraform
- AzureRM Provider
- Azure Functions Core Tools（`func`）
- uv

### GUI

- Azure Portal
- Azure Data Factory Studio
- Azure Storage Explorer（任意）

Azure Developer CLI（`azd`）は初期段階では使用しない。

Azure CLIとTerraformの役割を直接理解し、抽象化レイヤーを増やさないためである。

## Terraformの方針

Azureリソースは原則としてTerraformで管理する。

学習のためにPortalまたはADF Studioで設定を試した場合も、再現に必要な設定は最終的にTerraformまたはGit管理された定義へ戻す。

Azureリソースを実際に作成する前に`terraform plan`を確認し、明示的な承認を得る。

アクセスキーをコードやTerraform変数へ直書きせず、Managed IdentityとRBACを使う。

## Phase 0: ローカル環境

次を準備する。

- Gitリポジトリ
- Azure CLI
- Terraform
- Azure Functions Core Tools
- uv
- Azure Storage Explorer（任意）

確認コマンドは次のとおり。

```bash
git status
az version
az account show
terraform version
func --version
uv --version
```

完了条件は、対象Azure Subscriptionを確認でき、TerraformとFunctions Core Toolsを実行できることである。

## Phase 1: Storage

Terraformで次を作成する。

```text
Resource Group
   ↓
Storage Account（ADLS Gen2、Hierarchical Namespace有効）
   ├─ landing
   ├─ validated
   ├─ rejected
   └─ output
```

LRSかつ学習用途で安価な構成を選ぶ。

サンプルCSVをCLIで`landing`へアップロードし、PortalまたはStorage Explorerから内容を確認する。

完了条件は`terraform fmt`と`terraform validate`が成功し、承認された`terraform plan`どおりにStorageを作成できることである。

## Phase 2: Azure Functionsによる入力検証

Python Functionを実装し、検証ロジックをAzure Functions固有コードから分離してテストする。

依存関係の正は`function_app.py`のPEP 723インラインメタデータと、隣接するロックファイルに置く。

Azure FunctionsはPEP 723を直接解釈しないため、Linux環境でuvを使って`.python_packages/lib/site-packages`へ依存関係を配置し、`--no-build`で発行する。

```bash
uv lock --script functions/validator/function_app.py

uv export \
  --script functions/validator/function_app.py \
  --format requirements.txt \
| uv pip install \
    --requirements - \
    --target functions/validator/.python_packages/lib/site-packages

cd functions/validator
func azure functionapp publish "$FUNCTION_APP_NAME" --no-build
```

`requirements.txt`ファイルと`pyproject.toml`は作成しない。

この方式を実装する時点で再現性とAzure Functions上での動作を検証し、長期採用する場合はADRへ記録する。

完了条件は、正常なCSVをVALID、不正なCSVをINVALIDと判定し、構造化した結果を返せることである。

## Phase 3: Data Factory Pipeline

ADF Pipelineを親オーケストレーターとして構築する。

```text
Storage Event Trigger
  ↓
Pipeline
  ↓
Azure Function Activity
  ↓
If Condition
  ├─ VALID → validated → Mapping Data Flow → output
  └─ INVALID → rejected → 正常終了
```

Storage Event Triggerは`landing`のCSVだけを対象にする。

Retry、Timeout、Function例外時の失敗経路も試す。

完了条件は、VALIDとINVALIDが異なる経路を通り、INVALIDではMapping Data Flowを実行しないことである。

## Phase 4: Schema Evolution

Mapping Data Flowで次を試す。

- 列追加
- 列削除
- 型変更
- 未知の列
- Strict schemaとTolerant schema
- `Allow schema drift`
- `Infer drifted column types`

Mapping Data FlowのDebugは検証直前に有効化し、終了後すぐ無効化する。

完了条件は、許容する変更と拒否する変更の挙動を説明できることである。

## Phase 5: Monitoring

次を構築する。

- Application Insights
- Log Analytics
- Azure Monitor Alert
- Action Groupによるメール通知
- Azure BudgetとCost Alert

意図的にPipelineを失敗させ、システム障害ではメール通知され、業務Rejectでは通知されないことを確認する。

## Phase 6: IdempotencyとRetry

同じファイルのイベント配送と手動再実行を試す。

次を決定して検証する。

- 処理識別子
- 処理状態の保存先
- 同時実行時の排他制御
- 出力ファイル名と上書き方針
- 失敗後のRetry
- 正常完了後の再実行

完了条件は、同一入力を複数回処理しても二重出力や不整合が発生しないことである。

## Phase 7: IaCの整理

PortalまたはADF Studioで手動作成した設定を、可能な範囲でTerraformまたはGit管理された定義へ戻す。

主要インフラをTerraformから再構築できることを確認する。

Functionコードの発行はTerraformから分離してよい。

## サンプルデータ

| 目的 | ファイル |
|---|---|
| 正常な入力 | [`samples/valid/orders_v1.csv`](../samples/valid/orders_v1.csv) |
| 不正な入力 | [`samples/invalid/orders_invalid.csv`](../samples/invalid/orders_invalid.csv) |
| 列追加 | [`samples/schema-evolution/orders_v2.csv`](../samples/schema-evolution/orders_v2.csv) |
| 追加の列変更 | [`samples/schema-evolution/orders_v3.csv`](../samples/schema-evolution/orders_v3.csv) |

Schema Evolutionでは、新しい列を通す、無視する、Validation Errorにする場合を比較する。

必須列の削除と`amount`の型変更も追加し、スキーマ検出と変更受け入れが別の判断であることを確認する。
