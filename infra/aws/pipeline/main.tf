provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]
  default_tags {
    tags = { Project = "AzureDataTransformationLab", ManagedBy = "Terraform" }
  }
}
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
locals {
  account      = data.aws_caller_identity.current.account_id
  partition    = data.aws_partition.current.partition
  bucket_arn   = "arn:${local.partition}:s3:::${var.bucket_name}"
  resource_arn = "arn:${local.partition}"
  object_arns  = [for prefix in ["landing", "validated", "rejected", "staging", "output", "artifacts"] : "${local.bucket_arn}/${var.data_prefix}${prefix}/*"]
  crawler_arn  = "${local.resource_arn}:glue:${var.aws_region}:${local.account}:crawler/${var.name}"
  job_arn      = "${local.resource_arn}:glue:${var.aws_region}:${local.account}:job/${var.name}"
  machine_arn  = "${local.resource_arn}:states:${var.aws_region}:${local.account}:stateMachine:${var.name}"
}
resource "terraform_data" "guard" {
  lifecycle {
    precondition {
      condition     = var.create_bucket || (var.existing_bucket_eventbridge_enabled && var.data_prefix != "")
      error_message = "既存bucketは会社側のEventBridge有効化確認と自分用data_prefix指定が必要です。"
    }
    precondition {
      condition     = local.account == var.expected_account_id
      error_message = "対象AWSアカウントが一致しません。"
    }
  }
}
resource "aws_s3_bucket" "pipeline" {
  count         = var.create_bucket ? 1 : 0
  bucket        = var.bucket_name
  force_destroy = false
}
resource "aws_s3_bucket_public_access_block" "pipeline" {
  count                   = var.create_bucket ? 1 : 0
  bucket                  = aws_s3_bucket.pipeline[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "pipeline" {
  count  = var.create_bucket ? 1 : 0
  bucket = aws_s3_bucket.pipeline[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
resource "aws_s3_bucket_notification" "pipeline" {
  count       = var.create_bucket ? 1 : 0
  bucket      = aws_s3_bucket.pipeline[0].id
  eventbridge = true
}
resource "aws_s3_bucket_lifecycle_configuration" "pipeline" {
  count  = var.create_bucket ? 1 : 0
  bucket = aws_s3_bucket.pipeline[0].id
  dynamic "rule" {
    for_each = toset(["landing", "validated", "rejected", "staging", "output"])
    content {
      id     = "expire-${rule.value}"
      status = "Enabled"
      filter { prefix = "${var.data_prefix}${rule.value}/" }
      expiration { days = var.object_retention_days }
      abort_incomplete_multipart_upload { days_after_initiation = 1 }
    }
  }
}
resource "aws_s3_object" "glue" {
  bucket      = var.bucket_name
  key         = "${var.data_prefix}artifacts/transform_orders.py"
  source      = "${path.module}/../../../glue/transform_orders.py"
  source_hash = filemd5("${path.module}/../../../glue/transform_orders.py")
  depends_on  = [aws_s3_bucket.pipeline, terraform_data.guard, data.aws_s3_bucket.existing]
}
resource "aws_dynamodb_table" "state" {
  name         = "${var.name}-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "inputId"
  attribute {
    name = "inputId"
    type = "S"
  }
}
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
}
resource "aws_cloudwatch_log_group" "workflow" {
  name              = "/aws/vendedlogs/states/${var.name}"
  retention_in_days = var.log_retention_days
}
resource "aws_cloudwatch_log_group" "glue" {
  for_each          = toset(["error", "output"])
  name              = "/aws-glue/jobs/${var.name}/${each.value}"
  retention_in_days = var.log_retention_days
}
resource "aws_glue_catalog_database" "pipeline" {
  name = replace(var.name, "-", "_")
}
resource "aws_glue_crawler" "pipeline" {
  name          = var.name
  database_name = aws_glue_catalog_database.pipeline.name
  role          = aws_iam_role.glue.arn
  s3_target {
    path       = "s3://${var.bucket_name}/${var.data_prefix}validated/"
    exclusions = ["**/validation.json"]
  }
  schema_change_policy {
    delete_behavior = "LOG"
    update_behavior = "UPDATE_IN_DATABASE"
  }
  depends_on = [aws_iam_role_policy.glue]
}
resource "aws_glue_job" "pipeline" {
  name              = var.name
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.1"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = var.glue_timeout_minutes
  max_retries       = 0
  execution_property { max_concurrent_runs = 1 }
  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${var.bucket_name}/${aws_s3_object.glue.key}"
  }
  default_arguments = {
    "--job-language"                     = "python"
    "--enable-continuous-cloudwatch-log" = "true"
    "--custom-logGroup-prefix"           = "/aws-glue/jobs/${var.name}"
  }
}
resource "aws_lambda_function" "pipeline" {
  function_name    = var.name
  role             = aws_iam_role.lambda.arn
  handler          = "handler.handler"
  runtime          = var.lambda_runtime
  architectures    = [var.lambda_architecture]
  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)
  timeout          = 120
  memory_size      = 512
  environment {
    variables = {
      BUCKET_NAME           = var.bucket_name
      DATA_PREFIX           = var.data_prefix
      EXPECTED_BUCKET_OWNER = var.expected_account_id
      STATE_TABLE           = aws_dynamodb_table.state.name
      CRAWLER_NAME          = aws_glue_crawler.pipeline.name
      GLUE_JOB_NAME         = aws_glue_job.pipeline.name
      LOCK_WAIT_SECONDS     = tostring(var.lock_wait_seconds)
      CRAWLER_WAIT_SECONDS  = tostring(var.crawler_wait_seconds)
    }
  }
  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.lambda]
}
resource "aws_sfn_state_machine" "pipeline" {
  name     = var.name
  role_arn = aws_iam_role.workflow.arn
  type     = "STANDARD"
  definition = templatefile("${path.module}/../../../workflows/aws/pipeline.asl.json", {
    lambda_arn               = aws_lambda_function.pipeline.arn
    glue_job_name            = aws_glue_job.pipeline.name
    crawler_name             = aws_glue_crawler.pipeline.name
    workflow_timeout_seconds = var.workflow_timeout_seconds
  })
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.workflow.arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }
  depends_on = [aws_iam_role_policy.workflow]
}
resource "aws_sns_topic" "failures" { name = "${var.name}-failures" }
resource "aws_sns_topic_subscription" "email" {
  count     = var.notification_email == null ? 0 : 1
  topic_arn = aws_sns_topic.failures.arn
  protocol  = "email"
  endpoint  = var.notification_email
}
resource "aws_sqs_queue" "delivery" {
  name                      = "${var.name}-delivery-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}
resource "aws_cloudwatch_event_rule" "landing" {
  name = "${var.name}-landing"
  event_pattern = jsonencode({ source = ["aws.s3"], "detail-type" = ["Object Created"], detail = {
    bucket = { name = [var.bucket_name] }
    object = { key = [{ wildcard = "${var.data_prefix}landing/*.csv" }] }
  } })
}
resource "aws_cloudwatch_event_target" "pipeline" {
  rule     = aws_cloudwatch_event_rule.landing.name
  arn      = aws_sfn_state_machine.pipeline.arn
  role_arn = aws_iam_role.events.arn
  dead_letter_config { arn = aws_sqs_queue.delivery.arn }
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 3
  }
  depends_on = [aws_sqs_queue_policy.delivery, aws_iam_role_policy.events]
}
resource "aws_sqs_queue_policy" "delivery" {
  queue_url = aws_sqs_queue.delivery.id
  policy    = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "events.amazonaws.com" }, Action = "sqs:SendMessage", Resource = aws_sqs_queue.delivery.arn, Condition = { ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.landing.arn } } }] })
}
resource "aws_cloudwatch_metric_alarm" "execution" {
  for_each            = toset(["ExecutionsFailed", "ExecutionsTimedOut", "ExecutionsAborted"])
  alarm_name          = "${var.name}-${each.value}"
  namespace           = "AWS/States"
  metric_name         = each.value
  dimensions          = { StateMachineArn = aws_sfn_state_machine.pipeline.arn }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.failures.arn]
}
resource "aws_cloudwatch_metric_alarm" "delivery" {
  alarm_name          = "${var.name}-delivery-failed"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.delivery.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.failures.arn]
}
data "aws_s3_bucket" "existing" {
  count  = var.create_bucket ? 0 : 1
  bucket = var.bucket_name
  lifecycle {
    postcondition {
      condition     = self.bucket_region == var.aws_region
      error_message = "既存bucketのリージョンが対象AWSリージョンと一致しません。"
    }
  }
}
