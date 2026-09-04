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
  lab_access_enabled         = true
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
    condition     = azurerm_role_assignment.state_lease.scope == local.state_container && azurerm_role_assignment.state_lease.role_definition_name == "Storage Blob Data Contributor" && azurerm_role_assignment.lab_blob_reader[0].role_definition_name == "Storage Blob Data Reader"
    error_message = "stateのlease権限と学習データの読み取り権限を分離する必要があります。"
  }
  assert {
    condition     = toset(one(azurerm_role_definition.subscription_metadata.permissions).actions) == toset(["Microsoft.Resources/subscriptions/read"])
    error_message = "Subscription全体へ読み取りや書き込み権限を広げてはいけません。"
  }
  assert {
    condition     = length(data.azurerm_resource_group.lab) == 1 && length(azurerm_role_assignment.lab_reader) == 1 && length(azurerm_role_assignment.lab_blob_reader) == 1 && azurerm_role_assignment.lab_reader[0].scope == data.azurerm_resource_group.lab[0].id && azurerm_role_assignment.lab_reader[0].role_definition_name == "Reader" && azurerm_role_assignment.lab_blob_reader[0].scope == local.lab_account
    error_message = "既定の接続有効時は学習用RGとStorageだけに従来の読み取り権限を付与する必要があります。"
  }
}

run "reject_personal_data_when_detached" {
  command = plan
  variables {
    lab_access_enabled = false
  }
  override_data {
    target = data.azurerm_subscription.current
    values = { display_name = "Personal-Data" }
  }
  expect_failures = [azurerm_user_assigned_identity.plan]
}

run "detach_lab_without_reading_its_resource_group" {
  command = plan
  variables {
    lab_access_enabled = false
  }
  override_data {
    target = data.azurerm_subscription.current
    values = { display_name = "Personal-Sandbox" }
  }
  assert {
    condition     = length(data.azurerm_resource_group.lab) == 0 && length(azurerm_role_assignment.lab_reader) == 0 && length(azurerm_role_assignment.lab_blob_reader) == 0
    error_message = "接続無効時は学習用RGを参照せず、学習用の読み取り権限だけを外す必要があります。"
  }
  assert {
    condition     = azurerm_user_assigned_identity.plan.name == "id-adtl-terraform-plan" && azurerm_federated_identity_credential.github.subject == "${var.oidc_subject_prefix}:environment:terraform-plan"
    error_message = "接続無効時もCI IdentityとOIDCの信頼関係を保持する必要があります。"
  }
  assert {
    condition     = azurerm_role_assignment.state_reader.scope == local.state_account && azurerm_role_assignment.state_reader.role_definition_name == "Reader" && azurerm_role_assignment.state_lease.scope == local.state_container && azurerm_role_assignment.state_lease.role_definition_name == "Storage Blob Data Contributor" && azurerm_role_assignment.subscription_metadata.scope == local.subscription_scope
    error_message = "stateの読み取り・lease権限とSubscriptionの名前確認権限を保持する必要があります。"
  }
}
