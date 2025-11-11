# Centralized tagging strategy
# ALL AWS resources MUST use these tags

locals {
  # Common tags applied to ALL resources
  common_tags = {
    Project     = var.project_name
    Owner       = var.owner_email
    Environment = var.environment
    ManagedBy   = "terraform"
    CostCenter  = "colibri-digital"
    Application = "sow-po-management"
  }

  # Purpose-specific tags (merged with common_tags)
  storage_tags = merge(local.common_tags, {
    Purpose = "storage"
  })

  processing_tags = merge(local.common_tags, {
    Purpose = "document-processing"
  })

  search_tags = merge(local.common_tags, {
    Purpose = "search"
  })

  queue_tags = merge(local.common_tags, {
    Purpose = "queue"
  })

  monitoring_tags = merge(local.common_tags, {
    Purpose = "monitoring"
  })

  event_tags = merge(local.common_tags, {
    Purpose = "events"
  })
}
