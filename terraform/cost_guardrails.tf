# ===========================================================================
# Cost Guardrails: S3 Lifecycle + Budget Alerts
# ===========================================================================

# S3 lifecycle rules (replaces the generic one in s3.tf)
resource "aws_s3_bucket_lifecycle_configuration" "documents_lifecycle" {
  bucket = aws_s3_bucket.documents.id

  # Embeddings: transition to IA after 30 days, expire after 180 days
  rule {
    id     = "embeddings-lifecycle"
    status = "Enabled"

    filter {
      prefix = "embeddings/"
    }

    transition {
      days          = 30
      storage_class = "STANDARD_IA"  # Cheaper for infrequently accessed data
    }

    expiration {
      days = 180  # Delete after 6 months
    }
  }

  # Extracted text: expire after 3 months
  rule {
    id     = "text-lifecycle"
    status = "Enabled"

    filter {
      prefix = "text/"
    }

    expiration {
      days = 90  # Delete extracted text after 3 months
    }
  }

  # Original PDFs: move to IA after 90 days, Glacier after 365 days
  rule {
    id     = "uploads-transition"
    status = "Enabled"

    filter {
      prefix = "uploads/"
    }

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 365
      storage_class = "GLACIER"
    }
  }

  # Delete non-current versions after 30 days (for all objects)
  rule {
    id     = "delete-old-versions"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

}

# Note: S3 lifecycle configurations don't support tags

# NOTE: Budget alerts managed externally (existing Tier1-Tier6 budgets cover all AWS costs)
