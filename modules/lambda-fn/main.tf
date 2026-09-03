###############################################################################
# modules/lambda-fn — one Lambda, its own execution role, its own log group.
#
# Every function gets a dedicated role. No shared "lambda-execution-role", no
# wildcard actions. The caller passes the exact statements the function needs,
# which forces the permission question to be answered at the call site where
# the context is, rather than buried in a module default.
###############################################################################

data "archive_file" "src" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${path.module}/.build/${var.name}.zip"
}

###############################################################################
# Execution role
###############################################################################

data "aws_iam_policy_document" "assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.project}-${var.environment}-${var.name}"
  assume_role_policy = data.aws_iam_policy_document.assume.json

  tags = {
    Component = "lambda-role"
  }
}

# Logging, scoped to THIS function's log group rather than the AWS-managed
# AWSLambdaBasicExecutionRole policy, which grants logs:* on "*".
#
# This is the difference between "the function can write its own logs" and
# "the function can write to, and create, any log group in the account".
data "aws_iam_policy_document" "logs" {
  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.this.arn}:*"]
  }
}

resource "aws_iam_role_policy" "logs" {
  name   = "logs"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.logs.json
}

# Caller-supplied least-privilege statements, rendered as a single inline
# policy. Inline rather than managed because these permissions are meaningless
# outside this one role — a managed policy implies reuse that will not happen.
resource "aws_iam_role_policy" "app" {
  count = length(var.policy_statements) > 0 ? 1 : 0

  name = "app"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = var.policy_statements
  })
}

###############################################################################
# Log group
###############################################################################

# Created explicitly rather than letting Lambda create it on first invoke.
#
# An implicitly created group has retention set to "Never Expire", so logs
# accumulate forever and eventually leave the 5 GB CloudWatch free tier. That
# is the most common way a "free" serverless project starts costing money.
resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.project}-${var.environment}-${var.name}"
  retention_in_days = var.log_retention_days

  tags = {
    Component = "lambda-logs"
  }
}

###############################################################################
# Function
###############################################################################

resource "aws_lambda_function" "this" {
  function_name = "${var.project}-${var.environment}-${var.name}"
  role          = aws_iam_role.this.arn
  handler       = var.handler
  runtime       = var.runtime

  filename         = data.archive_file.src.output_path
  source_code_hash = data.archive_file.src.output_base64sha256

  # arm64 (Graviton). Cheaper per GB-second than x86 with no downside for pure
  # Python, and the runtime is identical. Free money.
  architectures = ["arm64"]

  memory_size = var.memory_mb
  timeout     = var.timeout_seconds

  # RESERVED CONCURRENCY IS A COST CONTROL, and the main defence for a function
  # sitting behind a public URL.
  #
  # It caps how many copies can run at once. Without it, a flood of requests
  # scales Lambda to the account limit (1000 by default) and the bill scales
  # with it. With it, excess requests are rejected rather than executed.
  #
  # It also protects everything downstream: this ceiling is what stops a burst
  # from opening a thousand simultaneous DynamoDB writes.
  reserved_concurrent_executions = var.reserved_concurrency

  environment {
    variables = var.environment_variables
  }

  # Without this, the function may create the log group itself on first invoke,
  # winning the race against Terraform and leaving retention unset forever.
  depends_on = [
    aws_cloudwatch_log_group.this,
    aws_iam_role_policy.logs,
  ]

  tags = {
    Component = "lambda"
  }
}
