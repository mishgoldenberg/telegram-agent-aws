# telegram-agent-aws

Moving the ingest path of a self-hosted Telegram assistant to AWS, while the language model
stays on local hardware. Everything is Terraform; nothing was created in the console.

Steady-state cost: **under $0.05/month.**

---

## Why this shape

The assistant is a Python agent on a local Ollama instance with tool-calling into Google
Calendar, Tasks, and Gmail, plus Whisper speech-to-text. The model runs on an RTX 3060 that
cannot move to the cloud, and paying for GPU inference would defeat the point of self-hosting.

So the parts that *can* move did: the public HTTPS endpoint, the work queue, conversation
state, and the alerting. What is left on the local machine is exactly what needs the GPU.

Be clear about what this is: **AWS is not doing the heavy compute here.** It is the ingest,
buffering, durability, and security boundary in front of compute that cannot move. That is a
real pattern — it is roughly how hybrid ML shops operate when the hardware cannot leave the
building — but it would be dishonest to present Lambda as the interesting part.

## Architecture

```
TEXT
  Telegram --webhook--> API Gateway (HTTP API)
                             |  route throttle 2 rps, burst 5
                             v
                        ingest Lambda  (arm64, python3.13)
                             |  1. verify X-Telegram-Bot-Api-Secret-Token
                             |  2. reject any user but the owner
                             |  3. conditional PutItem on update_id  -> DynamoDB
                             |  4. enqueue                            -> SQS
                             |  5. return 200 immediately
                             v
                        SQS jobs queue ---(3 failures)---> DLQ ---> alarm
                             ^
                             |  20s long poll — OUTBOUND ONLY
                    [ home PC: worker.py ]
                             |  Whisper -> agent.py -> Ollama :11434
                             |  read/write conversation state -> DynamoDB
                             +--> Telegram sendMessage (outbound HTTPS)

VOICE  (differs at step 4)
  ingest Lambda: getFile + download from api.telegram.org --> S3 (expires after 7 days)
                             |
                        S3 ObjectCreated event
                             v
                        audio-event Lambda --> SQS
```

### Decisions worth defending

**Telegram webhooks do not contain audio.** An update carries a `file_id`; retrieving the
recording is two more calls. The ingest Lambda does that and writes to S3.

**The voice path enqueues from the S3 event, not inline.** This makes the PUT the commit
point. If the Lambda enqueued directly, a crash between "send" and "put" would leave a job
pointing at audio that does not exist — three failures, then the DLQ. Driving the enqueue from
the bucket's own event closes that window: a job exists only if the audio is durably stored.

**The reply goes straight to Telegram, not back through AWS.** The obvious design returns the
answer to a Lambda that forwards it. That needs a second endpoint or a response queue and buys
nothing — the worker already holds the bot token. Once a job is dequeued, AWS is out of the loop.

**Long polling at 20 seconds is a cost control, not a latency tweak.** A worker polling
continuously at 20s makes ~130k requests/month, inside the 1M always-free SQS tier. At 1s it
would be 2.6M/month and start costing money for identical behaviour.

**Idempotency is a conditional write.** Telegram redelivers any update it does not get a timely
2xx for, and it will happen on a cold start. `PutItem` with `attribute_not_exists(pk)` is atomic
at the item level, so two concurrent invocations racing on the same `update_id` cannot both win.
Read-then-write would leave exactly that race open.

**The ingest Lambda always returns 200.** A 500 on a message we cannot process means Telegram
retries it forever. Genuine failures are logged and swallowed — dropped deliberately rather than
retried indefinitely. The only non-200 is 403 for a failed secret check.

## Layout

```
bootstrap/     state backend — run once, migrates into itself
modules/       budget, state-table, job-queue, audio-bucket,
               lambda-fn, http-api, observability
envs/dev/      the stack; prod is the same modules with different inputs
lambdas/       ingest, audio_event — stdlib + the runtime's boto3, no layers
worker/        local SQS consumer (not deployed by Terraform)
scripts/       set_webhook, smoke_test, reauth_google
docs/          GitHub Pages: home page and privacy policy
```

### Directories, not workspaces

Workspaces share one backend configuration and one set of credentials. dev and prod would live
in the same bucket under `env:/`, an apply in the wrong workspace is one forgotten `select`
away, and the two cannot diverge structurally without `count` hacks through the code.

Directories give separate state files, separate backends, and a clean path to separate AWS
*accounts* later — which is the real production answer. Workspaces are for short-lived parallel
copies of the same config, like a per-PR ephemeral stack.

### The bootstrap paradox

Every stack stores state in S3, but the bucket is itself a Terraform resource and cannot store
its own state in a bucket that does not exist yet. Resolution: `bootstrap/` runs once against
local state, creates the bucket, then migrates into itself with
`terraform init -migrate-state`. After that it is an ordinary stack.

The alternative is creating the bucket by hand and referencing it, which makes the backend the
one piece of infrastructure not described in code.

### Locking: built with DynamoDB, then removed

The canonical pattern is a DynamoDB lock table — a conditional write on a hash key, plus a
persistent `<key>-md5` digest item the backend uses to detect state corrupted between writes.
That was built first (commit `8b93713`).

Terraform 1.15 then warned on every plan that `dynamodb_table` is deprecated in favour of
`use_lockfile`, which takes the lock through S3's own conditional writes (`PutObject` with
`If-None-Match`, available since August 2024) by writing a `.tflock` object beside the state.
Same mutual exclusion, one fewer resource, one fewer IAM policy, and DynamoDB out of the
critical path of every apply.

The table was destroyed and the construction left in git history rather than as unreferenced
infrastructure. Keeping it would have meant a permanent warning in plan output.

## IAM

Every function has its own execution role. No shared `lambda-execution-role`, no wildcard
actions, every statement naming concrete ARNs.

| Role | Gets | Notably does **not** get |
|---|---|---|
| `ingest` | `ssm:GetParameter` on one path, `kms:Decrypt` on the SSM key, `dynamodb:PutItem`, `sqs:SendMessage`, `s3:PutObject` under `voice/` | Any read of DynamoDB; any S3 read, delete, or list |
| `audio-event` | `s3:GetObject` under `voice/`, `sqs:SendMessage` | DynamoDB and SSM entirely |
| `worker` (local) | Receive/Delete on one queue, `s3:GetObject` on one prefix, Get/Put/Update on one table, one SSM parameter | Console access, or the ability to create anything |

Logging is scoped to each function's own log group rather than the AWS-managed
`AWSLambdaBasicExecutionRole`, which grants `logs:*` on `*`. The difference is between "can
write its own logs" and "can write to, and create, any log group in the account".

## Cost

| Resource | Rate | At ~100 messages/day |
|---|---|---|
| Lambda | 1M req + 400k GB-s always free | $0.00 |
| SQS | 1M requests/month always free | $0.00 |
| API Gateway HTTP API | $1.20 per million (eu-central-1) | ~$0.004 |
| DynamoDB on-demand | $0.625/M writes | ~$0.01 |
| S3 | $0.023/GB-mo + requests | ~$0.01 |
| CloudWatch | 10 alarms, 5 GB logs free | $0.00 |
| SNS / SSM Standard / Budgets | free tiers | $0.00 |
| **Total** | | **< $0.05 / month** |

Three things deliberately excluded to hold that: **no VPC for the Lambdas** (a NAT Gateway is
~$32/month and there are no private resources to reach), **no customer-managed KMS keys**
($1/month each), **no custom domain** ($0.50/month for a hosted zone, for a URL nobody types).

**SSM Parameter Store, not Secrets Manager.** Secrets Manager is $0.40 per secret per month;
three secrets is $1.20, or 24% of a $5 budget, to store a few hundred bytes. Parameter Store
Standard is free and equally encrypted. What it gives up is native rotation and cross-account
resource policies — neither of which this uses.

**DynamoDB on-demand is outside the free tier**, and that is a deliberate choice. The always-free
tier covers 25 WCU/RCU of *provisioned* capacity only. On-demand costs about a cent a month here,
and provisioned 25/25 would mean managing capacity forever to save that cent, while throttling
on any burst that exceeded it.

### Guardrails

A budget is a smoke detector, not a circuit breaker — **AWS has no hard spend cap.** Budgets
evaluate on an 8–12 hour lag and then send email. What actually bounds spend is architectural:
no expensive resource types, API Gateway throttling at 2 rps, and (when the account allows it)
Lambda reserved concurrency.

Two budgets, which is exactly the free allowance: `$5` monthly, and `$1` as an "am I spending at
all" tripwire — the more useful question when the expectation is pennies.

**Reserved concurrency is currently disabled**, and not by choice. This account's total Lambda
concurrency limit is 10 — new AWS accounts start there, not at the classic 1000 — and AWS
rejects any reservation that would drop unreserved concurrency below 10. The account ceiling
currently provides tighter protection than the reservation would have, but it is *implicit*: AWS
raises the limit as an account matures, and the protection silently disappears. There is a `TODO`
in `envs/dev/main.tf` with the condition for restoring it.

### The alarm that matters

Five CloudWatch alarms exist; four are routine. The load-bearing one is
`ApproximateAgeOfOldestMessage` on the work queue.

It fires when the home machine is asleep, the worker crashed, Ollama died, or the house lost
internet. In every one of those cases **AWS is perfectly healthy** — Lambda errors are zero, API
Gateway returns 200, and messages simply pile up while the assistant answers nobody. Nothing on
the AWS side is broken, so nothing on the AWS side would alarm. Queue age is the only signal
that crosses into the part of the system AWS cannot see.

Note that an SNS email subscription sits in `PendingConfirmation` until the recipient clicks the
link. Until then every alarm delivers to nobody, while Terraform reports success and the alarms
read `OK`. That is a silent failure worth checking after any fresh deploy.

## What production would do differently

This is a single-account, free-tier build. At real scale:

**Multi-account.** AWS Organizations with a management account that holds no workloads, separate
accounts per environment, and SCPs enforcing guardrails centrally — deny expensive regions, deny
disabling CloudTrail, deny public S3. The blast radius of a mistake becomes one account instead
of everything. Enabling Identity Center here already created an Organization, so the foundation
exists.

**Cross-account IAM.** The CI/CD role would live in a shared tooling account and assume a
deployment role in each target account, with an `ExternalId` and a permissions boundary. The
deploy role is the honest weak point in any Terraform pipeline: it must hold `iam:CreateRole`,
so it cannot be least-privilege the way a runtime role can. The mitigation is a permissions
boundary — it may only create roles that carry a specific boundary policy, enforced with an
`iam:PermissionsBoundary` condition, and may only `PassRole` for roles under a fixed path. That
converts "can create any role" into "can create roles that can never exceed this ceiling".

**VPC placement.** Deliberately absent here, because a NAT Gateway costs 640× the entire monthly
bill and there are no private resources to reach. In production, Lambdas that touch RDS or
ElastiCache go in private subnets, egress through NAT or (better) VPC endpoints for AWS services,
which avoid NAT charges entirely for S3, DynamoDB, SQS, and SSM.

**Secrets rotation.** Parameter Store has no native rotation. Production would use Secrets
Manager with a rotation Lambda, and the $0.40/secret stops being an argument the moment a secret
matters. Telegram bot tokens cannot be rotated without re-registering the webhook, so rotation
would need a two-token overlap window.

**The remaining long-lived credential.** The local worker authenticates with an IAM access key,
because it runs unattended and Identity Center needs a browser. It is scoped to one queue, one
bucket prefix, one table, and one parameter — a leak grants an attacker this assistant's job
queue and nothing else. The proper fix is IAM Roles Anywhere with a self-signed CA as trust
anchor: free, no ACM Private CA needed, and it yields short-lived certificate-derived
credentials. That is the planned upgrade, documented here rather than quietly omitted.

**Observability.** Structured logs go to CloudWatch with 7-day retention. Production wants
distributed tracing (X-Ray or OpenTelemetry) across the API Gateway → Lambda → SQS → worker hop,
because the interesting failures are at the boundaries, and log retention long enough to satisfy
whatever the compliance answer is.

## Running it

```bash
# once: create the state backend, then migrate into it
cd bootstrap && terraform init && terraform apply
#   uncomment the backend block using the outputs, then:
terraform init -migrate-state

# the stack
cd ../envs/dev
terraform init && terraform apply

# point Telegram at it
$env:WEBHOOK_URL    = terraform output -raw webhook_url
$env:WEBHOOK_SECRET = terraform output -raw webhook_secret
python ../../scripts/set_webhook.py

# verify every hop, including the 403s and the duplicate drop
python ../../scripts/smoke_test.py

# the local half
python ../../worker/worker.py
```

`scripts/set_webhook.py --delete` reverts to long polling. Telegram allows a bot to use either
long polling or a webhook, never both, so registering the webhook stops `getUpdates` working.

### Google OAuth

The assistant's Google credentials live in `token.json` next to the agent, outside this repo.
While the OAuth app's publishing status is **Testing**, Google expires refresh tokens after
7 days — which presents as `invalid_grant: Token has been expired or revoked` and an assistant
that mysteriously stops knowing your calendar every week. Publishing the app to production fixes
it permanently; `scripts/reauth_google.py` is the manual recovery.

## Licence

MIT.
