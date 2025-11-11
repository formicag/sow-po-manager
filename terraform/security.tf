# ===========================================================================
# Security Polish: SSE + SSM for Secrets
# ===========================================================================

# S3 bucket encryption (SSE-S3)
resource "aws_s3_bucket_server_side_encryption_configuration" "documents_encryption" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"  # SSE-S3 (no extra cost)
    }
  }
}

# S3 block public access (defense in depth)
resource "aws_s3_bucket_public_access_block" "documents_block_public" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# NOTE: SQS encryption can be added to existing queues in sqs.tf
# For v1.5.0, we'll add it manually or in a future update to avoid queue recreation

# SSM Parameter for Gemini API key (for future migration)
resource "aws_ssm_parameter" "gemini_api_key" {
  name        = "/${var.project_name}/gemini-api-key"
  description = "Google Gemini API key for document extraction"
  type        = "SecureString"
  value       = var.gemini_api_key  # Set via TF_VAR_gemini_api_key

  tags = local.common_tags
}

# IAM policy to allow Lambdas to read from SSM
resource "aws_iam_role_policy" "lambda_ssm_access" {
  name = "${var.project_name}-lambda-ssm-access"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters"
        ]
        Resource = [
          aws_ssm_parameter.gemini_api_key.arn
        ]
      }
    ]
  })
}

# DynamoDB encryption (enabled by default with AWS managed keys, no extra cost)
# No explicit resource needed - DynamoDB uses SSE by default

# Variable for Gemini API key is defined in variables.tf
