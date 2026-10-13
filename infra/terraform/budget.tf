resource "azurerm_consumption_budget_subscription" "monthly" {
  count = var.budget_enabled ? 1 : 0

  name            = "budget-${var.storage_account_name}"
  subscription_id = data.azurerm_subscription.current.id
  amount          = 1000
  time_grain      = "Monthly"

  time_period {
    start_date = var.monitoring_budget_start_date
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThanOrEqualTo"
    threshold_type = "Actual"
    contact_emails = [var.monitoring_notification_email]
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThanOrEqualTo"
    threshold_type = "Actual"
    contact_emails = [var.monitoring_notification_email]
  }
}
