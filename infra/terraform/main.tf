resource "azurerm_resource_group" "lab" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.tags

  lifecycle {
    precondition {
      condition     = data.azurerm_subscription.current.display_name == "Personal-Sandbox"
      error_message = "学習用リソースはPersonal-Sandboxだけに作成できます。Subscription IDを確認してください。"
    }
  }
}
