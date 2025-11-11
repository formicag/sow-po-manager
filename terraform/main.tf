terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }

  # S3 backend for state management
  # Uncomment after creating the S3 bucket manually
  # backend "s3" {
  #   bucket         = "sow-po-manager-terraform-state"
  #   key            = "terraform.tfstate"
  #   region         = "eu-west-1"
  #   encrypt        = true
  #   dynamodb_table = "sow-po-manager-terraform-lock"
  # }
}

# AWS Provider configuration
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

# Random provider for unique naming
provider "random" {}

# Generate unique suffix for resource names (prevents naming conflicts)
resource "random_string" "suffix" {
  length  = 8
  special = false
  upper   = false
}
