provider "azurerm" {
  features {}

  # 必須変数で指定し、Azure CLIの既定Subscriptionへのフォールバックを防ぐ。
  subscription_id = var.subscription_id

  # 登録はplanレビュー手順で承認後に実施し、plan時にAzureを変更しない。
  resource_provider_registrations = "none"
  resource_providers_to_register  = []
  storage_use_azuread             = true
}

data "azurerm_subscription" "current" {
  subscription_id = var.subscription_id
}

data "azurerm_client_config" "current" {}
