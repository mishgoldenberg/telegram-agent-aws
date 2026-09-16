output "state_bucket_name" {
  description = "Paste into the backend block of every envs/* stack."
  value       = aws_s3_bucket.state.id
}

output "gha_plan_role_arn" {
  description = "Repository variable AWS_PLAN_ROLE_ARN."
  value       = module.github_oidc.plan_role_arn
}

output "gha_apply_role_arn" {
  description = "Repository variable AWS_APPLY_ROLE_ARN."
  value       = module.github_oidc.apply_role_arn
}

output "gha_trusted_subs" {
  description = "The exact sub claims CI may present. First thing to check when a workflow cannot assume a role."
  value       = module.github_oidc.trusted_subs
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
