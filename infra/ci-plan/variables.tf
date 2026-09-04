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

variable "oidc_subject_prefix" {
  description = "GitHub OIDC APIが返した対象リポジトリのsub_claim_prefix。"
  type        = string
  nullable    = false
  validation {
    condition     = can(regex("^repo:Ries630(@[0-9]+)?/AzureDataTransformationLab(@[0-9]+)?$", var.oidc_subject_prefix))
    error_message = "対象リポジトリのOIDC subject prefixを指定してください。"
  }
}
