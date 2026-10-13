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

variable "data_factory_enabled" {
  description = "Azure Data Factoryの学習用基盤を作成する。Functions基盤（functions_enabled）の有効化が前提。"
  type        = bool
  default     = false
  nullable    = false
}

variable "monitoring_enabled" {
  description = "Phase 5の監視・Pipeline失敗通知を作成する。"
  type        = bool
  default     = false
  nullable    = false

  validation {
    condition     = !var.monitoring_enabled || (var.functions_enabled && var.data_factory_enabled)
    error_message = "monitoring_enabledはFunctionsとData Factoryを有効にしてから指定してください。"
  }
}

variable "monitoring_notification_email" {
  description = "Pipeline失敗通知を送る宛先メールアドレス。"
  type        = string
  default     = ""
  sensitive   = true
  nullable    = false

  validation {
    condition     = !var.monitoring_enabled || can(regex("^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$", var.monitoring_notification_email))
    error_message = "monitoring_enabledの場合、monitoring_notification_emailに有効なメールアドレスを指定してください。"
  }
}

variable "budget_enabled" {
  description = "Personal-Sandbox Subscription全体の月次Cost Budgetを作成する。"
  type        = bool
  default     = false
  nullable    = false

  validation {
    condition     = !var.budget_enabled || var.monitoring_enabled
    error_message = "budget_enabledはmonitoring_enabledを有効にしてから指定してください。"
  }
}

variable "monitoring_budget_start_date" {
  description = "Budget期間の開始月の初日をUTCの固定値で指定する。既存Budgetの開始月は維持する。"
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.monitoring_budget_start_date == null || (
      can(regex("^[0-9]{4}-[0-9]{2}-01T00:00:00Z$", var.monitoring_budget_start_date)) &&
      can(formatdate("YYYY-MM", var.monitoring_budget_start_date))
    )
    error_message = "monitoring_budget_start_dateはYYYY-MM-01T00:00:00Z形式で指定してください。"
  }

  validation {
    condition = !var.budget_enabled || (
      var.monitoring_budget_start_date != null &&
      can(regex("^[0-9]{4}-[0-9]{2}-01T00:00:00Z$", var.monitoring_budget_start_date)) &&
      can(formatdate("YYYY-MM", var.monitoring_budget_start_date))
    )
    error_message = "Budget有効時は開始月の初日のUTC日時をmonitoring_budget_start_dateに明示してください。"
  }
}

variable "schema_evolution_lab_enabled" {
  description = "Phase 4のSchema Evolution比較用Data Flow（Tolerant・Drift・Drift＋型推論）を作成する。Data Factory基盤（data_factory_enabled）の有効化が前提。"
  type        = bool
  default     = false
  nullable    = false

  validation {
    condition     = !var.schema_evolution_lab_enabled || var.data_factory_enabled
    error_message = "schema_evolution_lab_enabledはData Factory基盤（data_factory_enabled）を有効にしてから指定してください。"
  }
}

variable "data_factory_name" {
  description = "Data Factory名。省略時はstorage_account_nameから導出する。"
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.data_factory_name == null || can(regex("^[A-Za-z0-9][A-Za-z0-9-]{1,62}$", var.data_factory_name))
    error_message = "data_factory_nameは英数字始まりの英数字・ハイフンで3〜63文字で指定してください。"
  }
}

variable "data_factory_ir_name" {
  description = "Data Flow用のAzure Integration Runtime名。省略時はstorage_account_nameから導出する。"
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.data_factory_ir_name == null || can(regex("^[A-Za-z0-9][A-Za-z0-9_-]{2,62}$", var.data_factory_ir_name))
    error_message = "data_factory_ir_nameは英数字始まりの英数字・ハイフン・アンダースコアで3〜63文字で指定してください。"
  }
}
