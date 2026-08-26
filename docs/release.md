# Release process

1. Run repository validation, unit tests, fixture tests, and real isolated installation.
2. Use the current stable standalone Codex CLI (not a bundled pre-release), selecting it with `--codex-bin` when necessary. Run `doctor --smoke-models` once from the installed plugin, require `luna_max_verified`, verify `SHA256SUMS`, and retain the complete evidence bundle.
3. Run or explicitly defer the billable benchmark matrix; do not claim performance without results.
4. Tag `v0.1.0-rc.1` for three-platform installation validation.
5. Promote to `v0.1.0` only after the release gates in `docs/benchmark.md` pass.
6. GitHub Actions builds repository-specific installer assets and `SHA256SUMS` from the tag.

Repository-owner metadata is synchronized once from the actual `origin` with
`tools/sync_repository_metadata.py`. CI and release jobs compare it with
`github.repository` so a transfer or renamed fork cannot silently publish stale author URLs.

Use patch releases for compatible fixes, minor releases for routing or installation contract changes, and `v1.0.0` only after the public interfaces and evaluation gates are stable.
