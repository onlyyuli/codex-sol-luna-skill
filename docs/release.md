# Release process

1. Run repository validation, unit tests, fixture tests, and real isolated installation.
2. In a fresh Codex Desktop task, select `$sol-luna` from the frontend Skill picker and run a
   `MAIN_ONLY` probe that forbids manually opening `SKILL.md`. Require the attached-skill run to
   complete with zero children. As a negative control, send the same raw `$sol-luna` text through a
   task API and require `NOT_ATTACHED` with zero children.
3. Use the current stable standalone Codex CLI (not a bundled pre-release), selecting it with
   `--codex-bin` when necessary. Run `tools/check_codex_release.py`, then run
   `doctor --smoke-models` once from the installed plugin, require `luna_max_verified`, verify
   `SHA256SUMS`, and retain the complete evidence bundle.
4. Run or explicitly defer the billable benchmark matrix; do not claim performance without results.
5. Tag `v0.1.0-rc.1` for three-platform installation validation. The `codex-integration` job must
   pass on `ubuntu-latest`, `macos-latest`, and `windows-latest`; a locally parsed workflow is not a
   substitute for those three runner results.
6. Promote to `v0.1.0` only after the release gates in `docs/benchmark.md` pass.
7. GitHub Actions builds repository-specific installer assets and `SHA256SUMS` from the tag.

Repository-owner metadata is synchronized once from the actual `origin` with
`tools/sync_repository_metadata.py`. CI and release jobs compare it with
`github.repository` so a transfer or renamed fork cannot silently publish stale author URLs.

Use patch releases for compatible fixes, minor releases for routing or installation contract changes, and `v1.0.0` only after the public interfaces and evaluation gates are stable.
