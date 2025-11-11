# ===========================================================================
# Observability: CloudWatch Alarms + Log Retention
# ===========================================================================

variable "alarm_email" {
  description = "Email address for CloudWatch alarm notifications"
  type        = string
  default     = "gianluca.formica@gmail.com"  # Update with your email
}

# SNS topic for operational alerts
resource "aws_sns_topic" "ops_alerts" {
  name = "${var.project_name}-ops-alerts"
  tags = local.common_tags
}

resource "aws_sns_topic_subscription" "ops_email" {
  topic_arn = aws_sns_topic.ops_alerts.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# Lambda error alarms (one per function)
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = toset([
    aws_lambda_function.extract_text.function_name,
    aws_lambda_function.chunk_and_embed.function_name,
    aws_lambda_function.extract_structured_data.function_name,
    aws_lambda_function.validate_data.function_name,
    aws_lambda_function.save_metadata.function_name,
  ])

  alarm_name          = "${each.value}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300  # 5 minutes
  statistic           = "Sum"
  dimensions = {
    FunctionName = each.value
  }
  alarm_description = "Lambda ${each.value} has errors"
  alarm_actions     = [aws_sns_topic.ops_alerts.arn]
  tags              = local.monitoring_tags
}

# SQS message age alarms (messages stuck for >10 minutes)
resource "aws_cloudwatch_metric_alarm" "sqs_oldest_message" {
  for_each = toset([
    aws_sqs_queue.extract_text.name,
    aws_sqs_queue.chunk.name,
    aws_sqs_queue.extraction.name,
    aws_sqs_queue.validation.name,
    aws_sqs_queue.save.name,
  ])

  alarm_name          = "${each.value}-message-age"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 600  # 10 minutes
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  dimensions = {
    QueueName = each.value
  }
  alarm_description = "Messages in ${each.value} aging >10 minutes"
  alarm_actions     = [aws_sns_topic.ops_alerts.arn]
  tags              = local.monitoring_tags
}

# DLQ message alarms (any visible messages in DLQ)
resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  for_each = toset([
    aws_sqs_queue.extract_text_dlq.name,
    aws_sqs_queue.chunk_dlq.name,
    aws_sqs_queue.extraction_dlq.name,
    aws_sqs_queue.validation_dlq.name,
    aws_sqs_queue.save_dlq.name,
  ])

  alarm_name          = "${each.value}-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  dimensions = {
    QueueName = each.value
  }
  alarm_description = "DLQ ${each.value} has failed messages"
  alarm_actions     = [aws_sns_topic.ops_alerts.arn]
  tags              = local.monitoring_tags
}

# CloudWatch log retention (7 days for cost efficiency)
# NOTE: Log groups are automatically created by Lambda, so we use lifecycle to avoid conflicts
resource "aws_cloudwatch_log_group" "lambda_logs" {
  for_each = toset([
    "/aws/lambda/${aws_lambda_function.extract_text.function_name}",
    "/aws/lambda/${aws_lambda_function.chunk_and_embed.function_name}",
    "/aws/lambda/${aws_lambda_function.extract_structured_data.function_name}",
    "/aws/lambda/${aws_lambda_function.validate_data.function_name}",
    "/aws/lambda/${aws_lambda_function.save_metadata.function_name}",
    "/aws/lambda/${aws_lambda_function.get_upload_link.function_name}",
    "/aws/lambda/${aws_lambda_function.search_api.function_name}",
  ])

  name              = each.value
  retention_in_days = 7  # 7 days (reduce from unlimited for cost)
  tags              = local.monitoring_tags

  lifecycle {
    ignore_changes = [name]  # Prevent recreation if already exists
  }
}
