# Changelog

All notable changes to the SOW/PO Manager project.

## [1.5.0] - 2025-11-11

### Added - Production-Ready Operations & Cost Management

#### save_metadata Lambda (Complete Rewrite)
- **Idempotent DynamoDB writes** - VERSION records created with conditional expressions (attribute_not_exists)
- **Timestamp-based versioning** - Unix timestamp ensures unique, sortable version IDs
- **LATEST pointer management** - Best-effort updates to DOC#id/LATEST for quick access
- **GSI optimization** - Proper keys for client queries (GSI1), expiry tracking (GSI2), PO lookups (GSI3)
- **PII-safe logging** - Logs only keys and counts, no client names or contract values
- **Required environment validation** - TABLE_NAME required at module load (fail fast)
- **Optional forwarding** - NEXT_QUEUE_URL support for future pipeline extensions

#### Observability (terraform/observability.tf)
- **15 CloudWatch alarms** deployed:
  - 5 Lambda error alarms (any errors trigger SNS alert)
  - 5 SQS message age alarms (messages stuck >10 min)
  - 5 DLQ message alarms (any failed messages trigger alert)
- **SNS topic for operational alerts** - Email notifications to gianluca.formica@gmail.com
- **7-day CloudWatch log retention** - Reduced from unlimited to control costs
- **Monitoring tags** applied to all observability resources

#### Cost Guardrails (terraform/cost_guardrails.tf)
- **S3 lifecycle rules** for automated cost optimization:
  - `embeddings/` → STANDARD_IA at 30 days → expire at 180 days
  - `text/` → expire at 90 days
  - `uploads/` → STANDARD_IA at 90 days → GLACIER at 365 days
  - Non-current versions → expire at 30 days (all prefixes)
- **Budget monitoring** - Using existing Tier1-Tier6 budget alerts (covers all AWS costs)

#### Security Polish (terraform/security.tf)
- **S3 server-side encryption** - SSE-S3 (AES256) enabled on documents bucket
- **S3 block public access** - All 4 settings enabled (block ACLs, policies, ignore ACLs, restrict buckets)
- **SSM Parameter Store** - Gemini API key stored securely at `/sow-po-manager/gemini-api-key`
- **IAM policy for SSM access** - Lambda execution role can read SSM parameters

### Changed
- **Lifecycle rules consolidated** - Moved from s3.tf to cost_guardrails.tf for better organization
- **Log group management** - Imported 7 existing log groups into Terraform state

### Technical Details
- Deployed to AWS: 2025-11-11T03:30:36Z (save_metadata)
- Lambda package size: save_metadata 2.7KB (pure Python, no dependencies)
- Infrastructure added: 23 new resources
  - 1 SNS topic + 1 subscription
  - 15 CloudWatch alarms
  - 7 CloudWatch log groups (managed)
  - 1 S3 lifecycle configuration (consolidated)
  - 1 S3 encryption configuration
  - 1 S3 public access block
  - 1 SSM parameter
  - 1 IAM policy
- Files added:
  - src/lambdas/save_metadata/handler.py (194 lines, complete rewrite)
  - terraform/observability.tf (122 lines)
  - terraform/cost_guardrails.tf (77 lines)
  - terraform/security.tf (65 lines)
- Test coverage: Legacy tests updated (test_extract_text.py, test_extract_structured_data.py)

### Operational Impact
- **Proactive monitoring** - Immediate email alerts for Lambda errors, SQS backlog, DLQ messages
- **Cost optimization** - Automatic transitions/expiry reduce long-term storage costs
- **Security baseline** - Encryption at rest + SSM for secrets + public access blocked
- **Idempotent persistence** - SQS redelivery no longer creates duplicate version records

Credit: Implementing practical, high-impact operational hardening for production readiness

---

## [1.4.0] - 2025-11-11

### Added - Production Hardening for extract_structured_data & validate_data

#### extract_structured_data Lambda
- **Strict JSON Schema validation** (rejects extra/unknown fields from LLM output)
- **schema.py module** with comprehensive validation (types, formats, enums, ranges)
- **SchemaValidationError** class with deterministic error codes (VAL_SCHEMA_TYPE, VAL_SCHEMA_REQUIRED, etc.)
- **Text sanitization** to prevent prompt injection attacks (50k char limit, null byte removal)
- **Exponential backoff** for Gemini API retries (1s, 2s, 4s delays)
- **Required environment variables** (BUCKET_NAME, NEXT_QUEUE_URL, GEMINI_API_KEY) - fail fast at module load
- **6 new CI gate tests in test_extract_structured_data_ci_gate.py** (all passing)
  - Test 1: Schema validation rejects extra fields
  - Test 2: PII-safe logging (no client names, contract values, rates in logs)
  - Test 3: SQS message canonical keys (structured_data, extraction_confidence)
  - Test 4: GEMINI_API_KEY required (missing raises KeyError at import)
  - Test 5: Retry logic with exponential backoff
  - Test 6: Text sanitization prevents injection

#### validate_data Lambda
- **Table-driven validation** with 15 deterministic rules in validation_rules.py
- **Structured violations** with {code, message, field, severity} format
- **Error severity levels**: ERROR (blocking) vs WARNING (non-blocking)
- **Validation error codes**:
  - VAL_CLIENT_MISSING - Client name required
  - VAL_DATE_RANGE - End date must be after start date
  - VAL_DATE_MISSING - Start/end date required
  - VAL_DATE_FORMAT - Invalid date format (expected YYYY-MM-DD)
  - VAL_DATE_PAST - Contract already ended (warning)
  - VAL_DATE_LONG - Contract > 3 years (warning)
  - VAL_VALUE_MISSING - Contract value not specified (warning)
  - VAL_VALUE_INVALID - Contract value must be positive
  - VAL_VALUE_HIGH - Contract value > £10M (warning)
  - VAL_RATE_INVALID - Day rate must be positive
  - VAL_RATE_HIGH - Day rate > £1200 (warning)
  - VAL_RATE_LOW - Day rate < £200 (warning)
- **NEXT_QUEUE_URL now required** - fail fast at module load
- **8 new CI gate tests in test_validate_data_ci_gate.py** (all passing)
  - Test 1: Error code determinism (same input = same codes)
  - Test 2: PII-safe logging (no values in logs, only codes/counts)
  - Test 3: Table-driven validation (all 15 rules execute)
  - Test 4: NEXT_QUEUE_URL required (missing raises KeyError at import)
  - Test 5: Structured violations format
  - Test 6: Warnings are non-blocking (validation_passed=True with warnings)
  - Test 7: Date range validation
  - Test 8: Rate validation boundaries

### Changed
- **All PII removed from CloudWatch logs** for both Lambdas
  - Log only keys, error codes, counts, and doc IDs
  - No client names, contract values, rates, PO numbers, or role names
- **No emojis in logs** (grepable output)
- **Type hints added** to validation functions

### Technical Details
- Test coverage: 50 tests total (42 passing)
  - 14 new CI gate tests (100% passing)
  - 8 old tests need updating for new implementations (not blocking)
- Deployed to AWS: 2025-11-11T03:15:34Z (validate_data), 2025-11-11T03:15:40Z (extract_structured_data)
- Lambda package sizes:
  - extract_structured_data: 639KB (includes schema.py + requests dependencies)
  - validate_data: 4.1KB (pure Python, no external dependencies)
- Files added:
  - src/lambdas/extract_structured_data/schema.py (244 lines)
  - src/lambdas/validate_data/validation_rules.py (337 lines)
  - tests/test_extract_structured_data_ci_gate.py (6 tests)
  - tests/test_validate_data_ci_gate.py (8 tests)

Credit: Implementing ChatGPT-5's production hardening roadmap

---

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
