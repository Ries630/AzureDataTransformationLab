output "github_identity" {
  description = "GitHub Environmentへ渡すOIDC構成値。長期資格情報は含まない。"
  sensitive   = true
  value = {
    client_id       = azurerm_user_assigned_identity.plan.client_id
    tenant_id       = azurerm_user_assigned_identity.plan.tenant_id
    subscription_id = var.subscription_id
  }
}
