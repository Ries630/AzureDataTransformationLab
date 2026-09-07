# ADR-0006: CIのFunctions設定読取権限をApp単体へ限定する

- ステータス: 提案（Azure権限適用・実検証待ち）
- 日付: 2026-09-07
- 関連: [Issue #16](https://github.com/Ries630/AzureDataTransformationLab/issues/16)、[ADR-0003](0003-use-scoped-oidc-for-pr-plans.md)

## 背景

AzureRM Provider 5.3.0のFunction App refreshは、アプリ本体に加え、Application Settings、Connection Strings、Publishing Credentials、認証設定を取得する。通常のReaderには設定のlist操作が含まれず、既存のCI権限だけではrefreshできない。一方、このlist操作は秘密を含む設定も取得できるため、付与範囲と実行コードの承認が重要になる。

## 決定

Functionの設定を取得する専用custom roleを用意し、割り当て先を対象Function App単体に限定する。追加権限の作成は明示的に有効化する。具体的なAction・scope・有効化条件の正は[CI用Terraform](../../infra/ci-plan/main.tf)、適用と再開手順は[planレビュー手順](../terraform-plan-review.md#functionsをrefresh対象へ追加する)に置く。

Function側ではSCM Basic認証による発行を無効にし、Core ToolsのBearer認証によるOneDeployを使う。CIが設定取得に伴って発行資格情報を受け取っても、それをBasic認証で使用する発行経路を開かないためである。

Azureへの権限付与と、付与後の実refreshは未実施である。対象を提示して承認後に確認する。

## 検討した代替

Resource GroupまたはSubscriptionへのContributor付与は、構成の作成・変更・削除まで許可するため採用しない。設定取得のActionをResource Groupへ割り当てる案も、同じRG内の他のAppの秘密まで読み取り対象になるため採用しない。

host/deployment StorageへのBlob Data Reader追加は、固定したProviderのStorage Container ReadがResource Manager経路を使い、既存のRG Readerで取得できるため採用しない。将来のProvider変更で必要になった場合は、その時点の呼び出し経路から再評価する。

## 受け入れた代償

App単体に限定しても、CIは秘密を含む設定を取得し得る。Terraformのsensitive指定やレポートのマスキングはAzure APIの認可範囲を狭めない。既存のEnvironmentによる実行コードの承認と、plan・state・ログの公開境界を維持する。

Basic認証を前提とする発行ツールは使用できなくなる。現行Core ToolsのソースでBearer認証を確認しているが、Azure上の発行成功とRBAC反映は初回適用後に検証する。

## 再評価の条件

- AzureRMのFunction設定取得APIやStorage Containerの読取経路が変わった場合
- 対象Appの分割・統合により、CIが必要とする取得範囲が変わった場合
- Core ToolsのOneDeployでBearer認証が使えなくなった場合

## 根拠

- [AzureRM 5.3.0のFunction App実装](https://github.com/hashicorp/terraform-provider-azurerm/blob/v5.3.0/internal/services/appservice/function_app_flex_consumption_resource.go)
- [AzureRM 5.3.0のStorage Container実装](https://github.com/hashicorp/terraform-provider-azurerm/blob/v5.3.0/internal/services/storage/storage_container_resource.go)
- [Azure Functionsのデプロイ方式](https://learn.microsoft.com/en-us/azure/azure-functions/functions-deployment-technologies)
- [Core Toolsの発行処理](https://github.com/Azure/azure-functions-core-tools/blob/main/src/Cli/func/Actions/AzureActions/PublishFunctionAppAction.cs)
