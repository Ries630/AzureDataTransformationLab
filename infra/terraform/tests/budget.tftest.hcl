mock_provider "azurerm" {
  override_during = plan

  mock_data "azurerm_subscription" {
    defaults = {
      display_name = "Personal-Sandbox"
      id           = "/subscriptions/00000000-0000-0000-0000-000000000001"
    }
  }
}

variables {
  subscription_id      = "00000000-0000-0000-0000-000000000001"
  resource_group_name  = "rg-adtl-test"
  storage_account_name = "adtlteststorage"
}

run "budget_disabled_creates_nothing" {
  command = plan

  assert {
    condition     = length(azurerm_consumption_budget_subscription.monthly) == 0
    error_message = "Budget無効時にSubscription Budgetを作成してはいけません。"
  }
}

run "budget_uses_subscription_monthly_limit_and_actual_notifications" {
  command = plan

  variables {
    functions_enabled             = true
    data_factory_enabled          = true
    monitoring_enabled            = true
    monitoring_notification_email = "ops@example.com"
    budget_enabled                = true
    monitoring_budget_start_date  = "2026-10-01T00:00:00Z"
  }

  assert {
    condition     = azurerm_consumption_budget_subscription.monthly[0].subscription_id == data.azurerm_subscription.current.id && azurerm_consumption_budget_subscription.monthly[0].amount == 1000 && azurerm_consumption_budget_subscription.monthly[0].time_grain == "Monthly" && azurerm_consumption_budget_subscription.monthly[0].time_period[0].start_date == "2026-10-01T00:00:00Z"
    error_message = "BudgetはSubscription全体・月額1000・Monthly・指定開始日時でなければなりません。"
  }

  assert {
    condition     = azurerm_consumption_budget_subscription.monthly[0].name == "budget-${var.storage_account_name}" && toset([for n in azurerm_consumption_budget_subscription.monthly[0].notification : n.threshold]) == toset([80, 100]) && alltrue([for n in azurerm_consumption_budget_subscription.monthly[0].notification : n.enabled && n.operator == "GreaterThanOrEqualTo" && n.threshold_type == "Actual" && n.contact_emails == tolist(["ops@example.com"])])
    error_message = "Budgetは決定的な名前とActual 80%・100%のメール通知を設定しなければなりません。"
  }
}

run "budget_requires_monitoring" {
  command = plan

  variables {
    budget_enabled               = true
    monitoring_budget_start_date = "2026-10-01T00:00:00Z"
  }

  expect_failures = [var.budget_enabled]
}

run "budget_requires_explicit_start_date" {
  command = plan

  variables {
    functions_enabled             = true
    data_factory_enabled          = true
    monitoring_enabled            = true
    monitoring_notification_email = "ops@example.com"
    budget_enabled                = true
  }

  expect_failures = [var.monitoring_budget_start_date]
}
