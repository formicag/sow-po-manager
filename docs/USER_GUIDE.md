# User Guide

Complete guide for using the SOW/PO Document Management System.

## Table of Contents
- [Getting Started](#getting-started)
- [Uploading Documents](#uploading-documents)
- [Viewing Documents](#viewing-documents)
- [Understanding Results](#understanding-results)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

---

## Getting Started

### Accessing the System

#### Option 1: Flask UI (Local)

1. **Start the UI**:
   ```bash
   # Using Makefile
   make ui

   # Or using desktop launcher (macOS)
   # Double-click: start-ui.command
   ```

2. **Access in browser**:
   - Open: http://localhost:5000 (or next available port)
   - UI automatically finds free port (5000-5100)

#### Option 2: AWS Console

1. Navigate to S3 Console
2. Find bucket: `sow-po-manager-documents-*`
3. Upload PDFs to `uploads/` folder

#### Option 3: Command Line

```bash
# Get upload link
aws lambda invoke \
  --function-name sow-po-manager-get-upload-link \
  --cli-binary-format raw-in-base64-out \
  --payload '{"filename": "contract.pdf"}' \
  /tmp/response.json

# Upload PDF
curl -X PUT "$(cat /tmp/response.json | jq -r '.body | fromjson | .upload_url')" \
  --data-binary @contract.pdf \
  -H "Content-Type: application/pdf"
```

---

## Uploading Documents

### Supported Formats

- **PDF only** (for now)
- Maximum size: 10 MB (Lambda limit)
- Multi-page documents supported
- Text must be extractable (not scanned images)

### Upload Process

#### Via Flask UI

1. **Click "Upload Document"**
2. **Select PDF file** from your computer
3. **Add metadata** (optional):
   - Client name
   - Project name
   - Tags
4. **Click "Submit"**
5. **Wait for confirmation**

#### Via Command Line

```bash
# Single document
python3 scripts/upload_single.py contract.pdf

# Batch upload
python3 scripts/batch_upload_sows.py
```

### What Happens After Upload

The system automatically processes your document through 5 stages:

1. **Text Extraction** (~1-2 seconds)
   - Extracts all text from PDF
   - Handles multi-page documents
   - Preserves page structure

2. **Chunking & Embedding** (~2-3 seconds)
   - Splits text into searchable chunks
   - Generates AI embeddings
   - Enables semantic search

3. **AI Extraction** (~4-6 seconds)
   - Analyzes document with Google Gemini
   - Extracts structured data:
     - Client name
     - Contract value
     - Dates
     - Day rates
     - Signatures

4. **Validation** (~1 second)
   - Checks data quality
   - Flags anomalies
   - Validates business rules

5. **Storage** (~1 second)
   - Saves to database
   - Creates searchable index
   - Generates document ID

**Total Time**: 10-15 seconds per document

### Monitoring Upload Progress

#### In Flask UI

- Progress bar shows current stage
- Real-time status updates
- Error notifications if issues occur

#### In CloudWatch Logs

```bash
# Follow logs for a specific stage
aws logs tail /aws/lambda/sow-po-manager-extract-text --follow

# Search for your document
aws logs filter-log-events \
  --log-group-name /aws/lambda/sow-po-manager-save-metadata \
  --filter-pattern "DOC#your-doc-id"
```

---

## Viewing Documents

### List All Documents

#### Via Flask UI

1. Navigate to "Documents" page
2. See table of all processed documents
3. Columns show:
   - Document name
   - Client
   - Upload date
   - Processing status
   - Actions

#### Via Command Line

```bash
# List all documents
aws dynamodb scan \
  --table-name sow-po-manager-documents \
  --filter-expression "begins_with(SK, :sk)" \
  --expression-attribute-values '{":sk":{"S":"LATEST"}}' \
  | jq '.Items[].structured_data.M.client_name.S'
```

### View Document Details

#### Via Flask UI

1. Click document name
2. See full details:
   - Extracted data (client, value, dates)
   - Day rates
   - Signatures detected
   - Confidence score
   - Processing timeline

#### Via Command Line

```bash
# Get specific document
aws dynamodb get-item \
  --table-name sow-po-manager-documents \
  --key '{"PK":{"S":"DOC#abc123"},"SK":{"S":"LATEST"}}' \
  | jq .
```

### Search Documents

#### By Client Name

```bash
# Using GSI
aws dynamodb query \
  --table-name sow-po-manager-documents \
  --index-name ClientNameIndex \
  --key-condition-expression "client_name = :name" \
  --expression-attribute-values '{":name":{"S":"TESCO MOBILE"}}'
```

#### By Date Range

```bash
# Filter scan
aws dynamodb scan \
  --table-name sow-po-manager-documents \
  --filter-expression "created_at BETWEEN :start AND :end" \
  --expression-attribute-values '{
    ":start":{"S":"2025-01-01"},
    ":end":{"S":"2025-12-31"}
  }'
```

#### By Contract Value

```bash
# High-value contracts (>£50k)
aws dynamodb scan \
  --table-name sow-po-manager-documents \
  --filter-expression "structured_data.contract_value > :min" \
  --expression-attribute-values '{":min":{"N":"50000"}}'
```

---

## Understanding Results

### Extracted Data Fields

#### Client Name
- **What**: Company receiving the service
- **Example**: "TESCO MOBILE LIMITED"
- **Confidence**: Usually high (95%+)
- **Issues**: May include legal entity suffixes (Ltd, Limited, PLC)

#### Contract Value
- **What**: Total contract value in GBP
- **Example**: 44800
- **Format**: Number (not formatted with £ or commas)
- **Note**: May be null if not found in document

#### Start Date / End Date
- **What**: Contract period
- **Format**: ISO date (YYYY-MM-DD)
- **Example**: "2025-10-01"
- **Validation**: End date must be after start date

#### PO Number
- **What**: Purchase Order reference
- **Example**: "PO-12345" or "O-031443"
- **Note**: Often null if not present in SOW

#### Day Rates
- **What**: List of roles and their daily rates
- **Format**: Array of {role, rate, currency}
- **Example**:
  ```json
  [
    {"role": "Solution Designer", "rate": 700, "currency": "GBP"},
    {"role": "Senior Developer", "rate": 650, "currency": "GBP"}
  ]
  ```

#### Signatures Present
- **What**: Boolean indicating if signatures detected
- **Values**: true/false
- **Detection**: Looks for signature blocks, "Signed", dates

### Confidence Scores

| Score | Meaning | Action |
|-------|---------|--------|
| 95-100% | Very confident | Trust the data |
| 85-94% | Confident | Review key fields |
| 70-84% | Moderate | Manual verification recommended |
| <70% | Low | Check all fields manually |

**Factors affecting confidence**:
- Document quality (scanned vs digital)
- Formatting consistency
- Clear section headers
- Complete information

### Validation Warnings

#### Common Warnings

**"End date before start date"**
- Contract dates are illogical
- May indicate extraction error
- Review dates in original document

**"Contract value unusually high"**
- Value > £500,000
- Likely correct but flagged for review
- Check for currency confusion ($ vs £)

**"Missing required field: client_name"**
- AI couldn't find client name
- Document may use different terminology
- Manual review required

**"Day rate below minimum (£100)"**
- May indicate hourly rate extracted as daily
- Or offshore rates
- Verify with original document

#### How to Handle Warnings

1. **Click warning message** to see details
2. **Review original PDF** (download link provided)
3. **Edit extracted data** if incorrect
4. **Mark as reviewed** to dismiss warning

---

## Batch Operations

### Bulk Upload

Upload multiple documents at once:

```bash
# Upload all PDFs in a folder
python3 scripts/batch_upload_sows.py

# The script will:
# - Find all PDFs in SOWs/ directory
# - Upload each one
# - Track progress
# - Save manifest of uploaded documents
```

**Progress Tracking**:
- Console shows upload progress
- Manifest saved to `upload_manifest.json`
- Failed uploads listed for retry

### Export Data

Export all extracted data to Excel:

```bash
# Coming soon
python3 scripts/export_to_excel.py --output sow_data.xlsx
```

Will include:
- All extracted fields
- Upload dates
- Processing status
- Confidence scores

---

## Troubleshooting

### Upload Issues

#### "Upload failed: 403 Forbidden"

**Cause**: Presigned URL expired (1 hour timeout)
**Solution**: Get a new upload link and retry

#### "Document too large"

**Cause**: PDF > 10 MB
**Solution**:
- Compress PDF
- Or split into multiple documents
- Contact admin to increase limit

#### "No text extracted"

**Cause**: Scanned PDF (image, not text)
**Solution**:
- Use OCR tool first
- Or upload text-based PDF

### Processing Issues

#### "Stuck in processing"

**Check processing time**:
```bash
# Has it been > 5 minutes?
aws logs tail /aws/lambda/sow-po-manager-save-metadata --since 5m
```

**Common causes**:
- Lambda timeout (300s)
- Gemini API rate limit
- Large document

**Solution**:
- Check CloudWatch Logs for errors
- Document will retry automatically (max 3 times)
- Check Dead Letter Queue if failed

#### "Low confidence score"

**Reasons**:
- Poor PDF quality
- Non-standard format
- Incomplete information
- Scanned document

**Solutions**:
- Review and correct data manually
- Re-scan document at higher quality
- Use template documents for consistency

#### "Wrong data extracted"

**Examples**:
- Wrong client name
- Incorrect dates
- Missing day rates

**Debugging**:
1. Check CloudWatch Logs for Gemini response
2. Review extracted text (S3: `text/` folder)
3. Verify PDF is readable
4. Report issue with example for improvement

### Search Issues

#### "Document not found"

**Checks**:
1. Processing complete? (check status)
2. Correct document ID?
3. Using LATEST or VERSION#1.0.0?

**Query**:
```bash
# List all versions
aws dynamodb query \
  --table-name sow-po-manager-documents \
  --key-condition-expression "PK = :pk" \
  --expression-attribute-values '{":pk":{"S":"DOC#your-id"}}'
```

#### "Search returns no results"

**Common issues**:
- Case sensitivity (client names are uppercase)
- Exact match vs partial match
- Date format (must be ISO: YYYY-MM-DD)

**Solution**: Use `contains()` or `begins_with()` for partial matching

---

## Best Practices

### Document Preparation

1. **Use digital PDFs** (not scans)
2. **Consistent formatting** helps extraction
3. **Clear section headers** improve accuracy
4. **Standard templates** work best

### Naming Conventions

Recommended filename format:
```
{Client}_{Type}_{Date}_{Version}.pdf

Examples:
TescoMobile_SOW_2025-10-01_v1.0.pdf
Nasstar_PO_2025-Q1_Signed.pdf
```

### Data Verification

1. **Always review** extracted data
2. **Check confidence scores**
3. **Verify key fields**:
   - Client name (spelling)
   - Contract value (decimal point!)
   - Dates (correct year)
4. **Mark as reviewed** when verified

### Organization

1. **Tag documents** with:
   - Project name
   - Client name
   - Contract type (SOW, PO, Amendment)
   - Status (Draft, Signed, Complete)

2. **Use consistent client names**:
   - "TESCO MOBILE" vs "Tesco Mobile Ltd"
   - Pick one format for better searching

---

## FAQ

**Q: How long does processing take?**
A: 10-15 seconds per document on average.

**Q: Can I upload Word documents?**
A: Not directly. Convert to PDF first.

**Q: What if extraction is wrong?**
A: Edit the data manually in the UI, or report it for AI improvement.

**Q: Can I delete a document?**
A: Yes, but it only marks as deleted. Original PDF retained for audit.

**Q: How do I re-process a document?**
A: Upload again. System creates a new version (VERSION#2.0.0).

**Q: Is my data secure?**
A: Yes. Encrypted at rest and in transit. Access controlled by IAM.

**Q: Can I access via API?**
A: Not yet. Coming soon with API Gateway integration.

**Q: How much does it cost?**
A: ~£2.70/month for typical usage (100 docs/month). Gemini API billed separately.

**Q: Can I export data?**
A: Yes, to JSON via DynamoDB. Excel export coming soon.

**Q: What file size limit?**
A: 10 MB (Lambda limit). Can be increased if needed.

**Q: How many documents can I store?**
A: Unlimited (DynamoDB and S3 scale infinitely).

**Q: How do I get support?**
A: Create GitHub issue or check CloudWatch Logs for errors.

---

## Keyboard Shortcuts (UI)

| Shortcut | Action |
|----------|--------|
| `Ctrl+U` | Upload document |
| `Ctrl+F` | Search documents |
| `Ctrl+R` | Refresh list |
| `Esc` | Close modal |

---

## Next Steps

1. Upload your first document
2. Review extracted data
3. Set up regular batch uploads
4. Export data for reporting
5. Integrate with your workflows

For technical details, see [ARCHITECTURE.md](ARCHITECTURE.md).
For deployment, see [DEPLOYMENT.md](DEPLOYMENT.md).
