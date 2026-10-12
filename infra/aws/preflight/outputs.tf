locals {
  account_id = data.aws_caller_identity.current.account_id

  # アカウントIDは末尾4桁だけを残してマスクする（共有結果に載せられるようにするため）。
  account_id_masked = "********${substr(local.account_id, 8, 4)}"

  principal_type = (
    can(regex(":role/", local.issuer_arn)) ? "role" :
    can(regex(":user/", local.issuer_arn)) ? "user" :
    "unknown"
  )

  denied_actions = sort([
    for r in data.aws_iam_principal_policy_simulation.deploy.results :
    r.action_name if r.decision != "allowed"
  ])

  allowed_action_count = length([
    for r in data.aws_iam_principal_policy_simulation.deploy.results :
    r if r.decision == "allowed"
  ])
}

output "account_id_masked" {
  description = "対象AWSアカウントID（末尾4桁以外をマスク）。共有してよい識別子。"
  value       = local.account_id_masked
}

output "region" {
  description = "会社の認証設定で解決されたAWSリージョン。"
  value       = data.aws_region.current.region
}

output "partition" {
  description = "対象環境のAWSパーティション（通常は aws）。"
  value       = data.aws_partition.current.partition
}

output "principal_type" {
  description = "実行主体の種別（role / user / unknown）。発行元ARNから判別。"
  value       = local.principal_type
}

output "issuer_name" {
  description = "実行主体のロール名またはユーザー名。ARNのアカウント部分は含まない。"
  value       = data.aws_iam_session_context.current.issuer_name
}

output "denied_actions" {
  description = "権限シミュレーションで allowed にならなかった操作の一覧（ソート済み）。管理者への依頼候補。"
  value       = local.denied_actions
}

output "allowed_action_count" {
  description = "権限シミュレーションで allowed と判定された操作数。"
  value       = local.allowed_action_count
}

output "checked_action_count" {
  description = "権限シミュレーションで確認した操作数。"
  value       = length(local.checked_actions)
}
