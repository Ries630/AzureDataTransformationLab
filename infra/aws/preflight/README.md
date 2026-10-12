# AWS 0 確認キット（会社学習環境の初回確認）

このディレクトリは、会社のAWS学習環境で**リソースを何も作らずに**次を確認するためのTerraform構成です。

- ツールの版（Terraform・AWS CLI）と会社PCのOS・CPU
- 実行主体（ロールまたはユーザー）と対象アカウント
- AWS版で予定している操作の権限シミュレーション
- Terraform AWS Provider の取得可否

`resource` ブロックを含まないため、`terraform plan` は読み取り専用のデータ取得だけを行います。**`terraform apply` は実行しないでください**（実行しても作成されるものはありませんが、このキットの用途は確認だけです）。

## 前提

- Terraform 1.16以上（`terraform version` で確認）
- AWS CLI v2（`aws --version` で確認）
- 会社で用意された認証で対象アカウントへログイン済み（SSOなら `aws sso login` など、会社の手順に従う）

手順はPowerShellを基準に書いています。WSL上で実行しても構いません。ただしTerraform・AWS CLI・会社の認証設定（プロファイル・SSOキャッシュ）が同じ環境（PowerShell側かWSL側か）に揃っている方で実行してください。WSLで実行した場合、`terraform version` のOS表示は `linux_amd64` または `linux_arm64` になります。

## 手順

すべてPowerShellで、このディレクトリに移動してから実行します。持ち込み用ZIPでは展開した `aws0-preflight` フォルダー、リポジトリでは `infra/aws/preflight` です。

```powershell
cd aws0-preflight
```

### 1. ツールの版とOS・CPUを確認する

```powershell
terraform version
```

1行目の `Terraform vX.Y.Z` がTerraformの版、`on windows_amd64` などの末尾が会社PCのOS・CPUです。WSLで実行した場合は `linux_amd64` または `linux_arm64` と表示されます。

```powershell
aws --version
```

### 2. 実行主体を画面で確認する（共有しない）

```powershell
aws sts get-caller-identity --query Arn --output text
```

表示されたARNが、想定している学習用アカウント・ロールかどうか**画面で確認するだけ**にしてください。ARNにはアカウントIDが含まれるため、この出力は共有しないでください。

### 3. Provider取得を確認する

```powershell
terraform init
```

`Terraform has been successfully initialized!` と出れば、registry から Provider（hashicorp/aws ~> 6.62）を取得できています。失敗した場合はエラー文を記録してください（Provider mirror の持ち込みが必要と判断します）。

### 4. 読み取りと権限シミュレーションを実行する

```powershell
terraform plan
```

data source の読み取り（アカウント・リージョン・実行主体）と、IAMの権限シミュレーションだけが実行されます。`Changes to Outputs:` に確認結果が表示され、リソースの追加・変更・削除がなければ完了です。**apply は不要です。実行しないでください。**

## 共有してよい結果

次の出力は共有して構いません（アカウントIDは末尾4桁だけが表示されます）。

- `terraform version` の出力
- `aws --version` の出力
- `terraform plan` の `Changes to Outputs:` 部分
- エラーが出た場合はエラーメッセージ（アカウントIDやARNが含まれていれば伏せる）

共有してはいけないもの:

- `aws sts get-caller-identity` の出力（ARNにアカウントIDが含まれる）
- アクセスキー、シークレットキー、セッショントークンなどの認証情報

## よくある失敗と意味

| 状況 | 意味と次の行動 |
|---|---|
| `terraform init` で registry に接続できない | Provider mirror を持ち込む必要がある。エラー文を記録する |
| `terraform plan` で `iam:SimulatePrincipalPolicy` が拒否される | シミュレーション権限がない。権限確認は管理者への確認に切り替える |
| `inconclusive_actions` に項目がある | 対象ARN・条件が未指定のため判定不能。権限追加を依頼せず、実装後に具体的な対象と条件を照合する |
| `explicitly_denied_actions` に項目がある | 評価条件で明示的拒否がある。管理者に理由と利用可能な範囲を確認する |
| 認証エラー（`ExpiredToken`・`NoCredentialProviders` など） | 会社の認証手順（SSOログイン等）を確認してやり直す |

## 権限シミュレーションの限界

結果はあくまで目安です。AWSの IAM policy simulator の仕様上、次の点に注意してください。

- identity-basedポリシーとpermissions boundaryの評価結果を確認する。SCPなど会社の組織制約は管理者にも確認する。
- リソースベースのポリシー（S3バケットポリシー、KMSキーポリシーなど）は自動では考慮されない。allowed と出ても、実際にはリソース側のポリシーで拒否される場合がある。
- 条件キーやタグ条件のようにコンテキスト情報が必要な評価は、実際の呼び出しと結果が変わる場合がある。
- このキットは対象ARNを指定しない。特定のARNだけを許可する最小権限ポリシーでは、利用可能な操作も`implicitDeny`になる。`inconclusive_actions`は不足権限の一覧ではない。操作一覧も実装前の確認候補であり、Terraformの全API呼び出しを網羅した保証ではない。

最終確認は、会社で実際の `terraform plan`・適用を行うときになります。

参考: [SimulatePrincipalPolicy - AWS IAM API Reference](https://docs.aws.amazon.com/IAM/latest/APIReference/API_SimulatePrincipalPolicy.html)

## 後片付け

確認が終わったら、ローカルに生成されたファイルは消して構いません。

- `.terraform/`（ダウンロードしたProvider）
Provider版を再現するため、同梱の`.terraform.lock.hcl`は残してください。

state ファイルは作成されません（plan のみで apply していないため）。
