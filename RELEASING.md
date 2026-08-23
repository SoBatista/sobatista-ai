# Releasing SoBatista AI

This document defines how SoBatista AI is versioned and released. It is the
authoritative reference for maintainers; contributors mainly need the
[Versioning](#versioning) and [Release impact](#release-impact-every-pr) sections.

> **Current state:** the project is at `0.1.0.dev0` — a development version. **No
> stable release exists yet. Do not treat any current build as stable `0.1.0`.**

## Versioning

- **Scheme:** [Semantic Versioning 2.0.0](https://semver.org/) for git tags,
  normalized to [PEP 440](https://peps.python.org/pep-0440/) for the Python
  distribution metadata. Tags are `vMAJOR.MINOR.PATCH[pre]`; the packaged version
  in `pyproject.toml` is the PEP 440 form.
- **Single source of truth:** `[project].version` in `pyproject.toml`. At runtime
  `sobai --version` reports the *installed package metadata* (built from that
  field). The constant in `src/sobai/__init__.py` is only a source-checkout
  fallback and is kept in sync automatically by Release Please.
- **Tag ↔ version:** the release workflow refuses to publish if the tag does not
  match the packaged version (`scripts/check_version_tag.py`).

### Pre-release lifecycle

Releases progress through PEP 440 pre-release phases before a stable line:

| Phase | git tag | PyPI version | Meaning |
|-------|---------|--------------|---------|
| alpha | `v0.1.0-alpha.1` | `0.1.0a1` | early, unstable, may change freely |
| beta  | `v0.1.0-beta.1`  | `0.1.0b1` | feature-complete for the line, stabilizing |
| rc    | `v0.1.0-rc.1`    | `0.1.0rc1`| release candidate; only fixes |
| stable| `v0.1.0`         | `0.1.0`   | supported release |

The **first** intended release is `v0.1.0-alpha.1` (`0.1.0a1`). It is **not**
created by this work — see the [runbook](#release-runbook).

### Pre-1.0 compatibility

While the major version is `0`, **minor** releases may contain breaking changes
and **patch** releases are reserved for backward-compatible fixes. Breaking
changes are always called out in the changelog. After `1.0.0`, standard SemVer
guarantees apply.

### Deprecation policy

- A feature is deprecated in a release with a changelog note and, where it is
  user-facing, a runtime warning and updated `--help`.
- Pre-1.0: a deprecated feature may be removed in the next **minor** release.
- Post-1.0: a deprecated feature is kept for at least one **minor** release and
  removed no earlier than the next **major**.

### Supported Python versions

The project supports the CPython versions declared in `pyproject.toml`
(`requires-python`) and exercised in the CI matrix — currently **3.12 and 3.13**.
Dropping a Python version is a breaking change (minor bump pre-1.0).

### Security support

Only the most recent released version receives security fixes. See
[`SECURITY.md`](SECURITY.md#supported-versions).

## Release impact (every PR)

Every pull request must declare **exactly one** release impact by ticking a box
in the PR template:

- `major` — backward-incompatible change
- `minor` — backward-compatible feature
- `patch` — backward-compatible fix
- `none` — docs/tests/chore only, no release

This is validated automatically by the **PR release impact** workflow
(`scripts/check_release_impact.py`). The impact must be consistent with the
Conventional Commit types in the PR (`feat` → minor, `fix` → patch,
`feat!`/`fix!`/`BREAKING CHANGE:` → major).

## How releases are prepared and published

Two workflows implement a **prepare → publish** split. Both are committed and
configured, but **publishing is inert** until a maintainer acts (no tag is
created by this repository's automation on its own).

1. **Prepare — `release-please.yml`.** On every push to `main`, Release Please
   maintains a *release PR* that bumps the version and updates `CHANGELOG.md`
   from Conventional Commits. Nothing is tagged or published until that PR is
   merged.
2. **Publish — `release.yml`.** Triggered only when a GitHub Release is published
   (normally by merging the release PR) or by manual `workflow_dispatch` against
   an existing tag. It:
   - builds the sdist + wheel once and reuses them for every downstream job;
   - verifies tag ↔ version, runs `twine check --strict`;
   - smoke-installs **both** artifacts and runs the CLI;
   - generates SHA-256 checksums and a **CycloneDX SBOM**;
   - creates **signed build-provenance attestations**;
   - uploads artifacts, checksums, and SBOM to the GitHub Release;
   - publishes to PyPI via **Trusted Publishing (OIDC)** from the protected
     `pypi` environment — **no long-lived token exists in this repo** — which
     also attaches PEP 740 attestations.

All third-party Actions are pinned to full commit SHAs; jobs use least-privilege
permissions.

## Release runbook

Prerequisites are the one-time settings in
[`docs/repo-settings-checklist.md`](docs/repo-settings-checklist.md) (PyPI
Trusted Publisher, protected `pypi` environment, `RELEASE_PLEASE_TOKEN`).

**Stable release (the normal path):**

1. Merge the open Release Please PR on `main`. This tags `vX.Y.Z` and creates the
   GitHub Release.
2. `release.yml` runs and publishes to PyPI. Watch the run.
3. Verify: `pipx install sobatista-ai==X.Y.Z` (or `uv tool install`), then
   `sobai --version`.

**First alpha / other pre-releases.** Release Please is configured for final
releases; cut a pre-release manually because SemVer pre-release ordering and PEP
440 differ:

1. Set the version in `pyproject.toml` to the PEP 440 pre-release (e.g.
   `0.1.0a1`) via a normal PR, or add a `Release-As: 0.1.0-alpha.1` footer to a
   commit so Release Please proposes it.
2. After merge, create the tag and release: `gh release create v0.1.0-alpha.1
   --prerelease --generate-notes`. Mark it a pre-release so it is not "latest".
3. `release.yml` publishes it as a PyPI pre-release (pip won't install it without
   `--pre` or an exact pin).

## Recovery / rollback

- **Failed publish job:** `release.yml` is idempotent. Re-run it — PyPI upload
  uses `skip-existing`, GitHub asset upload uses `--clobber`. Fix the cause first.
- **Bad version already on PyPI:** PyPI files are **immutable** and cannot be
  overwritten. [Yank](https://pypi.org/help/#yanked) the bad version on PyPI (it
  stops being installed by default but stays available for existing pins) and
  ship a corrected **new** patch version. Never try to reuse a version number.
- **Compromised publisher / leaked credential:** because publishing uses OIDC
  Trusted Publishing there is no static token to rotate. If compromise is
  suspected: remove/disable the PyPI Trusted Publisher and the GitHub `pypi`
  environment immediately, review the Actions run and audit logs, yank affected
  versions, and only then re-establish the publisher. See the incident steps in
  [`docs/repo-settings-checklist.md`](docs/repo-settings-checklist.md).

## Consuming provenance and SBOM

- Verify a wheel's provenance with `gh attestation verify <file> --repo
  SoBatista/sobatista-ai`.
- Verify checksums with `sha256sum -c SHA256SUMS` against the release assets.
- The CycloneDX `sbom.cdx.json` asset lists the runtime dependency components.
