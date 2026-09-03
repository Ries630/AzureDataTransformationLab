variable "subscription_id" {
  description = "Personal-SandboxのSubscription ID。環境変数で指定する。"
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "Personal-Sandboxの有効なSubscription IDを明示してください。"
  }
}

variable "resource_group_name" {
  description = "state保存専用に新設するResource Group名。"
  type        = string
  nullable    = false
}

variable "storage_account_name" {
  description = "state保存専用Storage Accountの一意な名前。"
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account_name))
    error_message = "Storage Account名は3〜24文字の英小文字・数字で指定してください。"
  }
}

variable "location" {
  description = "state保存先のAzureリージョン。"
  type        = string
  default     = "japaneast"
  nullable    = false
}
