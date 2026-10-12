mock_provider "aws" {
  mock_data "aws_caller_identity" { defaults = { account_id = "123456789012" } }
  mock_data "aws_partition" { defaults = { partition = "aws" } }
  mock_data "aws_s3_bucket" { defaults = { bucket_region = "ap-northeast-1" } }
}
variables {
  expected_account_id = "123456789012"
  bucket_name         = "adtl-test-bucket"
  lambda_zip_path     = "tests/fixture.zip"
}
run "owned_bucket" {
  command = plan
  assert {
    condition     = aws_sfn_state_machine.pipeline.type == "STANDARD" && aws_glue_job.pipeline.glue_version == "5.1" && aws_glue_job.pipeline.number_of_workers == 2 && aws_glue_job.pipeline.max_retries == 0
    error_message = "Glue費用と再実行境界、Standard契約を維持してください。"
  }
  assert {
    condition     = aws_dynamodb_table.state.billing_mode == "PAY_PER_REQUEST" && aws_dynamodb_table.state.hash_key == "inputId"
    error_message = "状態管理のキーとオンデマンド課金が必要です。"
  }
  assert {
    condition     = aws_s3_bucket_notification.pipeline[0].eventbridge && aws_lambda_function.pipeline.architectures == tolist(["arm64"])
    error_message = "所有bucketのEventBridgeとLambdaの対象CPUが必要です。"
  }
  assert {
    condition     = jsondecode(aws_cloudwatch_event_rule.landing.event_pattern).detail.object.key[0].wildcard == "landing/*.csv"
    error_message = "出力から再起動しないようCSV入力だけに限定してください。"
  }
}
run "existing_bucket_untouched" {
  command = plan
  variables {
    create_bucket                       = false
    existing_bucket_eventbridge_enabled = true
    data_prefix                         = "team-ries/"
  }
  assert {
    condition     = length(aws_s3_bucket.pipeline) == 0 && length(aws_s3_bucket_notification.pipeline) == 0 && length(aws_s3_bucket_lifecycle_configuration.pipeline) == 0 && length(aws_s3_bucket_public_access_block.pipeline) == 0 && length(aws_s3_bucket_server_side_encryption_configuration.pipeline) == 0
    error_message = "既存bucket全体の設定を変更してはいけません。"
  }
  assert {
    condition     = alltrue([for arn in local.object_arns : startswith(arn, "arn:aws:s3:::adtl-test-bucket/team-ries/")]) && jsondecode(aws_cloudwatch_event_rule.landing.event_pattern).detail.object.key[0].wildcard == "team-ries/landing/*.csv" && aws_s3_object.glue.key == "team-ries/artifacts/transform_orders.py" && aws_lambda_function.pipeline.environment[0].variables.DATA_PREFIX == "team-ries/"
    error_message = "共有bucketのIAM・入力イベント・配置物・Lambdaを自分のnamespaceへ制限してください。"
  }
}
run "reject_missing_namespace" {
  command = plan
  variables {
    create_bucket                       = false
    existing_bucket_eventbridge_enabled = true
  }
  expect_failures = [terraform_data.guard]
}
run "reject_unconfirmed_existing_bucket" {
  command = plan
  variables { create_bucket = false }
  expect_failures = [terraform_data.guard]
}
run "reject_wrong_account" {
  command = plan
  variables { expected_account_id = "999999999999" }
  expect_failures = [terraform_data.guard]
}
run "reject_wrong_bucket_region" {
  command = plan
  variables {
    create_bucket                       = false
    existing_bucket_eventbridge_enabled = true
    data_prefix                         = "team-ries/"
  }
  override_data {
    target = data.aws_s3_bucket.existing[0]
    values = { bucket_region = "us-east-1" }
  }
  expect_failures = [data.aws_s3_bucket.existing[0]]
}
