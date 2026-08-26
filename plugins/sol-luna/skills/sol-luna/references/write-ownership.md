# Write ownership

Use parallel write agents only when every writable path has one active owner and the packets do not
depend on each other's unfinished output.

Before spawning, create an ownership table with packet ID, writable paths, validation, and expected
integration point. Directory ownership is acceptable only when nested paths cannot overlap another
packet. Generated lockfiles, snapshots, shared registries, migrations, and formatting passes count
as writes and must also have one owner.

If an unexpected overlap appears:

1. Stop the later writer.
2. Preserve already completed work.
3. Reassign the overlapping portion to one owner or execute it sequentially in the main thread.
4. Re-run integration validation after the conflict is resolved.

Do not use parallel writers for destructive migrations, shared public interfaces, dependency
upgrades that rewrite common lockfiles, or repository-wide formatters.
