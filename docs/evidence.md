# Luna Max smoke evidence

`doctor --smoke-models` makes one real, potentially billable subagent request and automatically
writes an evidence bundle under:

```text
${CODEX_HOME}/sol-luna/evidence/smoke-<UTC timestamp>-<random id>/
├── events.jsonl
├── parent-rollout.jsonl                 # when the runtime persists the parent
├── child-rollout-<thread-id>.jsonl      # when the runtime persists the child
├── manifest.json
└── SHA256SUMS
```

The bundle is written for successful runs, failed runs, timeouts, and login preflight failures.
The doctor prints the absolute bundle path; JSON output also exposes it as
`checks[].evidence_path` on the model-smoke check.

## What each file means

- `events.jsonl` is the unmodified stdout from `codex exec --json`.
- `parent-rollout.jsonl` and `child-rollout-<thread-id>.jsonl`, when present, are immutable copies
  of the new local rollout files linked by the current parent/child thread IDs. They supply the
  child model and effort evidence when a pre-release CLI omits those fields from exported JSONL.
- `manifest.json` records the UTC start and completion times, Codex version, requested main and
  child settings, child thread IDs, observed model and reasoning metadata, marker linkage, child
  completion, and the resulting verification level.
- `SHA256SUMS` covers every included JSONL artifact and `manifest.json`. It detects accidental or
  unrecorded local changes; because the checksum file is stored beside the artifacts and is not
  signed, it is not an independent cryptographic attestation against a party that can replace the
  entire bundle.

Where supported, bundle directories are mode `0700` and files are mode `0600`.

## Verification levels

| Level | Meaning |
|---|---|
| `requested_only` | Luna Max was requested, but the activity did not prove a completed Luna child. |
| `luna_verified` | One completed child and Luna model metadata were proven, but Max metadata was absent. |
| `luna_max_verified` | The same newly created, completed child was linked to the marker, `gpt-5.6-luna`, and `max`. |

The doctor succeeds only for `luna_max_verified`. A child name, Agent TOML, local model catalog,
parent-thread statement, or marker echoed only by the parent is not sufficient.

## Check integrity

On macOS:

```sh
cd "$CODEX_HOME/sol-luna/evidence/<bundle>"
shasum -a 256 -c SHA256SUMS
```

On Linux, run `sha256sum -c SHA256SUMS` from the same directory.

On Windows, compare each recorded value with `Get-FileHash -Algorithm SHA256`.

## Privacy and lifecycle

Review every JSONL file before sharing it. Although the smoke prompt never asks the child to
inspect workspace files, runtime diagnostics and rollouts can contain local paths, prompt context,
or account-specific error text. Do not paste an unreviewed evidence bundle into a public Issue.

Evidence bundles are audit data, not installer-managed templates. Upgrade and uninstall therefore
leave them in place. Remove reviewed bundles manually when they are no longer needed.
