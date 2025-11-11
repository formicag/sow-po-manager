# Changelog

All notable changes to the SOW/PO Manager project.

## [1.3.0] - 2025-11-11

### Added - Atomic Handoff with manifest.json
- **manifest.json written LAST** after all chunks persisted to S3
- Manifest contains metadata: `document_id`, `embeddings_prefix`, `model`, `chunks`, `embedded`, `created_at`
- Downstream processes can now reliably detect completion by checking manifest existence
- Message now includes `embeddings_manifest` key for tracking

### Added - CI/CD Gate Tests
- **4 new tests in test_chunk_and_embed_ci_gate.py** (all passing)
- Test 1: Verifies S3 persistence (chunks + manifest.json)
- Test 2: Verifies SQS message purity (no PII, only canonical keys)
- Test 3: Verifies chunker guard (overlap < size raises ValueError)
- Test 4: Verifies NEXT_QUEUE_URL enforcement (missing raises KeyError)
- Uses fake AWS clients (no moto dependency, no real AWS calls)

### Changed
- Idempotency check now reads manifest.json instead of list_objects_v2 (more atomic)
- If manifest exists, metadata read from file instead of re-counting chunks
- Single S3 get_object call vs multiple list_objects calls (more efficient)

### Fixed
- NoSuchKey exception handling now uses ClientError (100% reliable)

### Technical Details
- Manifest provides audit trail with timestamp and model version
- Atomic handoff pattern: "if manifest exists, embeddings are complete"
- Test coverage: 9/9 passing (5 original + 4 CI gate)
- Deployed to AWS: 2025-11-11T02:48:58Z
- Manual verification: manifest created for DOC#test-v13

Credit: Implementing ChatGPT-5's enhancement suggestions and CI gate requirements

---

## [1.2.0] - 2025-11-11

### Fixed - Addressing Code Review Feedback
- **Production-correct defaults** - Changed fallback values from `us-east-1`/`titan-v1` to `eu-west-1`/`titan-v2:0` to match actual deployment
- **NEXT_QUEUE_URL now required** - Fails fast at module load if missing (was silently logging error)
- **Idempotency added** - Skips reprocessing if embeddings already exist in S3 (prevents duplicate work on SQS redelivery)

### Changed
- `BUCKET_NAME` and `NEXT_QUEUE_URL` now use `os.environ['KEY']` instead of `.get()` - raises KeyError immediately if missing
- Idempotency check uses `list_objects_v2` with `MaxKeys=1` for fast existence check
- Test suite updated to set required env vars before module import

### Technical Details
- Idempotency prevents wasted Bedrock API calls on message redelivery
- Environment variable validation happens at cold start, not request time
- All 5 chunk_and_embed tests still passing

Credit: Response to external code review (ChatGPT-5) identifying misleading defaults and missing idempotency

---

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
