output "name" {
  description = "Bucket name."
  value       = aws_s3_bucket.audio.id
}

output "arn" {
  description = "Bucket ARN, used to scope IAM policies."
  value       = aws_s3_bucket.audio.arn
}

output "object_prefix" {
  description = "Prefix under which voice notes are written."
  value       = var.object_prefix
}
