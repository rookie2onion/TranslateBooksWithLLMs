# Validation and Agent Environment

Read this before offline checks, code review, or agent setup.

## Development Environment

Use a project-local virtual environment; do not rely on the system Python:

```bash
python -m venv data/.venv
data/.venv/Scripts/python -m pip install -r requirements-dev.txt   # Windows
python -m pip install -r requirements-dev.txt                      # POSIX
```

`data/` is Git-ignored, so the environment never enters a commit. The environment
provides the application dependencies plus `pytest`, `pytest-asyncio`,
`pre-commit` and the pinned `isort`.

## Offline Checks

```bash
python scripts/check.py --install-hooks   # once: records agent.python + installs hooks
python scripts/check.py                   # lint changed files + offline unit gate
python scripts/check.py --unit-only       # what the pre-commit hook runs
python scripts/check.py --all-files       # explicit legacy audit, not routine
```

`scripts/check.py` re-executes the interpreter recorded in the repository-local
`agent.python` Git setting, so `git commit` works even when the shell PATH points
at another Python. That setting is shared by every worktree of this repository:
reinstall the hooks from the environment you want the gate to use, and expect the
last installation to win. `--unit-only` runs `tests/unit` plus `tests/test_mineru`
when that suite exists. `pytest.ini` already excludes integration/E2E tests; the
hook keeps that marker boundary. `PYTHON_DOTENV_DISABLED=1` is set by the entry
point, so checks never load private provider settings.

The pre-commit configuration is authoritative for formatting. Do not treat a
separately installed `isort` as the gate; `requirements-dev.txt` pins the same
version the hook uses.

If `check.py` reports a missing configured interpreter, reinstall the hooks from
the current environment:

```bash
python scripts/check.py --install-hooks
```

## Code Review

Freeze the implementation before dispatching a review (commit or stash the
working tree). Reviewers read a snapshot; reviewing a moving tree produces stale
findings that cost a round trip to disprove.

## Secrets

Credentials come from the Git-ignored `.env`; never from source, tests, examples
or commit messages. Offline checks must not require a provider key.
