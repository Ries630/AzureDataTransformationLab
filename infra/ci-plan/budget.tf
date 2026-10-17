# Subscription Budgetのrefreshだけを許可し、Subscription全体のReaderは付与しない。
resource "azurerm_role_definition" "budget_reader" {
  count = var.lab_access_enabled && var.budget_access_enabled ? 1 : 0

  name        = "ADTL Terraform Plan Budget Reader"
  scope       = local.subscription_scope
  description = "plan対象SubscriptionのBudgetだけを読み取る。"
  permissions {
    actions = ["Microsoft.Consumption/budgets/read"]
  }
  assignable_scopes = [local.subscription_scope]
}

resource "azurerm_role_assignment" "budget_reader" {
  count = var.lab_access_enabled && var.budget_access_enabled ? 1 : 0

  scope              = local.subscription_scope
  role_definition_id = azurerm_role_definition.budget_reader[0].role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.plan.principal_id
  principal_type     = "ServicePrincipal"
}
