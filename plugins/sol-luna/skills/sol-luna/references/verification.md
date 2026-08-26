# Verification contract

The main thread owns final acceptance.

For read-only packets, verify that the cited files, lines, logs, or tool outputs support the returned
conclusion. Reconcile contradictory findings explicitly.

For writable packets:

1. Inspect the actual changed files and repository diff.
2. Confirm every changed path was owned by that packet or by the main thread.
3. Run the packet validation and the smallest sufficient integration suite.
4. Check requirement coverage, compatibility, security, and remaining risk.
5. Accept, request one bounded correction, or report a blocker.

Do not report an effective model or effort from configuration alone. Prefer agent activity or tool
metadata. If only the request is observable, write "requested GPT-5.6 Luna Max" rather than
"used GPT-5.6 Luna Max".

Delegation evidence must contain at least one non-empty child thread ID returned by the runtime.
An empty wait call, a requested agent name, or a success marker repeated by the main thread does not
prove that a child ran. If the requested count and observed child IDs differ, report the mismatch
and do not claim the delegated route succeeded.
