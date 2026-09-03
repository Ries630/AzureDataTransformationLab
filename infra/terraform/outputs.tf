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
