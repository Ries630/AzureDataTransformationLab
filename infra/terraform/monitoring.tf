locals {
  monitoring_name = "mon-${var.storage_account_name}"
}

resource "azurerm_log_analytics_workspace" "lab" {
  count = var.monitoring_enabled ? 1 : 0

  name                         = "law-${var.storage_account_name}"
  location                     = azurerm_resource_group.lab.location
  resource_group_name          = azurerm_resource_group.lab.name
  sku                          = "PerGB2018"
  retention_in_days            = 31
  daily_quota_gb               = 0.1
  local_authentication_enabled = false
  tags                         = var.tags
}

resource "azurerm_application_insights" "lab" {
  count = var.monitoring_enabled ? 1 : 0

  name                         = "appi-${var.storage_account_name}"
  location                     = azurerm_resource_group.lab.location
  resource_group_name          = azurerm_resource_group.lab.name
  application_type             = "web"
  workspace_id                 = azurerm_log_analytics_workspace.lab[0].id
  retention_in_days            = 30
  local_authentication_enabled = false
  tags                         = var.tags
}

resource "azurerm_role_assignment" "function_monitoring_metrics_publisher" {
  count = var.monitoring_enabled ? 1 : 0

  scope                = azurerm_application_insights.lab[0].id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = azurerm_user_assigned_identity.function[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_monitor_diagnostic_setting" "data_factory" {
  count = var.monitoring_enabled ? 1 : 0

  name                           = "${local.monitoring_name}-adf"
  target_resource_id             = azurerm_data_factory.lab[0].id
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.lab[0].id
  log_analytics_destination_type = "Dedicated"

  enabled_log {
    category = "PipelineRuns"
  }
  enabled_log {
    category = "ActivityRuns"
  }
  enabled_log {
    category = "TriggerRuns"
  }
}

resource "azurerm_monitor_action_group" "pipeline_failure" {
  count = var.monitoring_enabled ? 1 : 0

  name                = "${local.monitoring_name}-pipeline-fail"
  resource_group_name = azurerm_resource_group.lab.name
  short_name          = "adf-fail"

  email_receiver {
    name                    = "pipeline-failure"
    email_address           = var.monitoring_notification_email
    use_common_alert_schema = true
  }
}

resource "azurerm_monitor_metric_alert" "pipeline_failure" {
  count = var.monitoring_enabled ? 1 : 0

  name                = "${local.monitoring_name}-pipeline-failure"
  resource_group_name = azurerm_resource_group.lab.name
  scopes              = [azurerm_data_factory.lab[0].id]
  description         = "Data Factory Pipelineの失敗を通知します。"
  enabled             = true
  severity            = 1
  frequency           = "PT1M"
  window_size         = "PT5M"
  auto_mitigate       = true

  criteria {
    metric_namespace = "Microsoft.DataFactory/factories"
    metric_name      = "PipelineFailedRuns"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = 0

    dimension {
      name     = "Name"
      operator = "Include"
      values   = [azurerm_data_factory_pipeline.csv_ingestion[0].name]
    }
  }

  action {
    action_group_id = azurerm_monitor_action_group.pipeline_failure[0].id
  }
}
