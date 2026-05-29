# aws-realtime-cost-mcp

MCP server that gives near real-time AWS cost estimates by querying service APIs directly, instead of waiting 8-24 hours for AWS Cost Explorer to catch up.

## Why

AWS Cost Explorer, Budgets, and Cost Anomaly Detection all share the same billing pipeline and lag behind by 8-24 hours. By the time a runaway resource shows up there, the bill has already accumulated. This server fills that gap by:

- Listing what's currently running via `Describe*` / `List*` APIs
- Multiplying instance state × hours-since-launch × on-demand price for an exact running rate
- Optionally adding CloudWatch volume metrics for services with usage-based costs (NAT Gateway egress, Bedrock tokens)

It's a complement to the official [AWS Labs MCP servers](https://github.com/awslabs/mcp), not a replacement — run both side by side.

## Coverage

The MVP focuses on the runaway-top-5: services where a forgotten resource silently burns money over a weekend.

| Service | State source | Volume source |
|---|---|---|
| EC2 | `DescribeInstances` | – |
| RDS | `DescribeDBInstances` | – |
| NAT Gateway | `DescribeNatGateways` | CloudWatch `BytesOutToDestination` |
| SageMaker endpoints | `ListEndpoints` + `DescribeEndpointConfig` | – |
| Bedrock | – | CloudWatch `InputTokenCount` / `OutputTokenCount` |

Services explicitly out of scope for now (not because they're cheap, but because their estimation needs more nuance): OpenSearch, ElastiCache, MSK, Redshift, Neptune. The `get_coverage_report` tool detects when these are running so the user is never silently underinforming.

## Tools

| Tool | Purpose |
|---|---|
| `get_running_cost_rate(region, account_id?)` | $/hour right now, broken down by service |
| `project_month_end_spend(region, account_id?)` | cumulative-so-far + extrapolation to end of calendar month |
| `list_expensive_resources(region, threshold_per_hour, account_id?)` | resources sorted descending by hourly cost |
| `get_coverage_report(region, account_id?)` | what is/isn't measured, plus uncovered services with running resources |
| `compare_estimate_vs_actual(days_ago)` | placeholder for future history-mode comparison against Cost Explorer |
| `refresh_pricing(service?)` | force-invalidate the local pricing cache |

## Multi-account setup

The server uses STS `AssumeRole` to read from any number of member accounts. The recommended workflow:

1. Pick a name for the reader role (default: `AWSRealtimeCostReader`).
2. Deploy the StackSet at `stacksets/reader-role.yaml` from your management account, targeting whichever OU or accounts you want visibility into. The template's parameters:
   - `RoleName` — keep as default unless your security team requires something else
   - `TrustedPrincipalArn` — the IAM principal in your management/home account that the MCP server runs as
3. (Optional, only if you renamed the role) export `AWS_REALTIME_COST_ROLE_NAME` in the environment where the MCP server runs.
4. Pass `account_id="…"` to any tool to target a specific member account. Omit it to query the home account with whatever credentials boto3 picks up locally.

Sessions are cached per account for ~15 minutes to avoid hammering STS on a batch of tool calls.

## Install

```bash
pip install git+https://github.com/gjoris/aws-realtime-cost-mcp
```

Then in your MCP client config:

```jsonc
{
  "mcpServers": {
    "aws-realtime-cost": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "git+https://github.com/gjoris/aws-realtime-cost-mcp",
        "aws-realtime-cost-mcp"
      ]
    }
  }
}
```

The server reads AWS credentials the same way boto3 does (env vars, `~/.aws/credentials`, instance profile, …). The local pricing cache lives at `~/.local/share/aws-realtime-cost-mcp/pricing.db` by default; override with `AWS_REALTIME_COST_PRICING_DB`.

## Development

```bash
pip install -e ".[test]"
pytest
```

100% line + branch coverage is required to merge. Tests use `moto` for AWS mocking — no real AWS calls.

## Limitations

- **Estimate, not invoice.** The numbers are derived from `Describe*` outputs × the AWS Pricing API. Reserved Instances, Savings Plans, EDP/PPA discounts, Spot pricing changes, and tax do **not** apply to these estimates.
- **No detection without an estimator.** A service that isn't covered will not show up in `get_running_cost_rate`. Always sanity-check with `get_coverage_report` before trusting the rate.
- **Pricing API granularity.** A few SKUs (mostly serverless / hybrid pricing models) need exact attribute matches that this MVP doesn't always emit. When the lookup misses, the cost falls back to `0` rather than guessing — visible in the `details` field.
