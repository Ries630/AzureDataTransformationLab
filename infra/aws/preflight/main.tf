# AWS 0 の確認キット。data source の読み取りと権限シミュレーションだけを行い、
# リソースは一切作成しない（resource ブロックを含めないこと）。

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

data "aws_partition" "current" {}

# assumed-role 形式の ARN を発行元ロールの ARN へ変換する。
# SSO や AssumeRole 経由でもシミュレーション対象を正しいロールに向けるため。
data "aws_iam_session_context" "current" {
  arn = data.aws_caller_identity.current.arn
}

locals {
  # AWS版で作成・更新・削除する予定のサービス操作。学習計画の対象サービスに合わせる。
  checked_actions = [
    "s3:CreateBucket",
    "s3:PutBucketPolicy",
    "s3:PutBucketVersioning",
    "s3:PutBucketNotification",
    "s3:PutEncryptionConfiguration",
    "s3:PutLifecycleConfiguration",
    "s3:PutBucketPublicAccessBlock",
    "s3:PutBucketTagging",
    "s3:DeleteBucket",
    "s3:PutObject",
    "s3:GetObject",
    "s3:DeleteObject",
    "s3:ListBucket",
    "iam:CreateRole",
    "iam:PutRolePolicy",
    "iam:AttachRolePolicy",
    "iam:DeleteRole",
    "iam:TagRole",
    "iam:PassRole",
    "lambda:CreateFunction",
    "lambda:UpdateFunctionCode",
    "lambda:DeleteFunction",
    "lambda:TagResource",
    "states:CreateStateMachine",
    "states:UpdateStateMachine",
    "states:DeleteStateMachine",
    "states:StartExecution",
    "states:TagResource",
    "events:PutRule",
    "events:PutTargets",
    "events:RemoveTargets",
    "events:DeleteRule",
    "events:TagResource",
    "glue:CreateDatabase",
    "glue:CreateCrawler",
    "glue:CreateJob",
    "glue:StartCrawler",
    "glue:StartJobRun",
    "glue:DeleteJob",
    "glue:DeleteCrawler",
    "glue:TagResource",
    "dynamodb:CreateTable",
    "dynamodb:DeleteTable",
    "dynamodb:TagResource",
    "sqs:CreateQueue",
    "sqs:DeleteQueue",
    "sqs:TagQueue",
    "sns:CreateTopic",
    "sns:Subscribe",
    "sns:DeleteTopic",
    "sns:TagResource",
    "logs:CreateLogGroup",
    "logs:PutRetentionPolicy",
    "logs:DeleteLogGroup",
    "cloudwatch:PutMetricAlarm",
    "cloudwatch:DeleteAlarms",
    "kms:CreateKey",
  ]

  issuer_arn = data.aws_iam_session_context.current.issuer_arn
}

# 実行主体（発行元ロールまたはユーザー）の既存ポリシーで、上記操作をシミュレートする。
# resource_arns を省略すると "*"（全リソース）としてシミュレートされる。
# リソースARNは未確定のため省略する。implicitDenyは権限不足と断定できない。
# なお "*" を明示指定すると provider 側のARN検証でエラーになるため省略する。
data "aws_iam_principal_policy_simulation" "deploy" {
  policy_source_arn = local.issuer_arn
  action_names      = local.checked_actions
}
