# Changelog

All notable changes follow Semantic Versioning.

## [Unreleased]

- Add the explicit-only Codex Sol + Luna Skill, packaged through a Plugin Marketplace.
- Add Luna Max reader and worker contracts with bounded delegation.
- Make routing economy-first: prefer one Luna that replaces main-thread execution, cap adaptive
  parallelism at two, and keep the main thread in a targeted judge-only role.
- Add parent/child token and Credit accounting, duplicate-execution evidence, and savings release
  gates to the benchmark harness.
- Repair installer-owned local Marketplace entries after a repository move without editing
  unrelated Codex configuration, with rollback when the previous source remains available.
- Record a sanitized one-task Credit canary while keeping the full 18-task release gate closed.
- Add managed cross-platform install, upgrade, doctor, and uninstall tooling.
- Add strict Luna Max smoke verification with private JSONL evidence bundles and SHA-256 integrity records.
- Add isolated installation tests and an opt-in 18-task benchmark harness.
