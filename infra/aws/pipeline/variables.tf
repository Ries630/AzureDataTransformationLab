variable "aws_region" {
  type    = string
  default = "ap-northeast-1"
}
variable "expected_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "対象AWSアカウントIDを12桁で指定してください。"
  }
}
variable "name" {
  type    = string
  default = "adtl"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.name))
    error_message = "名前は英小文字で始まる3〜25文字にしてください。"
  }
}
variable "bucket_name" {
  type = string
}
variable "create_bucket" {
  type    = bool
  default = true
}
variable "existing_bucket_eventbridge_enabled" {
  type    = bool
  default = false
}
variable "lambda_zip_path" {
  type = string
}
variable "lambda_architecture" {
  type    = string
  default = "arm64"
  validation {
    condition     = contains(["arm64", "x86_64"], var.lambda_architecture)
    error_message = "arm64またはx86_64を指定してください。"
  }
}
variable "lambda_runtime" {
  type    = string
  default = "python3.14"
}
variable "log_retention_days" {
  type    = number
  default = 14
}
variable "object_retention_days" {
  type    = number
  default = 30
  validation {
    condition     = var.object_retention_days >= 1
    error_message = "保存期間は1日以上にしてください。"
  }
}
variable "notification_email" {
  type    = string
  default = null
}
variable "workflow_timeout_seconds" {
  type    = number
  default = 1800
}
variable "lock_wait_seconds" {
  type    = number
  default = 900
}
variable "crawler_wait_seconds" {
  type    = number
  default = 600
}
variable "glue_timeout_minutes" {
  type    = number
  default = 10
}
variable "data_prefix" {
  type    = string
  default = ""
  validation {
    condition     = var.data_prefix == "" || can(regex("^[a-z][a-z0-9-]{2,40}/$", var.data_prefix))
    error_message = "data_prefixは英小文字で始まる3〜41文字の単一namespaceと末尾/にしてください。"
  }
}
