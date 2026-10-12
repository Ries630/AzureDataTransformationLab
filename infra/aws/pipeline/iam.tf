locals {
  trust        = { for service in ["lambda", "glue", "states", "events"] : service => jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "${service}.amazonaws.com" }, Action = "sts:AssumeRole" }] }) }
  catalog_arns = ["${local.resource_arn}:glue:${var.aws_region}:${local.account}:catalog", "${local.resource_arn}:glue:${var.aws_region}:${local.account}:database/${aws_glue_catalog_database.pipeline.name}", "${local.resource_arn}:glue:${var.aws_region}:${local.account}:table/${aws_glue_catalog_database.pipeline.name}/*"]
}
resource "aws_iam_role" "lambda" {
  name               = "${var.name}-lambda"
  assume_role_policy = local.trust.lambda
}
resource "aws_iam_role" "glue" {
  name               = "${var.name}-glue"
  assume_role_policy = local.trust.glue
}
resource "aws_iam_role" "workflow" {
  name               = "${var.name}-workflow"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "states.amazonaws.com" }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = var.expected_account_id }, ArnLike = { "aws:SourceArn" = local.machine_arn } } }] })
}
resource "aws_iam_role" "events" {
  name               = "${var.name}-events"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "events.amazonaws.com" }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = var.expected_account_id }, ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.landing.arn } } }] })
}
resource "aws_iam_role_policy" "lambda" {
  role = aws_iam_role.lambda.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.lambda.arn}:*" },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = local.object_arns },
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = [for prefix in ["validated", "rejected", "output"] : "${local.bucket_arn}/${var.data_prefix}${prefix}/*"] },
    { Effect = "Allow", Action = ["s3:DeleteObject"], Resource = "${local.bucket_arn}/${var.data_prefix}staging/*" },
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = local.bucket_arn, Condition = { StringLike = { "s3:prefix" = [for prefix in ["staging", "output"] : "${var.data_prefix}${prefix}/*"] } } },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"], Resource = aws_dynamodb_table.state.arn },
    { Effect = "Allow", Action = ["states:DescribeExecution"], Resource = "${local.resource_arn}:states:${var.aws_region}:${local.account}:execution:${var.name}:*" },
    { Effect = "Allow", Action = ["glue:GetCrawler", "glue:UpdateCrawler", "glue:StartCrawler"], Resource = local.crawler_arn },
    { Effect = "Allow", Action = ["glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"], Resource = local.job_arn },
    { Effect = "Allow", Action = ["iam:PassRole"], Resource = aws_iam_role.glue.arn, Condition = { StringEquals = { "iam:PassedToService" = "glue.amazonaws.com" } } }
  ] })
}
resource "aws_iam_role_policy" "glue" {
  role = aws_iam_role.glue.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = [for prefix in ["validated", "artifacts"] : "${local.bucket_arn}/${var.data_prefix}${prefix}/*"] },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:DeleteObject"], Resource = "${local.bucket_arn}/${var.data_prefix}staging/*" },
    { Effect = "Allow", Action = ["s3:GetBucketLocation"], Resource = local.bucket_arn },
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = local.bucket_arn, Condition = { StringLike = { "s3:prefix" = [for prefix in ["validated", "artifacts", "staging"] : "${var.data_prefix}${prefix}/*"] } } },
    { Effect = "Allow", Action = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables", "glue:CreateTable", "glue:UpdateTable", "glue:BatchCreatePartition", "glue:CreatePartition", "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition", "glue:UpdatePartition"], Resource = local.catalog_arns },
    { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${local.resource_arn}:logs:${var.aws_region}:${local.account}:log-group:/aws-glue/jobs/${var.name}/*" },
    # Crawlerのlog groupはAWSの共有固定名。保持設定は変更せず自分のstreamだけへ書く。
    { Effect = "Allow", Action = ["logs:CreateLogGroup"], Resource = "${local.resource_arn}:logs:${var.aws_region}:${local.account}:log-group:/aws-glue/crawlers" },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${local.resource_arn}:logs:${var.aws_region}:${local.account}:log-group:/aws-glue/crawlers:log-stream:${var.name}*" }
  ] })
}
resource "aws_iam_role_policy" "workflow" {
  role = aws_iam_role.workflow.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.pipeline.arn },
    { Effect = "Allow", Action = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"], Resource = local.job_arn },
    # CloudWatch Logs配信APIはリソース単位の権限制限を提供しない。
    { Effect = "Allow", Action = ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"], Resource = "*" }
  ] })
}
resource "aws_iam_role_policy" "events" {
  role   = aws_iam_role.events.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "states:StartExecution", Resource = local.machine_arn }] })
}
