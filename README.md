# SOW/PO Document Management System

Enterprise-grade document management system for Statement of Work (SOW) and Purchase Order (PO) documents. Built with AWS serverless architecture, targeting <£5/month operational costs.

## Overview

This system automatically extracts, validates, and indexes SOW/PO documents using:
- **AWS Lambda** for serverless processing
- **Amazon S3** for document storage
- **DynamoDB** for metadata and search
- **SQS** for reliable queue-based processing
- **Google Gemini Flash** for AI-powered data extraction
- **Vector search** for semantic document queries

## Architecture

```
User Upload → S3 (presigned URL)
   ↓
S3 PutObject → EventBridge
   ↓
EventBridge → SQS: extract-text-queue
   ↓
extract-text Lambda → chunk-queue
   ↓
chunk-and-embed Lambda → extraction-queue
   ↓
extract-structured-data Lambda (Gemini Flash) → validation-queue
   ↓
validate-data Lambda → save-queue
   ↓
save-metadata Lambda → DynamoDB
```

### Key Design Decisions

1. **SQS Queue Chain** (NOT Step Functions) - Cost-effective, simple, reliable
2. **DynamoDB Single Table** - Fast queries, low cost
3. **S3 for full text** - Avoid DynamoDB 400KB limit
4. **Gemini Flash for extraction** - Cheapest LLM with 1M context window
5. **In-memory vector search** - Avoid OpenSearch/Pinecone costs

## Cost Breakdown (Monthly)

| Service | Cost |
|---------|------|
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

## Quick Start

### Prerequisites

- Python 3.11+
- Terraform 1.5+
- AWS CLI configured
- Google Cloud API key (for Gemini Flash)

### Setup

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd sow-po-manager

# 2. Set up Python environment
make setup

# 3. Configure AWS credentials
aws configure

# 4. Deploy infrastructure
make plan      # Review changes
make deploy    # Deploy to AWS

# 5. Enable cost tracking
make enable-cost-tracking

# 6. Run local UI
make ui
```

### Local Development

```bash
# Run tests
make test

# Lint code
make lint

# Format code
make format

# Verify tags
make verify-tags

# View costs
make cost-report
make cost-report-detailed
```

## Project Structure

```
sow-po-manager/
├── .github/workflows/    # CI/CD pipeline
├── terraform/            # Infrastructure as Code
│   ├── main.tf          # Provider config
│   ├── locals.tf        # Centralized tags
│   ├── s3.tf            # S3 buckets
│   ├── dynamodb.tf      # DynamoDB table
│   ├── sqs.tf           # SQS queues + DLQs
│   ├── lambda.tf        # Lambda functions
│   └── eventbridge.tf   # S3 event triggers
├── src/lambdas/         # Lambda function code
│   ├── get_upload_link/
│   ├── extract_text/
│   ├── chunk_and_embed/
│   ├── extract_structured_data/
│   ├── validate_data/
│   ├── save_metadata/
│   └── search_api/
├── tests/               # Unit tests
├── ui/                  # Local Flask UI
├── scripts/             # Utility scripts
├── SOWs/                # Store real SOWs here (git-ignored)
├── POs/                 # Store real POs here (git-ignored)
├── RULES.md             # Persistent brain (architecture rules)
├── Makefile             # The Contract (commands)
└── README.md            # This file
```

## DynamoDB Schema

### Item Types

1. **Document Versions**
   ```
   PK: DOC#<uuid>
   SK: VERSION#1.0.0
   ```

2. **Latest Pointer** (fast reads)
   ```
   PK: DOC#<uuid>
   SK: LATEST
   ```

3. **Search Chunks**
   ```
   PK: DOC#<uuid>
   SK: CHUNK#001
   embedding_vector: <binary>
   ```

### Global Secondary Indexes (GSIs)

- **GSI1:** Client queries (`CLIENT#<name>` → `CREATED#<timestamp>`)
- **GSI2:** Chunk lookup (`DOC#<uuid>` → `CHUNK#<number>`)
- **GSI3:** Duplicate detection (`PO_NUM#<number>` → `CLIENT#<name>`)

## The Message Contract

This JSON structure flows through ALL Lambda functions:

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
  "chunks_created": 15,
  "embeddings_stored": true,

  "structured_data": {
    "client_name": "Virgin Media O2",
    "contract_value": 500000,
    "start_date": "2025-01-01",
    "end_date": "2025-12-31",
    "day_rates": [...]
  },

  "validation_passed": true,
  "errors": []
}
```

## Tagging Strategy

**ALL resources are tagged with:**

- `Project`: sow-po-manager
- `Owner`: gianluca@colibri.com
- `Environment`: production
- `ManagedBy`: terraform
- `CostCenter`: colibri-digital
- `Application`: sow-po-management
- `Purpose`: storage | document-processing | search | queue | monitoring

**Cost allocation tags enabled for:**
- Monthly cost tracking
- Cost breakdown by Purpose
- Budget forecasting

## Testing Strategy (TDD)

Every Lambda function follows Test-Driven Development:

1. Write failing test first (`tests/test_<lambda>.py`)
2. Run `make test` (should fail - red)
3. Write minimum code to pass
4. Run `make test` (should pass - green)
5. Refactor if needed
6. Run `make lint`
7. Commit with verbose message

## CI/CD Pipeline

GitHub Actions workflow runs on every push:

1. **Lint and Test** - Ruff, Black, Pytest
2. **Terraform Plan** - Review infrastructure changes
3. **Verify Tags** - Ensure all resources tagged
4. **Deploy** (main branch only) - Terraform apply
5. **Enable Cost Tracking** - Activate cost allocation tags

## Security

- All documents stored encrypted at rest (S3 AES256)
- S3 bucket blocks all public access
- IAM roles follow least privilege principle
- Secrets managed via environment variables (not committed)
- SOWs/ and POs/ directories git-ignored

## Monitoring

- CloudWatch Logs (7-day retention)
- SQS Dead Letter Queues for failed messages
- Lambda error metrics
- Cost Explorer with tag-based filtering

## Known Limitations

1. **No billing alarms** - User already has 6 alerts configured
2. **Manual secret management** - Google API key via environment variable
3. **Single region** - eu-west-1 only
4. **No authentication** - Local UI only (not public)

## Roadmap

- [ ] Add support for PO document processing
- [ ] Implement duplicate detection
- [ ] Add email notifications for failed processing
- [ ] Create admin dashboard for DLQ management
- [ ] Add document versioning UI
- [ ] Implement bulk upload

## Contributing

This is a personal project. For issues or suggestions, please create a GitHub issue.

## License

Private project - All rights reserved.

## Contact

**Owner:** Gianluca Formica
**Email:** gianluca@colibri.com

---

**Generated with Claude Code (Sonnet 4.5)**
**Last Updated:** 2025-11-10
