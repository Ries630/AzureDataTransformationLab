mock_provider "azurerm" {}

variables {
  subscription_id      = "00000000-0000-0000-0000-000000000001"
  resource_group_name  = "rg-adtl-state-test"
  storage_account_name = "adtlstatetest"
}

run "reject_personal_data" {
  command = plan

  override_data {
    target = data.azurerm_subscription.current
    values = { display_name = "Personal-Data" }
  }

  expect_failures = [azurerm_resource_group.state]
}

run "protect_state_without_shared_keys" {
  command = plan

  override_data {
    target = data.azurerm_subscription.current
    values = { display_name = "Personal-Sandbox" }
  }

  assert {
    condition     = !azurerm_storage_account.state.shared_access_key_enabled && !azurerm_storage_account.state.allow_nested_items_to_be_public && azurerm_storage_container.state.container_access_type == "private"
    error_message = "stateへのアクセスはEntra認証に限定してください。"
  }

  assert {
    condition     = !azurerm_storage_account.state.is_hns_enabled && azurerm_storage_account.state.account_replication_type == "LRS" && azurerm_storage_account.state.blob_properties[0].versioning_enabled && azurerm_storage_account.state.blob_properties[0].delete_retention_policy[0].days > 0 && azurerm_storage_account.state.blob_properties[0].container_delete_retention_policy[0].days > 0
    error_message = "低コストのstate保存先にバージョニングと削除からの復旧を備えてください。"
  }

  assert {
    condition     = azurerm_management_lock.state.lock_level == "CanNotDelete"
    error_message = "state Storageの削除ロックを維持してください。"
  }
}
