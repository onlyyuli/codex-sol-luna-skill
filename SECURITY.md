# Security policy

## Reporting

Do not include API keys, Codex authentication files, private configuration, private prompts, repository contents, or unredacted logs in public Issues.

For a suspected vulnerability, use GitHub private vulnerability reporting when enabled. If it is unavailable, contact the repository owner through the private contact method listed on their GitHub profile.

## Installer boundary

The installer manages only the `sol-luna` Plugin, its Marketplace entry, namespaced Agent files, optional Profile, routing settings, and install state. It does not intentionally modify model, provider, permission, authentication, history, or unrelated project settings.

Modified managed files and symlinks are preserved during uninstall. Release installers are accompanied by SHA-256 checksums.
