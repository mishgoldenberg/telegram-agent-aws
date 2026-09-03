output "arn" {
  description = "Function ARN."
  value       = aws_lambda_function.this.arn
}

output "name" {
  description = "Function name; also a CloudWatch metric dimension."
  value       = aws_lambda_function.this.function_name
}

output "invoke_arn" {
  description = "ARN in the form API Gateway integrations require."
  value       = aws_lambda_function.this.invoke_arn
}

output "role_arn" {
  value = aws_iam_role.this.arn
}

output "role_name" {
  value = aws_iam_role.this.name
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}
