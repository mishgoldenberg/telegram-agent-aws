###############################################################################
# modules/github-oidc — let GitHub Actions deploy without any stored AWS keys.
#
# THE PROBLEM THIS SOLVES
# -----------------------
# The usual way to give a pipeline AWS access is an IAM user with an access
# key, pasted into repository secrets. That key is long-lived, is visible to
# anyone who can edit the repo's settings, survives the employee who created
# it, and is the single most common cause of the "someone mined crypto in my
# account" story.
#
# OIDC replaces it with a trust relationship. GitHub signs a short-lived JSON
# Web Token describing the workflow run — which repository, which branch,
# which event — and AWS is configured to trust tokens from GitHub that match
# specific claims. Nothing is stored anywhere. Credentials last minutes.
###############################################################################

# The identity provider: AWS learns to trust tokens signed by GitHub.
#
# Registering this alone grants NOTHING. It says "tokens from GitHub are
# authentic", not "GitHub may do things". Authorisation lives entirely in the
# role trust policies below, which is the distinction worth being precise about
# in an interview.
resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  # The audience GitHub puts in the token when you use the official
  # aws-actions/configure-aws-credentials action.
  client_id_list = ["sts.amazonaws.com"]

  # Thumbprints are legacy. Since 2023 AWS validates GitHub's OIDC endpoint
  # against its own trusted CA store and ignores this list for well-known
  # providers, which is why nobody has to chase thumbprint rotations any more.
  # Terraform still requires the argument, so this is GitHub's published value.
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  tags = {
    Component = "github-oidc"
  }
}

###############################################################################
# Trust policies
#
# THIS IS THE ENTIRE SECURITY BOUNDARY. Read the sub condition carefully.
#
# A trust policy that checks only the audience:
#
#     "StringEquals": { "...:aud": "sts.amazonaws.com" }
#
# is satisfied by a token from ANY GitHub Actions workflow in ANY repository
# belonging to ANY user on GitHub. It is a world-readable role. This mistake
# appears in a great many blog posts and is the thing to be able to explain.
#
# The sub claim is what identifies the caller:
#
#     repo:owner/name:ref:refs/heads/main       push to main
#     repo:owner/name:pull_request              a pull request run
#     repo:owner/name:environment:prod          a deployment environment
#
# StringEquals on an exact sub, never StringLike with a trailing wildcard:
# "repo:mishgoldenberg/*" would trust every repository this account owns,
# including one created by an attacker who compromised the GitHub account.
###############################################################################

locals {
  oidc_provider = aws_iam_openid_connect_provider.github.arn

  # Plan runs on pull requests. GitHub emits this exact sub for PR events,
  # regardless of branch name.
  sub_pull_request = "repo:${var.github_repo}:pull_request"

  # Apply runs only on a push to the default branch.
  sub_main_branch = "repo:${var.github_repo}:ref:refs/heads/${var.default_branch}"
}

data "aws_iam_policy_document" "assume_plan" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.sub_pull_request]
    }
  }
}

data "aws_iam_policy_document" "assume_apply" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only a push to the default branch. A pull request from a fork cannot
    # assume this role, which matters: PR workflows can run attacker-authored
    # code, so they get the read-only plan role and nothing more.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.sub_main_branch]
    }
  }
}

###############################################################################
# Plan role — read-only
###############################################################################

resource "aws_iam_role" "plan" {
  name               = "${var.project}-gha-plan"
  description        = "GitHub Actions: terraform plan on pull requests. Read-only."
  assume_role_policy = data.aws_iam_policy_document.assume_plan.json

  # Sessions live only as long as the job needs. An hour is generous for a
  # plan and bounds the damage if a token leaks in a log.
  max_session_duration = 3600

  tags = { Component = "github-oidc" }
}

# ReadOnlyAccess covers reading every resource type a plan must refresh.
# Maintaining a hand-written equivalent would mean editing this module every
# time the stack gains a service, and getting it wrong shows up as a confusing
# plan diff rather than an obvious error.
resource "aws_iam_role_policy_attachment" "plan_readonly" {
  role       = aws_iam_role.plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# A plan still needs to WRITE, because it takes a state lock: use_lockfile
# writes a .tflock object beside the state. Read-only plus this is the
# smallest workable permission set.
data "aws_iam_policy_document" "state_access" {
  statement {
    sid       = "ListStateBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [var.state_bucket_arn]
  }

  statement {
    sid    = "ReadWriteStateAndLock"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["${var.state_bucket_arn}/*"]
  }
}

resource "aws_iam_role_policy" "plan_state" {
  name   = "terraform-state"
  role   = aws_iam_role.plan.id
  policy = data.aws_iam_policy_document.state_access.json
}

###############################################################################
# Apply role
###############################################################################

# THE HONEST PART: A DEPLOY ROLE CANNOT BE LEAST-PRIVILEGE.
#
# Terraform creates IAM roles, so the apply role must hold iam:CreateRole. Any
# principal that can create a role and attach policies to it can, in principle,
# escalate to administrator. No arrangement of action lists fixes that.
#
# The real mitigation is a PERMISSIONS BOUNDARY: this role may only create
# roles that carry a specific boundary policy, enforced by a condition below.
# A boundary caps what the created role can ever do, no matter what policies
# are attached to it later. That turns "can create any role" into "can create
# roles that can never exceed this ceiling".
#
# Being able to explain that trade-off honestly interviews better than
# claiming a deploy role is fully locked down, which is never true.

resource "aws_iam_policy" "boundary" {
  name        = "${var.project}-gha-boundary"
  description = "Ceiling on every role the CI apply role creates."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowWorkloadServices"
        Effect = "Allow"
        Action = [
          "logs:*", "dynamodb:*", "sqs:*", "s3:*",
          "ssm:GetParameter", "ssm:GetParameters",
          "kms:Decrypt", "lambda:InvokeFunction",
          "cloudwatch:PutMetricData",
        ]
        Resource = "*"
      },
      {
        # Nothing created by CI may ever touch IAM, billing, or the
        # organisation - the paths an escalation would take.
        Sid    = "DenyPrivilegeEscalation"
        Effect = "Deny"
        Action = [
          "iam:*", "organizations:*", "account:*",
          "billing:*", "aws-portal:*", "sts:AssumeRole",
        ]
        Resource = "*"
      },
    ]
  })

  tags = { Component = "github-oidc" }
}

resource "aws_iam_role" "apply" {
  name                 = "${var.project}-gha-apply"
  description          = "GitHub Actions: terraform apply on ${var.default_branch}."
  assume_role_policy   = data.aws_iam_policy_document.assume_apply.json
  max_session_duration = 3600

  tags = { Component = "github-oidc" }
}

data "aws_iam_policy_document" "apply" {
  # The services this stack actually manages. Scoped by service rather than by
  # ARN because Terraform must create resources that do not exist yet, so
  # there is no ARN to name in advance.
  statement {
    sid    = "ManageWorkloadResources"
    effect = "Allow"
    actions = [
      "lambda:*", "apigateway:*", "sqs:*", "dynamodb:*",
      "s3:*", "logs:*", "cloudwatch:*", "sns:*",
      "ssm:*", "budgets:*", "events:*",
    ]
    resources = ["*"]
  }

  # Read-only IAM is always safe and is needed constantly by plan/apply.
  statement {
    sid    = "ReadIAM"
    effect = "Allow"
    actions = [
      "iam:Get*", "iam:List*", "iam:SimulatePrincipalPolicy",
    ]
    resources = ["*"]
  }

  # Creating and updating roles is allowed ONLY when the boundary is attached.
  # Without this condition the role could create an unconstrained admin role
  # and assume it.
  statement {
    sid    = "CreateBoundedRolesOnly"
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:PutRolePolicy",
      "iam:AttachRolePolicy",
    ]
    resources = ["arn:aws:iam::${var.account_id}:role/${var.project}-*"]

    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [aws_iam_policy.boundary.arn]
    }
  }

  # Deleting and tagging do not need the boundary condition - they cannot
  # raise privilege - but stay confined to this project's name prefix.
  statement {
    sid    = "ManageOwnRoles"
    effect = "Allow"
    actions = [
      "iam:DeleteRole", "iam:DeleteRolePolicy", "iam:DetachRolePolicy",
      "iam:TagRole", "iam:UntagRole", "iam:UpdateAssumeRolePolicy",
    ]
    resources = ["arn:aws:iam::${var.account_id}:role/${var.project}-*"]
  }

  # PassRole is how a Lambda gets its execution role, and it is the classic
  # escalation vector: pass an admin role to a service you control and you are
  # an admin. Confined to this project's roles, and only to Lambda.
  statement {
    sid       = "PassRoleToLambdaOnly"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${var.account_id}:role/${var.project}-*"]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "apply" {
  name   = "terraform-apply"
  role   = aws_iam_role.apply.id
  policy = data.aws_iam_policy_document.apply.json
}

resource "aws_iam_role_policy" "apply_state" {
  name   = "terraform-state"
  role   = aws_iam_role.apply.id
  policy = data.aws_iam_policy_document.state_access.json
}
