# Architecture Documentation

Detailed technical architecture of the SOW/PO Document Management System.

## Table of Contents
- [System Overview](#system-overview)
- [AWS Architecture](#aws-architecture)
- [Data Flow](#data-flow)
- [Lambda Functions](#lambda-functions)
- [Database Schema](#database-schema)
- [Message Contract](#message-contract)
- [Security Architecture](#security-architecture)
- [Cost Optimization](#cost-optimization)

---

## System Overview

### High-Level Architecture

```
┌─────────────┐
│   User UI   │ (Flask / Web)
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│                    AWS Cloud (eu-west-1)                │
│                                                          │
│  ┌──────────┐     ┌─────────────┐     ┌──────────────┐│
│  │    S3    │────▶│ EventBridge │────▶│ SQS Queues   ││
│  │  Bucket  │     └─────────────┘     │  (5 stages)  ││
│  └──────────┘                         └───────┬──────┘│
│                                                │       │
│                                                ▼       │
│  ┌────────────────────────────────────────────────┐  │
│  │          Lambda Processing Pipeline           │  │
│  │  1. Extract Text → 2. Chunk & Embed →        │  │
│  │  3. Gemini AI → 4. Validate → 5. Save        │  │
│  └────────────────────┬───────────────────────────┘  │
│                       │                               │
│                       ▼                               │
│  ┌─────────────┐  ┌──────────────┐                  │
│  │  DynamoDB   │  │  CloudWatch  │                  │
│  │   Table     │  │     Logs     │                  │
│  └─────────────┘  └──────────────┘                  │
└─────────────────────────────────────────────────────┘
       ▲
       │
┌──────┴──────┐
│  Gemini AI  │ (External API)
└─────────────┘
```

### Key Design Principles

1. **Serverless-First**: No servers to manage, scales automatically
2. **Event-Driven**: S3 upload triggers EventBridge → SQS chain
3. **Message Contract**: Each stage adds data, preserves all previous fields
4. **Idempotent**: Can retry any stage safely
5. **Observable**: Comprehensive CloudWatch logging
6. **Cost-Optimized**: Pay only for what you use

---

## AWS Architecture

### Resource Inventory

| Resource Type | Count | Purpose |
|--------------|-------|---------|
| S3 Buckets | 1 | Document storage |
| DynamoDB Tables | 1 | Metadata storage |
| Lambda Functions | 7 | Processing pipeline |
| SQS Queues | 10 | 5 main + 5 DLQs |
| EventBridge Rules | 1 | S3 event routing |
| IAM Roles | 1 | Lambda execution |
| CloudWatch Log Groups | 7 | Function logs |
| **Total** | **45** | |

### S3 Bucket Structure

```
sow-po-manager-documents-{random}/
├── uploads/                    # Original PDFs
│   └── DOC#{uuid}/
│       └── document.pdf
│
├── text/                       # Extracted text
│   └── DOC#{uuid}.txt
│
└── [future]
    ├── thumbnails/            # PDF previews
    └── exports/               # Excel/CSV exports
```

**Lifecycle Rules**:
- `uploads/`: Transition to Glacier after 90 days
- `text/`: Delete after 365 days (can regenerate from PDF)

### DynamoDB Table Design

**Table**: `sow-po-manager-documents`

**Primary Key**:
- `PK` (String): Partition key - `DOC#{document_id}`
- `SK` (String): Sort key - `VERSION#{version}` or `LATEST`

**Global Secondary Index**:
- **ClientNameIndex**: `client_name` (hash) + `created_at` (range)

**Item Structure**:
```json
{
  "PK": "DOC#uploads/DOC#abc123/document.pdf",
  "SK": "VERSION#1.0.0",
  "document_id": "DOC#abc123",
  "s3_bucket": "sow-po-manager-documents-xyz",
  "s3_key": "uploads/DOC#abc123/document.pdf",
  "created_at": "2025-11-11T00:00:00Z",
  "structured_data": {
    "client_name": "TESCO MOBILE LIMITED",
    "contract_value": 44800,
    "start_date": "2025-10-01",
    "end_date": "2025-12-31",
    "po_number": "PO-12345",
    "day_rates": [
      {"role": "Solution Designer", "rate": 700, "currency": "GBP"}
    ],
    "signatures_present": true
  },
  "extraction_confidence": 0.95,
  "validation_passed": true,
  "page_count": 4,
  "text_length": 6207,
  "chunks_created": 8,
  "processing_time_seconds": 11
}
```

**Access Patterns**:
1. Get latest version: `PK = DOC#abc123 AND SK = LATEST`
2. Get specific version: `PK = DOC#abc123 AND SK = VERSION#1.0.0`
3. List all versions: `PK = DOC#abc123 AND SK BEGINS_WITH VERSION#`
4. Query by client: `ClientNameIndex WHERE client_name = "TESCO"`

### SQS Queue Chain

**Pattern**: Sequential processing through 5 stages

```
┌─────────────────┐
│ extract-text-   │
│     queue       │
└────────┬────────┘
         ▼
┌─────────────────┐
│  chunk-queue    │
└────────┬────────┘
         ▼
┌─────────────────┐
│ extraction-     │
│     queue       │
└────────┬────────┘
         ▼
┌─────────────────┐
│ validation-     │
│     queue       │
└────────┬────────┘
         ▼
┌─────────────────┐
│  save-queue     │
└─────────────────┘

Each queue has a DLQ:
- extract-text-dlq
- chunk-dlq
- extraction-dlq
- validation-dlq
- save-dlq
```

**Queue Configuration**:
- **Visibility Timeout**: 300s (matches Lambda timeout)
- **Message Retention**: 4 days (main), 14 days (DLQ)
- **Max Receive Count**: 3 (then → DLQ)
- **Batch Size**: 1 (process one document at a time)

**Why SQS Chain vs Step Functions?**
- Lower cost (SQS free tier covers most usage)
- Simpler debugging (logs in each Lambda)
- Better retry control (per-stage DLQs)
- No state machine complexity

---

## Data Flow

### Document Upload Flow

```
1. User requests upload URL
   └─▶ GET /upload-link
       └─▶ Lambda: get_upload_link
           └─▶ Returns: presigned S3 URL

2. User uploads PDF to presigned URL
   └─▶ PUT to S3
       └─▶ S3 PutObject event
           └─▶ EventBridge rule matches
               └─▶ Message to extract-text-queue

3. extract-text Lambda triggered
   └─▶ Reads PDF from S3
       └─▶ Extracts text using pypdf
           └─▶ Saves text to S3
               └─▶ Forwards to chunk-queue

4. chunk-and-embed Lambda triggered
   └─▶ Reads text from S3
       └─▶ Chunks text (1000 chars, 200 overlap)
           └─▶ Generates embeddings (Bedrock)
               └─▶ Forwards to extraction-queue

5. extract-structured-data Lambda triggered
   └─▶ Reads text from S3
       └─▶ Calls Gemini API for extraction
           └─▶ Validates extracted data
               └─▶ Forwards to validation-queue

6. validate-data Lambda triggered
   └─▶ Business logic validation
       └─▶ Checks dates, values, required fields
           └─▶ Forwards to save-queue

7. save-metadata Lambda triggered
   └─▶ Writes to DynamoDB
       └─▶ Creates VERSION#1.0.0 and LATEST
           └─▶ Processing complete!
```

### Message Evolution

Example of how message grows through pipeline:

**Stage 1 Input** (from EventBridge):
```json
{
  "document_id": "DOC#abc123",
  "s3_bucket": "bucket-name",
  "s3_key": "uploads/DOC#abc123/document.pdf",
  "timestamp": "2025-11-11T00:00:00Z"
}
```

**Stage 2 Output** (extract-text):
```json
{
  ...previous fields...,
  "text_extracted": true,
  "text_s3_key": "text/DOC#abc123.txt",
  "text_length": 6207,
  "page_count": 4
}
```

**Stage 3 Output** (chunk-and-embed):
```json
{
  ...previous fields...,
  "chunks_created": 8,
  "embeddings_persisted": 8,
  "embeddings_s3_prefix": "embeddings/DOC#abc123/"
}
```

**Note**: Embeddings are now actually persisted to S3 at `s3://bucket/embeddings/{doc_id}/00000.json`, etc. Each embedding file contains:
- document_id
- chunk_index
- embedding (1024-dimensional vector from Titan V2)
- text_len

**Stage 4 Output** (extract-structured-data):
```json
{
  ...previous fields...,
  "structured_data": {...},
  "extraction_confidence": 0.95
}
```

**Stage 5 Output** (validate-data):
```json
{
  ...previous fields...,
  "validation_passed": true,
  "validation_warnings": [],
  "validation_errors": []
}
```

**Final** (saved to DynamoDB).

---

## Lambda Functions

### 1. get_upload_link

**Purpose**: Generate presigned S3 URLs for document upload

**Trigger**: API Gateway / Direct invocation
**Runtime**: Python 3.11
**Memory**: 256 MB
**Timeout**: 30s

**Input**:
```json
{
  "filename": "contract.pdf",
  "client_name": "TESCO MOBILE" (optional)
}
```

**Output**:
```json
{
  "upload_url": "https://s3.amazonaws.com/...",
  "document_id": "DOC#abc123",
  "s3_key": "uploads/DOC#abc123/document.pdf",
  "expires_in": 3600
}
```

**Key Logic**:
- Generates UUID for document ID
- Creates presigned PUT URL (1 hour expiry)
- Adds metadata headers (client_name, timestamp)

### 2. extract_text

**Purpose**: Extract text from PDF documents

**Trigger**: SQS (extract-text-queue)
**Runtime**: Python 3.11
**Memory**: 512 MB
**Timeout**: 300s

**Dependencies**:
- pypdf==6.2.0

**Process**:
1. Download PDF from S3
2. Extract text page-by-page using pypdf
3. Combine all pages with page markers
4. Save to S3 as .txt file
5. Forward message with text metadata

**Error Handling**:
- Retry up to 3 times (SQS maxReceiveCount)
- Failed PDFs go to DLQ
- Logs full error details to CloudWatch

### 3. chunk_and_embed

**Purpose**: Chunk text and generate embeddings

**Trigger**: SQS (chunk-queue)
**Runtime**: Python 3.11
**Memory**: 512 MB
**Timeout**: 300s

**Recent Fixes (v1.1.0)**:
- ✅ Embeddings now actually persist to S3 (was falsely claiming success)
- ✅ PII removed from logs (GDPR compliance)
- ✅ Uses eu-west-1 Bedrock region (eliminates cross-region latency)
- ✅ Updated to Titan Embeddings V2 (1024 dimensions)
- ✅ Added retry/timeout config for resilience

**Dependencies**:
- boto3 (AWS Bedrock)
- botocore (for Config retry/timeout)

**Process**:
1. Download text from S3
2. Split into chunks (1000 chars, 200 overlap)
3. Generate embeddings via Bedrock Titan V2
4. **Persist embeddings to S3** at `s3://bucket/embeddings/{doc_id}/`
5. Forward message with embeddings metadata (not the embeddings themselves)

**Chunking Strategy**:
- Size: 1000 characters
- Overlap: 200 characters (20%)
- Preserves context across chunks
- Handles multi-page documents

### 4. extract_structured_data

**Purpose**: Extract structured data using Gemini AI

**Trigger**: SQS (extraction-queue)
**Runtime**: Python 3.11
**Memory**: 1024 MB
**Timeout**: 300s

**Dependencies**:
- requests==2.32.5

**Process**:
1. Download text from S3
2. Format extraction prompt
3. Call Gemini 2.5 Flash API
4. Parse JSON response
5. Validate extracted data
6. Forward with structured data

**Gemini Integration**:
- **API**: REST API (not SDK - avoids grpc issues)
- **Model**: gemini-2.5-flash
- **Temperature**: 0.1 (consistent extraction)
- **Max tokens**: 2048
- **Retry**: 3 attempts with exponential backoff

**Extracted Fields**:
- client_name (required)
- contract_value (GBP)
- start_date / end_date (ISO format)
- po_number
- day_rates (array of {role, rate, currency})
- signatures_present (boolean)

### 5. validate_data

**Purpose**: Business logic validation

**Trigger**: SQS (validation-queue)
**Runtime**: Python 3.11
**Memory**: 256 MB
**Timeout**: 300s

**Validation Rules**:
- Client name required and non-empty
- Contract value must be positive
- End date after start date
- Day rates must be positive
- Dates in reasonable range (not future >2 years)

**Validation Levels**:
- **Errors**: Block processing (rare)
- **Warnings**: Flag for review but continue
- **Info**: Informational only

### 6. save_metadata

**Purpose**: Persist to DynamoDB

**Trigger**: SQS (save-queue)
**Runtime**: Python 3.11
**Memory**: 256 MB
**Timeout**: 300s

**Process**:
1. Receive validated message
2. Calculate processing time
3. Write VERSION#1.0.0 item
4. Write LATEST pointer
5. Log completion

**Versioning Strategy**:
- Each re-process creates new version
- LATEST always points to newest
- Old versions retained for audit

### 7. search_api

**Purpose**: Vector search over documents (future)

**Trigger**: API Gateway (future)
**Runtime**: Python 3.11
**Memory**: 1024 MB
**Timeout**: 30s

**Planned Features**:
- Semantic search using embeddings
- Filter by client, date range, value
- Full-text search
- Export to Excel/CSV

---

## Message Contract

### Contract Pattern

**Rule**: Each Lambda MUST preserve all input fields

**Benefits**:
- Full traceability
- Easy debugging
- Can replay from any stage
- No lost data

**Example**:
```python
# ❌ WRONG - Discards fields
message = {
    "document_id": event["document_id"],
    "new_field": "value"
}

# ✅ CORRECT - Preserves all fields
message = {
    **event,  # Spread all existing fields
    "new_field": "value"  # Add new field
}
```

### Error Accumulation

Errors accumulate in `errors` array:

```json
{
  "document_id": "DOC#abc123",
  "errors": [
    {
      "stage": "extract-text",
      "error": "Warning: Low quality scan",
      "timestamp": "2025-11-11T00:00:00Z"
    },
    {
      "stage": "extraction",
      "error": "Could not parse PO number",
      "timestamp": "2025-11-11T00:00:05Z"
    }
  ]
}
```

This allows:
- Tracking which stage failed
- Multiple warnings without blocking
- Full error history

---

## Security Architecture

### IAM Permissions

**Lambda Execution Role**:
```json
{
  "S3": ["GetObject", "PutObject", "DeleteObject"],
  "DynamoDB": ["PutItem", "GetItem", "UpdateItem", "Query", "Scan"],
  "SQS": ["SendMessage", "ReceiveMessage", "DeleteMessage"],
  "Bedrock": ["InvokeModel"],
  "CloudWatch": ["PutLogEvents", "CreateLogStream"]
}
```

**Principle of Least Privilege**:
- Lambda can only access specific bucket
- DynamoDB restricted to one table
- SQS limited to project queues

### Secrets Management

**Current** (Development):
- Gemini API key in terraform.tfvars (git-ignored)
- Passed as environment variable to Lambda

**Recommended** (Production):
- Store in AWS Secrets Manager
- Lambda retrieves at runtime
- Rotate keys periodically

### Data Protection

**At Rest**:
- S3: Server-side encryption (SSE-S3)
- DynamoDB: Encryption enabled by default
- CloudWatch Logs: Encrypted

**In Transit**:
- All AWS API calls use HTTPS
- Gemini API calls use HTTPS
- No plaintext transmission

### Network Security

**Current**: Lambda in AWS managed VPC

**Future**:
- Deploy Lambda in custom VPC
- Use VPC endpoints for S3, DynamoDB, SQS
- Private subnets with NAT gateway
- Security groups restrict traffic

---

## Cost Optimization

### Current Costs (~£2.70/month)

| Service | Usage | Cost |
|---------|-------|------|
| Lambda | 1M requests | $0.50 |
| DynamoDB | On-demand, light | $1.25 |
| S3 | 100 docs/month | $0.50 |
| CloudWatch | 7-day retention | $0.25 |
| SQS | Free tier | $0.00 |
| Data transfer | Minimal | $0.10 |
| **Total** | | **~$2.70** |

### Optimization Strategies

**Lambda**:
- Right-size memory (currently 256-1024 MB)
- Reduce timeout where possible
- Use ARM64 (Graviton2) for 20% cost reduction

**DynamoDB**:
- On-demand good for variable load
- Consider provisioned if consistent traffic
- Enable TTL to auto-delete old items

**S3**:
- Lifecycle rules to Glacier (90 days)
- Delete processed text files (can regenerate)
- Use S3 Intelligent-Tiering

**CloudWatch**:
- Reduce log retention (currently 7 days)
- Filter logs to reduce volume
- Aggregate similar log lines

### Monitoring Costs

```bash
# Enable cost allocation tags
make enable-cost-tracking

# View monthly costs
make cost-report

# Detailed breakdown by service
make cost-report-detailed
```

---

## Scalability

### Current Limits

| Resource | Limit | Can Scale To |
|----------|-------|--------------|
| Lambda concurrency | 1000 default | 10,000+ |
| SQS throughput | Unlimited | Unlimited |
| DynamoDB writes | On-demand | Unlimited |
| S3 requests | 5,500 PUT/s | Higher with prefix |

### Scaling Considerations

**Lambda**:
- Auto-scales to handle load
- Reserve concurrency if needed
- Monitor cold starts

**SQS**:
- Scales automatically
- Increase batch size for higher throughput
- Use FIFO if ordering required

**DynamoDB**:
- On-demand auto-scales
- Monitor consumed capacity
- Switch to provisioned if predictable

**S3**:
- Infinite scale
- Use prefixes for >5500 req/s
- CloudFront if global access needed

---

## Monitoring & Observability

### CloudWatch Logs

Each Lambda has dedicated log group:
- `/aws/lambda/sow-po-manager-extract-text`
- `/aws/lambda/sow-po-manager-chunk-and-embed`
- `/aws/lambda/sow-po-manager-extract-structured-data`
- etc.

**Log Retention**: 7 days (configurable)

### Metrics

**Lambda Metrics**:
- Invocations
- Duration
- Errors
- Throttles
- Concurrent executions

**SQS Metrics**:
- Messages sent
- Messages received
- Messages in flight
- DLQ depth

**DynamoDB Metrics**:
- Read/write capacity
- Throttled requests
- Latency

### Alarms (Future)

Recommended CloudWatch Alarms:
- Lambda error rate > 5%
- DLQ depth > 0
- Lambda duration > 280s (near timeout)
- DynamoDB throttles > 0
- Extraction confidence < 80%

---

## Disaster Recovery

### Backup Strategy

**S3**:
- Versioning enabled
- Cross-region replication (future)
- Lifecycle to Glacier for long-term

**DynamoDB**:
- Point-in-time recovery enabled
- On-demand backups before major changes
- Backups retained 35 days

### Recovery Procedures

**Lost Document**:
1. Check S3 versions
2. Restore from version history
3. Re-trigger processing

**Corrupted DynamoDB**:
1. Restore from point-in-time
2. Or restore from on-demand backup
3. Replay SQS DLQ messages

**Lambda Failure**:
1. Check CloudWatch Logs
2. Fix code issue
3. Redeploy Lambda
4. Replay messages from DLQ

### RTO/RPO

- **RTO** (Recovery Time Objective): < 1 hour
- **RPO** (Recovery Point Objective): < 1 hour (point-in-time recovery)

---

## Future Enhancements

### Planned Features

1. **API Gateway**: RESTful API for programmatic access
2. **Cognito**: User authentication
3. **Step Functions**: Alternative to SQS for complex workflows
4. **ElasticSearch**: Full-text search
5. **CloudFront**: CDN for UI
6. **Route 53**: Custom domain
7. **WAF**: Web application firewall

### Scaling Roadmap

1. **Phase 1**: Current (1-100 docs/month)
2. **Phase 2**: Add caching, CDN (100-1000 docs/month)
3. **Phase 3**: Multi-region, reserved capacity (1000+ docs/month)

---

## References

- [AWS Lambda Best Practices](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html)
- [DynamoDB Best Practices](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/best-practices.html)
- [SQS Best Practices](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-best-practices.html)
- [Gemini API Documentation](https://ai.google.dev/docs)
