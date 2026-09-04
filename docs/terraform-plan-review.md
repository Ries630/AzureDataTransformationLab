# Terraform planのPRレビュー

## 現在の実装範囲

[Issue #9](https://github.com/Ries630/AzureDataTransformationLab/issues/9)のworkflowは、GitHub OIDCで既存stateを参照してplanを作り、PRコメントへ公開する。Azure側のIdentity適用とEnvironmentの設定を済ませてから実行する。

stateのAzureRM backend化はsub-issue [#12](https://github.com/Ries630/AzureDataTransformationLab/issues/12)で管理する。[stateの共有と移行](terraform-state.md)を完了してから実planのworkflowを有効にする。

学習環境を破棄するときのworkflow休止、CI依存の切り離し、再開前の確認は[Phase 1の後片付け](learning-plan.md#7-後片付けする)を参照する。

## ローカルで表示を確認する

Node.js 24を使用する。依存パッケージの追加は不要であり、GitHub ActionsのコメントAPIとの接続も同じJavaScriptで扱える。

```bash
LAB_RENDERER_DIR="$(mktemp -d)"
node scripts/terraform/install-tfplan2md.mjs "$LAB_RENDERER_DIR"
export TFPLAN2MD_PATH="$LAB_RENDERER_DIR/tfplan2md"

TFPLAN2MD_PATH="$TFPLAN2MD_PATH" node --test scripts/terraform/*.test.mjs
```

バージョンと公式配布物のSHA-256の正は[`tfplan2md.json`](../scripts/terraform/tfplan2md.json)とする。Linux x64とmacOS arm64を検証対象にする。インストーラーは取得したアーカイブのチェックサムが一致した場合だけ展開する。

既存の保存済みplanからレポートを作る場合は、[Phase 1の手順](learning-plan.md#phase-1-storage)で設定した`ARM_SUBSCRIPTION_ID`を使用する。

```bash
terraform -chdir=infra/terraform show -json phase1.tfplan \
  > infra/terraform/phase1.tfplan.json
node scripts/terraform/report.mjs \
  infra/terraform/phase1.tfplan.json \
  infra/terraform/phase1.tfplan.md
```

saved planを正とし、JSONとMarkdownは派生データとして扱う。作成済みの古いplanを現在の状態として再利用せず、実行日時と対象コミットを確認する。

## 公開境界

[`report.mjs`](../scripts/terraform/report.mjs)は元のplanでSubscriptionの一致、取得した名前、別Subscriptionへの参照、planの完了状態、操作種別を検証する。その後に表示専用コピーを作り、Terraformのsensitive情報で指定された値を除去し、UUIDを同じ入力に対して同じ架空UUIDへ置換する。

Providerの対象照合も同スクリプトで行う。[Terraformのplan JSON](https://developer.hashicorp.com/terraform/internals/json-format#expression-representation)にある`references`は式の依存先であり、評価結果ではない。変数を使うProviderでは、同じProviderに結び付いた`azurerm_client_config`の取得結果が必要になる。取得がapplyまで遅延するなど、対象を確定できないplanは公開しない。

`tfplan2md`はこのコピーだけを読み、GitHub向けに詳細を折りたたんだMarkdownを生成する。生成後も元の機密文字列とUUIDが残っていないか検査する。変換失敗、検証失敗、コメント上限超過の場合は出力を公開しない。診断に元データを転記しない。

この処理はSubscriptionの実在確認、Azureの認可、PRの信頼判定を代替しない。認証後の対象照合と、下記のEnvironmentによる承認を組み合わせる。

[`comment.mjs`](../scripts/terraform/comment.mjs)は専用マーカーで始まる`github-actions[bot]`のコメントだけを更新する。人の同名コメント、fork、終了済みPR、古いPR headは対象にしない。workflowは同じPRの実行を直列化し、同時作成を防ぐ。

## CIと操作ユーザーの分離

CIのIdentityを使ってplanしても、既存のユーザー向けRole Assignmentの対象は変えない。CIでは`TF_VAR_operator_object_id`に操作ユーザーのObject IDを明示する。ローカルで省略した場合は従来どおり実行ユーザーを使う。変数の定義は[`variables.tf`](../infra/terraform/variables.tf)を参照する。Resource属性へ渡す際は入力のsensitive表示フラグを除き、フラグの差だけで既存Role Assignmentを更新しない。実環境IDの公開防止は前述の公開境界で扱うため、Terraformの生ログを公開しない。

## OIDCの準備と適用

CI用Identityの定義は[`infra/ci-plan/`](../infra/ci-plan/)、信頼境界の理由は[ADR-0003](adr/0003-use-scoped-oidc-for-pr-plans.md)を参照する。state保存先とは別rootで管理し、既存の操作ユーザーの権限を変更しない。

1. [Phase 1の入力手順](learning-plan.md#2-ローカルの入力を用意する)でSubscriptionとユーザー認証を確認する。
2. `infra/ci-plan/terraform.tfvars.example`をローカルの`terraform.tfvars`へコピーし、作成済みの学習用・state用Resource GroupとStorageを指定する。Subscription IDは`TF_VAR_subscription_id`で渡す。
3. `gh api repos/Ries630/AzureDataTransformationLab/actions/oidc/customization/sub`の`sub_claim_prefix`を`oidc_subject_prefix`へ指定する。新形式は名前に不変IDを含むため、名前だけのsubjectを推測して作らない。
4. 下記のplanを提示し、承認を得てからMicrosoft.ManagedIdentityの登録と適用を行う。登録は`az provider show`で未登録を確認した場合だけ、対象Subscriptionを明示して実行する。

```bash
terraform -chdir=infra/ci-plan init -input=false -lockfile=readonly
terraform -chdir=infra/ci-plan plan -input=false -out=ci-bootstrap.tfplan
terraform -chdir=infra/ci-plan show -json ci-bootstrap.tfplan \
  > infra/ci-plan/ci-bootstrap.tfplan.json
node scripts/terraform/report.mjs \
  infra/ci-plan/ci-bootstrap.tfplan.json infra/ci-plan/ci-bootstrap.tfplan.md
```

承認後の登録コマンドは`az provider register --subscription "$ARM_SUBSCRIPTION_ID" --namespace Microsoft.ManagedIdentity`、適用は`terraform -chdir=infra/ci-plan apply ci-bootstrap.tfplan`とする。Providerの登録完了を確認してから適用する。CI用rootのlocal stateは[stateの保管・復旧手順](terraform-state.md)を適用し、`infra/ci-plan/.state-backups/`へ退避する。

権限の正は[`infra/ci-plan/main.tf`](../infra/ci-plan/main.tf)である。学習用Resource GroupとStorageには読み取り、state Storageには構成確認、state containerにはleaseを取得するための権限を付ける。Subscription全体には名前確認用の一つの操作だけを許可する。stateの書き換えが可能になるため、Environmentで実行コードを承認する境界を省かない。

## GitHub Environment

`terraform-plan` Environmentは所有者をrequired reviewerとし、管理者の承認バイパスを無効にする。個人リポジトリのため自分の実行への承認は許可する。Azure側のFederated Identity Credentialも同名Environmentに限定する。設定完了前に実plan jobを承認しない。

以下の値をEnvironment Secretsに保存する。含むのは環境IDと設定であり、Client Secret、Access Key、SASは作成・保存しない。Secretsを使う理由はActionsの入力表示から環境IDを隠すためである。

| 名前 | 値の取得元 |
|---|---|
| `AZURE_CLIENT_ID` | `infra/ci-plan`の`github_identity.client_id` |
| `AZURE_TENANT_ID` | 同`tenant_id` |
| `AZURE_SUBSCRIPTION_ID` | 同`subscription_id` |
| `TERRAFORM_BACKEND_CONFIG` | 移行済み`infra/terraform/backend.local.json`のJSON |
| `TERRAFORM_INPUTS` | 学習用rootの入力JSON。`subscription_id`、`operator_object_id`、Resource Group名、Storage名を必ず含む |

入力値はローカルのstateと設定から照合し、シェル引数や公開ログへ出さず`gh secret set --env terraform-plan`の標準入力へ渡す。CI用IdentityのObject IDを`operator_object_id`へ設定してはいけない。

## PRでの動作と確認

実行条件とjob権限の正は[`terraform-plan.yml`](../.github/workflows/terraform-plan.yml)とする。Azure認証前にも[`plan.mjs`](../scripts/terraform/plan.mjs)がPRコンテキストを検査する。fork、所有者以外が作成・実行したPR、異なるイベント・headは対象外である。

Environment承認後、既存remote stateの取得、構成検証、saved planの生成、公開用Markdownへの変換を行う。plan jobは生ログを公開せず、saved planとJSONを残さない。別のpublish jobが保持1日の公開用Markdownだけを受け取り、同じPRコメントを更新する。PRごとに実行を直列化し、古いheadの結果は投稿しない。apply jobは設けない。

初回接続時は、実planの生成と専用コメント1件の作成、同じPRの追加commit後のコメント更新、実環境IDがログ・artifact・コメントへ出ていないことを確認する。Environmentの承認待ちはplan失敗とは区別する。Azure認証、state取得、検証、rendererのいずれかが失敗した場合はコメントを投稿せず、公開ログに出していない診断を必要に応じてローカルで再現する。
