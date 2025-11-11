# Changelog

All notable changes to the SOW/PO Manager project.

## [1.1.0] - 2025-11-11

### Fixed - Critical Bugs in chunk_and_embed Lambda
- **Embeddings now actually persist** to S3 at `s3://bucket/embeddings/{doc_id}/` (was falsely claiming `embeddings_stored=True`)
- **PII removed from CloudWatch logs** - no more full message dumps with client names, rates, contract values
- **Bedrock region parameterized** - now uses `eu-west-1` instead of hard-coded `us-east-1` (eliminates 100-200ms latency)
- **Updated to Titan Embeddings V2** - correct model ID `amazon.titan-embed-text-v2:0` (1024 dimensions)
- **Retry/timeout config added** - Bedrock calls get 3 retries with 15s timeout
- **Chunker validation** - prevents infinite loops if `overlap >= chunk_size`
- **SQS payload reduced** - removed chunk previews that risked hitting 256KB limit

### Added
- 5 new unit tests for chunk_and_embed using botocore.stub.Stubber (all passing)
- Type hints to chunk_and_embed handler functions
- Environment variables for BEDROCK_REGION, EMBED_MODEL_ID, EMBED_S3_PREFIX, CHUNK_SIZE, CHUNK_OVERLAP
- Proper S3 persistence of embeddings with structured JSON format

### Changed
- Logging now outputs only message keys, not full content (PII compliance)
- Removed emoji from logs (grepable output)
- Better error handling for missing NEXT_QUEUE_URL

### Technical Details
- Test suite expanded from 27 to 32 tests
- Embeddings verified persisting with 1024-dimensional vectors
- Cross-region latency eliminated
- Message Contract Pattern preserved with no PII in logs

Credit: Based on detailed code review identifying real production bugs

---

## [1.0.0] - 2025-11-10

### Initial Release
- Complete serverless SOW/PO document management system
- AWS infrastructure deployment (45 resources via Terraform)
- 5-stage SQS pipeline for document processing
- Google Gemini 2.5 Flash AI for structured data extraction
- AWS Bedrock for embeddings and vector search
- Flask UI with smart port selection
- 27 initial tests (20 passing)
- Batch document upload capability
- Complete documentation suite

### Features
- PDF text extraction (pypdf)
- Text chunking and embedding generation (AWS Bedrock)
- AI-powered structured data extraction (Google Gemini)
- Business logic validation
- DynamoDB persistence with versioning
- Dead letter queues for error handling
- Comprehensive tagging for cost tracking
- Target cost: <£5/month

### Infrastructure
- 7 Lambda functions
- S3 bucket with lifecycle rules
- DynamoDB single-table design with GSI
- 10 SQS queues (5 main + 5 DLQs)
- EventBridge for S3 event triggers
- CloudWatch Logs for monitoring
