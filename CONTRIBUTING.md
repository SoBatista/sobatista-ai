# Contributing to SoBatista AI

Thanks for your interest! This project aims to be an exceptionally professional,
secure, and extensible provider-neutral AI CLI. Contributions of all sizes are
welcome.

## Ground rules

- Read [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) — the same engineering
  rules apply to humans and AI agents.
- Never commit secrets. Credentials belong in the OS keyring, not the repo.
- Keep providers and connectors decoupled (see [`ARCHITECTURE.md`](ARCHITECTURE.md)).
- Preserve the security invariants in [`SECURITY.md`](SECURITY.md).

## Development setup

```bash
git clone https://github.com/sobatistacyber/sobatista-ai
cd sobatista-ai
uv sync --group dev
uv run sobai --help
```

## Quality gates (all must pass)

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

- Tests must pass **without any live external API**. Live integration tests are
  opt-in behind the `live` pytest marker and require dedicated test accounts.
- New behavior ships with tests. Don't chase coverage with meaningless tests, but
  keep the threshold meaningful.

## Commits & PRs

- Use [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:` …).
- Every PR must declare its **release impact**: `major` / `minor` / `patch` /
  `none` (see the PR template).
- Keep PRs small and focused. Update docs and `--help` when behavior changes.
- Do not merge, publish packages, cut releases, create OAuth apps, or modify
  external accounts without explicit maintainer approval.

## Adding a provider or connector

- Providers implement `sobai.providers.base.Provider` and register in
  `providers/registry.py`. See the provider authoring guide (docs, planned).
- Connectors expose typed tools via `sobai.tools`. See the connector authoring
  guide (docs, planned). Never couple a connector to a provider.

## Reporting security issues

See [`SECURITY.md`](SECURITY.md) — report privately, never with real credentials.
