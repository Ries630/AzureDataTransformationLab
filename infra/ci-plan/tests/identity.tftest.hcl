mock_provider "azurerm" {}

override_data {
  target = data.azurerm_resource_group.state
  values = {
    id       = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-example-state"
    name     = "rg-example-state"
    location = "japaneast"
  }
}

override_data {
  target = data.azurerm_resource_group.lab
  values = {
    id       = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-example-lab"
    name     = "rg-example-lab"
    location = "japaneast"
  }
}

variables {
  subscription_id            = "11111111-1111-4111-8111-111111111111"
  state_resource_group_name  = "rg-example-state"
  state_storage_account_name = "exampleuniquestate"
  lab_resource_group_name    = "rg-example-lab"
  lab_storage_account_name   = "exampleuniquelab"
  oidc_subject_prefix        = "repo:Ries630@82589136/AzureDataTransformationLab@1350311992"
}

run "reject_personal_data" {
  command = plan
  override_data {
    target = data.azurerm_subscription.current
    values = { display_name = "Personal-Data" }
  }
  expect_failures = [azurerm_user_assigned_identity.plan]
}

run "restrict_identity_and_roles" {
  command = plan
  override_data {
    target = data.azurerm_subscription.current
    values = { display_name = "Personal-Sandbox" }
  }
  assert {
    condition     = azurerm_federated_identity_credential.github.subject == "${var.oidc_subject_prefix}:environment:terraform-plan" && azurerm_federated_identity_credential.github.issuer == "https://token.actions.githubusercontent.com"
    error_message = "対象リポジトリの承認付きEnvironmentだけを信頼する必要があります。"
  }
  assert {
    condition     = azurerm_role_assignment.state_lease.scope == local.state_container && azurerm_role_assignment.state_lease.role_definition_name == "Storage Blob Data Contributor" && azurerm_role_assignment.lab_blob_reader.role_definition_name == "Storage Blob Data Reader"
    error_message = "stateのlease権限と学習データの読み取り権限を分離する必要があります。"
  }
  assert {
    condition     = toset(one(azurerm_role_definition.subscription_metadata.permissions).actions) == toset(["Microsoft.Resources/subscriptions/read"])
    error_message = "Subscription全体へ読み取りや書き込み権限を広げてはいけません。"
  }
}
