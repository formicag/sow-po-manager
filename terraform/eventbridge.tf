# EventBridge Configuration
# Trigger: S3 PutObject event → SQS extract-text queue

# EventBridge rule for S3 object creation
resource "aws_cloudwatch_event_rule" "s3_upload" {
  name        = "${var.project_name}-s3-upload-trigger"
  description = "Trigger document processing when new file uploaded to S3"

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = {
        name = [aws_s3_bucket.documents.id]
      }
      object = {
        key = [{
          prefix = "uploads/"
        }]
      }
    }
  })

  tags = local.event_tags
}

# EventBridge target: Send S3 events to extract-text SQS queue
resource "aws_cloudwatch_event_target" "sqs" {
  rule      = aws_cloudwatch_event_rule.s3_upload.name
  target_id = "SendToSQS"
  arn       = aws_sqs_queue.extract_text.arn

  # Transform S3 event to our message contract
  input_transformer {
    input_paths = {
      bucket    = "$.detail.bucket.name"
      key       = "$.detail.object.key"
      timestamp = "$.time"
    }

    input_template = <<-EOT
    {
      "document_id": "DOC#<key>",
      "s3_bucket": "<bucket>",
      "s3_key": "<key>",
      "timestamp": "<timestamp>",
      "uploaded_by": "eventbridge",
      "errors": []
    }
    EOT
  }
}

# Allow EventBridge to send messages to SQS
resource "aws_sqs_queue_policy" "extract_text" {
  queue_url = aws_sqs_queue.extract_text.url

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = {
        Service = "events.amazonaws.com"
      }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.extract_text.arn
      Condition = {
        ArnEquals = {
          "aws:SourceArn" = aws_cloudwatch_event_rule.s3_upload.arn
        }
      }
    }]
  })
}
