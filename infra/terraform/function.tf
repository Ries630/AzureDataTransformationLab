locals {
  function_app_name  = coalesce(var.function_app_name, "func-${var.storage_account_name}")
  function_plan_name = coalesce(var.function_plan_name, "plan-${var.storage_account_name}")

  # 既存Storage名に固定の接頭辞を付け、24文字以内で別のStorage名を作る。
  function_storage_account_name = coalesce(
    var.function_storage_account_name,
    "fn${substr(var.storage_account_name, 0, 21)}",
  )
  function_identity_name = coalesce(var.function_identity_name, "id-${var.storage_account_name}-fn")
  function_tags = merge(var.tags, {
    component = "functions"
  })
}

resource "azurerm_storage_account" "function_host" {
  count = var.functions_enabled ? 1 : 0

  name                     = local.function_storage_account_name
  resource_group_name      = azurerm_resource_group.lab.name
  location                 = azurerm_resource_group.lab.location
  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = "LRS"
  access_tier              = "Hot"
  is_hns_enabled           = false

  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  public_network_access_enabled   = true
  tags                            = local.function_tags

  lifecycle {
    precondition {
      condition     = local.function_storage_account_name != var.storage_account_name
      error_message = "Functions専用Storage AccountはCSV用Storage Accountと別名にしてください。"
    }
  }
}

resource "azurerm_user_assigned_identity" "function" {
  count = var.functions_enabled ? 1 : 0

  name                = local.function_identity_name
  resource_group_name = azurerm_resource_group.lab.name
  location            = azurerm_resource_group.lab.location
  tags                = local.function_tags
}

# ローカルのAzure ADユーザーがdeployment containerを作れるよう、専用Storageだけへ付与する。
resource "azurerm_role_assignment" "function_operator_blob_data" {
  count = var.functions_enabled ? 1 : 0

  scope                = azurerm_storage_account.function_host[0].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = nonsensitive(coalesce(var.operator_object_id, data.azurerm_client_config.current.object_id))
  principal_type       = "User"
}

# Functions hostがAzureWebJobsStorageとdeployment packageをEntra IDで扱うための権限。
resource "azurerm_role_assignment" "function_host_blob_owner" {
  count = var.functions_enabled ? 1 : 0

  scope                = azurerm_storage_account.function_host[0].id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = azurerm_user_assigned_identity.function[0].principal_id
  principal_type       = "ServicePrincipal"
}

# Function Appはlandingだけを検証対象として読む。
resource "azurerm_role_assignment" "function_lab_landing_blob_reader" {
  count = var.functions_enabled ? 1 : 0

  # filesystem.idはDFSのデータプレーンIDなので、RBACのARMコンテナーscopeを明示する。
  scope                = "${azurerm_storage_account.lab.id}/blobServices/default/containers/landing"
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.function[0].principal_id
  principal_type       = "ServicePrincipal"

  # コンテナーは既存のADLS Gen2 filesystemとして先に作成する。
  depends_on = [azurerm_storage_data_lake_gen2_filesystem.zones["landing"]]
}

# Azure ADでのcontainer作成は、上のデータ権限が反映された後に行う。
# Role Assignmentの反映には時間差があるため、初回403時は再plan・待機・再適用で対処する。
resource "azurerm_storage_container" "function_deployment" {
  count = var.functions_enabled ? 1 : 0

  name                  = "function-deployment"
  storage_account_id    = azurerm_storage_account.function_host[0].id
  container_access_type = "private"

  depends_on = [azurerm_role_assignment.function_operator_blob_data]
}

resource "azurerm_service_plan" "function" {
  count = var.functions_enabled ? 1 : 0

  name                = local.function_plan_name
  resource_group_name = azurerm_resource_group.lab.name
  location            = azurerm_resource_group.lab.location
  os_type             = "Linux"
  sku_name            = "FC1"
  tags                = local.function_tags
}

resource "azurerm_function_app_flex_consumption" "function" {
  count = var.functions_enabled ? 1 : 0

  name                = local.function_app_name
  resource_group_name = azurerm_resource_group.lab.name
  location            = azurerm_resource_group.lab.location
  service_plan_id     = azurerm_service_plan.function[0].id

  storage_container_type            = "blobContainer"
  storage_container_endpoint        = "${azurerm_storage_account.function_host[0].primary_blob_endpoint}${azurerm_storage_container.function_deployment[0].name}"
  storage_authentication_type       = "UserAssignedIdentity"
  storage_user_assigned_identity_id = azurerm_user_assigned_identity.function[0].id
  runtime_name                      = "python"
  runtime_version                   = "3.14"
  maximum_instance_count            = 1
  instance_memory_in_mb             = 512
  http_concurrency                  = 1
  # always_readyブロックを指定せず、常時起動インスタンス数を0にする。

  https_only                    = true
  public_network_access_enabled = true
  # Core ToolsのFlex OneDeployはBearerトークンで発行するため、SCMのBasic認証を使わない。
  webdeploy_publish_basic_authentication_enabled = false

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.function[0].id]
  }

  # AzureRM 5.3.0はUAI指定時も空のAccountKeyを含むAzureWebJobsStorageを内部生成する。
  # ユーザー指定のapp_settingsを最後に結合する実装を利用し、空文字でその生成値を上書きする。
  # Microsoft公式のFlex Consumption Terraform例も、このproviderの回避策として空文字を指定している。
  # accountName・credential・clientIdでUAIによるhost接続を明示する。
  app_settings = {
    "AzureWebJobsStorage"              = ""
    "AzureWebJobsStorage__accountName" = azurerm_storage_account.function_host[0].name
    "AzureWebJobsStorage__credential"  = "managedidentity"
    "AzureWebJobsStorage__clientId"    = azurerm_user_assigned_identity.function[0].client_id
    "LAB_STORAGE_ACCOUNT_NAME"         = azurerm_storage_account.lab.name
    "AZURE_CLIENT_ID"                  = azurerm_user_assigned_identity.function[0].client_id
  }

  site_config {
    minimum_tls_version     = "1.2"
    scm_minimum_tls_version = "1.2"
  }

  tags = local.function_tags

  # host・landingのRBACが反映された後にFunction Appを作成する。
  depends_on = [
    azurerm_role_assignment.function_host_blob_owner,
    azurerm_role_assignment.function_lab_landing_blob_reader,
  ]
}
