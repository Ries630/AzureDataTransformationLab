# Data Factory無効時にADFリソースを作らないこと、有効時のTrigger絞り込みと
# RBAC scopeを検証する。Azure APIはmockに置き換える。
mock_provider "azurerm" {
  override_during = plan

  mock_resource "azurerm_storage_account" {
    defaults = {
      id                   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.Storage/storageAccounts/mockstorage"
      primary_dfs_endpoint = "https://mockstorage.dfs.core.windows.net/"
    }
  }

  mock_resource "azurerm_data_factory" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.DataFactory/factories/mock-adf"
    }
  }

  mock_data "azurerm_function_app_host_keys" {
    defaults = {
      default_function_key = "mock-function-key"
    }
  }
}

variables {
  subscription_id      = "00000000-0000-0000-0000-000000000001"
  resource_group_name  = "rg-adtl-test"
  storage_account_name = "adtlteststorage"
}

run "data_factory_disabled_by_default" {
  command = plan

  # phase3.auto.tfvarsがdata_factory_enabled=trueを設定するため、
  # このrunでは明示的に無効を指定する。
  variables {
    data_factory_enabled = false
  }

  override_data {
    target = data.azurerm_subscription.current
    values = {
      display_name = "Personal-Sandbox"
    }
  }

  assert {
    condition     = length(azurerm_data_factory.lab) == 0 && length(azurerm_data_factory_pipeline.csv_ingestion) == 0 && length(azurerm_data_factory_trigger_blob_event.landing_csv) == 0 && length(azurerm_data_factory_data_flow.transform_orders) == 0 && length(azurerm_data_factory_integration_runtime_azure.lab) == 0
    error_message = "Data Factory無効時にFactory・Pipeline・Trigger・Data Flow・IRを作成してはいけません。"
  }

  assert {
    condition     = length(azurerm_data_factory_linked_service_azure_function.validator) == 0 && length(data.azurerm_function_app_host_keys.validator) == 0
    error_message = "Data Factory無効時にFunctionキーを読み取ってはいけません。"
  }
}

run "data_factory_adds_scoped_pipeline" {
  command = plan

  variables {
    functions_enabled    = true
    data_factory_enabled = true
  }

  override_resource {
    target          = azurerm_storage_account.lab
    override_during = plan
    values = {
      id                   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.Storage/storageAccounts/adtlteststorage"
      primary_dfs_endpoint = "https://adtlteststorage.dfs.core.windows.net/"
    }
  }

  override_data {
    target = data.azurerm_subscription.current
    values = {
      display_name = "Personal-Sandbox"
    }
  }

  assert {
    condition     = azurerm_data_factory_trigger_blob_event.landing_csv[0].blob_path_begins_with == "/landing/blobs/" && azurerm_data_factory_trigger_blob_event.landing_csv[0].blob_path_ends_with == ".csv" && azurerm_data_factory_trigger_blob_event.landing_csv[0].events == toset(["Microsoft.Storage.BlobCreated"])
    error_message = "Triggerはlandingの.csv作成だけを対象にしなければなりません。"
  }

  assert {
    condition     = azurerm_role_assignment.adf_landing_blob_reader[0].scope == "${azurerm_storage_account.lab.id}/blobServices/default/containers/landing" && azurerm_role_assignment.adf_landing_blob_reader[0].role_definition_name == "Storage Blob Data Reader"
    error_message = "ADFのMIにはlandingコンテナーの読み取りだけを付与しなければなりません。"
  }

  assert {
    condition     = alltrue([for zone, ra in azurerm_role_assignment.adf_zone_blob_contributor : ra.scope == "${azurerm_storage_account.lab.id}/blobServices/default/containers/${zone}" && ra.role_definition_name == "Storage Blob Data Contributor"]) && toset(keys(azurerm_role_assignment.adf_zone_blob_contributor)) == toset(["validated", "rejected", "output"])
    error_message = "ADFのMIにはvalidated・rejected・outputだけへのBlob Data Contributorを付与しなければなりません。"
  }

  assert {
    condition     = azurerm_data_factory_integration_runtime_azure.lab[0].location == "japaneast" && azurerm_data_factory_integration_runtime_azure.lab[0].compute_type == "General" && azurerm_data_factory_integration_runtime_azure.lab[0].core_count == 8 && azurerm_data_factory_integration_runtime_azure.lab[0].time_to_live_min == 0
    error_message = "Data Flow用IRはjapaneast・General最小構成・TTL 0で固定しなければなりません。"
  }

  assert {
    condition     = azurerm_data_factory_pipeline.csv_ingestion[0].concurrency == 1
    error_message = "Pipelineの同時実行数は1に固定しなければなりません。"
  }

  assert {
    # keyはplan時点でunknownになるため、Functionの接続先URLで検証する。
    condition     = azurerm_data_factory_linked_service_azure_function.validator[0].url == "https://func-adtlteststorage.azurewebsites.net"
    error_message = "Function Linked Serviceは検証Function AppのURLを指さなければなりません。"
  }
}
