# RULES.md - The Persistent Brain

This document contains all architectural decisions, patterns, and non-negotiable rules for the SOW/PO Document Management System.

---

## PROJECT OVERVIEW

**Name:** SOW/PO Document Management System
**Cost Target:** <£5/month ongoing
**AWS Region:** eu-west-1 (Ireland)
**Architecture:** AWS Serverless (Lambda + SQS + DynamoDB + S3)
**LLM Provider:** Google Gemini Flash (primary)
**Owner:** gianluca@colibri.com
**Environment:** production

---

## ARCHITECTURE RULES

### 1. SQS QUEUE CHAIN PATTERN (NON-NEGOTIABLE)

**CRITICAL:** Use SQS queue chaining, NOT Step Functions.

```
Flow:
User uploads → S3 (presigned URL)
  ↓
S3 PutObject event → EventBridge
  ↓
EventBridge → SQS: extract-text-queue
  ↓
extract-text Lambda → SQS: chunk-queue
  ↓
chunk-and-embed Lambda → SQS: extraction-queue
  ↓
extract-structured-data Lambda → SQS: validation-queue
  ↓
validate-data Lambda → SQS: save-queue
  ↓
save-metadata Lambda → DynamoDB
```

**Rules:**
- Each Lambda polls ONE input queue
- Each Lambda sends to ONE output queue (except final stage)
- Every queue has a Dead Letter Queue (DLQ)
- MaxReceiveCount: 3 (after 3 retries → DLQ)
- Message visibility timeout: 300 seconds (5 minutes)

### 2. THE MESSAGE CONTRACT

This JSON structure flows through ALL Lambda functions. Each Lambda ADDS to it, never replaces.

```json
{
  "document_id": "DOC#abc123",
  "s3_bucket": "sow-documents-xyz",
  "s3_key": "uploads/contract.pdf",
  "client_name": "VMO2",
  "uploaded_by": "gianluca@colibri.com",
  "timestamp": "2025-11-10T14:30:00Z",

  "text_extracted": true,
  "text_s3_key": "text/DOC#abc123.txt",
  "text_length": 45230,
  "page_count": 12,

  "chunks_created": 15,
  "embeddings_stored": true,

  "structured_data": {
    "client_name": "Virgin Media O2",
    "contract_value": 500000,
    "start_date": "2025-01-01",
    "end_date": "2025-12-31",
    "day_rates": [...]
  },
  "extraction_confidence": 0.95,

  "validation_passed": true,
  "validation_errors": [],
  "validation_warnings": ["Day rate high for junior role"],

  "errors": []
}
```

### 3. LAMBDA HANDLER PATTERN

Every Lambda MUST follow this pattern:

```python
def lambda_handler(event, context):
    for record in event['Records']:
        # 1. Parse incoming message
        message = json.loads(record['body'])
        logger.info(f"📥 RECEIVED MESSAGE:")
        logger.info(json.dumps(message, indent=2))

        try:
            # 2. Extract required fields
            doc_id = message['document_id']

            # 3. DO YOUR ONE JOB
            result = do_the_work(doc_id, message)

            # 4. ADD results to message (don't replace!)
            message['your_field'] = result

            # 5. Log outgoing message
            logger.info(f"📤 FORWARDING MESSAGE:")
            logger.info(json.dumps(message, indent=2))

            # 6. Send to next queue
            if NEXT_QUEUE_URL:
                sqs.send_message(
                    QueueUrl=NEXT_QUEUE_URL,
                    MessageBody=json.dumps(message)
                )

        except Exception as e:
            logger.error(f"❌ ERROR: {str(e)}")
            if 'errors' not in message:
                message['errors'] = []
            message['errors'].append({
                'stage': 'lambda-name',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            })
            raise  # Re-raise for SQS retry → DLQ

    return {'statusCode': 200}
```

---

## DYNAMODB SINGLE TABLE DESIGN

**Table:** sow-documents

### Item Types

1. **Document Versions:**
   ```
   PK: DOC#<uuid>
   SK: VERSION#1.0.0
   Attributes: {structured_data, metadata, s3_keys, validation_results}
   ```

2. **Latest Pointer (fast reads):**
   ```
   PK: DOC#<uuid>
   SK: LATEST
   Attributes: {copy of latest version data}
   ```

3. **Search Chunks:**
   ```
   PK: DOC#<uuid>
   SK: CHUNK#001
   Attributes: {text_chunk, embedding_vector (binary), chunk_index}
   ```

### Global Secondary Indexes (GSIs)

- **GSI1:** Client queries
  `GSI1PK=CLIENT#name, GSI1SK=CREATED#timestamp`

- **GSI2:** Chunk lookup
  `GSI2PK=DOC#uuid, GSI2SK=CHUNK#number`

- **GSI3:** Duplicate detection
  `GSI3PK=PO_NUM#12345, GSI3SK=CLIENT#name`

**CRITICAL:** Full document text stored in S3, NOT DynamoDB (400KB item limit).

---

## MANDATORY TAGGING

ALL AWS resources MUST have these tags:

```hcl
locals {
  common_tags = {
    Project     = "sow-po-manager"
    Owner       = "gianluca@colibri.com"
    Environment = "production"
    ManagedBy   = "terraform"
    CostCenter  = "colibri-digital"
    Application = "sow-po-management"
  }

  storage_tags = merge(local.common_tags, { Purpose = "storage" })
  processing_tags = merge(local.common_tags, { Purpose = "document-processing" })
  search_tags = merge(local.common_tags, { Purpose = "search" })
  queue_tags = merge(local.common_tags, { Purpose = "queue" })
  monitoring_tags = merge(local.common_tags, { Purpose = "monitoring" })
}
```

**Apply to:**
- S3 buckets: `storage_tags`
- DynamoDB: `storage_tags`
- Lambda functions: `processing_tags` or `search_tags`
- SQS queues: `queue_tags`
- CloudWatch Log Groups: `monitoring_tags`
- EventBridge rules: `processing_tags`

---

## COST TRACKING RULES

**CRITICAL:** User already has 6 billing alerts.

### DO NOT CREATE:
- CloudWatch billing alarms
- SNS topics for billing
- SNS email subscriptions

### ONLY CREATE:
- Cost allocation tag enablement (terraform/cost_tracking.tf)
- CLI cost reporting commands (Makefile)

**cost_tracking.tf should ONLY contain:**
- `null_resource` to enable cost allocation tags via AWS CLI
- NO `aws_cloudwatch_metric_alarm`
- NO `aws_sns_topic`
- NO `aws_sns_topic_subscription`

---

## TDD WORKFLOW (MANDATORY)

For EVERY Lambda function:

1. **Write failing test first**
   ```bash
   # tests/test_<lambda_name>.py
   make test  # MUST FAIL (red)
   ```

2. **Write minimum code to pass**
   ```bash
   # src/lambdas/<lambda_name>/handler.py
   make test  # MUST PASS (green)
   ```

3. **Refactor if needed**
   ```bash
   make lint
   ```

4. **Commit with verbose message**

### Test Structure

```python
import pytest
import json
from unittest.mock import Mock, patch
from src.lambdas.extract_text.handler import lambda_handler

def test_extract_text_success():
    """Test successful text extraction from PDF"""
    event = {
        'Records': [{
            'body': json.dumps({
                'document_id': 'DOC#test123',
                's3_bucket': 'test-bucket',
                's3_key': 'uploads/test.pdf'
            })
        }]
    }

    with patch('boto3.client') as mock_boto:
        mock_s3 = Mock()
        mock_s3.get_object.return_value = {
            'Body': Mock(read=lambda: b'PDF content')
        }
        mock_boto.return_value = mock_s3

        result = lambda_handler(event, {})

        assert result['statusCode'] == 200
```

---

## LLM EXTRACTION STRATEGY

**Lambda:** extract_structured_data

1. Use **Google Gemini Flash** (cheapest, 1M context window)
2. Send full document text from S3
3. Use `instructor` library for structured output
4. Pydantic schema for validation

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class DayRate(BaseModel):
    role: str = Field(..., description="Job role")
    rate: float = Field(..., description="Day rate in GBP")
    currency: str = Field(default="GBP")

class SOWData(BaseModel):
    client_name: str
    contract_value: float
    start_date: str  # ISO format
    end_date: str
    po_number: Optional[str] = None
    day_rates: List[DayRate]
    signatures_present: bool
```

5. Retry 3 times if JSON parse fails
6. On all failures → DLQ

---

## VECTOR SEARCH IMPLEMENTATION

**Lambda:** search_api

1. User query arrives: `{"query": "day rate VMO2", "filter_client": "VMO2"}`
2. Generate query embedding via Amazon Titan (Bedrock)
3. Scan DynamoDB for all `CHUNK#` items (filter by client via GSI)
4. In Lambda memory (numpy):
   - Load all chunk embeddings
   - Calculate cosine similarity with query vector
   - Sort by similarity score
5. Return top 10 chunks with parent DOC IDs

**Cost:** £0.00 (fits in Lambda free tier)

---

## SENSITIVE FILES

Never commit to git:

```
# Sensitive documents
SOWs/*
!SOWs/.gitkeep
POs/*
!POs/.gitkeep

# Secrets
*.pem
*.key
.env
secrets.json

# Terraform
.terraform/
*.tfstate
*.tfstate.*
*.tfvars
```

---

## COST BREAKDOWN (Target: <£5/month)

| Service | Monthly Cost |
|---------|-------------|
| S3 Storage | £0.02 |
| DynamoDB | £0.00 (free tier) |
| DynamoDB PITR | £0.16 |
| Lambda | £0.00 (free tier) |
| SQS | £0.00 (free tier) |
| EventBridge | £0.00 (free tier) |
| Gemini Flash | £0.005 (10 docs) |
| Amazon Titan | £0.003 (embeddings) |
| CloudWatch Logs | £0.50 (7-day retention) |
| **TOTAL** | **£0.69/month** |

**Headroom:** £4.31 for growth

---

## CRITICAL REQUIREMENTS CHECKLIST

- [ ] ❌ DO NOT use Step Functions (use SQS chain)
- [ ] ❌ DO NOT create CloudWatch billing alarms
- [ ] ❌ DO NOT create SNS topics for billing
- [ ] ✅ DO use SQS queue chaining
- [ ] ✅ DO tag ALL resources
- [ ] ✅ DO follow TDD
- [ ] ✅ DO use extensive logging
- [ ] ✅ DO create DLQ for every queue (maxReceiveCount: 3)
- [ ] ✅ DO store full text in S3, not DynamoDB
- [ ] ✅ DO use LATEST pointer pattern

---

## DEPLOYMENT WORKFLOW

1. **Local development:**
   ```bash
   make setup    # Create venv, install deps
   make lint     # Run ruff + black
   make test     # Run pytest with coverage
   ```

2. **Terraform deployment:**
   ```bash
   make plan           # Terraform plan
   make verify-tags    # Verify all resources tagged
   make deploy         # Terraform apply
   ```

3. **Cost tracking:**
   ```bash
   make cost-report            # Monthly costs
   make cost-report-detailed   # Costs by Purpose tag
   ```

4. **GitHub Actions (automatic):**
   - Runs on push to main and PRs
   - Steps: lint → test → plan → verify-tags → deploy
   - Only deploys on main branch

---

## SESSION ZERO FILES (MUST CREATE FIRST)

1. RULES.md (this file)
2. Makefile
3. terraform/main.tf
4. terraform/locals.tf
5. terraform/variables.tf
6. terraform/outputs.tf
7. terraform/cost_tracking.tf
8. scripts/verify-tags.sh
9. .github/workflows/main.yml
10. requirements.txt
11. cost-filter.json
12. .gitignore
13. README.md
14. SOWs/.gitkeep
15. POs/.gitkeep

---

**Last Updated:** 2025-11-10
**Author:** Claude Code (Sonnet 4.5)
