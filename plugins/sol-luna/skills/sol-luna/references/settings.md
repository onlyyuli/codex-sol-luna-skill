# Settings

The optional settings file is `${CODEX_HOME}/sol-luna/settings.toml`; when `CODEX_HOME` is unset,
use the Codex default home directory.

Supported keys:

```toml
auto_min_agents = 2
auto_max_agents = 4
hard_max_agents = 8
write_parallelism = "disjoint-only"
strict_model = true
announce_route = true
```

Constraints:

- `1 <= auto_min_agents <= auto_max_agents <= hard_max_agents <= 8`.
- `write_parallelism` is `"off"` or `"disjoint-only"`.
- `strict_model` and `announce_route` are booleans.
- Unknown keys are invalid and should be reported rather than guessed.
- No setting can change the main-thread model, child model, or child reasoning effort.

If the file is absent, malformed, or invalid, use the built-in defaults and report the problem when
it materially affects the requested route.
