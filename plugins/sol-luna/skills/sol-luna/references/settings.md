# Settings

The optional settings file is `${CODEX_HOME}/sol-luna/settings.toml`; when `CODEX_HOME` is unset,
use the Codex default home directory.

Supported keys:

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

Constraints:

- `routing_objective` is fixed to `"minimize-credits"` in v0.1.x.
- `1 <= auto_min_agents <= auto_max_agents <= hard_max_agents <= 8`.
- `write_parallelism` is `"off"` or `"disjoint-only"`.
- `parent_review` is fixed to `"targeted"`; it requires judge-only acceptance instead of duplicate
  execution.
- `strict_model` and `announce_route` are booleans.
- Unknown keys are invalid and should be reported rather than guessed.
- No setting can change the main-thread model, child model, or child reasoning effort.

With the defaults, adaptive routing prefers one Luna and may use two only when independent packets
reduce duplicated context. Counts 3-8 are explicit-only and may consume more credits.

If the file is absent, malformed, or invalid, use the built-in defaults and report the problem when
it materially affects the requested route.
