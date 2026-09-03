output "api_endpoint" {
  description = "Base URL of the API, without the webhook path."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "webhook_url" {
  description = "Full URL to register with Telegram setWebhook. Sensitive: contains the secret path."
  value       = "${aws_apigatewayv2_api.this.api_endpoint}/${var.webhook_path}"
  sensitive   = true
}

output "api_id" {
  description = "API id; also the CloudWatch metric dimension ApiId."
  value       = aws_apigatewayv2_api.this.id
}

output "access_log_group" {
  value = aws_cloudwatch_log_group.access.name
}
