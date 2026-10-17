# devservices

Python CLI that manages Docker Compose and supervisor dependencies for Sentry services. User docs live in [README.md](README.md).

## Commands

- Set up: `direnv allow`. [.envrc](.envrc) runs `uv sync` and installs the pre-commit hooks.
- Test: `pytest -n4`. Tests marked `integration` call real GitHub.
- Lint, format, and type check: `pre-commit run --all-files` (ruff, mypy, shellcheck).

## Invariants

- `scripts/bump-version.sh` rewrites the version in `pyproject.toml` and the `devservices==<version>` line in [README.md](README.md). Keep that README line.

## Where things live

- CLI entry point and subcommand registration: [devservices/main.py](devservices/main.py)
- One module per subcommand: [devservices/commands/](devservices/commands/)
- Config parsing and validation: [devservices/configs/service_config.py](devservices/configs/service_config.py)
- Paths, versions, and timeouts: [devservices/constants.py](devservices/constants.py)
- Release: the `Release` workflow in [.github/workflows/release.yml](.github/workflows/release.yml) runs craft with [.craft.yml](.craft.yml). [.github/workflows/build.yml](.github/workflows/build.yml) builds the PyOxidizer binaries.
- Changes per version: [CHANGELOG.md](CHANGELOG.md)
