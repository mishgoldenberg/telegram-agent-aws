###############################################################################
# modules/audio-bucket — short-lived storage for Telegram voice notes.
#
# Telegram webhooks do NOT contain the audio. The update carries a file_id;
# something must call getFile and download from api.telegram.org. The ingest
# Lambda does that and writes the result here.
#
# WHY S3 IS IN THE PATH AT ALL
# ----------------------------
# The worker could download from Telegram directly and skip this bucket. S3
# earns its place by making the PUT the commit point: the transcription job is
# only enqueued once the audio is durably stored, via the bucket's own event
# notification. That removes an entire failure mode where a job references
# audio that was never saved.
###############################################################################

resource "aws_s3_bucket" "audio" {
  bucket        = "${var.project}-${var.environment}-audio-${var.name_suffix}"
  force_destroy = var.force_destroy

  tags = {
    Component = "audio-bucket"
  }
}

# Voice notes are personal data. This bucket must never be public.
resource "aws_s3_bucket_public_access_block" "audio" {
  bucket = aws_s3_bucket.audio.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audio" {
  bucket = aws_s3_bucket.audio.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# THE LIFECYCLE RULE IS THE POINT OF THIS BUCKET.
#
# Voice notes are transient: transcribed within seconds, never needed again.
# Without expiry the bucket accumulates recordings of everything you have ever
# said to the assistant, forever, at your expense. Expiring aggressively is
# both a cost control and a privacy control, and the second matters more.
resource "aws_s3_bucket_lifecycle_configuration" "audio" {
  bucket = aws_s3_bucket.audio.id

  rule {
    id     = "expire-voice-notes"
    status = "Enabled"

    filter {}

    expiration {
      days = var.expire_after_days
    }

    # A failed multipart upload leaves parts that are billed but invisible in
    # the console. This sweeps them.
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_policy" "tls_only" {
  bucket = aws_s3_bucket.audio.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.audio.arn,
        "${aws_s3_bucket.audio.arn}/*",
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.audio]
}

###############################################################################
# Event notification -> Lambda
###############################################################################

# S3 invokes Lambda using the S3 service principal, not an IAM role, so the
# permission lives on the FUNCTION as a resource policy rather than on a role.
#
# source_account is not decoration: without it, any S3 bucket in any AWS
# account could invoke this function by naming its ARN. This is the classic
# "confused deputy" gap in S3-to-Lambda wiring.
resource "aws_lambda_permission" "allow_s3" {
  statement_id   = "AllowExecutionFromS3"
  action         = "lambda:InvokeFunction"
  function_name  = var.notify_lambda_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.audio.arn
  source_account = var.account_id
}

resource "aws_s3_bucket_notification" "audio" {
  bucket = aws_s3_bucket.audio.id

  lambda_function {
    lambda_function_arn = var.notify_lambda_arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = var.object_prefix
  }

  # The permission must exist before S3 will accept the notification config —
  # S3 validates that it can actually invoke the target at configuration time.
  depends_on = [aws_lambda_permission.allow_s3]
}
