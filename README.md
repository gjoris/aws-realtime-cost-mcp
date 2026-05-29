# aws-realtime-cost-mcp

MCP server that gives near real-time AWS cost estimates by querying service APIs directly, instead of waiting 8-24 hours for AWS Cost Explorer to catch up.

## Why

AWS Cost Explorer, Budgets, and Cost Anomaly Detection all share the same billing pipeline and lag behind by 8-24 hours. By the time a runaway resource shows up there, the bill has already accumulated. This server fills that gap by:

- Listing what's currently running via `Describe*` / `List*` APIs
- Multiplying instance state × hours-since-launch × on-demand price for an exact running rate
- Optionally adding CloudWatch volume metrics for services with usage-based costs

It's a complement to the official [AWS Labs MCP servers](https://github.com/awslabs/mcp), not a replacement — run both side by side.

## Status

Early development. See PR history for current scope.
