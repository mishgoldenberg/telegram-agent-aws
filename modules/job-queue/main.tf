###############################################################################
# modules/job-queue — SQS work queue plus dead-letter queue.
#
# This is the outbound-only bridge to the local machine. The worker at home
# long-polls this queue; AWS never initiates a connection inwards, so nothing
# needs to be exposed on the home network and the whole thing works behind
# CGNAT.
###############################################################################

# DEAD-LETTER QUEUE — declared first because the main queue references it.
#
# Without a DLQ, a message that always fails is redelivered forever: the
# worker crashes on it, the visibility timeout expires, it reappears, the
# worker crashes again. That is an infinite loop that silently blocks every
# message behind it and quietly burns the SQS free tier.
resource "aws_sqs_queue" "dlq" {
  name = "${var.project}-${var.environment}-jobs-dlq"

  # Keep failures for the full two weeks. A DLQ message is a bug report; the
  # main queue's retention is about liveness, the DLQ's is about forensics.
  message_retention_seconds = 1209600 # 14 days, the maximum

  sqs_managed_sse_enabled = true

  tags = {
    Component = "job-queue-dlq"
  }
}

resource "aws_sqs_queue" "main" {
  name = "${var.project}-${var.environment}-jobs"

  # VISIBILITY TIMEOUT — the single most consequential setting here.
  #
  # When the worker receives a message it becomes invisible to other consumers
  # for this long. If processing takes longer, SQS assumes the worker died and
  # redelivers — so a slow job gets processed TWICE.
  #
  # Local Whisper transcription plus an LLM turn on a 3060 can take a while, so
  # this is set generously. Too short causes duplicate replies; too long means
  # a genuinely crashed worker's messages sit invisible before retrying.
  visibility_timeout_seconds = var.visibility_timeout_seconds

  # How long an unprocessed message survives. If the PC is off for longer than
  # this, the message is dropped rather than answered hours late — which is the
  # behaviour you want for a conversational assistant.
  message_retention_seconds = var.message_retention_seconds

  # Enables long polling by default: a ReceiveMessage call waits up to 20s for
  # a message instead of returning empty immediately.
  #
  # THIS IS A COST CONTROL, not just a latency tweak. At 20s a worker polling
  # continuously makes ~130k requests/month, inside the 1M always-free tier.
  # At 1s polling it is 2.6M/month and you start paying. Same behaviour,
  # different bill.
  receive_wait_time_seconds = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    # Three attempts. Enough to ride out a transient Ollama hiccup or a restart,
    # few enough that a genuinely poisonous message is quarantined quickly.
    maxReceiveCount = var.max_receive_count
  })

  sqs_managed_sse_enabled = true

  tags = {
    Component = "job-queue"
  }
}

# Allows the DLQ to name which queues may redrive into it. Without this the
# redrive_policy above still works, but the DLQ has no record of its source and
# the console cannot offer the "redrive to source" button.
resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.main.arn]
  })
}
