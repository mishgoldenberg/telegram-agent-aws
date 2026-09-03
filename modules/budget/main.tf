###############################################################################
# modules/budget — cost guardrail.
#
# IMPORTANT AND WORTH SAYING OUT LOUD: a budget is a SMOKE DETECTOR, NOT A
# CIRCUIT BREAKER. AWS has no hard spend cap. Budgets evaluate on a lag of
# roughly 8-12 hours and then send an email. Nothing stops.
#
# The things that actually bound spend in this build are architectural:
#   - no NAT Gateway, no EC2, no RDS, no customer-managed KMS keys
#   - API Gateway route-level throttling
#   - Lambda reserved concurrency
# This module is the backstop for the case where all of that is wrong.
###############################################################################

# Budgets is a global service. The API is reached through us-east-1 regardless
# of where the workload runs, which is why callers pass an aliased provider.

resource "aws_budgets_budget" "monthly" {
  name         = "${var.project}-monthly"
  budget_type  = "COST"
  limit_amount = var.limit_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Scope the budget to this project's tagged resources rather than the whole
  # account. On a shared account an account-wide budget is meaningless — it
  # would fire on someone else's spend. It also means the budget only sees
  # resources that were tagged correctly, which is a useful forcing function.
  #
  # NOTE: this requires the "Project" cost allocation tag to be ACTIVATED in
  # Billing > Cost allocation tags. Until AWS activates it (up to 24h after the
  # first tagged resource appears), a tag-filtered budget sees $0. See README.
  dynamic "cost_filter" {
    for_each = var.scope_to_project_tag ? [1] : []
    content {
      name   = "TagKeyValue"
      values = ["user:Project$${var.project}"]
    }
  }

  # ACTUAL notifications fire on money already spent. At 50% of $5 that is
  # $2.50 — early enough to investigate before it matters.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.alert_emails
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.alert_emails
  }

  # FORECASTED is the one that gives useful warning. AWS extrapolates the
  # month's run rate; a sudden burst trips this days before ACTUAL would.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.alert_emails
  }
}

# A second budget at effectively zero. The monthly budget above answers "am I
# spending too much"; this one answers "am I spending AT ALL", which is the
# more useful question when the expectation is a few cents. It catches a
# resource created by accident long before it reaches $5.
#
# The first two budgets per account are free; each additional one is $0.02/day.
# Two is exactly the free allowance.
resource "aws_budgets_budget" "any_spend" {
  name         = "${var.project}-any-spend"
  budget_type  = "COST"
  limit_amount = var.any_spend_threshold_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.alert_emails
  }
}
