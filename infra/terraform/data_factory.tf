locals {
  data_factory_name    = coalesce(var.data_factory_name, "adf-${var.storage_account_name}")
  data_factory_ir_name = coalesce(var.data_factory_ir_name, "ir-${var.storage_account_name}")
  data_factory_tags = merge(var.tags, {
    component = "data-factory"
  })
}

resource "azurerm_data_factory" "lab" {
  count = var.data_factory_enabled ? 1 : 0

  name                = local.data_factory_name
  resource_group_name = azurerm_resource_group.lab.name
  location            = azurerm_resource_group.lab.location
  tags                = local.data_factory_tags

  identity {
    type = "SystemAssigned"
  }

  lifecycle {
    precondition {
      condition     = !var.data_factory_enabled || var.functions_enabled
      error_message = "Data FactoryはFunctions基盤（functions_enabled）を有効にしてから作成してください。Pipelineが検証Functionを呼び出します。"
    }
  }
}

# Data Flow用のAzure IRはAutoResolveではなくjapaneast・General最小構成で固定し、
# 実行リージョンと課金単位をplan時点で確定させる。TTL 0でクラスターを再利用しない。
resource "azurerm_data_factory_integration_runtime_azure" "lab" {
  count = var.data_factory_enabled ? 1 : 0

  name             = local.data_factory_ir_name
  data_factory_id  = azurerm_data_factory.lab[0].id
  location         = azurerm_resource_group.lab.location
  compute_type     = "General"
  core_count       = 8
  time_to_live_min = 0
}

# Copy・ETag取得はlandingの読み取りだけを許可する。
resource "azurerm_role_assignment" "adf_landing_blob_reader" {
  count = var.data_factory_enabled ? 1 : 0

  scope                = "${azurerm_storage_account.lab.id}/blobServices/default/containers/landing"
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_data_factory.lab[0].identity[0].principal_id
  principal_type       = "ServicePrincipal"

  depends_on = [azurerm_storage_data_lake_gen2_filesystem.zones["landing"]]
}

# validated・rejected・outputへのCopy・Data Flow・検証結果PUTに必要な書き込み権限。
resource "azurerm_role_assignment" "adf_zone_blob_contributor" {
  for_each = var.data_factory_enabled ? toset(["validated", "rejected", "output"]) : toset([])

  scope                = "${azurerm_storage_account.lab.id}/blobServices/default/containers/${each.value}"
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_data_factory.lab[0].identity[0].principal_id
  principal_type       = "ServicePrincipal"

  # depends_onは静的参照のみ許可されるため、filesystem全体の作成完了を待つ。
  depends_on = [azurerm_storage_data_lake_gen2_filesystem.zones]
}

resource "azurerm_data_factory_linked_service_data_lake_storage_gen2" "lab" {
  count = var.data_factory_enabled ? 1 : 0

  name                 = "ls-adls-gen2"
  data_factory_id      = azurerm_data_factory.lab[0].id
  url                  = trimsuffix(azurerm_storage_account.lab.primary_dfs_endpoint, "/")
  use_managed_identity = true
}

# Functionキーはstateに保存される。公開Issue・PRへ貼り付けない。
# キーをローテーションした場合は次のplanでLinked Serviceの差分として反映される。
data "azurerm_function_app_host_keys" "validator" {
  count = var.data_factory_enabled ? 1 : 0

  name                = local.function_app_name
  resource_group_name = azurerm_resource_group.lab.name

  # 初回構築ではFunction Appの作成完了後にキーを読む。
  depends_on = [azurerm_function_app_flex_consumption.function]
}

resource "azurerm_data_factory_linked_service_azure_function" "validator" {
  count = var.data_factory_enabled ? 1 : 0

  name            = "ls-function-validator"
  data_factory_id = azurerm_data_factory.lab[0].id
  url             = "https://${local.function_app_name}.azurewebsites.net"
  key             = data.azurerm_function_app_host_keys.validator[0].default_function_key
}

# Binary datasetは1つにパラメーター化し、landing→validatedとlanding→rejectedで共用する。
resource "azurerm_data_factory_custom_dataset" "binary" {
  count = var.data_factory_enabled ? 1 : 0

  name            = "ds_adls_binary"
  data_factory_id = azurerm_data_factory.lab[0].id
  type            = "Binary"
  parameters = {
    fileSystem = ""
    folderPath = ""
    fileName   = ""
  }

  linked_service {
    name = azurerm_data_factory_linked_service_data_lake_storage_gen2.lab[0].name
  }

  type_properties_json = jsonencode({
    location = {
      type       = "AzureBlobFSLocation"
      fileSystem = { value = "@dataset().fileSystem", type = "Expression" }
      folderPath = { value = "@dataset().folderPath", type = "Expression" }
      fileName   = { value = "@dataset().fileName", type = "Expression" }
    }
  })
}

# Data Flowのsource・sinkで共用するDelimitedText dataset。
resource "azurerm_data_factory_dataset_delimited_text" "csv" {
  count = var.data_factory_enabled ? 1 : 0

  name                = "ds_adls_csv"
  data_factory_id     = azurerm_data_factory.lab[0].id
  linked_service_name = azurerm_data_factory_linked_service_data_lake_storage_gen2.lab[0].name
  parameters = {
    fileSystem = ""
    folderPath = ""
    fileName   = ""
  }

  column_delimiter    = ","
  quote_character     = "\""
  escape_character    = "\""
  first_row_as_header = true
  encoding            = "UTF-8"

  azure_blob_fs_location {
    file_system                 = "@dataset().fileSystem"
    path                        = "@dataset().folderPath"
    filename                    = "@dataset().fileName"
    dynamic_file_system_enabled = true
    dynamic_path_enabled        = true
    dynamic_filename_enabled    = true
  }
}

resource "azurerm_data_factory_data_flow" "transform_orders" {
  count = var.data_factory_enabled ? 1 : 0

  name            = "df_transform_orders"
  data_factory_id = azurerm_data_factory.lab[0].id
  script          = file("${path.module}/adf/transform_orders.dfsql")

  source {
    name = "source1"
    dataset {
      name = azurerm_data_factory_dataset_delimited_text.csv[0].name
    }
  }

  # script内の変換は名前だけ宣言しないとtransformationsがnullになり、sinkまで実行されない。
  transformation {
    name = "RenameColumns"
  }
  transformation {
    name = "ConvertTypes"
  }
  transformation {
    name = "DropInvalidRows"
  }

  sink {
    name = "sink1"
    dataset {
      name = azurerm_data_factory_dataset_delimited_text.csv[0].name
    }
  }
}

resource "azurerm_data_factory_pipeline" "csv_ingestion" {
  count = var.data_factory_enabled ? 1 : 0

  name            = "pl-csv-ingestion"
  data_factory_id = azurerm_data_factory.lab[0].id
  concurrency     = 1

  parameters = {
    folderPath = ""
    fileName   = ""
  }
  variables = {
    relativeDir  = ""
    relativePath = ""
  }

  activities_json = templatefile("${path.module}/adf/csv_ingestion.activities.json", {
    storage_account_name = azurerm_storage_account.lab.name
    ir_name              = local.data_factory_ir_name
  })

  # activities_json内の参照は名前だけなので、作成順序を明示する。
  depends_on = [
    azurerm_data_factory_linked_service_azure_function.validator,
    azurerm_data_factory_custom_dataset.binary,
    azurerm_data_factory_dataset_delimited_text.csv,
    azurerm_data_factory_data_flow.transform_orders,
    azurerm_data_factory_integration_runtime_azure.lab,
  ]
}

# landingのCSVだけを対象にし、validated・rejected・outputへの書き込みで再起動しない。
# 0バイトのCSVも拾えるようignore_empty_blobsをfalseにする。
resource "azurerm_data_factory_trigger_blob_event" "landing_csv" {
  count = var.data_factory_enabled ? 1 : 0

  name                  = "tr-landing-csv-created"
  data_factory_id       = azurerm_data_factory.lab[0].id
  storage_account_id    = azurerm_storage_account.lab.id
  events                = ["Microsoft.Storage.BlobCreated"]
  blob_path_begins_with = "/landing/blobs/"
  blob_path_ends_with   = ".csv"
  ignore_empty_blobs    = false
  activated             = true

  pipeline {
    name = azurerm_data_factory_pipeline.csv_ingestion[0].name
    parameters = {
      folderPath = "@triggerBody().folderPath"
      fileName   = "@triggerBody().fileName"
    }
  }

  depends_on = [azurerm_data_factory_pipeline.csv_ingestion]
}
