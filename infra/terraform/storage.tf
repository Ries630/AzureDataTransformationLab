resource "azurerm_storage_account" "lab" {
  name                     = var.storage_account_name
  resource_group_name      = azurerm_resource_group.lab.name
  location                 = azurerm_resource_group.lab.location
  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = "LRS"
  access_tier              = "Hot"
  is_hns_enabled           = true

  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  public_network_access_enabled   = true
  tags                            = var.tags
}

resource "azurerm_role_assignment" "operator_blob_data" {
  scope                = azurerm_storage_account.lab.id
  role_definition_name = "Storage Blob Data Contributor"
  # 入力のsensitive伝播だけで既存stateとの差分を作らない。公開時のID除去はreport.mjsが行う。
  principal_id   = nonsensitive(coalesce(var.operator_object_id, data.azurerm_client_config.current.object_id))
  principal_type = "User"
}

resource "azurerm_storage_data_lake_gen2_filesystem" "zones" {
  for_each = toset(["landing", "validated", "rejected", "output"])

  name               = each.value
  storage_account_id = azurerm_storage_account.lab.id

  # データ操作は権限付与後に開始する。Azure側の反映遅延は別途起こり得る。
  depends_on = [azurerm_role_assignment.operator_blob_data]
}
