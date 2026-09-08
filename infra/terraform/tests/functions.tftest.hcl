# Functions無効時は、Storage再構築用の既存リソースだけが対象であることを確認する。
# plan時にもmockのcomputed値を確定させ、RBAC scopeまで検証する。
mock_provider "azurerm" {
  override_during = plan

  mock_resource "azurerm_storage_account" {
    defaults = {
      id                    = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.Storage/storageAccounts/mockstorage"
      primary_blob_endpoint = "https://mockstorage.blob.core.windows.net/"
    }
  }

  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/mock-function"
      client_id    = "00000000-0000-0000-0000-000000000002"
      principal_id = "00000000-0000-0000-0000-000000000003"
    }
  }
}

variables {
  subscription_id      = "00000000-0000-0000-0000-000000000001"
  resource_group_name  = "rg-adtl-test"
  storage_account_name = "adtlteststorage"
}

run "functions_disabled_by_default" {
  command = plan

  override_data {
    target = data.azurerm_subscription.current
    values = {
      display_name = "Personal-Sandbox"
    }
  }

  assert {
    condition     = length(azurerm_function_app_flex_consumption.function) == 0 && length(azurerm_storage_account.function_host) == 0 && length(azurerm_user_assigned_identity.function) == 0
    error_message = "Functions無効時にFunction App・専用Storage・UAIを作成してはいけません。"
  }
}

run "functions_add_secure_flex_stack" {
  command = plan

  variables {
    functions_enabled = true
  }

  override_resource {
    target          = azurerm_storage_account.lab
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.Storage/storageAccounts/adtlteststorage"
    }
  }

  override_resource {
    target          = azurerm_storage_account.function_host[0]
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.Storage/storageAccounts/fnadtlteststorage"
    }
  }

  override_resource {
    target          = azurerm_user_assigned_identity.function[0]
    override_during = plan
    values = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-adtlteststorage-fn"
      client_id    = "00000000-0000-0000-0000-000000000002"
      principal_id = "00000000-0000-0000-0000-000000000003"
    }
  }

  override_data {
    target = data.azurerm_subscription.current
    values = {
      display_name = "Personal-Sandbox"
    }
  }

  assert {
    condition     = azurerm_storage_account.function_host[0].is_hns_enabled == false && azurerm_storage_account.function_host[0].account_tier == "Standard" && azurerm_storage_account.function_host[0].account_replication_type == "LRS" && azurerm_storage_account.function_host[0].shared_access_key_enabled == false
    error_message = "Functions専用Storageは非HNS・Standard LRS・Shared Key無効でなければなりません。"
  }

  assert {
    condition     = azurerm_storage_container.function_deployment[0].container_access_type == "private"
    error_message = "deployment containerはprivateでなければなりません。"
  }

  assert {
    condition     = azurerm_service_plan.function[0].os_type == "Linux" && azurerm_service_plan.function[0].sku_name == "FC1"
    error_message = "FunctionsはLinuxのFlex Consumption FC1でなければなりません。"
  }

  assert {
    condition     = azurerm_function_app_flex_consumption.function[0].storage_authentication_type == "UserAssignedIdentity" && azurerm_function_app_flex_consumption.function[0].storage_user_assigned_identity_id == azurerm_user_assigned_identity.function[0].id && azurerm_function_app_flex_consumption.function[0].runtime_name == "python" && azurerm_function_app_flex_consumption.function[0].runtime_version == "3.14"
    error_message = "Function AppはUAI接続のPython 3.14として構成しなければなりません。"
  }

  assert {
    condition     = azurerm_function_app_flex_consumption.function[0].instance_memory_in_mb == 2048 && azurerm_function_app_flex_consumption.function[0].maximum_instance_count == 1 && azurerm_function_app_flex_consumption.function[0].http_concurrency == 1 && length(azurerm_function_app_flex_consumption.function[0].always_ready) == 0
    error_message = "Functionsのメモリ・最大インスタンス・HTTP同時実行数を学習用の上限へ固定し、常時起動を0にしなければなりません。"
  }

  assert {
    condition     = azurerm_function_app_flex_consumption.function[0].https_only && azurerm_function_app_flex_consumption.function[0].site_config[0].minimum_tls_version == "1.2" && azurerm_function_app_flex_consumption.function[0].site_config[0].scm_minimum_tls_version == "1.2"
    error_message = "Function AppとSCMはHTTPSおよびTLS 1.2以上でなければなりません。"
  }

  assert {
    condition     = azurerm_function_app_flex_consumption.function[0].webdeploy_publish_basic_authentication_enabled == false
    error_message = "OneDeployはEntraのBearer認証を使い、SCMのBasic認証を無効にしなければなりません。"
  }

  assert {
    condition = alltrue([
      azurerm_function_app_flex_consumption.function[0].app_settings["AzureWebJobsStorage"] == "",
      azurerm_function_app_flex_consumption.function[0].app_settings["AzureWebJobsStorage__accountName"] == azurerm_storage_account.function_host[0].name,
      azurerm_function_app_flex_consumption.function[0].app_settings["AzureWebJobsStorage__credential"] == "managedidentity",
      azurerm_function_app_flex_consumption.function[0].app_settings["AzureWebJobsStorage__clientId"] == azurerm_user_assigned_identity.function[0].client_id,
      azurerm_function_app_flex_consumption.function[0].app_settings["LAB_STORAGE_ACCOUNT_NAME"] == azurerm_storage_account.lab.name,
      azurerm_function_app_flex_consumption.function[0].app_settings["AZURE_CLIENT_ID"] == azurerm_user_assigned_identity.function[0].client_id,
      !contains(keys(azurerm_function_app_flex_consumption.function[0].app_settings), "FUNCTIONS_EXTENSION_VERSION"),
      !contains(keys(azurerm_function_app_flex_consumption.function[0].app_settings), "FUNCTIONS_WORKER_RUNTIME"),
    ])
    error_message = "Functionsのhost接続と検証対象StorageはUAI向けapp settingsで明示しなければなりません。"
  }

  assert {
    condition     = azurerm_role_assignment.function_host_blob_owner[0].scope == azurerm_storage_account.function_host[0].id && azurerm_role_assignment.function_host_blob_owner[0].role_definition_name == "Storage Blob Data Owner"
    error_message = "FunctionsのUAIには専用host StorageだけへBlob Data Ownerを付与しなければなりません。"
  }

  assert {
    condition     = azurerm_role_assignment.function_lab_landing_blob_reader[0].scope == "${azurerm_storage_account.lab.id}/blobServices/default/containers/landing" && azurerm_role_assignment.function_lab_landing_blob_reader[0].role_definition_name == "Storage Blob Data Reader"
    error_message = "FunctionsのUAIにはlabのlandingコンテナーだけへBlob Data Readerを付与しなければなりません。"
  }

  assert {
    condition     = azurerm_role_assignment.function_operator_blob_data[0].scope == azurerm_storage_account.function_host[0].id && azurerm_role_assignment.function_operator_blob_data[0].role_definition_name == "Storage Blob Data Contributor"
    error_message = "deployment container作成用のユーザー権限は専用Storageへ限定しなければなりません。"
  }
}
