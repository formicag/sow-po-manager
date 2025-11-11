# Terraform Outputs

# S3 Outputs
output "documents_bucket_name" {
  description = "Name of the S3 bucket for document storage"
  value       = aws_s3_bucket.documents.id
}

output "documents_bucket_arn" {
  description = "ARN of the S3 bucket for document storage"
  value       = aws_s3_bucket.documents.arn
}

# DynamoDB Outputs
output "dynamodb_table_name" {
  description = "Name of the DynamoDB table"
  value       = aws_dynamodb_table.sow_documents.name
}

output "dynamodb_table_arn" {
  description = "ARN of the DynamoDB table"
  value       = aws_dynamodb_table.sow_documents.arn
}

# SQS Queue URLs
output "extract_text_queue_url" {
  description = "URL of the extract-text SQS queue"
  value       = aws_sqs_queue.extract_text.url
}

output "chunk_queue_url" {
  description = "URL of the chunk-and-embed SQS queue"
  value       = aws_sqs_queue.chunk.url
}

output "extraction_queue_url" {
  description = "URL of the extraction SQS queue"
  value       = aws_sqs_queue.extraction.url
}

output "validation_queue_url" {
  description = "URL of the validation SQS queue"
  value       = aws_sqs_queue.validation.url
}

output "save_queue_url" {
  description = "URL of the save-metadata SQS queue"
  value       = aws_sqs_queue.save.url
}

# Lambda Function ARNs
output "get_upload_link_function_arn" {
  description = "ARN of the get-upload-link Lambda function"
  value       = aws_lambda_function.get_upload_link.arn
}

output "extract_text_function_arn" {
  description = "ARN of the extract-text Lambda function"
  value       = aws_lambda_function.extract_text.arn
}

output "search_api_function_arn" {
  description = "ARN of the search-api Lambda function"
  value       = aws_lambda_function.search_api.arn
}

# EventBridge Rule
output "s3_event_rule_arn" {
  description = "ARN of the EventBridge rule for S3 events"
  value       = aws_cloudwatch_event_rule.s3_upload.arn
}

# Unique suffix for resource naming
output "resource_suffix" {
  description = "Random suffix used for unique resource naming"
  value       = random_string.suffix.result
}

# API Gateway URL (if created)
# output "api_gateway_url" {
#   description = "URL of the API Gateway endpoint"
#   value       = aws_apigatewayv2_api.main.api_endpoint
# }
