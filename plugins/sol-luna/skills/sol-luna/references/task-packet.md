# Task packet contract

Use this contract for every delegated agent. Omit no field; use `none` when a field is intentionally
empty.

```text
id: stable packet identifier
role: reader | worker
objective: one bounded outcome
context_and_evidence: only facts needed for this packet
read_scope: files, directories, or resources the agent may inspect
write_scope: exact files the agent may edit, or none
constraints: permissions, compatibility, style, and non-goals
acceptance_criteria: observable conditions for success
validation: exact checks or commands the agent should run
return_contract: the result fields listed below
stop_conditions: ambiguity, scope expansion, risk, unavailable validation, or two failed attempts
```

Require this return shape:

```text
status: completed | blocked | failed
summary: concise result
files_inspected: exact paths
files_changed: exact paths, or none
commands_and_results: each command and its outcome
evidence: facts supporting the conclusion
remaining_risks: unresolved risks, or none
decision_needed: question for the main thread, or none
```

The child does not approve the overall task. If repository facts contradict the packet, it returns
the contradiction instead of silently redefining the work.
