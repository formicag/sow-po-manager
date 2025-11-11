# Deployment Guide

Complete guide for deploying the SOW/PO Manager to AWS.

## Prerequisites

### Required Tools
- AWS CLI configured with credentials
- Terraform >= 1.5
- Python 3.11+
- Make (build tool)

### AWS Account Requirements
- IAM permissions to create:
  - Lambda functions
  - S3 buckets
  - DynamoDB tables
  - SQS queues
  - EventBridge rules
  - IAM roles and policies
  - CloudWatch Log Groups

### API Keys
- Google Gemini API key (for document extraction)
  - Get from: https://makersuite.google.com/app/apikey
  - Model: gemini-2.5-flash

## Initial Setup

### 1. Clone Repository
```bash
git clone https://github.com/yourusername/sow-po-manager.git
cd sow-po-manager
```

### 2. Configure AWS CLI
```bash
aws configure
# Enter your AWS credentials
# Default region: eu-west-1 (or your preferred region)
```

### 3. Set Up Python Environment
```bash
make setup
```

This creates a virtual environment and installs all dependencies.

### 4. Configure Terraform Variables

Edit `terraform/terraform.tfvars`:

```hcl
# Required: Your Gemini API key
gemini_api_key = "your-api-key-here"

# Optional: Override defaults
aws_region = "eu-west-1"
project_name = "sow-po-manager"
owner_email = "your-email@example.com"
environment = "production"
```

**Important**: Never commit `terraform.tfvars` to git (already in .gitignore)

## Deployment Steps

### Step 1: Package Lambda Functions
```bash
make package-lambdas
```

This creates ZIP files in `dist/` for all Lambda functions.

**Expected output**:
```
Packaging Lambda functions...
Packaging get_upload_link...
Packaging extract_text...
Packaging chunk_and_embed...
Packaging extract_structured_data...
Packaging validate_data...
Packaging save_metadata...
Packaging search_api...
✅ Lambda functions packaged in dist/
```

### Step 2: Initialize Terraform
```bash
cd terraform
terraform init
```

### Step 3: Review Terraform Plan
```bash
terraform plan
```

**Expected**: 45 resources to be created
- 1 S3 bucket
- 1 DynamoDB table
- 7 Lambda functions
- 7 CloudWatch log groups
- 10 SQS queues (5 main + 5 DLQs)
- 1 EventBridge rule
- IAM roles and policies

### Step 4: Deploy Infrastructure
```bash
terraform apply
```

Type `yes` when prompted.

**Deployment time**: ~2-3 minutes

**Or use the Makefile**:
```bash
cd ..
make deploy
```

### Step 5: Verify Deployment
```bash
make verify-tags
```

This checks that all AWS resources have proper tags.

### Step 6: Enable Cost Tracking
```bash
make enable-cost-tracking
```

Activates cost allocation tags for AWS Cost Explorer.

## Post-Deployment Verification

### Test Upload Link Lambda
```bash
aws lambda invoke \
  --function-name sow-po-manager-get-upload-link \
  --cli-binary-format raw-in-base64-out \
  --payload '{"filename": "test.pdf"}' \
  --region eu-west-1 \
  /tmp/test-response.json

cat /tmp/test-response.json | jq .
```

### Check S3 Bucket
```bash
aws s3 ls s3://sow-po-manager-documents-* --region eu-west-1
```

### Check DynamoDB Table
```bash
aws dynamodb describe-table \
  --table-name sow-po-manager-documents \
  --region eu-west-1 \
  --query 'Table.{Name:TableName,Status:TableStatus,ItemCount:ItemCount}'
```

### Check SQS Queues
```bash
aws sqs list-queues --region eu-west-1 | grep sow-po-manager
```

### View Lambda Functions
```bash
aws lambda list-functions --region eu-west-1 | grep sow-po-manager
```

## Environment-Specific Deployments

### Development Environment
```hcl
# terraform/terraform.tfvars
environment = "development"
project_name = "sow-po-manager-dev"
log_retention_days = 3
lambda_memory = 256  # Smaller for dev
```

### Staging Environment
```hcl
environment = "staging"
project_name = "sow-po-manager-staging"
log_retention_days = 7
```

### Production Environment
```hcl
environment = "production"
project_name = "sow-po-manager"
log_retention_days = 30
lambda_memory = 512
enable_point_in_time_recovery = true
```

## Updating Deployment

### Update Lambda Code
```bash
# Make changes to Lambda code
# Repackage Lambda
make package-lambdas

# Apply changes
cd terraform
terraform apply -target=aws_lambda_function.extract_structured_data
```

### Update Infrastructure
```bash
# Edit Terraform files
cd terraform
terraform plan
terraform apply
```

## Rollback Procedure

### Rollback Lambda Function
```bash
# Get previous version
aws lambda list-versions-by-function \
  --function-name sow-po-manager-extract-text \
  --region eu-west-1

# Update alias to point to previous version
aws lambda update-alias \
  --function-name sow-po-manager-extract-text \
  --name production \
  --function-version 2 \
  --region eu-west-1
```

### Rollback Terraform
```bash
cd terraform
terraform plan -destroy
# Review what will be destroyed
terraform destroy  # CAUTION: This deletes everything
```

## Monitoring Deployment

### CloudWatch Logs
```bash
# Tail logs for a Lambda function
aws logs tail /aws/lambda/sow-po-manager-extract-text \
  --follow \
  --region eu-west-1
```

### View Recent Errors
```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/sow-po-manager-extract-text \
  --filter-pattern "ERROR" \
  --start-time $(date -u -v-1H +%s)000 \
  --region eu-west-1
```

### Check SQS Queue Depth
```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.eu-west-1.amazonaws.com/ACCOUNT/sow-po-manager-extraction-queue \
  --attribute-names ApproximateNumberOfMessages \
  --region eu-west-1
```

## Cost Monitoring

### View Monthly Costs
```bash
make cost-report
```

### Detailed Cost Breakdown
```bash
make cost-report-detailed
```

### Set Up Billing Alerts (Optional)
```bash
aws cloudwatch put-metric-alarm \
  --alarm-name sow-po-manager-high-cost \
  --alarm-description "Alert when monthly costs exceed £5" \
  --metric-name EstimatedCharges \
  --namespace AWS/Billing \
  --statistic Maximum \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold
```

## Troubleshooting Deployment

### Lambda Function Fails to Create
**Error**: "The role defined for the function cannot be assumed by Lambda"
**Solution**: Wait a few seconds and retry - IAM role creation is eventually consistent

### Terraform State Lock
**Error**: "Error locking state"
**Solution**:
```bash
cd terraform
terraform force-unlock LOCK_ID
```

### Lambda Package Too Large
**Error**: "Unzipped size must be smaller than 262144000 bytes"
**Solution**: Lambda is too large. Check dependencies in requirements.txt

### S3 Bucket Already Exists
**Error**: "BucketAlreadyExists"
**Solution**: Change `project_name` in terraform.tfvars (bucket names must be globally unique)

### Insufficient IAM Permissions
**Error**: "User is not authorized to perform X"
**Solution**: Ensure your AWS user has AdministratorAccess or required permissions

## Security Best Practices

### Secrets Management
- Never commit API keys to git
- Use AWS Secrets Manager for production:
  ```bash
  aws secretsmanager create-secret \
    --name sow-po-manager/gemini-api-key \
    --secret-string "your-api-key"
  ```
- Update Lambda to read from Secrets Manager

### IAM Permissions
- Review `terraform/lambda.tf` for least privilege
- Lambda execution role should only have required permissions
- Enable MFA on AWS account

### Encryption
- Enable S3 bucket encryption:
  ```hcl
  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "AES256"
      }
    }
  }
  ```

### Network Security
- Consider deploying Lambda in VPC
- Use VPC endpoints for AWS services
- Enable CloudTrail for audit logging

## Cleanup / Destroy

### Remove All Resources
```bash
cd terraform
terraform destroy
```

This will delete:
- All Lambda functions
- S3 bucket (must be empty first)
- DynamoDB table
- SQS queues
- CloudWatch logs
- IAM roles

### Empty S3 Bucket First
```bash
aws s3 rm s3://sow-po-manager-documents-SUFFIX --recursive --region eu-west-1
```

### Delete DynamoDB Table Data
```bash
# DynamoDB table will be deleted by Terraform
# Point-in-time recovery backups retained for 35 days
```

## Production Checklist

Before going to production:

- [ ] API keys stored in AWS Secrets Manager (not terraform.tfvars)
- [ ] S3 bucket encryption enabled
- [ ] DynamoDB point-in-time recovery enabled
- [ ] CloudWatch alarms configured
- [ ] Cost budgets set up
- [ ] Backup strategy defined
- [ ] Disaster recovery plan documented
- [ ] Security review completed
- [ ] Load testing performed
- [ ] Monitoring dashboards created
- [ ] On-call rotation established
- [ ] Documentation reviewed and updated

## Support

- **Issues**: Create GitHub issue
- **AWS Support**: Use AWS Support Center
- **Documentation**: See docs/ folder
- **Logs**: Check CloudWatch Logs

## Next Steps

After successful deployment:

1. Test document upload (see USER_GUIDE.md)
2. Monitor first few documents through pipeline
3. Set up CloudWatch dashboard
4. Configure alerting
5. Train users on UI
