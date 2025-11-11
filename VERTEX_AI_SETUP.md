# Vertex AI Setup Guide

This document explains how the SOW/PO Manager uses Google Vertex AI (Gemini Flash) for document extraction.

## Overview

We use **Vertex AI** instead of the direct Gemini API because:
- ✅ Better for production (enterprise-grade)
- ✅ Service account authentication (no API keys)
- ✅ Integrated with GCP IAM
- ✅ Better rate limits
- ✅ Proper billing tracking

## GCP Project Setup

**Project:** `context-engine-gf-2025`
**Service Account:** `sow-po-manager-sa@context-engine-gf-2025.iam.gserviceaccount.com`
**Region:** `us-central1`

### What We Created

1. **Enabled Vertex AI API** on the project
2. **Created service account** with Vertex AI User role
3. **Generated JSON key file** stored at `.secrets/vertex-ai-key.json`

### Service Account Permissions

The service account has the following role:
- `roles/aiplatform.user` - Allows using Vertex AI models (Gemini)

## How It Works

### In Lambda Functions

The `extract_structured_data` Lambda function:

1. **Loads credentials** from `vertex-ai-key.json` (packaged with Lambda)
2. **Initializes Vertex AI** client
3. **Calls Gemini 1.5 Flash** for document extraction
4. **Returns structured JSON** (validated with Pydantic)

### Environment Variables

The Lambda has these environment variables set:

```bash
GOOGLE_APPLICATION_CREDENTIALS=/var/task/vertex-ai-key.json
GCP_PROJECT_ID=context-engine-gf-2025
GCP_LOCATION=us-central1
```

### Packaging

When you run `make package-lambdas`, the Makefile:
1. Installs Python dependencies
2. **Copies `.secrets/vertex-ai-key.json`** into the Lambda package
3. Creates the ZIP file
4. Removes the key from the source directory (keeps it in ZIP only)

## Security

### Key File Protection

The key file is protected in multiple ways:

1. **gitignore** - Never committed to git
   ```
   .secrets/
   vertex-ai-key.json
   ```

2. **File permissions** - Owner read/write only (`-rw-------`)

3. **Lambda-only** - Key is only in the Lambda ZIP, not on disk elsewhere

### Key Rotation

To rotate the key:

```bash
# Delete old key
gcloud iam service-accounts keys list \
  --iam-account=sow-po-manager-sa@context-engine-gf-2025.iam.gserviceaccount.com

gcloud iam service-accounts keys delete KEY_ID \
  --iam-account=sow-po-manager-sa@context-engine-gf-2025.iam.gserviceaccount.com

# Create new key
gcloud iam service-accounts keys create .secrets/vertex-ai-key.json \
  --iam-account=sow-po-manager-sa@context-engine-gf-2025.iam.gserviceaccount.com \
  --project=context-engine-gf-2025

# Repackage and redeploy Lambda
make package-lambdas
make deploy
```

## Cost Tracking

Vertex AI costs are billed to your GCP project:

**Check costs:**
```bash
# Switch to the project
gcloud config set project context-engine-gf-2025

# View current month costs
gcloud billing projects describe context-engine-gf-2025 \
  --format="value(billingAccountName)"
```

**Gemini 1.5 Flash Pricing:**
- Input: $0.075 per 1M tokens (~$0.000075 per 1K tokens)
- Output: $0.30 per 1M tokens (~$0.0003 per 1K tokens)

**Example cost for 10 SOW documents:**
- Average document: 5,000 tokens input + 500 tokens output
- Cost per document: (5K × $0.000075) + (0.5K × $0.0003) = $0.000525
- **10 documents: ~$0.005 (half a penny)**

## Testing Vertex AI

### Test Locally

```python
import os
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '.secrets/vertex-ai-key.json'
os.environ['GCP_PROJECT_ID'] = 'context-engine-gf-2025'
os.environ['GCP_LOCATION'] = 'us-central1'

from vertexai.generative_models import GenerativeModel
import vertexai

vertexai.init(
    project='context-engine-gf-2025',
    location='us-central1'
)

model = GenerativeModel('gemini-1.5-flash')
response = model.generate_content('Hello, Vertex AI!')
print(response.text)
```

### Test in Lambda

After deploying, check CloudWatch Logs:

```bash
aws logs tail /aws/lambda/sow-po-manager-extract-structured-data \
  --region eu-west-1 \
  --follow
```

Look for:
```
✅ Vertex AI initialized: context-engine-gf-2025 / us-central1
```

## Troubleshooting

### Error: "Could not automatically determine credentials"

**Problem:** Lambda can't find the key file

**Solution:**
1. Check the key exists: `ls .secrets/vertex-ai-key.json`
2. Repackage Lambda: `make package-lambdas`
3. Check ZIP contents: `unzip -l dist/extract_structured_data.zip | grep vertex`

### Error: "Permission denied"

**Problem:** Service account doesn't have Vertex AI permissions

**Solution:**
```bash
gcloud projects add-iam-policy-binding context-engine-gf-2025 \
  --member="serviceAccount:sow-po-manager-sa@context-engine-gf-2025.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

### Error: "Quota exceeded"

**Problem:** Too many API calls

**Solution:** Check quotas in GCP Console:
```
https://console.cloud.google.com/iam-admin/quotas?project=context-engine-gf-2025
```

### Error: "Model not found"

**Problem:** Gemini model not available in region

**Solution:** Try different region:
```python
# In lambda handler
GCP_LOCATION = 'us-east1'  # or 'europe-west1'
```

## Key File Location

**Local development:**
```
.secrets/vertex-ai-key.json
```

**In Lambda:**
```
/var/task/vertex-ai-key.json
```

**Never in these locations:**
- ❌ git repository (gitignored)
- ❌ src/lambdas/extract_structured_data/ (except during build)
- ❌ GitHub secrets (too large)

## Updating the Key

If you need to regenerate the key or use a different project:

1. **Delete old key file:**
   ```bash
   rm .secrets/vertex-ai-key.json
   ```

2. **Create new key:**
   ```bash
   gcloud iam service-accounts keys create .secrets/vertex-ai-key.json \
     --iam-account=YOUR_SERVICE_ACCOUNT_EMAIL \
     --project=YOUR_PROJECT_ID
   ```

3. **Update Lambda environment variables** in `terraform/lambda.tf`:
   ```hcl
   GCP_PROJECT_ID = "your-new-project-id"
   ```

4. **Redeploy:**
   ```bash
   make package-lambdas
   make deploy
   ```

## Best Practices

1. **Never commit the key file** (already in .gitignore)
2. **Rotate keys every 90 days** (set a calendar reminder)
3. **Use separate service accounts** for dev/staging/prod
4. **Monitor costs** in GCP Console monthly
5. **Set up billing alerts** in GCP (separate from AWS)

## Support

If you encounter issues:

1. Check CloudWatch Logs for the Lambda
2. Verify service account permissions in GCP Console
3. Test Vertex AI credentials locally first
4. Check GCP quotas and billing

---

**Created:** 2025-11-10
**Author:** Claude Code (Sonnet 4.5)
