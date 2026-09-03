###############################################################################
# modules/state-table — DynamoDB table for conversation state and idempotency.
#
# SINGLE TABLE, TWO ACCESS PATTERNS
# ---------------------------------
# A generic pk/sk pair rather than named columns, so one table serves both:
#
#   pk = "chat#<chat_id>"    sk = "session"   -> conversation history
#   pk = "update#<id>"       sk = "dedupe"    -> webhook idempotency marker
#
# The alternative is two tables. That is arguably clearer to read, and at this
# scale the cost is identical. Single-table was chosen because it is the
# pattern you will be asked about, and because both items share one TTL sweep
# and one IAM policy. At larger scale single-table design earns its keep by
# letting related items be fetched in one query; here it is mostly about
# keeping the surface small.
###############################################################################

resource "aws_dynamodb_table" "this" {
  name = "${var.project}-${var.environment}-state"

  # ON-DEMAND, and this is a deliberate cost decision worth defending.
  #
  # The DynamoDB always-free tier covers 25 WCU + 25 RCU of PROVISIONED
  # capacity and does NOT cover on-demand request pricing. So on-demand is
  # technically outside the free tier, at roughly $0.01/month here.
  #
  # It is still the right choice: a personal assistant's traffic is bursty and
  # mostly zero. Provisioned 25/25 would mean paying attention to capacity
  # forever to save one cent, and would throttle if a burst exceeded it.
  # On-demand scales to zero and needs no operational thought.
  billing_mode = "PAY_PER_REQUEST"

  hash_key  = "pk"
  range_key = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  # TTL does the cleanup that would otherwise need a scheduled job.
  # Dedupe markers expire after a day; sessions after a period of inactivity.
  # DynamoDB deletes expired items within ~48h and charges nothing for it.
  #
  # Important subtlety: expired items remain READABLE until the sweeper gets to
  # them, so application code must treat expires_at as authoritative rather
  # than assuming an expired item is gone.
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  # AWS-owned key: encrypted at rest, no monthly charge. A customer-managed
  # key would cost $1/month and buy an auditable key policy — worth it in
  # production, not at this budget.
  server_side_encryption {
    enabled = true
  }

  # PITR is charged per GB-month of table size. This table holds kilobytes, so
  # it rounds to zero, and it converts "I corrupted the session table" from a
  # disaster into an inconvenience.
  point_in_time_recovery {
    enabled = var.point_in_time_recovery
  }

  tags = {
    Component = "state-table"
  }
}
