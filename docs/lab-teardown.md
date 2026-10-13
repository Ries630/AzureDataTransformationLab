# 学習環境の後片付けと再構築

この手順は、学習用のAzureリソースが不要になったときに学習用root（[`infra/terraform/`](../infra/terraform/)）を削除し、必要になったら再構築するためのものである。Phaseを終えるたびに行う作業ではない。削除すると、次のPhaseへ進む前に再構築が必要になる。

削除するもの、保持するもの、一時的に外すものは次のとおりである。

| 扱い | 対象 |
|---|---|
| 削除する | 学習用rootが管理するResource Group、Storage、その中のデータと、後続Phaseで追加したリソース |
| 保持する | stateの保存先と過去バージョン、空になった学習用state、CI Identity、Resource Providerの登録 |
| 一時的に外す | PR planのworkflow（`terraform-plan.yml`）、CIが学習用リソースを読むための権限とその専用ロール定義 |

stateの保存先の保護は[stateの後片付け規定](terraform-state.md#復旧と後片付け)に従う。

作業は次の順に進める。削除の承認を受けるまでは、Azureのリソースを削除しない。

1. [CIを休止する](#1-ciを休止する)
2. [削除範囲を確定し、データを退避する](#2-削除範囲を確定しデータを退避する)
3. [CIの依存を切り離すplanを作る](#3-ciの依存を切り離すplanを作る)
4. [学習用rootの破棄planを作る](#4-学習用rootの破棄planを作る)
5. [削除の承認を受ける](#5-削除の承認を受ける)
6. [承認されたplanを適用し、削除を確かめる](#6-承認されたplanを適用し削除を確かめる)

途中でやめる場合は[中止時の復旧](#中止時の復旧)、削除後に作り直す場合は[再構築](#再構築)へ進む。

## 1. CIを休止する

まず、対象のSubscriptionと入力を、学習計画の[ローカル入力の手順](learning-plan.md#2-ローカルの入力を用意する)で確認する。

CIを接続済みの場合は、承認を受けて、Azureへ接続するPR planのworkflowを休止する。認証を使わない`terraform.yml`は止めない。

```bash
gh workflow disable terraform-plan.yml --repo Ries630/AzureDataTransformationLab
gh api repos/Ries630/AzureDataTransformationLab/actions/workflows/terraform-plan.yml --jq .state
gh api --paginate 'repos/Ries630/AzureDataTransformationLab/actions/workflows/terraform-plan.yml/runs?per_page=100' \
  --jq '.workflow_runs[] | select(.status != "completed") | {id,status}'
```

2行目の出力が`disabled_manually`であることを確かめる。workflowを無効にしても、すでに始まった実行は止まらない。3行目の照会で未完了の実行が出た場合は、完了を待つか、中止の承認を受けたうえで、そのIDを`LAB_RUN_ID`に設定して中止する。

```bash
gh run cancel "${LAB_RUN_ID:?}" --repo Ries630/AzureDataTransformationLab
```

照会を繰り返し、未完了の実行が0件（出力なし）になるまで次へ進まない。ローカルで動かしているTerraformの処理も、終わっていることを確かめる。

休止した日時と確認結果は、作業IssueかPRに記録する。削除を終えた後は、再構築するまで休止を続ける。途中でやめる場合は[中止時の復旧](#中止時の復旧)へ進む。

## 2. 削除範囲を確定し、データを退避する

Resource Group内の現在のリソースと、全Filesystemのデータの一覧を取り、stateの管理対象と照合する。

サンプルCSVも削除されるうえ、stateだけからCSVは復元できない。そこで、次の3つを非公開の保管先へ退避し、元と内容が一致することを確かめる。

- 最新の学習用remote state
- CI用rootのlocal state
- Storage内のデータ

stateの保管方法と権限は[stateの保管手順](terraform-state.md#2-認証と保護を確認する)に従う。データも、Git管理外のディレクトリ（0700）とファイル（0600）で保管する。

**stateの管理対象にない追加データやリソースが見つかった場合は、ここで止まる。** Resource GroupやStorageを削除すると、中にあるデータやリソースも一緒に失われる。それらはTerraformのplanに個別には表示されないが、削除の影響範囲に入っている。退避や移動、または削除対象の確定をやり直し、改めて承認を得るまで適用しない。

## 3. CIの依存を切り離すplanを作る

この手順はCIを接続済みの場合だけ行う。CIを構築していなければ[4.](#4-学習用rootの破棄planを作る)へ進む。

[`infra/ci-plan/`](../infra/ci-plan/)は、CIが学習用のResource GroupとStorageを読むための権限を、学習用rootとは別のstateで管理している。学習用リソースを削除する前に、この権限を解除する。

解除は変数`lab_access_enabled`で切り替える。既定値は`true`である。この変数を導入する前のアドレスからの移行は、[`main.tf`](../infra/ci-plan/main.tf)の`moved`ブロックが扱う（[Terraformの説明](https://developer.hashicorp.com/terraform/language/modules/develop/refactoring#enable-count-or-for_each-for-a-resource)）。初めてこの切り替えを使うときは、まず`true`のままplanし、不要な再作成が出ないことを確かめる。

次に、Git管理外の`infra/ci-plan/cleanup.auto.tfvars`を次の内容で作る。ファイルが既にある場合は上書きせず、内容を確認する。

```hcl
lab_access_enabled = false
```

この値は、一度限りの`-var`ではなくファイルに保存し、削除後も残しておく。`-var`で渡しただけだと、次のplanで既定値の`true`に戻り、権限を作り直そうとしてしまうためである。CI用rootを別の端末で操作する場合も、同じ入力を非公開の経路で引き継ぐ。

```bash
terraform -chdir=infra/ci-plan plan -input=false -out=detach-lab.tfplan
terraform -chdir=infra/ci-plan show -no-color detach-lab.tfplan
```

削除対象が、学習用リソースの読み取り権限と、そのための専用ロール定義だけであることを確かめる。何が対象かの正は、[CIの権限構成](terraform-plan-review.md)と、そこから参照するTerraformのコードである。

CI Identity、OIDC、Subscription名を確認する権限、stateの読み取りとleaseの権限は保持する。これらにも変更が出た場合は止まる。

## 4. 学習用rootの破棄planを作る

```bash
terraform -chdir=infra/terraform plan -destroy -input=false -out=destroy.tfplan
terraform -chdir=infra/terraform show -no-color destroy.tfplan
```

CI用rootの解除planと学習用rootの破棄planを別々に確認し、どちらも対象が`Personal-Sandbox`に限られていることを照合する。

承認を求めるときは、初期構築時の件数（7件）と比べるだけで済ませず、現在の構成、データ、退避の結果を提示する。生のplanやstateは、公開のIssueやPRに貼らない。

## 5. 削除の承認を受ける

**ここで一度止まり、削除対象とデータが失われることについて明示的な承認を受ける。** 準備のための修正PRを承認・マージしたことは、削除の承認にはならない。

## 6. 承認されたplanを適用し、削除を確かめる

各planを適用する直前に、コード、入力、対応するstate、対象のリソースとデータが、承認したときから変わっていないことを確かめる。変わっていた場合は古いplanを適用せず、作り直して再び確認と承認を受ける。適用に失敗した場合も、stateを削除せずにplanを作り直す。

CIを接続済みの場合は、先にCI用rootの解除planを適用し、`lab_access_enabled = false`のまま再planして差分がないことを確かめる。

```bash
terraform -chdir=infra/ci-plan apply detach-lab.tfplan
terraform -chdir=infra/ci-plan plan -input=false -detailed-exitcode
```

CIの権限を解除した後も、学習用rootの破棄planが承認した内容と一致することを照合してから、学習用rootを破棄する。

```bash
terraform -chdir=infra/terraform apply destroy.tfplan
az group exists --subscription "${ARM_SUBSCRIPTION_ID:?}" --name "${LAB_RESOURCE_GROUP:?}"
set -o pipefail
terraform -chdir=infra/terraform state pull \
  | jq -e '[.resources[]? | select(.mode == "managed") | .instances[]?] | length == 0'
```

削除が終わったことを、次の結果で確かめる。

| 確認すること | 期待する結果 |
|---|---|
| Resource Group | `az group exists`が`false` |
| 学習用stateの管理対象 | 最後の照合が`true`で、終了コードが0 |
| CI用root | 再planが差分なし |
| 保持するもの | state、過去バージョン、保護設定、CI Identityが残っている |

stateの照合で`state list`の出力が空かどうかを見ないのは、data sourceも一覧に出るためである。代わりに`mode == "managed"`の実体の数を数える。

学習用rootの通常のplanは、削除後の確認には使えない。コードの定義は残っているので、通常のplanはすべてを作り直す予定を表示する。

完了の記録には、実施した時刻と確認結果を残す。

## 中止時の復旧

管理外のリソースが見つかった場合や、削除の承認を見送った場合は、後片付けを中止する。中止した理由と、それまでに適用した操作を記録する。復旧の間もworkflowは休止したままにし、保存してある`detach-lab.tfplan`と`destroy.tfplan`は以後適用しない。

その後の進め方は、学習用rootの削除を始めたかどうかで分かれる。

- **学習用rootの削除を始めていない場合**：Resource Group、Storage、Filesystem、データ、remote stateが残っていることを確かめ、下の[CIの復旧](#ciの復旧)へ進む。
- **学習用rootの削除を始めた場合、または現状を確認できない場合**：一部だけ削除された状態や、stateと実環境が食い違った状態になっている可能性がある。Resource Groupが存在することだけを根拠に再開しない。ここで本節の手順を終え、CIの権限の復旧とworkflowの再有効化も行わない。実リソース、データ、stateを照合し、復旧範囲の確認と承認を[再構築](#再構築)の作業として引き継ぐ。

### CIの復旧

この手順を行うのは、学習用rootの削除が始まっておらず、環境が残っていることを確認済みで、CIを接続済みの場合だけである。CIを構築していない場合は、中止の記録を残して終える。

`infra/ci-plan/cleanup.auto.tfvars`を作っていた場合は、`lab_access_enabled = true`に戻す。他の端末へ引き継いだ入力もそろえる。CIの権限解除をまだ適用していない場合も、次のplanが解除を予定しないよう、入力を確かめておく。

```bash
terraform -chdir=infra/ci-plan plan -input=false -out=reattach-lab.tfplan
terraform -chdir=infra/ci-plan show -no-color reattach-lab.tfplan
```

planの期待する内容は、権限解除を適用したかどうかで異なる。

- 解除を適用していない場合：変更なし
- 解除を適用した場合：[CIの権限構成](terraform-plan-review.md)のうち、失われた学習用の権限と専用ロール定義だけが作成対象

Identity、OIDC、stateへの権限などにも変更が出た場合は止まる。権限の再作成が必要な場合は、この復旧planを提示して別に承認を受ける。適用の直前にコード、入力、state、対象を再び照合してから適用し、CI用rootの再planで差分がないことを確かめる。

```bash
terraform -chdir=infra/ci-plan apply reattach-lab.tfplan
```

続けて、学習用rootの通常のplanが実環境のstateを参照できることを確かめる。差分が出た場合は理由を調べ、復旧のためだからといって自動で適用しない。

最後に、[PRでの動作と確認](terraform-plan-review.md#prでの動作と確認)に従ってCIの入力、権限、Environmentの設定を照合し、休止したworkflowを再開する承認を得てから有効にする。

```bash
gh workflow enable terraform-plan.yml --repo Ries630/AzureDataTransformationLab
gh api repos/Ries630/AzureDataTransformationLab/actions/workflows/terraform-plan.yml --jq .state
```

出力が`active`であることを確かめ、再開した日時を記録する。有効にしただけでは、PR planが成功するかどうかはわからない。次にworkflowの実行条件を満たすPRを更新したとき、Environmentの承認後にplanとPRへの公開コメントができることを確かめる。それまでは「workflow再有効化済み・実plan未確認」と記録しておく。

中止したことを理由に、権限の再作成やworkflowの再開を自動で行わない。どちらも上の確認と承認を経てから行う。

## 再構築

削除後に学習環境を作り直す作業は、後片付けとは別の承認作業として扱う。

通常の`backend.mjs init`は、管理対象が0件のstateを拒否する。このコマンドは、各環境から既存の同じstateを使うための初期化であり、空のstateからplanする用途を想定していないためである（[移行後の初期化](terraform-state.md#5-移行後のローカルciの初期化)）。再構築でもこの拒否を緩めたり、stateを削除したりはしない。

代わりに、削除を承認した時点で保持した空stateのファイル（ベースライン）を使う。任意に作った空stateで代用せず、承認済みの後片付けで保持したファイルのパスを`LAB_EMPTY_STATE_BASELINE`に設定する。

```bash
node scripts/terraform/backend.mjs prepare-rebuild infra/terraform "$LAB_EMPTY_STATE_BASELINE"
terraform -chdir=infra/terraform plan -var=functions_enabled=false -out=rebuild.tfplan
terraform -chdir=infra/terraform show -no-color rebuild.tfplan
```

`prepare-rebuild`は、保存先、保護設定、初期化済みのbackend、ベースラインのSubscriptionとstateの属性を照合するだけである。Azureへstateを転送したり、リソースを変更したりはしない。

この`rebuild.tfplan`で学習用Storageの作成内容と費用を確かめ、明示的な承認を受けてから適用する。適用後にサンプルCSVと4つのFilesystemを復元し、通常のplanで差分を確かめる。

Function基盤は、Storageを復元した後のstateからplanを作り直す。秘密の`phase2.auto.tfvars`に`functions_enabled = true`を保存してから、入力、権限、対象を照合する。`functions_enabled=true`を指定した事前のpreflight planは、ベースラインからの作成とFunctionの追加を一度に表示する参照用であり、Storage復元後の適用には使わない。Data Factory以降も、Function Appを適用した後に各Phaseの手順でplanを作る（[ADR-0010](adr/0010-require-function-applied-before-data-factory.md)）。

CIの読み取り権限の復旧とPR planのworkflowの再開は、Function基盤の再構築とは別の承認作業として扱う。
