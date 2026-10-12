# AWS pipeline Terraform root

AWS版のコードとリソースを配置する独立root。処理契約は[docs/aws-architecture.md](../../../docs/aws-architecture.md)、コード生成と運用は[docs/aws-implementation.md](../../../docs/aws-implementation.md)を参照する。会社での適用はAWS 4で実施する。

## 設定

Terraform 1.16以上2未満、AWS CLI、会社の認証と承認済みLambda ZIPが必要。Providerの版は`versions.tf`とlockに従う。WindowsとWSLを混在させず、認証・Terraform・AWS CLIを同じ環境で使う。

`terraform.tfvars.example`を`company.tfvars`へコピーし、次を会社で設定する。

| 変数 | 設定内容 |
|---|---|
| `expected_account_id` / `aws_region` | 許可されたアカウントとリージョン。Providerがアカウントを照合する |
| `name` / `bucket_name` | 会社の命名規則に適合する自分用の名前 |
| `create_bucket` | 専用bucketを新規作成するなら`true`、提供済みbucketを参照するなら`false` |
| `data_prefix` | 既存共有bucketでは専用namespaceが必須（例`adtl-ries/`）。新規bucketでは空文字も可 |
| `existing_bucket_eventbridge_enabled` | 既存bucketのEventBridge有効化を管理者が確認した場合だけ`true` |
| `lambda_zip_path` / `lambda_architecture` | 生成済みZIPのパスとCPU。既定はarm64 |
| `notification_email` | 会社で許可された購読先。未設定ならメール購読を作らない |
| 保持期間・各Timeout | 会社の保存規則、起動時間と予算に合わせる |

既存bucketではbucket設定、通知設定、保持期間、暗号化をこのrootから変更しない。EventBridgeが既に有効であること、配置先prefixへの権限と既存の暗号化方式へのアクセスを会社で確認する。新規bucketにはこのrootが保持設定を作る。共有基盤の提供条件を満たせない場合は、会社側での対応を依頼してから適用する。

会社のstate用S3 bucketを用意し、`backend.tf.example`を`backend.tf`へ、`backend.hcl.example`を`company.backend.hcl`へコピーして保存先を設定する。AWS用のstate keyをAzureや他者と共有しない。設定値、認証情報、state、保存済みplanは配布物やGitへ含めない。

## 検査とplan

会社の認証で実行主体を照合してから、root内で実行する。PowerShellとbashで同じ一行コマンドを使える。

```bash
aws sts get-caller-identity
terraform init -backend-config=company.backend.hcl
terraform validate
terraform plan -var-file=company.tfvars -out=company.tfplan
terraform show -no-color company.tfplan
```

`lambda_zip_path`はこのrootから辿れるパスにする。TerraformはGlueスクリプト、Lambda ZIP、ワークフローと関連リソースを配置する。planではIAMとPassRole、S3対象prefix、DynamoDB、Glue workerとTimeout、EventBridge、SQS DLQ、SNSとAlarm、保持期間を確認する。実権限・実サービス連携と費用は会社環境で確認する。

会社で生成したplanを確認し、承認を得てから同じplanを適用する。設定やコードを変えた場合はplanを作り直す。

```bash
terraform apply company.tfplan
terraform output
```

メール購読を設定した場合は、会社の通知先で確認リンクを操作する。実通知の送信とサンプル投入は別途会社で許可を確認する。投入・結果取得・再実行・ロック復旧は[運用手順](../../../docs/aws-implementation.md#サンプル投入と公開結果)に従う。

## 後片付け

会社で承認された保存対象を先に確保し、共有bucketを参照している場合は自分のprefixだけを扱う。新規bucketの`force_destroy`は無効なので、データを残したままbucketを削除できない。残すデータと自分用データの削除範囲を確認した後、削除planを作り、承認後に適用する。state用bucketはこのrootの作成対象ではない。

```bash
terraform plan -destroy -var-file=company.tfvars -out=destroy.tfplan
terraform show -no-color destroy.tfplan
terraform apply destroy.tfplan
```
