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

variable "operator_object_id" {
  description = "Storageを操作するユーザーのObject ID。CIのplanでは実行Identityと分離して指定し、ローカルでは省略できる。"
  type        = string
  default     = null
  sensitive   = true

  validation {
    condition     = var.operator_object_id == null || can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.operator_object_id))
    error_message = "operator_object_idにはユーザーの有効なObject IDを指定してください。"
  }
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

variable "functions_enabled" {
  description = "Azure Functionsの学習用基盤を作成する。Storage再構築だけのplanではfalseのままにする。"
  type        = bool
  default     = false
  nullable    = false
}

variable "function_app_name" {
  description = "Flex Consumption Function App名。省略時はstorage_account_nameから導出する。"
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.function_app_name == null || (
      length(var.function_app_name) >= 2 && length(var.function_app_name) <= 32 &&
      can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", var.function_app_name))
    )
    error_message = "function_app_nameは英小文字・数字・ハイフンで2〜32文字、先頭と末尾は英小文字または数字で指定してください。"
  }
}

variable "function_plan_name" {
  description = "Flex ConsumptionのApp Service Plan名。省略時はstorage_account_nameから導出する。"
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.function_plan_name == null || can(regex("^[a-z0-9-]{1,40}$", var.function_plan_name))
    error_message = "function_plan_nameは英小文字・数字・ハイフンで1〜40文字で指定してください。"
  }
}

variable "function_storage_account_name" {
  description = "Functionsのhostとdeployment専用Storage Account名。省略時はstorage_account_nameから導出する。"
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.function_storage_account_name == null || can(regex("^[a-z0-9]{3,24}$", var.function_storage_account_name))
    error_message = "function_storage_account_nameは3〜24文字の英小文字・数字で指定してください。"
  }
}

variable "function_identity_name" {
  description = "Functionsのhostとdeploymentに使うUser Assigned Managed Identity名。省略時はstorage_account_nameから導出する。"
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.function_identity_name == null || can(regex("^[a-zA-Z0-9][a-zA-Z0-9-_]{1,127}$", var.function_identity_name))
    error_message = "function_identity_nameは英数字で始まる2〜128文字の英数字・ハイフン・アンダースコアで指定してください。"
  }
}
