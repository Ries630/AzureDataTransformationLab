# Azure APIだけを置き換え、誤ったSubscriptionでplanが失敗することを確認する。
mock_provider "azurerm" {}

variables {
  subscription_id      = "00000000-0000-0000-0000-000000000001"
  resource_group_name  = "rg-adtl-test"
  storage_account_name = "adtlteststorage"
}

run "reject_personal_data" {
  command = plan

  override_data {
    target = data.azurerm_subscription.current
    values = {
      display_name = "Personal-Data"
    }
  }

  expect_failures = [azurerm_resource_group.lab]
}

run "accept_personal_sandbox" {
  command = plan

  override_data {
    target = data.azurerm_subscription.current
    values = {
      display_name = "Personal-Sandbox"
    }
  }
}

run "keep_operator_when_ci_runs_plan" {
  command = plan

  variables {
    operator_object_id = "00000000-0000-0000-0000-000000000002"
  }

  override_data {
    target = data.azurerm_subscription.current
    values = {
      display_name = "Personal-Sandbox"
    }
  }

  override_data {
    target = data.azurerm_client_config.current
    values = {
      object_id = "00000000-0000-0000-0000-000000000003"
    }
  }

  assert {
    condition     = azurerm_role_assignment.operator_blob_data.principal_id == var.operator_object_id && azurerm_role_assignment.operator_blob_data.principal_type == "User"
    error_message = "CIのplanは実行IdentityへユーザーのRole Assignmentを付け替えてはいけません。"
  }

  assert {
    condition     = !issensitive(azurerm_role_assignment.operator_blob_data.principal_id)
    error_message = "入力の機密表示フラグだけで既存Role Assignmentの更新を生成してはいけません。公開時のID除去はreport.mjsが担当します。"
  }
}
