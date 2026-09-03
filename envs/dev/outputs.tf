output "webhook_url" {
  description = "Register this with Telegram setWebhook. Contains the secret path."
  value       = module.http_api.webhook_url
  sensitive   = true
}

output "webhook_secret" {
  description = "Pass as secret_token to setWebhook; Telegram echoes it in every request."
  value       = random_password.webhook_secret.result
  sensitive   = true
}

output "queue_url" {
  description = "The local worker long-polls this."
  value       = module.job_queue.url
}

output "dlq_url" {
  value = module.job_queue.dlq_url
}

output "table_name" {
  value = module.state_table.name
}

output "audio_bucket" {
  value = module.audio_bucket.name
}

output "worker_access_key_id" {
  description = "Access key for the local worker."
  value       = aws_iam_access_key.worker.id
}

output "worker_secret_access_key" {
  description = <<-EOT
    Secret key for the local worker. Written into worker/.env, which is
    gitignored.

    This value lives in Terraform state in plaintext. That is inherent to
    creating an access key in Terraform and is the strongest argument for the
    IAM Roles Anywhere upgrade described in the README.
  EOT
  value       = aws_iam_access_key.worker.secret
  sensitive   = true
}

output "alarm_names" {
  description = "Every CloudWatch alarm created."
  value       = module.observability.alarm_names
}

output "sns_topic_arn" {
  value = module.observability.topic_arn
}
