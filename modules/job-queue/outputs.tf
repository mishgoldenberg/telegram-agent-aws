output "url" {
  description = "Queue URL for producers and the local worker."
  value       = aws_sqs_queue.main.id
}

output "arn" {
  description = "Queue ARN, used to scope IAM policies to this queue alone."
  value       = aws_sqs_queue.main.arn
}

output "name" {
  description = "Queue name, used as a CloudWatch metric dimension."
  value       = aws_sqs_queue.main.name
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.id
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}

output "dlq_name" {
  description = "DLQ name, used as a CloudWatch metric dimension."
  value       = aws_sqs_queue.dlq.name
}
