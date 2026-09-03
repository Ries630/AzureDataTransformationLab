# Azure APIだけを置き換え、誤ったSubscriptionでplanが失敗することを確認する。
mock_provider "azurerm" {}

variables {
  subscription_id      = "00000000-0000-0000-0000-000000000001"
  resource_group_name  = "rg-adtl-test"
  storage_account_name = "adtlteststorage"
}

run "reject_personal_data" {
  command = plan

  override_data {
    target = data.azurerm_subscription.current
    values = {
      display_name = "Personal-Data"
    }
  }

  expect_failures = [azurerm_resource_group.lab]
}

run "accept_personal_sandbox" {
  command = plan

  override_data {
    target = data.azurerm_subscription.current
    values = {
      display_name = "Personal-Sandbox"
    }
  }
}
