# SQS Queue Chain for Document Processing
# Pattern: extract-text → chunk → extraction → validation → save
# Each queue has a Dead Letter Queue (DLQ) for failed messages

# ============================================================================
# EXTRACT TEXT QUEUE + DLQ
# ============================================================================

resource "aws_sqs_queue" "extract_text_dlq" {
  name                      = "${var.project_name}-extract-text-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = local.queue_tags
}

resource "aws_sqs_queue" "extract_text" {
  name                       = "${var.project_name}-extract-text-queue"
  visibility_timeout_seconds = var.sqs_visibility_timeout
  message_retention_seconds  = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.extract_text_dlq.arn
    maxReceiveCount     = var.sqs_max_receive_count
  })

  tags = local.queue_tags
}

# ============================================================================
# CHUNK AND EMBED QUEUE + DLQ
# ============================================================================

resource "aws_sqs_queue" "chunk_dlq" {
  name                      = "${var.project_name}-chunk-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = local.queue_tags
}

resource "aws_sqs_queue" "chunk" {
  name                       = "${var.project_name}-chunk-queue"
  visibility_timeout_seconds = var.sqs_visibility_timeout
  message_retention_seconds  = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.chunk_dlq.arn
    maxReceiveCount     = var.sqs_max_receive_count
  })

  tags = local.queue_tags
}

# ============================================================================
# EXTRACT STRUCTURED DATA QUEUE + DLQ
# ============================================================================

resource "aws_sqs_queue" "extraction_dlq" {
  name                      = "${var.project_name}-extraction-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = local.queue_tags
}

resource "aws_sqs_queue" "extraction" {
  name                       = "${var.project_name}-extraction-queue"
  visibility_timeout_seconds = var.sqs_visibility_timeout
  message_retention_seconds  = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.extraction_dlq.arn
    maxReceiveCount     = var.sqs_max_receive_count
  })

  tags = local.queue_tags
}

# ============================================================================
# VALIDATE DATA QUEUE + DLQ
# ============================================================================

resource "aws_sqs_queue" "validation_dlq" {
  name                      = "${var.project_name}-validation-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = local.queue_tags
}

resource "aws_sqs_queue" "validation" {
  name                       = "${var.project_name}-validation-queue"
  visibility_timeout_seconds = var.sqs_visibility_timeout
  message_retention_seconds  = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.validation_dlq.arn
    maxReceiveCount     = var.sqs_max_receive_count
  })

  tags = local.queue_tags
}

# ============================================================================
# SAVE METADATA QUEUE + DLQ (Final stage)
# ============================================================================

resource "aws_sqs_queue" "save_dlq" {
  name                      = "${var.project_name}-save-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = local.queue_tags
}

resource "aws_sqs_queue" "save" {
  name                       = "${var.project_name}-save-queue"
  visibility_timeout_seconds = var.sqs_visibility_timeout
  message_retention_seconds  = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.save_dlq.arn
    maxReceiveCount     = var.sqs_max_receive_count
  })

  tags = local.queue_tags
}

# ============================================================================
# QUEUE CHAIN FLOW:
# ============================================================================
# 1. S3 Upload → EventBridge → extract_text queue
# 2. extract_text Lambda → chunk queue
# 3. chunk_and_embed Lambda → extraction queue
# 4. extract_structured_data Lambda → validation queue
# 5. validate_data Lambda → save queue
# 6. save_metadata Lambda → DynamoDB (final)
#
# Each stage has DLQ for failed messages (maxReceiveCount = 3)
