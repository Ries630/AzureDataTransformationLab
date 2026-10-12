output "resource_group_name" {
  description = "作成した学習用Resource Groupの名前。"
  value       = azurerm_resource_group.lab.name
}

output "storage_account_name" {
  description = "CSV配置先のStorage Account名。"
  value       = azurerm_storage_account.lab.name
}

output "filesystem_names" {
  description = "作成したFilesystemの名前。"
  value       = sort([for filesystem in azurerm_storage_data_lake_gen2_filesystem.zones : filesystem.name])
}

output "function_app_name" {
  description = "Functions有効時に作成したFlex Consumption Function App名。"
  value       = var.functions_enabled ? azurerm_function_app_flex_consumption.function[0].name : null
}

output "function_plan_name" {
  description = "Functions有効時に作成したFlex ConsumptionのApp Service Plan名。"
  value       = var.functions_enabled ? azurerm_service_plan.function[0].name : null
}

output "function_storage_account_name" {
  description = "Functions有効時に作成したhost・deployment専用Storage Account名。"
  value       = var.functions_enabled ? azurerm_storage_account.function_host[0].name : null
}

output "function_deployment_container_name" {
  description = "Functions有効時に作成したprivate deployment container名。"
  value       = var.functions_enabled ? azurerm_storage_container.function_deployment[0].name : null
}

output "function_identity_client_id" {
  description = "Functionsのhost・deploymentに使うUAIのClient ID。秘密鍵ではないため非機密出力とする。"
  value       = var.functions_enabled ? azurerm_user_assigned_identity.function[0].client_id : null
}

output "data_factory_name" {
  description = "Data Factory有効時に作成したData Factory名。"
  value       = var.data_factory_enabled ? azurerm_data_factory.lab[0].name : null
}

output "data_factory_ir_name" {
  description = "Data Factory有効時に作成したData Flow用Azure IR名。"
  value       = var.data_factory_enabled ? azurerm_data_factory_integration_runtime_azure.lab[0].name : null
}

output "data_factory_pipeline_name" {
  description = "Data Factory有効時に作成したCSV取り込みPipeline名。"
  value       = var.data_factory_enabled ? azurerm_data_factory_pipeline.csv_ingestion[0].name : null
}

output "data_factory_trigger_name" {
  description = "Data Factory有効時に作成したStorage Event Trigger名。"
  value       = var.data_factory_enabled ? azurerm_data_factory_trigger_blob_event.landing_csv[0].name : null
}
