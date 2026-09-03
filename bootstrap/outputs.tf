output "state_bucket_name" {
  description = "Paste into the backend block of every envs/* stack."
  value       = aws_s3_bucket.state.id
}

output "region" {
  description = "Region the backend lives in."
  value       = var.region
}

output "backend_block" {
  description = <<-EOT
    Ready-to-paste backend configuration; substitute <STACK> per stack.

    No dynamodb_table: locking uses use_lockfile, which relies on S3
    conditional writes. See the comment in main.tf for why the DynamoDB lock
    table was built and then removed.
  EOT
  value       = <<-EOT
    backend "s3" {
      bucket       = "${aws_s3_bucket.state.id}"
      key          = "<STACK>/terraform.tfstate"
      region       = "${var.region}"
      use_lockfile = true
      encrypt      = true
    }
  EOT
}
