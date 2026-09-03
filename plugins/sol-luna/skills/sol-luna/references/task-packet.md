# Compact task packet contract

Every delegated agent receives a self-contained packet with no unrelated conversation history.
Use `none` only where an optional field is intentionally empty.

```text
id: stable packet identifier
role: reader | worker
objective: one bounded outcome
scope: exact files, directories, or resources needed for the outcome
write_scope: exact writable paths, or none
constraints: permissions, compatibility requirements, and non-goals
acceptance: observable conditions for success
validation: smallest sufficient checks the child should run
evidence_budget: concise facts and paths; no full logs or large source excerpts
stop_conditions: ambiguity, scope expansion, risk, unavailable validation, or two failed attempts
```

Require this compact return shape:

```text
status: completed | blocked | failed
outcome: concise result
evidence: exact paths and essential facts supporting the outcome
files_changed: exact paths, or none
validation: commands/checks and pass/fail result; omit routine full output
risk_or_blocker: unresolved risk, needed decision, or none
```

The child does not approve the overall task. It reports contradictions instead of silently
redefining the packet. Prefer paths, symbols, and short factual excerpts over copied logs. The main
thread requests one bounded correction from the same child when evidence is insufficient; it does
not redo the packet by default.
