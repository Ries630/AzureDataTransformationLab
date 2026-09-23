variable "subscription_id" {
  description = "Personal-SandboxのSubscription ID。環境変数から指定する。"
  type        = string
  sensitive   = true
  nullable    = false
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "対象SubscriptionのUUIDを指定してください。"
  }
}

variable "state_resource_group_name" {
  description = "作成済みstate保存先のResource Group名。Identityの配置先にも使う。"
  type        = string
  nullable    = false
}

variable "state_storage_account_name" {
  description = "作成済みstate保存先のStorage Account名。"
  type        = string
  nullable    = false
}

variable "lab_access_enabled" {
  description = "学習環境へのCI読み取り接続を有効にする。後片付け時だけfalseにして権限を解除する。"
  type        = bool
  default     = true
  nullable    = false
}

variable "lab_resource_group_name" {
  description = "planが読み取る学習用Resource Group名。"
  type        = string
  nullable    = false
}

variable "lab_storage_account_name" {
  description = "filesystemを読み取る学習用Storage Account名。"
  type        = string
  nullable    = false
}

variable "functions_access_enabled" {
  description = "既存のFunction AppをCI planのrefresh対象にする。"
  type        = bool
  default     = false
  nullable    = false
}

variable "function_app_name" {
  description = "既存のFlex Consumption Function App名。省略時はlab_storage_account_nameから導出する。"
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

variable "oidc_subject_prefix" {
  description = "GitHub OIDC APIが返した対象リポジトリのsub_claim_prefix。"
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^repo:Ries630(@[0-9]+)?/AzureDataTransformationLab(@[0-9]+)?$", var.oidc_subject_prefix))
    error_message = "対象リポジトリのOIDC subject prefixを指定してください。"
  }
}
