output "topic_arn" {
  description = "SNS topic all alarms publish to."
  value       = aws_sns_topic.alerts.arn
}

output "alarm_names" {
  description = "Every alarm created, for the README and for verification."
  value = concat(
    [
      aws_cloudwatch_metric_alarm.queue_age.alarm_name,
      aws_cloudwatch_metric_alarm.dlq_not_empty.alarm_name,
      aws_cloudwatch_metric_alarm.ingest_throttles.alarm_name,
    ],
    [for a in aws_cloudwatch_metric_alarm.lambda_errors : a.alarm_name],
  )
}
