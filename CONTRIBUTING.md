# Contributing

Thank you for improving codex-sol-luna-skill.

Use Conventional Commits and keep changes project-agnostic. Do not add root model pins, implicit skill activation, silent model fallbacks, overlapping write ownership, or destructive installer behavior.

Before opening a pull request:

```sh
python3 tools/validate_repository.py
python3 -m unittest discover -s tests
python3 -m unittest discover -s benchmarks/fixture/tests -t benchmarks/fixture
python3 tests/integration_local_install.py
```

Real model smoke and benchmark runs consume account quota. State whether they were run and attach evidence without secrets or private prompts.

Pull requests should explain behavior changes, compatibility impact, validation performed, and any remaining risk.
