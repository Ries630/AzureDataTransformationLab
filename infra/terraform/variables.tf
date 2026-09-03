variable "subscription_id" {
  description = "Personal-SandboxのSubscription ID。TF_VAR_subscription_idでローカル環境から渡す。"
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_idにはPersonal-Sandboxの有効なSubscription IDを明示してください。"
  }
}

variable "resource_group_name" {
  description = "この学習環境で新規作成するResource Group名。"
  type        = string
  nullable    = false
}

variable "location" {
  description = "学習用リソースを作成するAzureリージョン。"
  type        = string
  default     = "japaneast"
  nullable    = false
}

variable "storage_account_name" {
  description = "新規Storage Account名。Azure全体で一意な3〜24文字の英小文字・数字を指定する。"
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account_name))
    error_message = "storage_account_nameは3〜24文字の英小文字・数字で指定してください。"
  }
}

variable "tags" {
  description = "Resource GroupとStorage Accountへ付ける共通タグ。"
  type        = map(string)
  default = {
    project     = "AzureDataTransformationLab"
    environment = "learning"
    managed_by  = "terraform"
  }
  nullable = false
}
