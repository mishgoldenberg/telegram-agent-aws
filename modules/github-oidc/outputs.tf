output "plan_role_arn" {
  description = "Set as AWS_PLAN_ROLE_ARN in the workflow. Assumed on pull requests."
  value       = aws_iam_role.plan.arn
}

output "apply_role_arn" {
  description = "Set as AWS_APPLY_ROLE_ARN in the workflow. Assumed on pushes to the default branch."
  value       = aws_iam_role.apply.arn
}

output "boundary_policy_arn" {
  description = "Permissions boundary every CI-created role must carry."
  value       = aws_iam_policy.boundary.arn
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.github.arn
}

output "trusted_subs" {
  description = <<-EOT
    The exact sub claims these roles accept. Worth printing: if a workflow
    fails with "Not authorized to perform sts:AssumeRoleWithWebIdentity", the
    token's sub did not match one of these, and comparing the two is the
    fastest way to see why.
  EOT
  value = {
    plan  = local.sub_pull_request
    apply = local.sub_apply_environment
  }
}
