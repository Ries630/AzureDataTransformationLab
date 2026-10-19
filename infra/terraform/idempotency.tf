locals {
  ingestion_state_table_name = "ingestionstate"
  idempotency_enabled        = var.data_factory_enabled && var.idempotency_enabled
}

# 入力の世代ごとの処理状態。PartitionKeyは相対パスのbase64url、RowKeyはETag（ADR-0013）。
resource "azurerm_storage_table" "ingestion_state" {
  count = local.idempotency_enabled ? 1 : 0

  name               = local.ingestion_state_table_name
  storage_account_id = azurerm_storage_account.lab.id
}

# ADFのMIは状態Tableだけを読み書きする。
resource "azurerm_role_assignment" "adf_ingestion_state" {
  count = local.idempotency_enabled ? 1 : 0

  scope                = "${azurerm_storage_account.lab.id}/tableServices/default/tables/${local.ingestion_state_table_name}"
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = azurerm_data_factory.lab[0].identity[0].principal_id
  principal_type       = "ServicePrincipal"

  depends_on = [azurerm_storage_table.ingestion_state]
}

# 状態を取得した世代を処理する子Pipeline。If・Switchを入れ子にできないため、
# 親のSwitchから呼び出す。並列の制御は親のconcurrencyに任せる。
resource "azurerm_data_factory_pipeline" "process_generation" {
  count = local.idempotency_enabled ? 1 : 0

  name            = "pl-csv-process-generation"
  data_factory_id = azurerm_data_factory.lab[0].id

  parameters = {
    relativeDir  = ""
    relativePath = ""
    fileName     = ""
    inputEtag    = ""
    partitionKey = ""
    # 親の実行ID。状態の所有者の確認と、Functionのログとの関連付けに使う。
    ownerRunId = ""
  }
  variables = {
    generationDir = ""
    publishStatus = "none"
    rowCounts     = ""
    finalStatus   = ""
  }

  activities_json = templatefile("${path.module}/adf/process_generation.activities.json", {
    storage_account_name = azurerm_storage_account.lab.name
    ir_name              = local.data_factory_ir_name
    state_table_name     = local.ingestion_state_table_name
  })

  depends_on = [
    azurerm_data_factory_linked_service_azure_function.validator,
    azurerm_data_factory_custom_dataset.binary,
    azurerm_data_factory_dataset_delimited_text.csv,
    azurerm_data_factory_data_flow.transform_orders,
    azurerm_data_factory_integration_runtime_azure.lab,
  ]
}
