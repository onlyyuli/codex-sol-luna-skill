# Configuration

## Routing settings

Managed installations create `${CODEX_HOME}/sol-luna/settings.toml`:

```toml
routing_objective = "minimize-credits"
auto_min_agents = 1
auto_max_agents = 2
hard_max_agents = 8
write_parallelism = "disjoint-only"
parent_review = "targeted"
strict_model = true
announce_route = true
```

`routing_objective` and `parent_review` are fixed in v0.1.x. The adaptive route prefers one Luna
and may choose two only when independent scopes avoid duplicated context. Counts 3-8 require an
explicit user request and may use more Credits.

Limits must satisfy `1 <= auto_min_agents <= auto_max_agents <= hard_max_agents <= 8`.
`write_parallelism` accepts `off` or `disjoint-only`.

The settings file cannot select the main model, child model, or reasoning effort. The child
contract remains GPT-5.6 Luna Max.

## Agent templates

- `${CODEX_HOME}/agents/sol-luna-reader.toml`: read-only Luna Max leaf executor.
- `${CODEX_HOME}/agents/sol-luna-worker.toml`: workspace-write Luna Max leaf executor.

Both return concise evidence instead of raw logs. Live permissions can still constrain children,
so the main thread performs targeted evidence or diff checks before acceptance.

## CLI profile

`${CODEX_HOME}/sol-luna.config.toml` is optional and loaded only with
`codex --profile sol-luna`. It selects Sol High and enables Luna Max defaults with a hard maximum
of eight open child threads.

The Desktop composer remains authoritative for Desktop tasks.
