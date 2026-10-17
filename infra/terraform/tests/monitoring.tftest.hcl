mock_provider "azurerm" {
  override_during = plan

  mock_data "azurerm_subscription" {
    defaults = {
      display_name = "Personal-Sandbox"
    }
  }

  mock_resource "azurerm_storage_account" {
    defaults = {
      id                    = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.Storage/storageAccounts/mockstorage"
      primary_blob_endpoint = "https://mockstorage.blob.core.windows.net/"
      primary_dfs_endpoint  = "https://mockstorage.dfs.core.windows.net/"
    }
  }

  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/mock-function"
      client_id    = "00000000-0000-0000-0000-000000000002"
      principal_id = "00000000-0000-0000-0000-000000000003"
    }
  }

  mock_resource "azurerm_data_factory" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.DataFactory/factories/mock-adf"
    }
  }

  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.OperationalInsights/workspaces/mock-law"
    }
  }

  mock_resource "azurerm_application_insights" {
    defaults = {
      id                = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.Insights/components/mock-appi"
      connection_string = "InstrumentationKey=mock;IngestionEndpoint=https://mock.example/"
    }
  }

  mock_resource "azurerm_monitor_action_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/microsoft.insights/actionGroups/mock-ag"
    }
  }
}

variables {
  subscription_id      = "00000000-0000-0000-0000-000000000001"
  resource_group_name  = "rg-adtl-test"
  storage_account_name = "adtlteststorage"
}

run "monitoring_disabled_preserves_existing_configuration" {
  command = plan

  override_data {
    target = data.azurerm_subscription.current
    values = {
      display_name = "Personal-Sandbox"
    }
  }

  assert {
    condition     = length(azurerm_log_analytics_workspace.lab) == 0 && length(azurerm_application_insights.lab) == 0 && length(azurerm_monitor_diagnostic_setting.data_factory) == 0 && length(azurerm_monitor_action_group.pipeline_failure) == 0 && length(azurerm_monitor_metric_alert.pipeline_failure) == 0
    error_message = "監視無効時に監視リソースを作成してはいけません。"
  }

  assert {
    condition     = length(azurerm_log_analytics_workspace_table.application_insights) == 0
    error_message = "監視無効時にApplication Insights用のLog Analytics tableを作成してはいけません。"
  }
}

run "monitoring_configures_diagnostics_identity_and_failure_alert" {
  command = plan

  variables {
    functions_enabled             = true
    data_factory_enabled          = true
    monitoring_enabled            = true
    monitoring_notification_email = "ops@example.com"
    schema_evolution_lab_enabled  = false
  }

  override_data {
    target = data.azurerm_subscription.current
    values = {
      display_name = "Personal-Sandbox"
    }
  }

  override_resource {
    target          = azurerm_storage_account.lab
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-adtl-test/providers/Microsoft.Storage/storageAccounts/adtlteststorage"
    }
  }

  assert {
    condition     = azurerm_log_analytics_workspace.lab[0].sku == "PerGB2018" && azurerm_log_analytics_workspace.lab[0].retention_in_days == 31 && azurerm_log_analytics_workspace.lab[0].daily_quota_gb == 0.1 && azurerm_log_analytics_workspace.lab[0].local_authentication_enabled == false && azurerm_log_analytics_workspace.lab[0].location == "japaneast"
    error_message = "Log AnalyticsはPerGB2018・31日・0.1GB/日・japaneastでなければなりません。"
  }

  assert {
    condition     = azurerm_application_insights.lab[0].workspace_id == azurerm_log_analytics_workspace.lab[0].id && azurerm_application_insights.lab[0].retention_in_days == 30 && !azurerm_application_insights.lab[0].local_authentication_enabled
    error_message = "Application Insightsはworkspace型・providerが受け付ける30日保持・local authentication無効でなければなりません。"
  }

  assert {
    condition = toset([for table in values(azurerm_log_analytics_workspace_table.application_insights) : table.name]) == toset([
      "AppAvailabilityResults", "AppBrowserTimings", "AppDependencies", "AppEvents", "AppExceptions", "AppMetrics",
      "AppPageViews", "AppPerformanceCounters", "AppRequests", "AppSystemEvents", "AppTraces", "AppGenAIContent",
      ]) && alltrue([for table in values(azurerm_log_analytics_workspace_table.application_insights) :
      table.workspace_id == azurerm_log_analytics_workspace.lab[0].id && table.plan == "Analytics" &&
      table.retention_in_days == 31 && table.total_retention_in_days == 31
    ])
    error_message = "Application Insightsの12 tableは指定workspaceのAnalytics planで保持期間を31日に設定しなければなりません。"
  }

  assert {
    condition     = azurerm_role_assignment.function_monitoring_metrics_publisher[0].scope == azurerm_application_insights.lab[0].id && azurerm_role_assignment.function_monitoring_metrics_publisher[0].role_definition_name == "Monitoring Metrics Publisher" && azurerm_role_assignment.function_monitoring_metrics_publisher[0].principal_id == azurerm_user_assigned_identity.function[0].principal_id
    error_message = "Function UAIのMonitoring Metrics PublisherはApplication Insights scopeに限定しなければなりません。"
  }

  assert {
    condition     = azurerm_function_app_flex_consumption.function[0].site_config[0].application_insights_connection_string == azurerm_application_insights.lab[0].connection_string && azurerm_function_app_flex_consumption.function[0].app_settings["APPLICATIONINSIGHTS_AUTHENTICATION_STRING"] == "ClientId=${azurerm_user_assigned_identity.function[0].client_id};Authorization=AAD" && azurerm_function_app_flex_consumption.function[0].app_settings["LAB_STORAGE_ACCOUNT_NAME"] == azurerm_storage_account.lab.name
    error_message = "Function AppはUAI認証のApplication Insights設定を追加し、既存app settingsを保たなければなりません。"
  }

  assert {
    condition     = toset([for log in azurerm_monitor_diagnostic_setting.data_factory[0].enabled_log : log.category]) == toset(["PipelineRuns", "ActivityRuns", "TriggerRuns"]) && azurerm_monitor_diagnostic_setting.data_factory[0].log_analytics_destination_type == "Dedicated"
    error_message = "ADF diagnosticsは3種類のrun logだけをDedicated tablesへ送らなければなりません。"
  }

  assert {
    condition     = azurerm_monitor_action_group.pipeline_failure[0].email_receiver[0].email_address == "ops@example.com" && azurerm_monitor_action_group.pipeline_failure[0].email_receiver[0].use_common_alert_schema
    error_message = "Action Groupは指定宛先1件へCommon Alert Schemaで通知しなければなりません。"
  }

  assert {
    condition     = azurerm_monitor_metric_alert.pipeline_failure[0].name == "mon-${var.storage_account_name}-pipeline-failure" && azurerm_monitor_metric_alert.pipeline_failure[0].criteria[0].metric_name == "PipelineFailedRuns" && azurerm_monitor_metric_alert.pipeline_failure[0].criteria[0].aggregation == "Total" && azurerm_monitor_metric_alert.pipeline_failure[0].criteria[0].operator == "GreaterThan" && azurerm_monitor_metric_alert.pipeline_failure[0].criteria[0].threshold == 0 && azurerm_monitor_metric_alert.pipeline_failure[0].criteria[0].dimension[0].name == "Name" && azurerm_monitor_metric_alert.pipeline_failure[0].criteria[0].dimension[0].values == tolist([azurerm_data_factory_pipeline.csv_ingestion[0].name]) && azurerm_monitor_metric_alert.pipeline_failure[0].frequency == "PT1M" && azurerm_monitor_metric_alert.pipeline_failure[0].window_size == "PT5M" && azurerm_monitor_metric_alert.pipeline_failure[0].severity == 1 && azurerm_monitor_metric_alert.pipeline_failure[0].auto_mitigate
    error_message = "Pipeline失敗alertは要求されたmetric条件・時間幅・severityを使わなければなりません。"
  }
}

run "monitoring_requires_functions_and_data_factory" {
  command = plan

  variables {
    monitoring_enabled            = true
    monitoring_notification_email = "ops@example.com"
  }

  expect_failures = [var.monitoring_enabled]
}

run "monitoring_rejects_invalid_notification_email" {
  command = plan

  variables {
    functions_enabled             = true
    data_factory_enabled          = true
    monitoring_enabled            = true
    monitoring_notification_email = "not-an-email"
  }

  expect_failures = [var.monitoring_notification_email]
}
