###############################################################################
# modules/observability — alarms that would actually wake someone up.
#
# The design question is not "what can I measure" but "what failure would I
# otherwise not notice". Everything here is chosen against that test; metrics
# that merely look impressive on a dashboard are omitted.
#
# All alarms are STANDARD resolution (60s periods). The CloudWatch free tier
# covers 10 standard-resolution alarm metrics; high-resolution alarms are
# billed separately and buy nothing here.
###############################################################################

resource "aws_sns_topic" "alerts" {
  name = "${var.project}-${var.environment}-alerts"

  tags = {
    Component = "observability"
  }
}

# Email subscriptions require the recipient to click a confirmation link. Until
# then the subscription is "PendingConfirmation" and alarms deliver to nobody —
# a silent failure that looks exactly like success in the Terraform output.
resource "aws_sns_topic_subscription" "email" {
  for_each = toset(var.alert_emails)

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = each.value
}

###############################################################################
# THE ALARM THAT MATTERS
###############################################################################

# Age of the oldest message on the work queue.
#
# This is the only alarm here that detects the failure mode nobody else would
# catch: the home machine is asleep, the worker crashed, Ollama died, or the
# house lost internet. In every one of those cases AWS is perfectly healthy.
# Lambda errors are zero. API Gateway returns 200. Messages simply pile up
# and the assistant stops answering, silently.
#
# Nothing on the AWS side is broken, so nothing on the AWS side would alarm.
# Queue age is the one signal that crosses the boundary into the part of the
# system AWS cannot see.
resource "aws_cloudwatch_metric_alarm" "queue_age" {
  alarm_name        = "${var.project}-${var.environment}-worker-not-consuming"
  alarm_description = "Oldest job has waited over ${var.queue_age_threshold_seconds}s. The local worker is probably down: PC asleep, worker crashed, Ollama down, or no internet at home."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateAgeOfOldestMessage"
  statistic   = "Maximum"
  period      = 60

  dimensions = {
    QueueName = var.queue_name
  }

  comparison_operator = "GreaterThanThreshold"
  threshold           = var.queue_age_threshold_seconds
  evaluation_periods  = 2 # two consecutive minutes, so a slow single job is not an alert

  # An empty queue emits no datapoints at all. Treating missing data as
  # breaching would page every time the assistant is simply idle, which is
  # most of the time.
  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Component = "observability" }
}

# Anything in the DLQ is a message that failed three times. That is always a
# bug and always worth a human looking, however small the number.
resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name        = "${var.project}-${var.environment}-dlq-not-empty"
  alarm_description = "A job failed ${var.max_receive_count} times and was quarantined. Inspect the DLQ."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"
  statistic   = "Maximum"
  period      = 300

  dimensions = {
    QueueName = var.dlq_name
  }

  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1

  treat_missing_data = "notBreaching"
  alarm_actions      = [aws_sns_topic.alerts.arn]

  tags = { Component = "observability" }
}

# Per-function error alarms. Scoped per function rather than one aggregate, so
# the notification says which half of the pipeline broke.
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = toset(var.lambda_function_names)

  # each.value is already the fully-qualified function name
  # (project-environment-function), so no prefix here.
  alarm_name        = "${each.value}-errors"
  alarm_description = "Lambda ${each.value} is throwing. Check its log group."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  statistic   = "Sum"
  period      = 300

  dimensions = {
    FunctionName = each.value
  }

  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1

  treat_missing_data = "notBreaching"
  alarm_actions      = [aws_sns_topic.alerts.arn]

  tags = { Component = "observability" }
}

# Lambda throttling means reserved concurrency was hit: either a genuine flood,
# or the cap is set too low. Either way it means messages are being dropped on
# the floor, and it is invisible in the Errors metric because a throttled
# invocation never runs.
resource "aws_cloudwatch_metric_alarm" "ingest_throttles" {
  alarm_name        = "${var.ingest_function_name}-throttled"
  alarm_description = "Ingest hit its reserved concurrency ceiling. Either a flood against the public webhook, or the cap is too low for real traffic."

  namespace   = "AWS/Lambda"
  metric_name = "Throttles"
  statistic   = "Sum"
  period      = 300

  dimensions = {
    FunctionName = var.ingest_function_name
  }

  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1

  treat_missing_data = "notBreaching"
  alarm_actions      = [aws_sns_topic.alerts.arn]

  tags = { Component = "observability" }
}
