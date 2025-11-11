# DynamoDB Single Table Design

resource "aws_dynamodb_table" "sow_documents" {
  name         = "${var.project_name}-documents"
  billing_mode = "PAY_PER_REQUEST" # On-demand pricing for cost efficiency

  hash_key  = "PK"
  range_key = "SK"

  # Primary key attributes
  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  # GSI1: Client queries
  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  # GSI2: Chunk lookup
  attribute {
    name = "GSI2PK"
    type = "S"
  }

  attribute {
    name = "GSI2SK"
    type = "S"
  }

  # GSI3: Duplicate detection (by PO number)
  attribute {
    name = "GSI3PK"
    type = "S"
  }

  attribute {
    name = "GSI3SK"
    type = "S"
  }

  # Global Secondary Index 1: Query by client
  global_secondary_index {
    name            = "ClientIndex"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  # Global Secondary Index 2: Query chunks by document
  global_secondary_index {
    name            = "ChunkIndex"
    hash_key        = "GSI2PK"
    range_key       = "GSI2SK"
    projection_type = "ALL"
  }

  # Global Secondary Index 3: Duplicate detection by PO number
  global_secondary_index {
    name            = "PONumberIndex"
    hash_key        = "GSI3PK"
    range_key       = "GSI3SK"
    projection_type = "ALL"
  }

  # Enable Point-in-Time Recovery (PITR)
  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  # Enable server-side encryption
  server_side_encryption {
    enabled = true
  }

  # TTL for temporary data (optional)
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = local.storage_tags
}

# DynamoDB Table Item Structure:
#
# 1. Document Versions:
#    PK: DOC#<uuid>
#    SK: VERSION#1.0.0
#    GSI1PK: CLIENT#<client_name>
#    GSI1SK: CREATED#<timestamp>
#    GSI3PK: PO_NUM#<po_number>
#    GSI3SK: CLIENT#<client_name>
#    Attributes: structured_data, metadata, s3_keys, validation_results
#
# 2. Latest Pointer (for fast reads):
#    PK: DOC#<uuid>
#    SK: LATEST
#    Attributes: copy of latest version data
#
# 3. Search Chunks:
#    PK: DOC#<uuid>
#    SK: CHUNK#001
#    GSI2PK: DOC#<uuid>
#    GSI2SK: CHUNK#001
#    Attributes: text_chunk, embedding_vector (binary), chunk_index
