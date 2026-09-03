output "state_bucket_name" {
  description = "Paste into the backend block of this stack and every envs/* stack."
  value       = aws_s3_bucket.state.id
}

output "lock_table_name" {
  description = "Paste into the backend block as dynamodb_table."
  value       = aws_dynamodb_table.lock.name
}

output "region" {
  description = "Region the backend lives in."
  value       = var.region
}

output "backend_block" {
  description = "Ready-to-paste backend configuration; substitute <STACK> per stack."
  value       = <<-EOT
    backend "s3" {
      bucket         = "${aws_s3_bucket.state.id}"
      key            = "<STACK>/terraform.tfstate"
      region         = "${var.region}"
      dynamodb_table = "${aws_dynamodb_table.lock.name}"
      encrypt        = true
    }
  EOT
}
