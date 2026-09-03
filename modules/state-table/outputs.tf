output "name" {
  description = "Table name, passed to Lambdas as an environment variable."
  value       = aws_dynamodb_table.this.name
}

output "arn" {
  description = "Table ARN, used to scope IAM policies to this table alone."
  value       = aws_dynamodb_table.this.arn
}
