# ADR-0004: Versioning and automated, OIDC-based releases

- Status: Superseded by [ADR-0006](0006-one-pull-request-one-version.md)
- Date: 2026-08-23
- Superseded: 2026-08-24. The Release Please prepare/publish split and the
  major/minor/patch/none impact declaration described below were replaced by
  one-pull-request-one-version. The Trusted Publishing, OIDC, checksum, SBOM,
  and provenance decisions are **still in force** — ADR-0006 changes only how
  the version is decided and how publishing is triggered.

## Context

The project needs a professional, auditable release process for an open-source
Python package: a predictable version scheme, a single source of truth for the
version, changelog discipline, and a supply-chain-hardened path to PyPI. Storing
a long-lived PyPI API token in the repository or in CI secrets is a standing
liability, and manual releases are error-prone.

## Decision

- **Versioning:** Semantic Versioning for git tags, normalized to PEP 440 for the
  Python distribution. `[project].version` in `pyproject.toml` is the single
  source of truth; `sobai --version` reports installed package metadata, and the
  fallback constant in `__init__.py` is kept in sync by automation. Pre-1.0,
  minor versions may break; patches never do. The full policy (pre-release
  lifecycle, deprecation, supported Pythons, security support, rollback) lives in
  `RELEASING.md`.
- **Prepare/publish split:** [Release Please](https://github.com/googleapis/release-please)
  maintains a release PR (version bump + changelog from Conventional Commits).
  Merging it tags and creates a GitHub Release, which triggers a separate publish
  workflow. Neither this repo's automation nor this change creates a tag or
  publishes on its own.
- **Trusted Publishing:** publishing uses PyPI Trusted Publishing (GitHub OIDC)
  from a protected `pypi` environment — **no long-lived PyPI token exists in the
  repository**. Each release carries SHA-256 checksums, a CycloneDX SBOM, signed
  build-provenance attestations, and PyPI's PEP 740 attestations, and both
  artifacts are smoke-installed before publish.
- **Release impact:** every PR declares exactly one of major/minor/patch/none,
  validated in CI, keeping automated version bumps deterministic.

## Consequences

- No static publishing credential to leak or rotate; compromise response is to
  disable the trusted publisher and environment (see `RELEASING.md`).
- Releases are reproducible-by-recipe and independently verifiable (checksums,
  provenance, SBOM).
- Pre-releases (alpha/beta/rc) are cut manually because SemVer pre-release
  ordering and PEP 440 differ; this is documented rather than automated to avoid
  emitting invalid versions.
- Maintainers must complete one-time GitHub/PyPI settings (protected environment,
  trusted publisher, a PAT so releases cascade) documented in
  `docs/repo-settings-checklist.md`.
