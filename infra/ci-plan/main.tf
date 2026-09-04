data "azurerm_resource_group" "state" {
  name = var.state_resource_group_name
}

data "azurerm_resource_group" "lab" {
  count = var.lab_access_enabled ? 1 : 0
  name  = var.lab_resource_group_name
}

locals {
  subscription_scope = "/subscriptions/${var.subscription_id}"
  state_account      = "${data.azurerm_resource_group.state.id}/providers/Microsoft.Storage/storageAccounts/${var.state_storage_account_name}"
  state_container    = "${local.state_account}/blobServices/default/containers/tfstate"
  lab_account        = var.lab_access_enabled ? "${data.azurerm_resource_group.lab[0].id}/providers/Microsoft.Storage/storageAccounts/${var.lab_storage_account_name}" : null
}

resource "azurerm_user_assigned_identity" "plan" {
  name                = "id-adtl-terraform-plan"
  resource_group_name = data.azurerm_resource_group.state.name
  location            = data.azurerm_resource_group.state.location
  tags = {
    project    = "AzureDataTransformationLab"
    purpose    = "terraform-plan"
    managed_by = "terraform"
  }

  lifecycle {
    precondition {
      condition     = data.azurerm_subscription.current.display_name == "Personal-Sandbox"
      error_message = "CI IdentityはPersonal-Sandboxだけに作成できます。"
    }
  }
}

resource "azurerm_federated_identity_credential" "github" {
  name                      = "github-terraform-plan"
  user_assigned_identity_id = azurerm_user_assigned_identity.plan.id
  issuer                    = "https://token.actions.githubusercontent.com"
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = "${var.oidc_subject_prefix}:environment:terraform-plan"
}

resource "azurerm_role_definition" "subscription_metadata" {
  name        = "ADTL Terraform Plan Subscription Metadata Reader"
  scope       = local.subscription_scope
  description = "plan対象Subscriptionの名前と状態だけを読み取る。"
  permissions {
    actions = ["Microsoft.Resources/subscriptions/read"]
  }
  assignable_scopes = [local.subscription_scope]
}

resource "azurerm_role_assignment" "subscription_metadata" {
  scope              = local.subscription_scope
  role_definition_id = azurerm_role_definition.subscription_metadata.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.plan.principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "lab_reader" {
  count                = var.lab_access_enabled ? 1 : 0
  scope                = data.azurerm_resource_group.lab[0].id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.plan.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "lab_blob_reader" {
  count                = var.lab_access_enabled ? 1 : 0
  scope                = local.lab_account
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.plan.principal_id
  principal_type       = "ServicePrincipal"
}

# 接続切替の導入だけで既存権限を削除・再作成しないよう、対応を明示する。
moved {
  from = azurerm_role_assignment.lab_reader
  to   = azurerm_role_assignment.lab_reader[0]
}

moved {
  from = azurerm_role_assignment.lab_blob_reader
  to   = azurerm_role_assignment.lab_blob_reader[0]
}

resource "azurerm_role_assignment" "state_reader" {
  scope                = local.state_account
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.plan.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "state_lease" {
  scope                = local.state_container
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.plan.principal_id
  principal_type       = "ServicePrincipal"
}
