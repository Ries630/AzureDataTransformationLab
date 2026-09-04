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

### 1. Terraformのファイルと実行対象を理解する

構成は[`infra/terraform/`](../infra/terraform/)に置く。Terraformは同じディレクトリの`.tf`をまとめて読むため、ファイル名が実行順序を決めるわけではない。

| ファイル | 読むポイント |
|---|---|
| [`versions.tf`](../infra/terraform/versions.tf) | TerraformとAzureRMのバージョン制約、AzureRM backend |
| [`providers.tf`](../infra/terraform/providers.tf) | Azureへの接続、Provider自動登録の抑止、Entra認証 |
| [`variables.tf`](../infra/terraform/variables.tf) | 環境ごとの入力とその制約 |
| [`main.tf`](../infra/terraform/main.tf) | Resource Groupと対象Subscriptionの検証 |
| [`storage.tf`](../infra/terraform/storage.tf) | Storage、実行ユーザーの権限、Filesystem間の依存 |
| [`outputs.tf`](../infra/terraform/outputs.tf) | 後続のCLI操作で使う名前 |

実行対象は`Personal-Sandbox`とする。分離の理由は[ADR-0001](adr/0001-isolate-learning-subscription.md)を参照する。

実行ユーザーにはResource GroupとStorageの作成、および新設Storageへのロール割り当て権限が必要である。TerraformはAzure CLIでログインしたユーザーを使用し、そのユーザーに新設Storage限定のデータ用ロールを付ける。サービス向けManaged Identityは後続Phaseで追加する。

### 2. ローカルの入力を用意する

以降のコマンドはリポジトリルートで実行する。BashまたはZsh、Azure CLI、Terraformに加え、plan JSONの確認に`jq`を使う。

```bash
umask 077
export ARM_SUBSCRIPTION_ID="$(az account show --subscription Personal-Sandbox --query id -o tsv)"
export TF_VAR_subscription_id="${ARM_SUBSCRIPTION_ID:?Subscription IDを取得できていません}"

az account show --subscription "$ARM_SUBSCRIPTION_ID" \
  --query '{name:name,state:state,userType:user.type}' -o json
```

結果が`Personal-Sandbox`、`Enabled`、`user`であることを確認する。`az account set`でCLIの既定Subscriptionを変更する必要はない。

初回だけ[`terraform.tfvars.example`](../infra/terraform/terraform.tfvars.example)を`infra/terraform/terraform.tfvars`へコピーし、新規のResource Group名と、Azure全体で一意なStorage Account名を指定する。

```bash
cp -n infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
```

Subscription IDは環境変数から渡す。`.tfvars`、state、保存したplanとそのJSON・テキストはGit管理しない。stateやplanには識別子・機密値が含まれ得るため、内容を公開IssueやPRへ貼り付けない。`.terraform.lock.hcl`は選択したProviderを再現するためGit管理する。

Providerを更新したときは、Mac（Apple Silicon）とCI（Linux x86_64）の両方のチェックサムを記録する。

```bash
terraform -chdir=infra/terraform providers lock -platform=darwin_arm64 -platform=linux_amd64
```

学習用stateは専用StorageのAzureRM backendへ移す。[stateの共有と移行](terraform-state.md)で保存先の構築と既存stateの移行を済ませてから、以降の操作へ進む。bootstrap root自身のstate保管と復旧方法も同文書を参照する。

### 3. Microsoft.Storageだけを登録する

Provider登録はAzure側への変更である。前準備の承認を受けたうえで、未登録の場合だけ実行する。

```bash
az provider show --subscription "${ARM_SUBSCRIPTION_ID:?}" \
  --namespace Microsoft.Storage --query registrationState -o tsv

# 未登録であり、登録を承認済みの場合だけ実行する。
az provider register --subscription "${ARM_SUBSCRIPTION_ID:?}" \
  --namespace Microsoft.Storage
```

登録処理は非同期である。`az provider show`を再実行し、`Registered`になってから次へ進む。AzureRMによる自動登録は構成で無効化しているため、plan中に別のProviderを登録することはない。

入力したResource Groupが既存でないことを`az group exists`、Storage Account名が使用可能なことを`az storage account check-name`で確認する。どちらにも`--subscription "$ARM_SUBSCRIPTION_ID"`を明示する。既存のリソースを流用・importせず、新規名を選ぶ。

### 4. planを作り、作成内容を読む

PR上での変更確認は[Terraform planのPRレビュー](terraform-plan-review.md)を参照する。以下はローカルで適用対象のsaved planを作成し、機械的に照合する手順である。詳細が必要な場合は`terraform show`でsaved planを確認する。

```bash
node scripts/terraform/backend.mjs init
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform test
terraform -chdir=infra/terraform plan -input=false -out=phase1.tfplan
terraform -chdir=infra/terraform show -json phase1.tfplan \
  > infra/terraform/phase1.tfplan.json
```

`terraform test`はAzure APIをモックし、対象の取り違えを拒否できるかを確認する。実際のAzure権限や作成可否は、実planと承認後の適用で確認する。

planの`+`は作成予定を表す。Phase 1の初回構築ではResource Group、Storage、実行ユーザーのRole Assignment、4つのFilesystemの計7件を追加した。state移行直後は、これらを再作成せず差分なしになることを確認する。

plan JSONから対象Subscriptionと操作一覧を確認する。Subscription ID自体を出力せず、ローカルで指定値と照合する。

```bash
jq --arg expected "${ARM_SUBSCRIPTION_ID:?}" '
  {
    subscription_matches: (.variables.subscription_id.value == $expected),
    subscription: [.prior_state.values.root_module.resources[]
      | select(.address == "data.azurerm_subscription.current")
      | {name: .values.display_name, matches: (.values.subscription_id == $expected)}],
    changes: [.resource_changes[] | select(.mode == "managed")
      | {address, actions: .change.actions}]
  }
' infra/terraform/phase1.tfplan.json
```

照合結果がすべて`true`で、Subscription名が対象と一致し、操作一覧が今回のコード変更に対応するものだけであることを確認する。state移行直後は`no-op`だけになる。コード上でも、全リソースが単一のProviderと学習用Resource Group・Storageの参照からつながっていることを照合し、`Personal-Data`への変更がないことを確認する。

Storage定義の`is_hns_enabled`が階層名前空間を有効にし、`for_each`が名前をキーとして4つのFilesystemを管理する。`scope`はデータ用ロールの効く範囲をStorageに限定する。Filesystemの`depends_on`は、Storageの存在に加えて権限の付与完了も待つために必要である。

plan提示時には、リージョンとSKU、想定する保存容量・操作回数、取得日の明らかな[公式料金](https://azure.microsoft.com/pricing/details/storage/data-lake/)から費用を見積もる。Hot/LRSでも保存容量、操作、メタデータ、外向き転送等に従量料金がある。予算目標は[プロジェクト概要](project-brief.md#学習環境の制約)を参照する。BudgetとCost AlertはPhase 5で追加するため、この段階では費用を自動停止する仕組みはない。

### 5. 承認されたplanを適用する

**plan内容と費用・後片付け方法を提示し、明示的な適用承認を受けてから実行する。**

```bash
terraform -chdir=infra/terraform apply phase1.tfplan
```

保存したplanを指定することで、確認済みの変更を適用する。コード、入力、stateが変わった場合は新しいplanを作り、再度確認・承認する。

Role Assignmentの作成完了と権限の反映完了は同時ではない。[Azureの説明](https://learn.microsoft.com/azure/storage/blobs/assign-azure-role-data-access)では反映に最大10分かかる場合がある。初回にFilesystem作成が403で失敗した場合は、付与先ユーザー・ロール・スコープを確認し、反映を待つ。stateを削除せず再planし、残っている変更を提示して承認後に再適用する。403をキー認証への切り替えで回避しない。

### 6. 作成したStorageとCSVを確認する

```bash
export LAB_RESOURCE_GROUP="$(terraform -chdir=infra/terraform output -raw resource_group_name)"
export LAB_STORAGE_ACCOUNT="$(terraform -chdir=infra/terraform output -raw storage_account_name)"

az storage account show --subscription "${ARM_SUBSCRIPTION_ID:?}" \
  --resource-group "${LAB_RESOURCE_GROUP:?}" --name "${LAB_STORAGE_ACCOUNT:?}" \
  --query '{hns:isHnsEnabled,sku:sku.name,sharedKey:allowSharedKeyAccess}' -o json
az storage fs list --subscription "$ARM_SUBSCRIPTION_ID" \
  --account-name "$LAB_STORAGE_ACCOUNT" --auth-mode login --query '[].name' -o json

az storage fs file upload --subscription "$ARM_SUBSCRIPTION_ID" \
  --account-name "$LAB_STORAGE_ACCOUNT" --auth-mode login \
  --file-system landing --path orders_v1.csv \
  --source samples/valid/orders_v1.csv --overwrite false

LAB_DOWNLOAD="$(mktemp)"
az storage fs file download --subscription "$ARM_SUBSCRIPTION_ID" \
  --account-name "$LAB_STORAGE_ACCOUNT" --auth-mode login \
  --file-system landing --path orders_v1.csv --destination "$LAB_DOWNLOAD" \
  --overwrite true
cmp samples/valid/orders_v1.csv "$LAB_DOWNLOAD"
rm "$LAB_DOWNLOAD"

terraform -chdir=infra/terraform plan -input=false -detailed-exitcode
```

HNS有効・Standard_LRS・Shared Key無効、4つのFilesystem、CSVの内容一致を確認する。PortalまたはStorage Explorerでも`landing/orders_v1.csv`を開いて構成を確かめる。検証用CSVはTerraform管理対象にしないため、再planが差分なし（終了コード0）になることを確認する。終了コード2は差分あり、1はエラーである。

### 7. 後片付けする

この節は、学習環境が不要になったときに実施する。Phase 1の構築完了は削除完了を意味しない。削除すると後続Phaseへ進む前に再構築が必要になる。

#### 準備とCIの休止

対象Subscriptionと入力を[ローカル入力の手順](#2-ローカルの入力を用意する)で確認する。学習用rootだけを削除し、state保存先・履歴とCI Identityは保持する。保存先の保護は[stateの後片付け規定](terraform-state.md#復旧と後片付け)を参照する。Provider登録も解除しない。

CI接続済みの場合は、承認を受けてAzure接続ありのPR planを休止する。認証不要の`terraform.yml`は停止しない。

```bash
gh workflow disable terraform-plan.yml --repo Ries630/AzureDataTransformationLab
gh api repos/Ries630/AzureDataTransformationLab/actions/workflows/terraform-plan.yml --jq .state
gh run list --repo Ries630/AzureDataTransformationLab --workflow terraform-plan.yml
```

`disabled_manually`を確認し、開始済み・承認待ちの実行やローカルのTerraform処理が残っていれば先に解消する。workflowの無効化だけでは開始済みの実行は停止しない。休止日時と確認結果を作業IssueまたはPRへ記録し、再構築まで休止を維持する。

現時点のResource Group内のリソースと全Filesystemのデータ一覧を、stateの管理対象と照合する。サンプルCSVも削除対象なので、最新の学習用remote state、CI用local state、データを非公開の保管先へ退避して内容一致を確認する。stateだけではCSVを復元できない。stateの保管・権限は[stateの保管手順](terraform-state.md#2-認証と保護を確認する)に従い、データもGit管理外の0700ディレクトリ・0600ファイルで保管する。

**追加データや管理外リソースが見つかった場合は停止する。** RG・Storageの削除は内部のデータやリソースも失わせるため、Terraformのplanに個別表示されなくても削除の影響範囲に入る。退避・移動または削除対象の再確定を済ませ、改めて承認を得るまで適用しない。

#### CIの依存を切り離すplan

CI接続済みの場合、[`infra/ci-plan/`](../infra/ci-plan/)が別stateで管理する学習用RG・Storageの読み取り権限を先に解除する。`lab_access_enabled`の既定値は`true`であり、既存アドレスからの移行は[`main.tf`](../infra/ci-plan/main.tf)の`moved`ブロックで扱う。[Terraformの説明](https://developer.hashicorp.com/terraform/language/modules/develop/refactoring#enable-count-or-for_each-for-a-resource)も参照できる。

初回の準備修正では、接続有効時のplanに不要な再作成がないことを先に確認する。その後、Git管理外の`infra/ci-plan/cleanup.auto.tfvars`を次の内容で用意する。既に存在する場合は上書きせず内容を確認する。

```hcl
lab_access_enabled = false
```

これは削除後も保持するローカル入力である。一度限りの`-var`だけにすると次のplanが既定値へ戻るため、保存した入力を使う。CI用rootを別端末で操作する場合も同じ入力を非公開経路で引き継ぐ。

```bash
terraform -chdir=infra/ci-plan plan -input=false -out=detach-lab.tfplan
terraform -chdir=infra/ci-plan show -no-color detach-lab.tfplan
```

操作が`lab_reader`と`lab_blob_reader`の2件の削除だけであることを確認する。CI Identity・OIDC・Subscription名前確認権限・stateの読み取りとlease権限は保持する。これらにも変更が出る場合は停止する。CI未構築の場合だけ、この切り離しは不要である。

#### 学習用rootの破棄plan

```bash
terraform -chdir=infra/terraform plan -destroy -input=false -out=destroy.tfplan
terraform -chdir=infra/terraform show -no-color destroy.tfplan
```

CI解除planと学習用destroy planを別々に確認し、対象が`Personal-Sandbox`に限定されることを照合する。初期構築の7件という数だけで判断せず、現在の構成・データ・退避結果を提示する。生のplanやstateを公開Issue・PRへ貼り付けない。

**ここで一度止まり、削除対象とデータ消失について明示的な承認を受けてから、次へ進む。準備修正のPR承認・マージは削除の承認ではない。**

#### 承認後の適用と確認

CI接続済みの場合は先に保存した`detach-lab.tfplan`を適用し、`lab_access_enabled=false`のままCI用rootの再planが差分なしになることを確認する。その後に学習用rootを破棄する。

```bash
terraform -chdir=infra/ci-plan apply detach-lab.tfplan
terraform -chdir=infra/ci-plan plan -input=false -detailed-exitcode
```

各planの適用直前にcode・入力・対応するstate、対象リソースとデータを再確認する。CI権限解除後も学習用planが承認対象と一致することを照合し、変化があれば古いplanを適用せず、作り直して再確認・承認する。適用に失敗した場合もstateを削除せず再planする。

```bash
terraform -chdir=infra/terraform apply destroy.tfplan
az group exists --subscription "${ARM_SUBSCRIPTION_ID:?}" --name "${LAB_RESOURCE_GROUP:?}"
terraform -chdir=infra/terraform state list
```

Resource Groupが存在せず、学習用stateの管理対象リソースが0件になったことを確認する。CI用rootの再planも差分なしであることを確認し、保持するstate・過去バージョン・保護設定・CI Identityが残っていることを照合する。完了記録には実施時刻と検証結果を残す。学習用rootは定義を残しているため、通常のplanを実行すると再作成予定になる。削除後の差分なし確認には使わない。

#### 再構築とCI再開は別作業

現在の`backend.mjs init`は管理対象0件のstateを拒否する。破棄後の失敗を回避するために、stateを削除したり空state拒否を緩めたりしない。再構築時は保持した空stateを正として使う手順を別途確認・承認し、学習用リソースとCIの読み取り権限を復旧する。その後に入力・権限・通常planを確認してからPR planの再開を承認する。本節の削除承認には、再構築とworkflowの再開を含めない。

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
