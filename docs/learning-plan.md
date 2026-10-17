# 学習計画

この文書は、Azure学習環境をPhaseごとに構築する順序と、各Phaseで実行する手順・確認項目を定める。目的と完成条件は[プロジェクト概要](project-brief.md)、サービス構成と処理の仕様は[アーキテクチャ](architecture.md)を正とする。各Phaseの仕組みは、表の「解説」から読める。

| Phase | 作るもの・確かめること | Issue | 解説 |
|---|---|---|---|
| [0](#phase-0-ローカル環境) | ローカルのツールとAzure認証 | [#6](https://github.com/Ries630/AzureDataTransformationLab/issues/6) | |
| [1](#phase-1-storage) | ADLS Gen2の保存先 | [#7](https://github.com/Ries630/AzureDataTransformationLab/issues/7) | [Phase 1](tutorials/phase-1-storage.md) |
| [2](#phase-2-azure-functionsによる入力検証) | FunctionsによるCSV検証 | [#16](https://github.com/Ries630/AzureDataTransformationLab/issues/16) | [Phase 2](tutorials/phase-2-validation.md) |
| [3](#phase-3-data-factory-pipeline) | Data Factoryによる自動処理 | [#17](https://github.com/Ries630/AzureDataTransformationLab/issues/17) | [Phase 3](tutorials/phase-3-data-factory.md) |
| [4](#phase-4-schema-evolution) | スキーマ変化への対応の比較 | [#18](https://github.com/Ries630/AzureDataTransformationLab/issues/18) | [Phase 4](tutorials/phase-4-schema-evolution.md) |
| [5](#phase-5-monitoring) | 障害通知と費用監視 | [#19](https://github.com/Ries630/AzureDataTransformationLab/issues/19) | |
| [6](#phase-6-idempotencyとretry) | 冪等性と再実行 | [#20](https://github.com/Ries630/AzureDataTransformationLab/issues/20) | |
| [7](#phase-7-iacの整理) | IaCの整理と再構築 | [#21](https://github.com/Ries630/AzureDataTransformationLab/issues/21) | |

## 進め方

Phaseは表の順に1つずつ実装し、完了条件を確かめてから次へ進む。完成形を一度に構築せず、Azure PortalとADF Studioで実物を確認した結果を、TerraformとGit管理の定義へ戻していく。現在の作業Phaseと進捗はIssueで管理する。

Phase 4を終えた後は、AWS版の構築を優先した。AWS 4（会社環境での構築）の受け入れ確認は会社の手順書を待つため、その完了を待たずにPhase 5〜7をこの順で進める。[外部SQL取得（#28）](https://github.com/Ries630/AzureDataTransformationLab/issues/28)と[対応表マスタ（#29）](https://github.com/Ries630/AzureDataTransformationLab/issues/29)は、AWS側も含めて当面の対象外とし、[後から追加する機能](aws-learning-plan.md#後から追加する機能)で扱う。

学習環境が不要になったときの削除と、削除後の再構築は、[後片付けと再構築](lab-teardown.md)にまとめている。

## 利用ツール

| 種類 | ツール | 用途 |
|---|---|---|
| コマンドライン | Git | リポジトリの管理 |
| | Azure CLI（`az`） | ログイン、Subscriptionの確認、Storageの読み書き |
| | TerraformとAzureRM Provider | Azureリソースの定義と作成 |
| | Azure Functions Core Tools（`func`） | Functionのローカル実行と発行 |
| | uv | Pythonの実行と依存関係の固定 |
| | jq | plan JSONや応答の確認 |
| GUI | Azure Portal | 作成したリソースの確認 |
| | Azure Data Factory Studio | Pipelineの閲覧とData FlowのDebug |
| | Azure Storage Explorer（任意） | Storageの中身の確認 |

Azure Developer CLI（`azd`）は初期段階では使わない。Azure CLIとTerraformがそれぞれ何をしているかを直接理解したいので、抽象化の層を増やさない。

## Terraformの方針

- Azureリソースは原則としてTerraformで管理する。PortalやADF Studioで設定を試した場合も、再現に必要な設定は最終的にTerraformかGit管理の定義へ戻す。
- Azureリソースを作成・変更する前に`terraform plan`の内容を確認し、明示的な承認を得る。適用には、承認したplanを保存したファイルを使う。
- アクセスキーをコードやTerraform変数に書かず、Managed IdentityとRBACで認可する。

Phase 2以降の機能は、Terraform変数のフラグ（`functions_enabled`など）で有効にする。フラグはGit管理外の`infra/terraform/phase<N>.auto.tfvars`に保存し、Terraformが自動で読み込む。各Phaseのplan手順にある次の形のブロックは、この入力ファイルを初めて作るためのものである。

```bash
(
set -eu
umask 077
set -o noclobber
printf '%s\n' 'functions_enabled = true' > infra/terraform/phase2.auto.tfvars
terraform -chdir=infra/terraform plan -input=false -out=phase2.tfplan
terraform -chdir=infra/terraform show -no-color phase2.tfplan
)
```

`set -o noclobber`により、同名のファイルが既にあると書き込みが失敗し、`set -e`によってplanを実行せずにブロックが終わる。既存の入力を誤って上書きしないためである。ファイルが既にある場合は、中身を確認・編集してから、planとshowの2行だけを実行する。

## Phase 0: ローカル環境

[利用ツール](#利用ツール)のコマンドラインツールを用意し、次のコマンドで動作を確かめる。

```bash
git status
az version
az account show
terraform version
func --version
uv --version
```

完了条件は、対象のAzure Subscriptionを確認でき、TerraformとFunctions Core Toolsを実行できることである。

## Phase 1: Storage

Terraformで、CSVを置く保存先を作る。

```text
Resource Group
   ↓
Storage Account（ADLS Gen2、Hierarchical Namespace有効、LRS）
   ├─ landing
   ├─ validated
   ├─ rejected
   └─ output
```

学習用途なので、LRSの安価な構成を選ぶ。作成後はサンプルCSVをCLIで`landing`へアップロードし、PortalまたはStorage Explorerで中身を確かめる。

完了条件は、`terraform fmt`と`terraform validate`が成功し、承認された`terraform plan`どおりにStorageを作成できることである。

### 1. Terraformのファイルと実行対象を理解する

構成は[`infra/terraform/`](../infra/terraform/)に置く。Terraformは同じディレクトリの`.tf`をまとめて読むため、ファイル名で実行順序が決まるわけではない。

| ファイル | 読むポイント |
|---|---|
| [`versions.tf`](../infra/terraform/versions.tf) | TerraformとAzureRMのバージョン制約、AzureRM backend |
| [`providers.tf`](../infra/terraform/providers.tf) | Azureへの接続、Provider自動登録の抑止、Entra認証 |
| [`variables.tf`](../infra/terraform/variables.tf) | 環境ごとの入力とその制約 |
| [`main.tf`](../infra/terraform/main.tf) | Resource Groupと対象Subscriptionの検証 |
| [`storage.tf`](../infra/terraform/storage.tf) | Storage、実行ユーザーの権限、Filesystem間の依存 |
| [`outputs.tf`](../infra/terraform/outputs.tf) | 後続のCLI操作で使う名前 |

実行対象のSubscriptionは`Personal-Sandbox`である。ほかのSubscriptionと分けた理由は[ADR-0001](adr/0001-isolate-learning-subscription.md)にある。

TerraformはAzure CLIでログインしたユーザーとして実行する。このユーザーには、Resource GroupとStorageを作成する権限と、新設したStorageにロールを割り当てる権限が必要である。Terraformは、このユーザーに新設Storageだけを範囲とするデータ用ロールを付ける。サービス用のManaged Identityは後続のPhaseで追加する。

### 2. ローカルの入力を用意する

以降のコマンドはリポジトリのルートで、BashまたはZshから実行する。まず、対象Subscriptionの情報を取得する。

```bash
umask 077
export ARM_SUBSCRIPTION_ID="$(az account show --subscription Personal-Sandbox --query id -o tsv)"
export TF_VAR_subscription_id="${ARM_SUBSCRIPTION_ID:?Subscription IDを取得できていません}"

az account show --subscription "$ARM_SUBSCRIPTION_ID" \
  --query '{name:name,state:state,userType:user.type}' -o json
```

結果が`Personal-Sandbox`、`Enabled`、`user`であることを確かめる。コマンドごとにSubscriptionを指定するので、`az account set`でCLIの既定を変える必要はない。

初回だけ、[`terraform.tfvars.example`](../infra/terraform/terraform.tfvars.example)をコピーし、新規のResource Group名と、Azure全体で一意なStorage Account名を記入する。Subscription IDはファイルに書かず、上で設定した環境変数から渡す。

```bash
cp -n infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
```

stateと保存したplanには、識別子や機密値が含まれることがある。そのため、次のようにGitでの扱いを分ける。

| ファイル | Git管理 | 理由 |
|---|---|---|
| `.tfvars`、state、保存したplanとそのJSON・テキスト | しない | 識別子や機密値を含みうる。中身を公開のIssueやPRにも貼らない |
| `.terraform.lock.hcl` | する | 選択したProviderを再現する |

Providerを更新したときは、Mac（Apple Silicon）とCI（Linux x86_64）の両方のチェックサムをロックファイルに記録する。

```bash
terraform -chdir=infra/terraform providers lock -platform=darwin_arm64 -platform=linux_amd64
```

stateは専用StorageのAzureRM backendに置く。保存先の構築、local stateからの移行、保存先自身（bootstrap root）のstateの保管と復旧は、[stateの共有と移行](terraform-state.md)の手順で行う。移行を済ませてから次へ進む。

### 3. Microsoft.Storageだけを登録する

AzureでStorageのAPIを使うには、Subscriptionに`Microsoft.Storage`のResource Providerを登録する必要がある。登録はAzure側への変更なので、前準備として承認を受け、未登録の場合だけ実行する。

```bash
az provider show --subscription "${ARM_SUBSCRIPTION_ID:?}" \
  --namespace Microsoft.Storage --query registrationState -o tsv

# 未登録であり、登録を承認済みの場合だけ実行する。
az provider register --subscription "${ARM_SUBSCRIPTION_ID:?}" \
  --namespace Microsoft.Storage
```

登録は非同期に進む。`az provider show`を再実行し、`Registered`になってから次へ進む。AzureRMによる自動登録は構成で無効にしているので、planの途中で別のProviderが登録されることはない。

続けて、記入した名前が使えることを確かめる。Resource Groupが存在しないことを`az group exists`で、Storage Account名が使用可能なことを`az storage account check-name`で確認する。どちらにも`--subscription "$ARM_SUBSCRIPTION_ID"`を付ける。既存のリソースは流用もimportもせず、新しい名前を選ぶ。

### 4. planを作り、作成内容を読む

ここでは、適用に使うplanをローカルで作り、内容を機械的に照合する。PR上でplanを確認する方法は[Terraform planのPRレビュー](terraform-plan-review.md)にある。詳細を人が読む形で確かめたいときは、`terraform show`でsaved planを表示する。

```bash
node scripts/terraform/backend.mjs init
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform test
terraform -chdir=infra/terraform plan -input=false -out=phase1.tfplan
terraform -chdir=infra/terraform show -json phase1.tfplan \
  > infra/terraform/phase1.tfplan.json
```

`terraform test`はAzure APIをモックに置き換え、対象Subscriptionを取り違えたときにplanを拒否できるかを確かめる。実際のAzure権限で作成できるかどうかは、実planと承認後の適用で確かめる。

planの`+`は作成予定を表す。Phase 1の初回構築では、Resource Group、Storage、実行ユーザーのRole Assignment、4つのFilesystemの計7件が作成予定になった。stateを移行した直後のplanでは、これらを作り直さず、差分なしになることを確かめる。

次に、plan JSONから対象Subscriptionと操作の一覧を取り出す。Subscription IDそのものは出力せず、ローカルで指定値と照合した結果だけを表示する。

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

出力では次を確かめる。

- 照合結果がすべて`true`で、Subscription名が対象と一致する。
- 操作の一覧に、今回のコード変更に対応するものだけが並んでいる。state移行の直後なら`no-op`だけになる。
- コード上でも、全リソースが単一のProviderと、学習用のResource Group・Storageへの参照からつながっている。`Personal-Data`への変更は含まれない。

コードの読みどころは次の4つである。`is_hns_enabled`が階層名前空間を有効にし、`for_each`が名前をキーとして4つのFilesystemを管理する。`scope`はデータ用ロールの範囲を作成したStorageに限定する。Filesystemの`depends_on`は、Storageの存在に加えて、権限の付与が終わるのを待つために必要である。

planを提示するときは、リージョンとSKU、想定する保存容量と操作回数、取得日を明記した[公式料金](https://azure.microsoft.com/pricing/details/storage/data-lake/)から費用を見積もる。Hot・LRSでも、保存容量、操作、メタデータ、外向きの転送などに従量料金がかかる。予算の目標は[プロジェクト概要](project-brief.md#学習環境の制約)にある。BudgetはPhase 5で追加するので、この段階には費用の通知がない。Budgetを追加した後も、費用でリソースを自動停止する仕組みはない。

### 5. 承認されたplanを適用する

**planの内容、費用、後片付けの方法を提示し、明示的な適用承認を受けてから実行する。**

```bash
terraform -chdir=infra/terraform apply phase1.tfplan
```

保存したplanを指定するので、確認した変更だけが適用される。コード、入力、stateのいずれかが変わった場合は、planを作り直して再び確認と承認を受ける。

Role Assignmentの作成が終わっても、権限がすぐに有効になるとは限らない。[Azureの説明](https://learn.microsoft.com/azure/storage/blobs/assign-azure-role-data-access)では、反映に最大10分かかる場合がある。初回にFilesystemの作成が403で失敗したときは、次の順で対処する。

1. 付与先のユーザー、ロール、スコープを確認し、反映を待つ。
2. stateを削除せずにplanを作り直し、残っている変更を提示する。
3. 承認を受けてから再適用する。

403は、アカウントキーによる認証へ切り替えて回避しない。

### 6. 作成したStorageとCSVを確認する

Terraformのoutputから名前を取り出し、Storageの設定、Filesystem、CSVの読み書きを順に確かめる。

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

| 確認すること | 期待する結果 |
|---|---|
| Storageの設定 | HNSが有効、`Standard_LRS`、Shared Keyが無効 |
| Filesystem | `landing`、`validated`、`rejected`、`output`の4つがある |
| CSVの往復 | `cmp`が差分を出さず、終了コードが0になる |
| 再plan | 終了コード0（差分なし） |

CSVはTerraformの管理対象ではないので、アップロード後の再planも差分なしになる。`-detailed-exitcode`の終了コードは、0が差分なし、2が差分あり、1がエラーである。最後にPortalまたはStorage Explorerでも`landing/orders_v1.csv`を開き、構成を確かめる。

### 7. 後片付けする

学習環境を削除する手順と、削除後に再構築する手順は[後片付けと再構築](lab-teardown.md)にある。Phase 1を終えたら削除する、という手順ではない。削除すると、次のPhaseへ進む前に再構築が必要になる。

## Phase 2: Azure Functionsによる入力検証

PythonのFunctionでCSVを検証する。検証ロジックはAzure Functions固有のコードから分離し、Azureなしでテストできるようにする。HTTP契約とCSV検証規則の正は[アーキテクチャのAzure Functions節](architecture.md#azure-functionsの責務)、コードの読み方と演習は[Phase 2の解説](tutorials/phase-2-validation.md)にある。Azureへの適用、Azure上での動作確認、CI接続の復旧は、それぞれplanを確認して別々に承認を得てから行う。

### 1. ローカルの公開境界を確認する

次の3つの責務を、別々のファイルに実装する。

| ファイル | 学習する責務 |
|---|---|
| `functions/validator/validation.py` | Azure SDKを使わずにCSVのバイト列を判定する |
| `functions/validator/storage.py` | Managed Identityで`landing`のBlobを読み取り、ETagを照合する |
| `functions/validator/function_app.py` | HTTP入力、検証処理、StorageエラーをHTTP応答へつなぐ |

まず`validation.py`の公開関数をローカルから呼び出し、正常なサンプルと不正なサンプルについて、判定、エラーの位置、エラーの件数を確かめる。このPhaseの中心となる学習点は、HTTP 200で返る`INVALID`（データの不備）と、読み取り失敗などの5xx（処理の失敗）を別の状態として扱うことである。

### 2. ローカルで実行する

リポジトリのルートで、テストとサンプルの検証を実行する。

```bash
uv run --locked functions/validator/function_app.py test
uv run scripts/validator/test_pure.py
uv run --locked functions/validator/function_app.py sample samples/valid/orders_v1.csv
uv run --locked functions/validator/function_app.py sample samples/invalid/orders_invalid.csv
```

`test_pure.py`はAzure SDKを使わずに公開関数を確かめる。`sample`では、VALIDとINVALIDの構造化された結果を読む。続けて、不正サンプルのコピーを1項目ずつ書き換え、どのエラーが消え、どのエラーが残るかを記録する。CSVの規則は[アーキテクチャのAzure Functions節](architecture.md#azure-functionsの責務)を参照する。

ここから先のローカルHTTP確認は、学習用Storageの`landing/orders_v1.csv`を実際に読む。後片付けでStorageを削除している場合は、上のテストとサンプル実行だけを済ませて[基盤のplan](#5-azureの基盤をplanで確認する)へ進み、Storageを再構築してサンプルCSVを配置してから本節に戻る。

Functionsホストは状態の保存先を必要とするので、`serve`の前にAzuriteを起動する。ローカル設定ファイルを作り、`LAB_STORAGE_ACCOUNT_NAME`を実際の学習用Storage名に書き換える。

```bash
docker compose -f functions/validator/compose.local.yml up -d
cp -n functions/validator/local.settings.json.example functions/validator/local.settings.json
# local.settings.jsonのLAB_STORAGE_ACCOUNT_NAMEを編集する。
unset AZURE_CLIENT_ID
az account show --subscription Personal-Sandbox --query '{name:name,state:state,userType:user.type}' -o json
```

`AZURE_CLIENT_ID`は設定しない。ローカルの`storage.py`はAzure CLIのログインで認証するので、User Assigned Managed IdentityのClient IDを指定すると接続方法が変わってしまう。`userType`が`user`で、対象のSubscriptionであることを確かめてから、別のターミナルでFunctionsホストを起動する。

```bash
uv run --locked functions/validator/function_app.py serve
```

ローカルのHTTP呼び出しでは、Azure CLIのログインで取得したETagを使う。ローカルではFunction keyは不要である。

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

### 3. 依存関係をロックする

依存関係の正は、`function_app.py`に書いたPEP 723のインラインメタデータと、隣に置くロックファイルである。

```bash
uv lock --script functions/validator/function_app.py
uv run --locked functions/validator/function_app.py test
```

`uv lock --script`が作るロックファイルをレビューし、`--locked`付きで実行してもロックが変わらないことを確かめる。`requirements.txt`と`pyproject.toml`は作らない。

### 4. Azure Functions用の依存関係を生成する

Azure FunctionsのホストはPEP 723のメタデータを読んで依存関係をインストールしない。そこで、Linux x86_64・Python 3.14の環境でロックどおりの依存関係を`.python_packages/lib/site-packages`へ配置し、そのディレクトリごと発行する。生成処理は`scripts/validator/package.py`にまとめてあり、ハッシュを検証しながらwheelだけをインストールする。

配置先はリポジトリ内の`.artifacts/`の下に、実行のたびに新しい名前で指定する。Macでは固定したLinux x86_64コンテナーで生成し、Linux x86_64では`--docker`を省く。

```bash
# Mac
uv run scripts/validator/package.py --docker .artifacts/validator-build-1

# Linux x86_64
uv run scripts/validator/package.py .artifacts/validator-build-1
```

第1引数の配置先は、まだ存在しないパスでなければならない。生成後は、依存パッケージ、`host.json`、`.funcignore`、`package-manifest.json`がそろっていることを確かめる。

同じロックから再生成するときは`validator-build-2`のような別名を使い、2つのmanifestで依存の名前・バージョンとロックのSHA256を比べる。ZIPのバイト列までは一致しない。Mac上で依存パッケージを直接生成せず、CIでも同じLinux用の生成処理を使う。

### 5. Azureの基盤をplanで確認する

後片付けで学習用Storageを削除している場合は、先に[後片付けと再構築](lab-teardown.md#再構築)の手順でStorageを再構築する。再構築は、このPhaseとは別のplanと適用承認として扱う。

Storageがある状態で、Function用のTerraform planを作る。作成対象と実行時の設定は[アーキテクチャ](architecture.md#storageと実行環境)、Storage構成の判断理由は[ADR-0004](adr/0004-separate-function-host-storage.md)、スケール上限の判断理由は[ADR-0007](adr/0007-set-flex-max-instance-count.md)にある。

plan の前に、対象リージョンでランタイムが提供されているかと、必要なResource Providerの登録状態をAzure CLIで確かめる。登録が必要なら、対象を提示して承認を受けてから登録する。

```bash
# phase2.auto.tfvarsが既にある場合は内容を確認し、上書きせず編集する。
(
set -eu
umask 077
set -o noclobber
printf '%s\n' 'functions_enabled = true' > infra/terraform/phase2.auto.tfvars
terraform -chdir=infra/terraform plan -input=false -out=phase2.tfplan
terraform -chdir=infra/terraform show -no-color phase2.tfplan
)
```

このブロックの動きは[Terraformの方針](#terraformの方針)で説明している。planでは、対象のSubscription、Resource Group、Storage Account、ロール割り当て、アプリ設定を照合し、費用の見積もりと後片付けの方法を添えて提示する。Azureリソースの作成・変更には、このplanに対する明示的な承認が必要である。

### 6. 発行して動作を確認する

基盤の適用が承認されたら、[依存関係の生成](#4-azure-functions用の依存関係を生成する)で作った配置先をFunctionプロジェクトとして`--no-build`で発行する。配置先には`function_app.py`、`validation.py`、`storage.py`、`host.json`、`.funcignore`、`.python_packages`が含まれる。

```bash
(
set -eu
test "$(az account show --subscription "${ARM_SUBSCRIPTION_ID:?}" --query name -o tsv)" = Personal-Sandbox
FUNCTION_APP_NAME="$(terraform -chdir=infra/terraform output -raw function_app_name)"
LAB_FUNCTION_RG="$(terraform -chdir=infra/terraform output -raw resource_group_name)"
az functionapp show --subscription "$ARM_SUBSCRIPTION_ID" \
  --resource-group "$LAB_FUNCTION_RG" --name "$FUNCTION_APP_NAME" \
  --query '{name:name,resourceGroup:resourceGroup}' -o json
cd .artifacts/validator-build-1
func azure functionapp publish "$FUNCTION_APP_NAME" --subscription "$ARM_SUBSCRIPTION_ID" --no-build --python
)
```

`--python`で配置先の言語を明示している。PEP 723と事前に生成したパッケージを使う配置先では、Core Toolsが言語を自動で判定できないためである。

発行後は、Function keyを付けて次の呼び出しを行い、結果が[HTTP契約](architecture.md#http契約)どおりかを確かめる。

- 正常なサンプルと不正なサンプル
- ETagが一致しない場合
- Storageからの取得に失敗する場合

あわせて、FunctionがCSVをコピーも更新もしていないことをStorage側で照合する。ローカルとAzureに同じ入力を渡し、判定結果とエラーの位置が一致することを記録する。最後に、発行後のTerraform planに意図しない差分がないことと、同じロックからLinux用パッケージを再生成できることを確かめる。

### Phase 2の完了条件

- ローカルテストが成功し、正常なCSVと不正なCSVの構造化された結果を説明できる。
- `validation.py`をAzure SDKなしでテストでき、`function_app.py`と`storage.py`の責務を説明できる。
- PEP 723のメタデータと隣接するロックから、Ubuntu 24.04でAzure Functions用のパッケージを生成できる。
- 承認されたTerraform planどおりに基盤を構築し、Function key付きのHTTP呼び出しでローカルと同じ結果を得られる。
- 業務Reject（HTTP 200・`INVALID`）とシステム障害（HTTP 5xx）を区別できる。

ADF Pipeline、`validated`・`rejected`へのコピー、Mapping Data Flow、監視通知はPhase 3以降で扱う。

## Phase 3: Data Factory Pipeline

ADF Pipelineを親オーケストレーターとして構築し、`landing`にCSVが置かれてから、検証、振り分け、変換までを自動で進める。処理の流れと異常系の正は[アーキテクチャ](architecture.md#azure側の処理フロー)、仕組みの解説は[Phase 3の解説](tutorials/phase-3-data-factory.md)にある。

```text
Storage Event Trigger（landingの.csv）
  ↓
Pipeline
  ↓
Web Activity + Filter（ETag取得）
  ↓
Azure Function Activity（入力検証）
  ↓
Switch
  ├─ VALID → Copy → validated → Mapping Data Flow → 行数確認 → output
  ├─ INVALID → Copy → rejected + 検証結果JSON → 正常終了
  └─ その他 → Fail
```

### 1. Providerを登録する

Data Factoryの作成には`Microsoft.DataFactory`、Storage Event Triggerには`Microsoft.EventGrid`のResource Providerが必要である。登録状態を確かめ、未登録の場合だけ、前準備として承認を受けてから登録する。

```bash
az provider show --subscription "${ARM_SUBSCRIPTION_ID:?}" \
  --namespace Microsoft.DataFactory --query registrationState -o tsv
az provider show --subscription "${ARM_SUBSCRIPTION_ID:?}" \
  --namespace Microsoft.EventGrid --query registrationState -o tsv

# 未登録であり、登録を承認済みの場合だけ実行する。
az provider register --subscription "${ARM_SUBSCRIPTION_ID:?}" --namespace Microsoft.DataFactory
az provider register --subscription "${ARM_SUBSCRIPTION_ID:?}" --namespace Microsoft.EventGrid
```

登録は非同期に進む。`registrationState`が`Registered`になってから次へ進む。

### 2. Data Factory基盤をplanで確認する

Data Factoryは`data_factory_enabled`で有効にする。PipelineがFunctionを呼び出すので、Phase 2の`phase2.auto.tfvars`（`functions_enabled = true`）を残したまま、Phase 3用の入力ファイルを追加する。

このplanの前に、Phase 2のplanを適用してFunction Appを作っておく。Function Appがないまま`data_factory_enabled = true`でplanすると、Linked ServiceがFunctionのキーを読み取れずにエラーになる（[ADR-0010](adr/0010-require-function-applied-before-data-factory.md)）。

```bash
# phase3.auto.tfvarsが既にある場合は内容を確認し、上書きせず編集する。
(
set -eu
umask 077
set -o noclobber
printf '%s\n' 'data_factory_enabled = true' > infra/terraform/phase3.auto.tfvars
terraform -chdir=infra/terraform plan -input=false -out=phase3.tfplan
terraform -chdir=infra/terraform show -no-color phase3.tfplan
)
```

planでは次を照合する。

- 対象のSubscription（`Personal-Sandbox`）とResource Group
- Data FactoryとData Flow用のIR（japaneast・General 8コア・TTL 0）
- ADFのManaged Identityの権限（`landing`は読み取り、`validated`・`rejected`・`output`は書き込み）
- Triggerの対象範囲（`landing`の`.csv`だけ、空Blobは無視）
- 費用の見積もりと後片付けの方法

Data Flowは、実行場所をAzureが選ぶ`AutoResolve`のIRではなく、専用のIRで実行する。実行リージョンと課金の単位をplanの時点で確定させるためである。また、Pipelineの同時実行数を1に固定し、Data Flowのクラスターが並行して起動して費用が膨らむことを防ぐ。

### 3. 承認されたplanを適用し、動作を確認する

planの内容、費用、後片付けの方法を提示し、明示的な適用承認を受けてから適用する。Triggerは適用した時点で有効になるので、それ以降に`landing`へCSVを置くと、すぐにPipelineが起動する。

VALIDのCSVを1本処理するたびにData Flowのクラスターが起動し、課金される。検証の実行は5〜8回程度に抑え、次の4点を確かめる。

| 確認すること | 期待する結果 |
|---|---|
| 正常なCSVを投入する | `validated`に原本、`output`に変換結果ができ、Pipelineが成功する |
| 不正なCSVを投入する | `rejected`に原本と`<path>.validation.json`ができ、Mapping Data Flowを実行せずにPipelineが成功する |
| `validated`・`output`へ書き込む、`landing`へ`.csv`以外のファイルを置く | Pipelineが起動しない |
| Functionを停止する、存在しないパスでPipelineを実行する | Pipelineが失敗する |

### Phase 3の完了条件

- VALIDとINVALIDが異なる経路を通り、INVALIDではMapping Data Flowを実行しないことを説明できる。
- Triggerの対象範囲と、Activity間で値を受け渡す方法を説明できる。
- ADFがStorageへはManaged Identityで、FunctionへはFunctionキーで接続する構成を説明できる。
- 障害時にPipelineが失敗の経路へ進むことを確認できる。

## Phase 4: Schema Evolution

列や型が変わったCSVに対して、どの層が何を検出し、何を受け入れるかを比較する。比較結果と読み方は[Phase 4の解説](tutorials/phase-4-schema-evolution.md)にある。

比較するData Flowは次の4つである。Strictの基準には、本番の`df_transform_orders`（`allowSchemaDrift: false`・`validateSchema: true`）を変更せずに使う。残りの3つは比較用として`schema_evolution_lab_enabled`で追加し、Pipeline・Triggerからは参照しない。

| Data Flow | 設定 | 確かめること |
|---|---|---|
| `df_transform_orders`（本番） | Strict | 宣言と異なる入力で失敗するか |
| `df_schema_tolerant` | `validateSchema: false` | 宣言外の列が無視されるか |
| `df_schema_drift` | `Allow schema drift`、列名のルールで出力へ通す | 宣言外の列がstringのまま出力に残るか |
| `df_schema_drift_infer` | 上記＋`Infer drifted column types` | 宣言外の列の型が値から推論されるか |

入力には、[サンプルデータ](#サンプルデータ)のschema-evolutionの5本と`orders_v1.csv`を使う。Functionが各サンプルを受け入れるか拒否するかは、`tests/validator/test_schema_evolution_samples.py`で確かめる。

### 1. 比較用Data Flowをplanで確認する

```bash
# phase4.auto.tfvarsが既にある場合は内容を確認し、上書きせず編集する。
(
set -eu
umask 077
set -o noclobber
printf '%s\n' 'schema_evolution_lab_enabled = true' > infra/terraform/phase4.auto.tfvars
terraform -chdir=infra/terraform plan -input=false -out=phase4.tfplan
terraform -chdir=infra/terraform show -no-color phase4.tfplan
)
```

planでは、比較用のData Flow 3つが追加されるだけで、既存のPipeline・Trigger・`df_transform_orders`に差分がないことを照合する。Data Flowは定義しただけでは費用がかからない。

既存のリソースに差分が出た場合、その差分はPhase 4の変更が原因ではない。その場合は`-target='azurerm_data_factory_data_flow.schema_evolution'`で比較用Data Flowだけのplanを作り直して適用し、既存の差分は別に扱う。

### 2. 比較用の入力を配置する

比較用のCSVは`validated/schema-lab/input/`に置く。`landing`に置くとTriggerがPipelineを起動してしまうためである。ADFのManaged Identityは`validated`を読み書きできる。

```bash
for sample in samples/valid/orders_v1.csv samples/schema-evolution/*.csv; do
  az storage fs file upload --subscription "${ARM_SUBSCRIPTION_ID:?}" \
    --account-name "${LAB_STORAGE_ACCOUNT:?}" --auth-mode login \
    --file-system validated --path "schema-lab/input/${sample##*/}" --source "$sample"
done
```

### 3. Debugで設定とサンプルの組み合わせを比較する

Mapping Data FlowのDebugは、検証の直前に有効にし、終わったらすぐ無効にする。Debug中は8 vCoreのクラスターが動き続け、General Purpose・japaneastの従量単価（2026-10-12時点で1 vCore時間あたり0.30225 USD）で、1時間あたり約2.42 USDかかる。4つのData Flowと6本のサンプルを1回のセッションでまとめて確かめ、1時間以内に終えることを目安にする。

1. ADF Studioで`Data flow debug`を有効にし、IRに`ir-<storage_account_name>`を選ぶ。
2. 各Data Flowの`Debug Settings`で、パラメーターを次のように設定する。
   - source1：`fileSystem=validated`、`folderPath=schema-lab/input`、`fileName=<サンプル名>`
   - sink1：`fileSystem=validated`、`folderPath=schema-lab/output`、`fileName`は空欄（Data Previewはsinkへ書き込まない）
3. sourceと最後の変換で`Data preview`と`Inspect`を開き、失敗の有無、列の一覧と型、行数を記録する。
4. 終わったらすぐ`Data flow debug`を無効にする。

ADF Studioで設定を編集しても、発行（Publish）はしない。比較する設定の正はTerraformの定義である。

### 4. Pipeline全体で拒否した層を確認する

`orders_v2.csv`、`orders_missing_required.csv`、`orders_amount_type_change.csv`の3本を`landing`へ投入し、Pipelineの結果と出力先を確かめる。このうちData Flowまで進むのは、Functionが受け入れる`orders_v2.csv`だけである。

| 投入するCSV | 確認すること |
|---|---|
| `orders_v2.csv` | Functionが受け入れた後、本番のStrictなData Flowが成功するか失敗するか |
| `orders_missing_required.csv` | Functionが拒否し、`rejected`に原本と検証結果JSONができる |
| `orders_amount_type_change.csv` | Functionが拒否し、`rejected`に原本と検証結果JSONができる |

`orders_v2.csv`でPipelineが失敗した場合は、Functionの契約（追加列を許容する）とData Flowの設定が食い違っていることを結果として記録する。修正は別のIssueで扱う。

### 5. 後片付けする

`phase4.auto.tfvars`を`schema_evolution_lab_enabled = false`に書き換えてplanを作り、比較用Data Flow 3つの削除だけであることを確かめてから適用する。`validated/schema-lab/`と比較の出力も削除する。

### Phase 4の完了条件

- 4つの設定とサンプルの組み合わせについて、失敗・列の無視・列の通過を比較表で説明できる。`Infer drifted column types`で推論された型をDebugのpreviewでは判別できなかったことを記録している。
- 必須列の欠落と型の変更を、Pipelineのどの層で拒否したかを説明できる。
- スキーマの推論と、変更を受け入れるかどうかの判断が別のものであることを、比較結果をもとに説明できる。

## Phase 5: Monitoring

FunctionとPipelineの実行をログから追跡し、システム障害だけをメールで通知する。あわせて、Subscription全体の費用をBudgetで監視する。作成するリソースと通知の対象は[アーキテクチャ](architecture.md#監視と通知)を正とする。

| 変数 | 作成するもの | 前提 |
|---|---|---|
| `monitoring_enabled` | Log Analytics、Application Insights、ADFの診断設定、Pipeline失敗のMetric AlertとAction Group、FunctionのIdentityへの送信権限 | `functions_enabled`と`data_factory_enabled`が`true` |
| `budget_enabled` | `Personal-Sandbox`全体の月次Budget（1,000円、実績80%・100%でメール） | `monitoring_enabled`が`true` |

Budgetは超過を通知するだけで、リソースを停止しない。予算到達時の自動停止はこのPhaseの対象外である。

### 1. 監視と通知をplanで確認する

`phase2.auto.tfvars`と`phase3.auto.tfvars`を残したまま、Phase 5用の入力ファイルを追加する。通知先のメールアドレスは`sensitive`な変数として扱い、Git、Issue、PRに書かない。`monitoring_budget_start_date`には、Budgetを作る月の1日（UTC）を指定し、作成後は変えない。

```bash
# phase5.auto.tfvarsが既にある場合は内容を確認し、上書きせず編集する。
(
set -eu
umask 077
set -o noclobber
printf 'Notification email: '
read -r -s LAB_NOTIFICATION_EMAIL
printf '\n'
{
  printf '%s\n' 'monitoring_enabled = true' 'budget_enabled = true'
  printf 'monitoring_notification_email = "%s"\n' "$LAB_NOTIFICATION_EMAIL"
  printf 'monitoring_budget_start_date = "%s"\n' "$(date -u +%Y-%m-01T00:00:00Z)"
} > infra/terraform/phase5.auto.tfvars
terraform -chdir=infra/terraform plan -input=false -out=phase5.tfplan
terraform -chdir=infra/terraform show -no-color phase5.tfplan
)
```

planでは次を照合する。

- 追加：Log Analytics workspace、Application Insights、Application Insightsが使うLog Analyticsのtable 12件、`Monitoring Metrics Publisher`のRole Assignment、ADFの診断設定、Action Group、Metric Alert、Budgetの19件
- 更新：Function App（`site_config`のApplication Insights接続文字列と、アプリ設定のEntra ID認証）と、Pipelineの`ValidateCsv`が送る`x-adf-pipeline-run-id`ヘッダーの2件
- 削除：0件
- 保存期間と取り込み上限（Log Analytics 31日・1日0.1GB、Application Insightsのtable 12件も31日）と、ローカル認証の無効化。Application Insights自体の指定は30日だが、実際の保持期間はtable側の31日になる
- Alertの対象が`pl-csv-ingestion`の`PipelineFailedRuns`だけであること
- 費用の見積もりと後片付けの方法

Log Analyticsは取り込み量、Metric Alertは監視する時系列の数で課金される。planを提示するときは、取得日を明記した公式料金から見積もる。1日の取り込みが上限に達すると、その日の残りのログは記録されない。

CIのPR planで同じ構成を読む場合は、先に[Budgetをrefresh対象へ追加する](terraform-plan-review.md#budgetをrefresh対象へ追加する)手順でCIの権限と`TERRAFORM_INPUTS`を更新する。

### 2. 承認されたplanを適用し、Functionを発行する

planの内容、費用、後片付けの方法を提示し、明示的な適用承認を受けてから適用する。

```bash
terraform -chdir=infra/terraform apply phase5.tfplan
```

適用すると、Action Groupの宛先に登録を知らせるメールが届く。届かない場合は迷惑メールと宛先を確かめてから次へ進む。

構造化ログを出すFunctionのコードは、Terraformの適用では配置されない。[依存関係の生成](#4-azure-functions用の依存関係を生成する)で新しい配置先を作り、[Phase 2の発行手順](#6-発行して動作を確認する)と同じ方法で発行する。発行後にTerraformのplanを作り、差分がないことを確かめる。

### 3. 正常・業務Reject・障害を比較する

同じPipelineで次の3つを実行し、実行状態、ログ、通知を記録する。VALIDの実行ではData Flowのクラスターが起動するので、1回に抑える。

| 実行 | Pipeline | Functionのログ | メール |
|---|---|---|---|
| `samples/valid/orders_v1.csv`を`landing`へ置く | Succeeded | `outcome`が`VALID`、`http_status`が200 | 届かない |
| `samples/invalid/orders_invalid.csv`を`landing`へ置く | Succeeded | `outcome`が`INVALID`、`http_status`が200 | 届かない |
| ADF Studioの「今すぐトリガー」で、存在しない`fileName`を指定して実行する | Failed | 記録されない（Functionを呼ぶ前に失敗する） | 届く。解決後に解決のメールも届く |

ログはLog Analytics workspaceで次のように確かめる。ADFの診断ログとApplication Insightsのログは、反映まで数分かかることがある。

```kusto
ADFPipelineRun
| where PipelineName == "pl-csv-ingestion" and Status in ("Succeeded", "Failed")
| project TimeGenerated, RunId, Status, FailureType
| join kind=leftouter (
    AppTraces
    | where Message has "csv_validation"
    | extend event = parse_json(Message)
    | project RunId = tostring(event.pipeline_run_id),
        outcome = tostring(event.outcome), http_status = toint(event.http_status)
  ) on RunId
| order by TimeGenerated desc
```

Functionのログには入力のパス、値、例外の本文を含めない。Pipelineとの関連付けには、ADFが渡す実行IDだけを使う。

Metric Alertは1分ごとに直近5分を評価するので、失敗してからメールが届くまで数分かかる。

### 4. Budgetの設定を確かめる

Budgetは通知の条件を設定から確かめる。費用データの反映には時間がかかり、学習環境の費用では閾値に届かないため、実際の通知は待たない。

```bash
az consumption budget show --subscription "${ARM_SUBSCRIPTION_ID:?}" \
  --budget-name "$(terraform -chdir=infra/terraform output -raw monitoring_budget_name)" \
  --query '{amount:amount,currency:currentSpend.unit,timeGrain:timeGrain,start:timePeriod.startDate,thresholds:notifications.*.threshold,contacts:notifications.*.contactEmails}' -o json
```

金額が1,000、通貨がJPY、期間が月次、閾値が80と100、宛先が`monitoring_notification_email`に指定したアドレスだけであることを確かめ、実通知は未検証として記録する。

### Phase 5の完了条件

- Pipelineの実行IDで、ADFの実行結果とFunctionの判定結果を突き合わせられる。
- システム障害ではメールが届き、業務Rejectでは届かないことを確認し、その理由を説明できる。
- Budgetの金額・期間・閾値・宛先を確認し、実通知を検証していないことを記録している。

## Phase 6: IdempotencyとRetry

同じファイルの重複イベント、途中で失敗した後の再実行、正常に終わった後の再実行で、二重出力や状態の不整合が起きないことを確かめる。入力の世代、状態ファイル、出力の配置は[アーキテクチャ](architecture.md#冪等性)を正とし、判断の理由は[ADR-0013](adr/0013-track-input-generations-in-blob-state.md)にある。

| 変数 | 作成・変更するもの | 前提 |
|---|---|---|
| `idempotency_enabled` | filesystem`state`、ADFのIdentityへの`state`の書き込み権限、`pl-csv-ingestion`の状態確認・版の固定・世代ごとの出力 | `data_factory_enabled`が`true` |

新しい常時稼働のリソースは作らない。費用が増えるのは、状態ファイルの読み書きと、検証で起動するData Flowのクラスターである。

### 1. 状態管理をplanで確認する

`phase6.auto.tfvars`に`idempotency_enabled = true`を書いてplanを作る。追加はfilesystemとRole Assignment、更新はPipelineだけで、削除がないことを確かめる。Pipelineの変更は、Activityの追加と、出力先のパスの変更である。

### 2. 承認されたplanを適用する

planの内容と後片付けの方法を提示し、明示的な適用承認を受けてから適用する。適用前に作った`validated`・`rejected`・`output`のファイルは、世代ごとのパスにないので、Phase 6の確認では対象外として扱う。

### 3. 重複、失敗後の再実行、完了後の再実行を確かめる

Data Flowのクラスターが起動する実行は、表の3回に抑える。

| 確認 | 操作 | 期待する結果 |
|---|---|---|
| 重複 | `orders_v1.csv`を`landing`へ置き、処理中に「今すぐトリガー」で同じ`folderPath`・`fileName`を2回実行する | 後の2回は順番待ちの後、何も書かずに正常終了する。`output`は1世代だけで、状態は`SUCCEEDED`、`attempts`は1 |
| 失敗後の再実行 | 別名で置いた`orders_v1.csv`の実行を、Data Flowの前にADF Studioでキャンセルし、同じ入力で再実行する | 状態は`RUNNING`のまま残り、再実行が引き継いで`SUCCEEDED`になる。`attempts`は2 |
| 完了後の再実行 | 重複で使った入力を、`force`なしと`force = true`で1回ずつ再実行する | `force`なしは何もしない。`force = true`は同じ世代のパスを同じ内容で上書きし、`attempts`が増える |
| 版の変更 | 同じパスに`orders_invalid.csv`の内容を置き直す | 新しい世代として`REJECTED`になる。前の世代の`output`と状態は残る |

各確認で、Pipelineの実行状態、状態ファイルの内容、各領域の世代ディレクトリを記録する。版の固定（コピー後のETag照合）は、コピーの瞬間に上書きを起こしにくいので、実機では確かめず、Pipelineの定義の確認だけにする。

### Phase 6の完了条件

- 同じ世代の重複イベントと順番待ちの実行で、出力と状態が1世代分だけになる。
- 途中で失敗した世代を再実行すると引き継いで完了し、完了した世代は`force`がなければ処理し直さない。
- ADR-0013の未検証の点について、確かめた結果か、未検証のまま残した理由を記録している。

## Phase 7: IaCの整理

PortalやADF Studioで手動作成した設定を、できる範囲でTerraformかGit管理の定義へ戻し、主要インフラをTerraformから再構築できることを確かめる。Functionコードの発行は、Terraformから分離してよい。

## サンプルデータ

| 目的 | ファイル |
|---|---|
| 正常な入力 | [`samples/valid/orders_v1.csv`](../samples/valid/orders_v1.csv) |
| 不正な入力 | [`samples/invalid/orders_invalid.csv`](../samples/invalid/orders_invalid.csv) |
| 列追加 | [`samples/schema-evolution/orders_v2.csv`](../samples/schema-evolution/orders_v2.csv) |
| 追加の列変更 | [`samples/schema-evolution/orders_v3.csv`](../samples/schema-evolution/orders_v3.csv) |
| 型推論の確認 | [`samples/schema-evolution/orders_drifted_types.csv`](../samples/schema-evolution/orders_drifted_types.csv) |
| 必須列の欠落 | [`samples/schema-evolution/orders_missing_required.csv`](../samples/schema-evolution/orders_missing_required.csv) |
| `amount`の型変更 | [`samples/schema-evolution/orders_amount_type_change.csv`](../samples/schema-evolution/orders_amount_type_change.csv) |

Schema Evolutionの比較では、新しい列を通す場合、無視する場合、Validation Errorにする場合を比べる。必須列の欠落と`amount`の型変更では、スキーマを検出することと、変更を受け入れることが別の判断であることを確かめる。
