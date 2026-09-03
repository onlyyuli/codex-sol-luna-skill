# Verification contract

The main thread owns final acceptance.

For read-only packets, verify the minimum cited files, lines, logs, or tool outputs needed to
support the conclusion. Do not repeat the child's broad search or read the entire delegated scope.
Reconcile contradictory findings explicitly.

For writable packets:

1. In one combined tool round where practical, inspect the repository diff and only the critical
   changed paths needed for acceptance.
2. Confirm every changed path was owned by that packet or by the main thread.
3. Use the child's local validation evidence and run the smallest sufficient integration check in
   that same round when the runtime supports parallel or batched checks.
4. Check requirement coverage, compatibility, security, and remaining risk.
5. Accept, request one bounded correction from the same child, or report a blocker.

The main thread is a judge, not a duplicate executor. It must not repeat delegated searches,
reconstruct the full analysis, rerun every child command, or reimplement the same change unless the
child failed and a safe fallback is explicitly disclosed. Targeted verification is required;
duplicated execution is an economy failure.

Do not add a second verification round merely to restate evidence already returned by the child.
Use it only when the first round exposes a concrete unresolved issue.

Do not report an effective model or effort from configuration alone. Prefer agent activity or tool
metadata. If only the request is observable, write "requested GPT-5.6 Luna Max" rather than
"used GPT-5.6 Luna Max".

Delegation evidence must contain at least one non-empty child thread ID returned by the runtime.
An empty wait call, a requested agent name, or a success marker repeated by the main thread does not
prove that a child ran. If the requested count and observed child IDs differ, report the mismatch
and do not claim the delegated route succeeded.
