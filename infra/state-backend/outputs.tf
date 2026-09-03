output "backend_config" {
  description = "学習用rootの初期化設定。backend.local.jsonへ保存し、Gitや公開ログに出さない。"
  sensitive   = true
  value = {
    subscription_id      = var.subscription_id
    resource_group_name  = azurerm_resource_group.state.name
    storage_account_name = azurerm_storage_account.state.name
    container_name       = azurerm_storage_container.state.name
    key                  = "lab.terraform.tfstate"
  }
}
