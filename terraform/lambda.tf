# Lambda Functions Configuration
# All Lambda functions with IAM roles and permissions

# ============================================================================
# IAM ROLE - Common Lambda Execution Role
# ============================================================================

resource "aws_iam_role" "lambda_execution" {
  name = "${var.project_name}-lambda-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })

  tags = local.processing_tags
}

# Attach basic Lambda execution policy
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Custom policy for S3, DynamoDB, and SQS access
resource "aws_iam_role_policy" "lambda_custom" {
  name = "${var.project_name}-lambda-custom-policy"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = "${aws_s3_bucket.documents.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket"
        ]
        Resource = aws_s3_bucket.documents.arn
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.sow_documents.arn,
          "${aws_dynamodb_table.sow_documents.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = [
          aws_sqs_queue.extract_text.arn,
          aws_sqs_queue.chunk.arn,
          aws_sqs_queue.extraction.arn,
          aws_sqs_queue.validation.arn,
          aws_sqs_queue.save.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = "*"
      }
    ]
  })
}

# ============================================================================
# LAMBDA 1: Get Upload Link (Returns presigned S3 URL)
# ============================================================================

resource "aws_lambda_function" "get_upload_link" {
  filename         = "../dist/get_upload_link.zip"
  function_name    = "${var.project_name}-get-upload-link"
  role             = aws_iam_role.lambda_execution.arn
  handler          = "handler.lambda_handler"
  source_code_hash = fileexists("../dist/get_upload_link.zip") ? filebase64sha256("../dist/get_upload_link.zip") : "placeholder"
  runtime          = "python3.11"
  timeout          = 30
  memory_size      = 256

  environment {
    variables = {
      BUCKET_NAME = aws_s3_bucket.documents.id
    }
  }

  tags = local.processing_tags
}

resource "aws_cloudwatch_log_group" "get_upload_link" {
  name              = "/aws/lambda/${aws_lambda_function.get_upload_link.function_name}"
  retention_in_days = var.log_retention_days
  tags              = local.monitoring_tags
}

# ============================================================================
# LAMBDA 2: Extract Text (PDF → Text)
# ============================================================================

resource "aws_lambda_function" "extract_text" {
  filename         = "../dist/extract_text.zip"
  function_name    = "${var.project_name}-extract-text"
  role             = aws_iam_role.lambda_execution.arn
  handler          = "handler.lambda_handler"
  source_code_hash = fileexists("../dist/extract_text.zip") ? filebase64sha256("../dist/extract_text.zip") : "placeholder"
  runtime          = "python3.11"
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory

  environment {
    variables = {
      BUCKET_NAME      = aws_s3_bucket.documents.id
      NEXT_QUEUE_URL   = aws_sqs_queue.chunk.url
    }
  }

  tags = local.processing_tags
}

resource "aws_cloudwatch_log_group" "extract_text" {
  name              = "/aws/lambda/${aws_lambda_function.extract_text.function_name}"
  retention_in_days = var.log_retention_days
  tags              = local.monitoring_tags
}

# SQS trigger for extract_text Lambda
resource "aws_lambda_event_source_mapping" "extract_text" {
  event_source_arn = aws_sqs_queue.extract_text.arn
  function_name    = aws_lambda_function.extract_text.arn
  batch_size       = 1
}

# ============================================================================
# LAMBDA 3: Chunk and Embed (Text → Chunks + Embeddings)
# ============================================================================

resource "aws_lambda_function" "chunk_and_embed" {
  filename         = "../dist/chunk_and_embed.zip"
  function_name    = "${var.project_name}-chunk-and-embed"
  role             = aws_iam_role.lambda_execution.arn
  handler          = "handler.lambda_handler"
  source_code_hash = fileexists("../dist/chunk_and_embed.zip") ? filebase64sha256("../dist/chunk_and_embed.zip") : "placeholder"
  runtime          = "python3.11"
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory

  environment {
    variables = {
      BUCKET_NAME      = aws_s3_bucket.documents.id
      NEXT_QUEUE_URL   = aws_sqs_queue.extraction.url
      BEDROCK_REGION   = var.aws_region
      EMBED_MODEL_ID   = "amazon.titan-embed-text-v2:0"
      EMBED_S3_PREFIX  = "embeddings/"
      CHUNK_SIZE       = "1000"
      CHUNK_OVERLAP    = "200"
    }
  }

  tags = local.processing_tags
}

resource "aws_cloudwatch_log_group" "chunk_and_embed" {
  name              = "/aws/lambda/${aws_lambda_function.chunk_and_embed.function_name}"
  retention_in_days = var.log_retention_days
  tags              = local.monitoring_tags
}

# SQS trigger for chunk_and_embed Lambda
resource "aws_lambda_event_source_mapping" "chunk_and_embed" {
  event_source_arn = aws_sqs_queue.chunk.arn
  function_name    = aws_lambda_function.chunk_and_embed.arn
  batch_size       = 1
}

# ============================================================================
# LAMBDA 4: Extract Structured Data (LLM extraction with Gemini Flash)
# ============================================================================

resource "aws_lambda_function" "extract_structured_data" {
  filename         = "../dist/extract_structured_data.zip"
  function_name    = "${var.project_name}-extract-structured-data"
  role             = aws_iam_role.lambda_execution.arn
  handler          = "handler.lambda_handler"
  source_code_hash = fileexists("../dist/extract_structured_data.zip") ? filebase64sha256("../dist/extract_structured_data.zip") : "placeholder"
  runtime          = "python3.11"
  timeout          = var.lambda_timeout
  memory_size      = 1024

  environment {
    variables = {
      BUCKET_NAME      = aws_s3_bucket.documents.id
      NEXT_QUEUE_URL   = aws_sqs_queue.validation.url
      GEMINI_API_KEY   = var.gemini_api_key
    }
  }

  tags = local.processing_tags
}

resource "aws_cloudwatch_log_group" "extract_structured_data" {
  name              = "/aws/lambda/${aws_lambda_function.extract_structured_data.function_name}"
  retention_in_days = var.log_retention_days
  tags              = local.monitoring_tags
}

# SQS trigger for extract_structured_data Lambda
resource "aws_lambda_event_source_mapping" "extract_structured_data" {
  event_source_arn = aws_sqs_queue.extraction.arn
  function_name    = aws_lambda_function.extract_structured_data.arn
  batch_size       = 1
}

# ============================================================================
# LAMBDA 5: Validate Data (Business logic validation)
# ============================================================================

resource "aws_lambda_function" "validate_data" {
  filename         = "../dist/validate_data.zip"
  function_name    = "${var.project_name}-validate-data"
  role             = aws_iam_role.lambda_execution.arn
  handler          = "handler.lambda_handler"
  source_code_hash = fileexists("../dist/validate_data.zip") ? filebase64sha256("../dist/validate_data.zip") : "placeholder"
  runtime          = "python3.11"
  timeout          = var.lambda_timeout
  memory_size      = 256

  environment {
    variables = {
      NEXT_QUEUE_URL = aws_sqs_queue.save.url
    }
  }

  tags = local.processing_tags
}

resource "aws_cloudwatch_log_group" "validate_data" {
  name              = "/aws/lambda/${aws_lambda_function.validate_data.function_name}"
  retention_in_days = var.log_retention_days
  tags              = local.monitoring_tags
}

# SQS trigger for validate_data Lambda
resource "aws_lambda_event_source_mapping" "validate_data" {
  event_source_arn = aws_sqs_queue.validation.arn
  function_name    = aws_lambda_function.validate_data.arn
  batch_size       = 1
}

# ============================================================================
# LAMBDA 6: Save Metadata (Write to DynamoDB)
# ============================================================================

resource "aws_lambda_function" "save_metadata" {
  filename         = "../dist/save_metadata.zip"
  function_name    = "${var.project_name}-save-metadata"
  role             = aws_iam_role.lambda_execution.arn
  handler          = "handler.lambda_handler"
  source_code_hash = fileexists("../dist/save_metadata.zip") ? filebase64sha256("../dist/save_metadata.zip") : "placeholder"
  runtime          = "python3.11"
  timeout          = var.lambda_timeout
  memory_size      = 256

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.sow_documents.name
    }
  }

  tags = local.processing_tags
}

resource "aws_cloudwatch_log_group" "save_metadata" {
  name              = "/aws/lambda/${aws_lambda_function.save_metadata.function_name}"
  retention_in_days = var.log_retention_days
  tags              = local.monitoring_tags
}

# SQS trigger for save_metadata Lambda
resource "aws_lambda_event_source_mapping" "save_metadata" {
  event_source_arn = aws_sqs_queue.save.arn
  function_name    = aws_lambda_function.save_metadata.arn
  batch_size       = 1
}

# ============================================================================
# LAMBDA 7: Search API (Vector search)
# ============================================================================

resource "aws_lambda_function" "search_api" {
  filename         = "../dist/search_api.zip"
  function_name    = "${var.project_name}-search-api"
  role             = aws_iam_role.lambda_execution.arn
  handler          = "handler.lambda_handler"
  source_code_hash = fileexists("../dist/search_api.zip") ? filebase64sha256("../dist/search_api.zip") : "placeholder"
  runtime          = "python3.11"
  timeout          = 30
  memory_size      = 1024

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.sow_documents.name
    }
  }

  tags = local.search_tags
}

resource "aws_cloudwatch_log_group" "search_api" {
  name              = "/aws/lambda/${aws_lambda_function.search_api.function_name}"
  retention_in_days = var.log_retention_days
  tags              = local.monitoring_tags
}
