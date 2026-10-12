# AWSへ接続せず、権限追加の誤案内とIAMユーザー名の欠落を検出する。
mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012", arn = "arn:aws:iam::123456789012:user/team/operator" }
  }
  mock_data "aws_region" {
    defaults = { region = "ap-northeast-1" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_data "aws_iam_session_context" {
    defaults = { issuer_arn = "arn:aws:iam::123456789012:user/team/operator", issuer_name = "" }
  }
  mock_data "aws_iam_principal_policy_simulation" {
    defaults = {
      results = [
        { action_name = "s3:PutObject", decision = "implicitDeny" },
        { action_name = "iam:CreateRole", decision = "explicitDeny" },
        { action_name = "events:RemoveTargets", decision = "allowed" },
      ]
    }
  }
}

run "separate_unknown_from_denial" {
  command = plan
  assert {
    condition     = output.inconclusive_actions == tolist(["s3:PutObject"]) && output.explicitly_denied_actions == tolist(["iam:CreateRole"])
    error_message = "ARN未指定のimplicitDenyを権限不足と案内してはいけません。"
  }
  assert {
    condition     = output.issuer_name == "operator" && output.principal_type == "user"
    error_message = "パス付きIAMユーザーの名前も共有用出力へ含めてください。"
  }
  assert {
    condition     = contains(local.checked_actions, "events:RemoveTargets")
    error_message = "後片付けに必要なEventBridgeターゲット削除操作が必要です。"
  }
}

run "keep_assumed_role_name" {
  command = plan
  override_data {
    target = data.aws_iam_session_context.current
    values = { issuer_arn = "arn:aws:iam::123456789012:role/team/learner", issuer_name = "learner" }
  }
  assert {
    condition     = output.issuer_name == "learner" && output.principal_type == "role"
    error_message = "SSO/AssumeRoleの発行元ロール名を維持してください。"
  }
}
