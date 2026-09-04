# ADR-0003: PRのplanを専用Identityと承認付きEnvironmentで実行する

- ステータス: 承認済み
- 日付: 2026-09-04
- 関連: [Issue #9](https://github.com/Ries630/AzureDataTransformationLab/issues/9)

## 背景

PRのTerraformは外部プログラムも実行でき、stateには機密属性が含まれる。Azureへ書き込めないIdentityでも、任意のPRコードへstateを渡してよいことにはならない。既存の操作ユーザーの資格情報をCIへ持ち込まず、実行コードの信頼確認とAzureの権限を分ける必要がある。

## 決定

専用のUser Assigned Managed IdentityをAzureRMで管理し、GitHubの対象リポジトリとEnvironmentに一致するOIDC subjectだけを信頼する。既存の操作ユーザー向けRole Assignmentとは別rootに置く。

個人リポジトリの所有者による同一リポジトリ内のPRだけを対象とし、Azure認証jobにはEnvironmentの承認を要求する。planとコメント公開を別jobにし、後者にはAzure認証を渡さない。設定と権限の正は[planレビュー手順](../terraform-plan-review.md)および参照先のTerraform・workflowとする。

## 検討した代替

Entraアプリ登録でもFederationを構成できるが、本件はAzure内の既存リソースの読み取りであり、既存AzureRM Providerで管理できるManaged Identityを選んだ。Client SecretはIssueの前提により採用しない。

Subscription全体へのReader付与より、Subscriptionの名前確認だけを許可するcustom roleと、対象Resource Group・Storageの権限を分ける。state lockingにはstate containerへの書き込み権限が必要であり、stateを改変できる制約は残る。

## 受け入れた代償

Microsoft.ManagedIdentityの登録と、Environmentによる実行ごとの承認が必要になる。fork、bot、所有者以外のPRはこの実planの対象外となり、認証不要の既存CIで検証する。Identity用rootのstateも機密バックアップを要する。

根拠: [GitHub OIDCとAzure](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure)、[AzureRM backendの権限](https://developer.hashicorp.com/terraform/language/backend/azurerm)。
