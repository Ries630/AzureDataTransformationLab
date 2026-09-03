# Terraform stateの共有と移行

この手順は、作成済みの学習用リソースをlocal backendからAzureRM backendへ移すためのものである。実リソースの作り直しは行わない。設計理由は[ADR-0002](adr/0002-share-state-in-dedicated-storage.md)を参照する。

保存先を作るrootは[`infra/state-backend/`](../infra/state-backend/)、移行対象は[`infra/terraform/`](../infra/terraform/)である。以降はリポジトリルートから実行する。Azure CLI、Terraform、Node.js 24、jqを使用する。

## 1. 保存先の作成を計画する

```bash
umask 077
export ARM_SUBSCRIPTION_ID="$(az account show --subscription Personal-Sandbox --query id -o tsv)"
export TF_VAR_subscription_id="${ARM_SUBSCRIPTION_ID:?}"

cp -n infra/state-backend/terraform.tfvars.example infra/state-backend/terraform.tfvars
```

例示ファイルを編集し、既存の学習用Resource Groupとは異なる新規名と、Azure全体で一意なStorage Account名を指定する。`az group exists`と`az storage account check-name`で未使用を確認する。どちらも`--subscription "$ARM_SUBSCRIPTION_ID"`を明示する。

このrootは操作ユーザーへのRole Assignmentを作るため、[Phase 1のローカル入力手順](learning-plan.md#2-ローカルの入力を用意する)にある認証種別の確認も行う。

Provider登録は[Phase 1の手順](learning-plan.md#3-microsoftstorageだけを登録する)に従う。Role Assignmentと削除ロックはMicrosoft.Authorizationを使うが、こちらは`RegistrationFree`であり登録操作を要しない。`az provider show --subscription "$ARM_SUBSCRIPTION_ID" --namespace Microsoft.Authorization --query '{policy:registrationPolicy,state:registrationState}'`で前提を確認する。

```bash
terraform -chdir=infra/state-backend init -input=false -lockfile=readonly
terraform -chdir=infra/state-backend fmt -check -recursive
terraform -chdir=infra/state-backend validate
terraform -chdir=infra/state-backend test
terraform -chdir=infra/state-backend plan -input=false -out=bootstrap.tfplan
terraform -chdir=infra/state-backend show -json bootstrap.tfplan \
  > infra/state-backend/bootstrap.tfplan.json
```

初回はResource Group、Storage Account、container、操作ユーザーのRole Assignment、Storageの削除ロックを追加する。実際のplanで、Personal-Sandboxの新設先だけを対象にしていることを照合する。保護設定と権限範囲の正は[`main.tf`](../infra/state-backend/main.tf)とする。

planと費用、後片付け方法を提示し、**明示的な承認後だけ**適用する。

```bash
terraform -chdir=infra/state-backend apply bootstrap.tfplan
```

保存先の構成は、バージョニングとsoft deleteが保持する履歴容量にも従量料金がかかる。[Blob料金](https://azure.microsoft.com/pricing/details/storage/blobs/)から、使用リージョン、保存容量、操作回数を指定して見積もる。State用Storageは学習リソース破棄後も残す。

## 2. 認証と保護を確認する

作成したStorageの実値をCLIの照合に使う。Subscription IDを含む設定は公開しない。

```bash
terraform -chdir=infra/state-backend output -json backend_config \
  > infra/terraform/backend.local.json
```

Azure CLIで、Storageの構成、Blobサービスの保護設定、削除ロック、操作ユーザーのcontainer限定ロールをTerraform定義と照合する。RBACが反映されるまで移行を始めない。403をShared KeyやSASへの切り替えで回避しない。

bootstrap root自身のstateも機密バックアップとして保管する。適用後の`infra/state-backend/terraform.tfstate`を`infra/state-backend/.state-backups/bootstrap-<日時>/terraform.tfstate`へ複製し、端末の紛失・故障にも備えた非公開の保管先へ退避する。ディレクトリは0700、ファイルは0600とし、元ファイルとのハッシュ一致を確認する。学習用stateの退避先`infra/terraform/.state-backups/`とは分ける。バックアップの内容をIssue、PR、Actions artifactへ載せない。

## 3. 移行前のstateを退避する

移行中は学習用rootに対するplan/applyを止める。既存の`terraform.tfstate`とlocal backendの初期化キャッシュを残したまま実行する。`terraform init -reconfigure`を先に実行すると移行元の情報を失うため、移行前には実行しない。

```bash
node scripts/terraform/backend.mjs prepare-migration
```

このコマンドは対象Subscription、専用Storageの認証・復旧設定と削除ロック、containerの非公開設定を実照合し、保存先Blobが存在しないこと、有効な既存local stateがあることを確認する。その後に機密バックアップと初期化用の`remote.backend.hcl`を作る。表示される退避先に元stateが保存されたことを確認する。Azureへの書き込みやstateの転送は行わない。

すでにremote stateが存在する場合は停止する。以前の移行が途中で止まった場合も、remote側と退避元を調べ、どちらが正か確認するまで上書きしない。

## 4. 承認されたstate移行を実行する

保存先の作成承認とは別に、退避元と保存先を示してstateの移行承認を得る。一括で承認を得た場合は、承認済みの同じ組み合わせに対する再確認は不要である。

```bash
terraform -chdir=infra/terraform init -migrate-state -lockfile=readonly \
  -backend-config=remote.backend.hcl
```

Terraformが示すコピー元とコピー先を確認し、想定どおりの移行確認にだけ応答する。`-force-copy`は使わない。既存remote stateの上書きを求められたら停止し、準備時から保存先が変わっていないか確認する。

```bash
node scripts/terraform/backend.mjs verify-migration
terraform -chdir=infra/terraform plan -input=false -detailed-exitcode
```

照合コマンドは、backendキャッシュの保存先と認証方式、退避したバックアップ実体、移行前後のlineage・serial・属性・outputsを確認する。再planの終了コード0で、実リソースへの意図しない差分がないことを確認する。失敗した場合はlocal/remote stateを削除せず停止する。

Azure CLIの`az storage blob show --auth-mode login`でも保存されたBlobのサイズとlease状態を確認する。ロック確認は、承認済みの検証として同じBlobへ短いleaseを取得し、その間の`terraform plan -lock-timeout=1s`がロック取得で失敗することを確認した後、leaseを解放して再planする。`force-unlock`で稼働中の処理のロックを解除しない。

## 5. 移行後のローカル・CIの初期化

新しいcheckoutには`backend.local.json`を非公開経路で用意し、`ARM_SUBSCRIPTION_ID`を指定する。ローカルではAzure CLIのユーザー認証を使う。CIのIdentityとOIDCは[Issue #9](https://github.com/Ries630/AzureDataTransformationLab/issues/9)で接続する。

```bash
node scripts/terraform/backend.mjs init
```

このコマンドはremote Blobと有効な既存stateを確認する。未作成、空、不正、権限不足の場合は停止し、local backendへ戻したり空stateからplanしたりしない。各環境から既存の同じstateを使うための初期化コマンドであり、新しい学習環境の空stateを作る用途には使わない。

認証は[AzureRM backendの仕様](https://developer.hashicorp.com/terraform/language/backend/azurerm)に従う。保存先構成の検査を行うため、このコマンドの実行者にはstate Storageの管理面の読み取り権限も必要となる。state lockingを無効化する`-lock=false`は使わない。GitHub ActionsのconcurrencyはBlob leaseによるロックの代わりにはならない。

## 復旧と後片付け

bootstrap rootのlocal stateを復元する場合は、このrootへの操作を止め、残っているstateとキャッシュを別名で退避する。バックアップのlineage、serial、対象Subscriptionとリソースを照合し、復元対象を確定してから`infra/state-backend/terraform.tfstate`へ戻す。機密ファイルの権限を維持し、`terraform -chdir=infra/state-backend init -input=false -lockfile=readonly`の後に`terraform -chdir=infra/state-backend plan -input=false -detailed-exitcode`で終了コード0を確認する。差分が出た場合はapplyせず、バックアップの世代と実環境を再確認する。

- 移行に失敗したら、退避stateを保持したままlocal/remoteとbackendキャッシュを照合する。どちらが正か判断せずに`state push`や強制コピーを実行しない。
- 過去のBlobバージョンへ戻す場合は、処理を止め、現行stateを退避してから対象バージョンとserialを確認し、復旧の承認を得る。
- 学習用rootのdestroyは保存先rootを削除しない。学習リソースを全て破棄した後も、空になったstateと過去バージョンを保存先に保持する。
- 保存先自体を廃止するときは、全stateと必要な履歴の退避、残る利用者の確認、削除承認を先に行う。削除ロックの解除と`prevent_destroy`の変更はその別作業で扱う。
