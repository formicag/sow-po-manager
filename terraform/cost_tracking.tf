# Cost Tracking Configuration
# CRITICAL: This file enables cost allocation tags ONLY.
# NO CloudWatch billing alarms - user already has 6 existing alerts.
# NO SNS topics for billing.

# Enable cost allocation tags via AWS CLI
# This is safe to run multiple times (idempotent)
resource "null_resource" "enable_cost_allocation_tags" {
  triggers = {
    # Re-run if tags change
    tags = jsonencode([
      "Project",
      "Owner",
      "Environment",
      "Purpose",
      "CostCenter",
      "Application",
      "ManagedBy"
    ])
  }

  provisioner "local-exec" {
    command = <<-EOT
      aws ce update-cost-allocation-tags-status \
        --cost-allocation-tags-status \
        '[
          {"TagKey":"Project","Status":"Active"},
          {"TagKey":"Owner","Status":"Active"},
          {"TagKey":"Environment","Status":"Active"},
          {"TagKey":"Purpose","Status":"Active"},
          {"TagKey":"CostCenter","Status":"Active"},
          {"TagKey":"Application","Status":"Active"},
          {"TagKey":"ManagedBy","Status":"Active"}
        ]' \
        --region us-east-1 2>/dev/null || echo "Note: Cost allocation tags may already be enabled"
    EOT
  }
}

# Note: Cost allocation tags can take up to 24 hours to activate
# Use these Makefile commands to view costs:
#   make cost-report            - Monthly costs for this project
#   make cost-report-detailed   - Costs by Purpose tag
