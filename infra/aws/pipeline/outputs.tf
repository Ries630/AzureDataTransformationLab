output "bucket_name" { value = var.bucket_name }
output "state_machine_arn" { value = aws_sfn_state_machine.pipeline.arn }
output "state_table" { value = aws_dynamodb_table.state.name }
output "crawler_name" { value = aws_glue_crawler.pipeline.name }
output "glue_job_name" { value = aws_glue_job.pipeline.name }
output "notification_topic_arn" { value = aws_sns_topic.failures.arn }
output "delivery_dlq_url" { value = aws_sqs_queue.delivery.url }
output "data_prefix" { value = var.data_prefix }
