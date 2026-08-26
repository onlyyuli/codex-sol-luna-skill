# Repository contribution rules

- Keep this repository project-agnostic. Runtime orchestration belongs in the packaged `sol-luna`
  skill, not in this file.
- Do not add a root `.codex/config.toml` or otherwise pin a contributor's main-thread model.
- Preserve explicit-only skill invocation and the fixed GPT-5.6 Luna Max child contract for v0.1.x.
- Installer changes must remain idempotent. Only the official Codex Plugin CLI may update its own
  Marketplace/Plugin namespaces in the base `config.toml`; never rewrite model, agent, permission,
  or unrelated fields. Preserve pre-existing and user-modified files during upgrade and uninstall.
- Run the repository validation and unit tests before submitting changes.
