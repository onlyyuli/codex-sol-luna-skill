# Configuration

## Routing settings

Managed installations create `${CODEX_HOME}/sol-luna/settings.toml`:

```toml
auto_min_agents = 2
auto_max_agents = 4
hard_max_agents = 8
write_parallelism = "disjoint-only"
strict_model = true
announce_route = true
```

Limits must satisfy `1 <= auto_min_agents <= auto_max_agents <= hard_max_agents <= 8`. `write_parallelism` accepts `off` or `disjoint-only`.

The file cannot select the main model, child model, or reasoning effort. In v0.1.x the child contract is always GPT-5.6 Luna Max.

## Agent templates

- `${CODEX_HOME}/agents/sol-luna-reader.toml`: read-only Luna Max leaf worker.
- `${CODEX_HOME}/agents/sol-luna-worker.toml`: workspace-write Luna Max leaf worker.

Live parent permission choices may still affect child sessions. The main thread must verify actual write scope and diffs even when a custom agent declares read-only mode.

## CLI profile

`${CODEX_HOME}/sol-luna.config.toml` is optional and loaded only with `codex --profile sol-luna`. It selects Sol High and enables Luna Max defaults with a maximum of eight open child threads.

The Desktop composer remains authoritative for Desktop tasks.
