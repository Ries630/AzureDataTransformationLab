# Phase 6の状態Table・権限・子Pipelineの有無と、親Pipelineが状態を確認してから
# 子Pipelineを呼ぶことを検証する。Azure APIはmockに置き換える。
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

run "idempotency_disabled_by_default" {
  command = plan

  variables {
    functions_enabled            = true
    data_factory_enabled         = true
    schema_evolution_lab_enabled = false
    idempotency_enabled          = false
  }

  override_data {
    target = data.azurerm_subscription.current
    values = {
      display_name = "Personal-Sandbox"
    }
  }

  assert {
    condition     = length(azurerm_storage_table.ingestion_state) == 0 && length(azurerm_role_assignment.adf_ingestion_state) == 0 && length(azurerm_data_factory_pipeline.process_generation) == 0
    error_message = "idempotency_enabledが無効の場合、状態Table・権限・子Pipelineを作成してはいけません。"
  }

  assert {
    condition     = !strcontains(azurerm_data_factory_pipeline.csv_ingestion[0].activities_json, "ExecutePipeline") && !contains(keys(azurerm_data_factory_pipeline.csv_ingestion[0].parameters), "force")
    error_message = "idempotency_enabledが無効の場合、Pipelineは従来の処理のままでなければなりません。"
  }
}

run "idempotency_adds_state_table_and_child_pipeline" {
  command = plan

  variables {
    functions_enabled            = true
    data_factory_enabled         = true
    schema_evolution_lab_enabled = false
    idempotency_enabled          = true
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
    condition     = azurerm_storage_table.ingestion_state[0].name == "ingestionstate"
    error_message = "状態Tableはingestionstateでなければなりません。"
  }

  assert {
    condition     = azurerm_role_assignment.adf_ingestion_state[0].scope == "${azurerm_storage_account.lab.id}/tableServices/default/tables/ingestionstate" && azurerm_role_assignment.adf_ingestion_state[0].role_definition_name == "Storage Table Data Contributor"
    error_message = "ADFのMIには状態Tableだけへの書き込み権限を付与しなければなりません。"
  }

  assert {
    condition     = azurerm_data_factory_pipeline.csv_ingestion[0].concurrency == 1 && azurerm_data_factory_pipeline.csv_ingestion[0].parameters["force"] == "false"
    error_message = "親Pipelineは同時実行数1を保ち、forceの既定値をfalseにしなければなりません。"
  }

  assert {
    condition = length([
      for a in flatten([for c in jsondecode(azurerm_data_factory_pipeline.csv_ingestion[0].activities_json)[index(jsondecode(azurerm_data_factory_pipeline.csv_ingestion[0].activities_json)[*].name, "ClaimOrSkip")].typeProperties.cases : c.activities]) :
      a if a.type == "ExecutePipeline" && a.typeProperties.pipeline.referenceName == "pl-csv-process-generation"
    ]) == 2
    error_message = "親Pipelineは、新しい世代と引き継いだ世代の両方で子Pipelineを呼ばなければなりません。"
  }

  assert {
    # 状態の書き込みは、初回の挿入（POST）を除き、すべてIf-Matchで条件付きにし、本文にもキーを含める。
    condition = alltrue([
      for a in concat(
        flatten([for c in jsondecode(azurerm_data_factory_pipeline.csv_ingestion[0].activities_json)[index(jsondecode(azurerm_data_factory_pipeline.csv_ingestion[0].activities_json)[*].name, "ClaimOrSkip")].typeProperties.cases : c.activities]),
        jsondecode(azurerm_data_factory_pipeline.process_generation[0].activities_json)
      ) : contains(keys(a.typeProperties.headers), "If-Match") && contains(keys(a.typeProperties.body), "PartitionKey") && contains(keys(a.typeProperties.body), "RowKey")
      if a.type == "WebActivity" && a.typeProperties.method == "PUT" && strcontains(a.typeProperties.url.value, ".table.core.windows.net/")
    ])
    error_message = "状態Tableの更新はIf-Matchで条件付きにし、本文にPartitionKeyとRowKeyを含めなければなりません。"
  }

  assert {
    condition     = one([for a in jsondecode(azurerm_data_factory_pipeline.process_generation[0].activities_json) : a.typeProperties.headers["x-adf-pipeline-run-id"] if a.name == "ValidateCsv"]) == "@{pipeline().parameters.ownerRunId}"
    error_message = "Functionのログを親Pipelineの実行IDと関連付けなければなりません。"
  }
}

run "idempotency_requires_data_factory" {
  command = plan

  variables {
    data_factory_enabled         = false
    schema_evolution_lab_enabled = false
    idempotency_enabled          = true
  }

  override_data {
    target = data.azurerm_subscription.current
    values = {
      display_name = "Personal-Sandbox"
    }
  }

  expect_failures = [var.idempotency_enabled]
}
