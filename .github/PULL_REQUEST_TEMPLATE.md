<!-- Thanks for contributing to SoBatista AI! -->

## Summary

<!-- What does this change do and why? -->

## Release (required)

Every pull request carries its own version bump, so the version reaching `main`
is the one that was reviewed. Before requesting review:

1. Apply **exactly one** label: `release:major`, `release:minor`, or
   `release:patch` (`patch` covers fixes, docs, configuration, and maintenance).
2. Bump `[project].version` in `pyproject.toml` by that one increment, and run
   `uv lock` so `uv.lock` follows.
3. Update `_FALLBACK_VERSION` in `src/sobai/__init__.py` to match.
4. Add a dated `## [x.y.z] - YYYY-MM-DD` section to `CHANGELOG.md` describing the
   change — it becomes the GitHub Release notes verbatim.

`scripts/check_version.py --consistency` checks steps 2–4 locally; CI runs
`--pr` and fails if the label and the version disagree.

## Checklist

- [ ] `uv run ruff check .` passes
- [ ] `uv run ruff format --check .` passes
- [ ] `uv run mypy` passes
- [ ] `uv run pytest` passes (no live external APIs)
- [ ] Tests added/updated for the change
- [ ] Docs and `--help` updated to match behavior
- [ ] No secrets added to code, config, fixtures, or logs
- [ ] Providers and connectors remain decoupled (see ARCHITECTURE.md)
- [ ] Conventional Commit title
- [ ] Exactly one `release:*` label, and `scripts/check_version.py --consistency` passes

## Notes for reviewers

<!-- Anything reviewers should focus on, risks, follow-ups. -->
