# Orchestrator monitor

This small service polls Redis `dlq:failed`, applies exponential backoff per
`pipeline_run_id`, republishes original messages when their retry window has
elapsed, and marks runs as `failed` after the configured number of attempts.

Run locally:

```bash
source .venv/bin/activate
python -m orchestrator.monitor --poll-interval 30 --base-delay 60 --max-attempts 3
```

The monitor publishes human alerts to the `alerts:human` Redis stream when
it marks a run failed.
