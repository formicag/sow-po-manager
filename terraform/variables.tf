# Project Variables

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "eu-west-1"
}

variable "project_name" {
  description = "Project name used for resource naming and tagging"
  type        = string
  default     = "sow-po-manager"
}

variable "owner_email" {
  description = "Email of the project owner"
  type        = string
  default     = "gianluca@colibri.com"
}

variable "environment" {
  description = "Environment name (e.g., production, staging, dev)"
  type        = string
  default     = "production"
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention period in days"
  type        = number
  default     = 7
}

variable "lambda_timeout" {
  description = "Default Lambda function timeout in seconds"
  type        = number
  default     = 300
}

variable "lambda_memory" {
  description = "Default Lambda function memory in MB"
  type        = number
  default     = 512
}

variable "sqs_visibility_timeout" {
  description = "SQS message visibility timeout in seconds"
  type        = number
  default     = 300
}

variable "sqs_max_receive_count" {
  description = "Maximum number of receives before moving to DLQ"
  type        = number
  default     = 3
}

variable "dynamodb_read_capacity" {
  description = "DynamoDB read capacity units (on-demand mode ignores this)"
  type        = number
  default     = 5
}

variable "dynamodb_write_capacity" {
  description = "DynamoDB write capacity units (on-demand mode ignores this)"
  type        = number
  default     = 5
}

variable "enable_point_in_time_recovery" {
  description = "Enable DynamoDB Point-in-Time Recovery (PITR)"
  type        = bool
  default     = true
}

variable "gemini_api_key" {
  description = "Google Gemini API key for document extraction"
  type        = string
  sensitive   = true
}
