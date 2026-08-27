# Architecture

## Control plane

The model selected by the user in Codex is the only controller. The plugin never pins, replaces, or infers that model. Sol is recommended but not required.

The controller owns requirement interpretation, route selection, task packets, architecture and safety decisions, writable-file ownership, integration, final validation, and the user-facing result.

## Execution plane

Luna children are bounded leaf workers. Every spawn requests `gpt-5.6-luna` with `max` reasoning and uses either the reader or worker contract.

Routes:

- `MAIN_ONLY`: no child threads.
- `LUNA_READ_PARALLEL`: independent evidence-gathering packets.
- `LUNA_WRITE_PARALLEL`: independent packets with disjoint write scopes.

The skill is explicit-only. It activates only when the Codex runtime attaches it after the user
selects `$sol-luna` in the frontend Skill picker. Ordinary prompts, natural-language Luna requests,
raw `$sol-luna` text, and task-API messages cannot activate it through implicit discovery.

## Ownership and validation

Every writable file has one active owner. Shared interfaces, lockfiles, migrations, repository-wide formatting, and overlapping edits run sequentially. Child summaries are advisory; the main thread must inspect files and diffs and run the smallest sufficient integration checks.

## Truthfulness boundary

A config file proves intent, not execution. The Skill reports an effective model only when agent activity or tool metadata identifies it. Otherwise it reports that Luna Max was requested.

## Failure behavior

- Adaptive route and unavailable Luna: disclose and continue in the main thread.
- Explicitly required Luna and unavailable Luna: stop delegation without substitution.
- Child scope expansion, high-risk finding, validation failure, or two failed attempts: return control and evidence to the main thread.
- Unexpected write overlap: stop the later writer and serialize the overlapping work.
