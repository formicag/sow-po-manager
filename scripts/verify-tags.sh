#!/bin/bash

# verify-tags.sh - Verify all AWS resources are properly tagged
# Exit code 0 if all resources tagged, 1 if any missing tags

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Required tags
REQUIRED_TAGS=(
  "Project"
  "Owner"
  "Environment"
  "ManagedBy"
  "CostCenter"
  "Application"
  "Purpose"
)

# Track if any resources are missing tags
MISSING_TAGS=0

echo -e "${YELLOW}Verifying AWS resource tags...${NC}\n"

# ============================================================================
# Check S3 Buckets
# ============================================================================

echo "Checking S3 buckets..."
BUCKETS=$(aws s3api list-buckets --query 'Buckets[?contains(Name, `sow-po-manager`)].Name' --output text)

for bucket in $BUCKETS; do
  echo "  Checking bucket: $bucket"

  TAGS=$(aws s3api get-bucket-tagging --bucket "$bucket" 2>/dev/null || echo "")

  if [ -z "$TAGS" ]; then
    echo -e "    ${RED}✗ No tags found${NC}"
    MISSING_TAGS=1
    continue
  fi

  for tag in "${REQUIRED_TAGS[@]}"; do
    if ! echo "$TAGS" | grep -q "\"Key\": \"$tag\""; then
      echo -e "    ${RED}✗ Missing tag: $tag${NC}"
      MISSING_TAGS=1
    fi
  done
done

# ============================================================================
# Check DynamoDB Tables
# ============================================================================

echo -e "\nChecking DynamoDB tables..."
TABLES=$(aws dynamodb list-tables --query 'TableNames[?contains(@, `sow-po-manager`)]' --output text)

for table in $TABLES; do
  echo "  Checking table: $table"

  TAGS=$(aws dynamodb list-tags-of-resource --resource-arn "arn:aws:dynamodb:eu-west-1:$(aws sts get-caller-identity --query Account --output text):table/$table" 2>/dev/null || echo "")

  if [ -z "$TAGS" ]; then
    echo -e "    ${RED}✗ No tags found${NC}"
    MISSING_TAGS=1
    continue
  fi

  for tag in "${REQUIRED_TAGS[@]}"; do
    if ! echo "$TAGS" | grep -q "\"Key\": \"$tag\""; then
      echo -e "    ${RED}✗ Missing tag: $tag${NC}"
      MISSING_TAGS=1
    fi
  done
done

# ============================================================================
# Check Lambda Functions
# ============================================================================

echo -e "\nChecking Lambda functions..."
FUNCTIONS=$(aws lambda list-functions --query 'Functions[?contains(FunctionName, `sow-po-manager`)].FunctionName' --output text)

for function in $FUNCTIONS; do
  echo "  Checking function: $function"

  TAGS=$(aws lambda list-tags --resource "arn:aws:lambda:eu-west-1:$(aws sts get-caller-identity --query Account --output text):function:$function" 2>/dev/null || echo "")

  if [ -z "$TAGS" ]; then
    echo -e "    ${RED}✗ No tags found${NC}"
    MISSING_TAGS=1
    continue
  fi

  for tag in "${REQUIRED_TAGS[@]}"; do
    if ! echo "$TAGS" | grep -q "\"$tag\""; then
      echo -e "    ${RED}✗ Missing tag: $tag${NC}"
      MISSING_TAGS=1
    fi
  done
done

# ============================================================================
# Check SQS Queues
# ============================================================================

echo -e "\nChecking SQS queues..."
QUEUES=$(aws sqs list-queues --queue-name-prefix sow-po-manager --query 'QueueUrls' --output text 2>/dev/null || echo "")

for queue_url in $QUEUES; do
  queue_name=$(basename "$queue_url")
  echo "  Checking queue: $queue_name"

  TAGS=$(aws sqs list-queue-tags --queue-url "$queue_url" 2>/dev/null || echo "")

  if [ -z "$TAGS" ] || [ "$TAGS" == "{}" ]; then
    echo -e "    ${RED}✗ No tags found${NC}"
    MISSING_TAGS=1
    continue
  fi

  for tag in "${REQUIRED_TAGS[@]}"; do
    if ! echo "$TAGS" | grep -q "\"$tag\""; then
      echo -e "    ${RED}✗ Missing tag: $tag${NC}"
      MISSING_TAGS=1
    fi
  done
done

# ============================================================================
# Check CloudWatch Log Groups
# ============================================================================

echo -e "\nChecking CloudWatch Log Groups..."
LOG_GROUPS=$(aws logs describe-log-groups --log-group-name-prefix /aws/lambda/sow-po-manager --query 'logGroups[].logGroupName' --output text 2>/dev/null || echo "")

for log_group in $LOG_GROUPS; do
  echo "  Checking log group: $log_group"

  TAGS=$(aws logs list-tags-log-group --log-group-name "$log_group" 2>/dev/null || echo "")

  if [ -z "$TAGS" ] || [ "$TAGS" == "{}" ]; then
    echo -e "    ${RED}✗ No tags found${NC}"
    MISSING_TAGS=1
    continue
  fi

  for tag in "${REQUIRED_TAGS[@]}"; do
    if ! echo "$TAGS" | grep -q "\"$tag\""; then
      echo -e "    ${RED}✗ Missing tag: $tag${NC}"
      MISSING_TAGS=1
    fi
  done
done

# ============================================================================
# Summary
# ============================================================================

echo ""
if [ $MISSING_TAGS -eq 0 ]; then
  echo -e "${GREEN}✓ All resources are properly tagged!${NC}"
  exit 0
else
  echo -e "${RED}✗ Some resources are missing required tags${NC}"
  echo -e "${YELLOW}Required tags: ${REQUIRED_TAGS[*]}${NC}"
  exit 1
fi
