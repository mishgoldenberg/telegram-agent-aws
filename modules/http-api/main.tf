###############################################################################
# modules/http-api — API Gateway HTTP API fronting the Telegram webhook.
#
# HTTP API, NOT REST API. The choice matters and gets asked about:
#   - roughly 70% cheaper per request ($1.20 vs $4.25 per million here)
#   - lower latency, simpler configuration
#   - gives up: request/response transformation, API keys and usage plans,
#     WAF integration, caching, private endpoints
#
# A Telegram webhook needs none of what REST API adds. If this ever needed WAF
# in front of it, that alone would force REST API or CloudFront.
###############################################################################

resource "aws_apigatewayv2_api" "this" {
  name          = "${var.project}-${var.environment}-webhook"
  protocol_type = "HTTP"
  description   = "Telegram webhook ingest for ${var.project} (${var.environment})"

  tags = {
    Component = "http-api"
  }
}

# Payload format 2.0 is the HTTP API native shape. The handler reads
# event["headers"] and event["body"] rather than the REST-style structure.
resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = var.lambda_invoke_arn
  payload_format_version = "2.0"

  # Telegram treats a slow webhook as a failure and retries. This ceiling makes
  # the API give up before Telegram does, so a hung Lambda surfaces as a clean
  # 504 rather than a duplicate update.
  timeout_milliseconds = var.integration_timeout_ms
}

# A single explicit route. No $default catch-all: an unmatched path should be
# rejected by API Gateway for free rather than invoking Lambda so the function
# can decide to ignore it. Every invocation avoided is money not spent and one
# less way in.
#
# The path includes a secret component so the URL alone is unguessable. That is
# defence in depth, not the actual authentication — the Lambda verifies
# Telegram's X-Telegram-Bot-Api-Secret-Token header on every request.
resource "aws_apigatewayv2_route" "webhook" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "POST /${var.webhook_path}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# API Gateway invokes Lambda as a service principal, so the permission is a
# resource policy on the function.
#
# source_arn is scoped to this API, this stage, this method and this path.
# Without it, any API Gateway in any account could invoke the function.
resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/POST/${var.webhook_path}"
}

###############################################################################
# Stage
###############################################################################

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/apigateway/${var.project}-${var.environment}-webhook"
  retention_in_days = var.log_retention_days

  tags = {
    Component = "http-api-logs"
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  # THROTTLING IS THE PRIMARY COST CONTROL FOR A PUBLIC ENDPOINT.
  #
  # This URL is on the internet. The secret-token header stops an attacker
  # doing anything useful, but without a limit here every request still costs
  # an API Gateway call and a Lambda invocation.
  #
  # A human sends a handful of messages a minute. 2 requests/second sustained
  # with a burst of 5 is enormous headroom for one user, and caps a sustained
  # flood at roughly $6/month of API Gateway rather than an unbounded bill.
  default_route_settings {
    throttling_rate_limit  = var.throttle_rate_limit
    throttling_burst_limit = var.throttle_burst_limit
  }

  # Access logs answer "did Telegram actually call us, and what did we return".
  # Without them a webhook that Telegram considers broken is invisible, because
  # a request rejected at the API layer never reaches the Lambda's logs.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn

    format = jsonencode({
      requestId         = "$context.requestId"
      ip                = "$context.identity.sourceIp"
      requestTime       = "$context.requestTime"
      routeKey          = "$context.routeKey"
      status            = "$context.status"
      responseLatency   = "$context.responseLatency"
      integrationError  = "$context.integration.error"
      integrationStatus = "$context.integration.status"
    })
  }

  tags = {
    Component = "http-api-stage"
  }
}
