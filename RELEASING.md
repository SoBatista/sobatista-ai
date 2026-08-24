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
  fallback; `scripts/check_version.py` fails CI if it ever drifts from
  `pyproject.toml`.
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

## One pull request, one version

Every pull request merged into `main` includes **exactly one** version increase,
so the version that reaches `main` is the one that was reviewed:

- `release:major` — breaking behavior; `X.y.z` becomes `X+1.0.0`.
- `release:minor` — backward-compatible feature; `x.Y.z` becomes `x.Y+1.0`.
- `release:patch` — fix, documentation, configuration, or maintenance;
  `x.y.Z` becomes `x.y.Z+1`.

The arithmetic is exactly what the label says, at every version. There are no
pre-1.0 special cases: `release:minor` on `0.1.1` is `0.2.0`, never `0.1.2`.

The pull request must apply exactly one label and update all four places the
version is recorded, plus the changelog:

| What | Where |
|---|---|
| Source of truth | `[project].version` in `pyproject.toml` |
| Lockfile | `uv.lock` — run `uv lock` |
| Source-checkout fallback | `_FALLBACK_VERSION` in `src/sobai/__init__.py` |
| Release notes | a dated `## [x.y.z] - YYYY-MM-DD` section in `CHANGELOG.md` |

Check it locally before pushing:

```bash
uv run python scripts/check_version.py --consistency
```

CI runs `--pr` on every pull request (including when a label changes) and fails
if the label and the version disagree. Requiring the reviewed pull request to
carry the version avoids a post-merge bot commit: it keeps branch protection
intact, needs no bot able to open pull requests, and makes the exact release
state visible during review.

**Dependabot pull requests** carry no label and do not touch `pyproject.toml`, so
they fail release metadata until a maintainer pushes a `release:patch` bump onto
the branch. This is a deliberate, accepted cost.

## How releases are published

There is no release PR and no bot commit. A successful CI run on `main` is, by
construction, a reviewed release candidate, and `release.yml` takes it from
there:

1. **gate** — re-validates version consistency, refuses to move an existing tag,
   and refuses a version that is not newer than the newest existing tag.
2. **build** — sdist + wheel built once and reused; tag ↔ version check;
   `twine check --strict`; SHA-256 checksums; CycloneDX SBOM.
3. **smoke** — installs **both** artifacts and runs the CLI.
4. **provenance** — signed build-provenance attestations.
5. **tag-and-release** — only now is the annotated `vX.Y.Z` tag created, with a
   GitHub Release whose notes are that version's reviewed changelog section, and
   the artifacts, checksums, and SBOM attached.
6. **pypi-publish** — Trusted Publishing (OIDC) from the protected `pypi`
   environment. **No long-lived token exists in this repository.**

Nothing is tagged before the artifacts are built, installed, and attested, and
PyPI — the only irreversible step — runs last. The trigger is `workflow_run`
rather than `release: published` because a Release created by `GITHUB_TOKEN`
cannot trigger another workflow; publishing therefore needs **no personal access
token**.

All third-party Actions are pinned to full commit SHAs; jobs use least-privilege
permissions.

## Release runbook

Prerequisites are the one-time settings in
[`docs/repo-settings-checklist.md`](docs/repo-settings-checklist.md) (PyPI
Trusted Publisher and the protected `pypi` environment).

**Stable release (the normal path):**

1. Open a PR that makes the change, applies one `release:*` label, bumps the
   version in all four places, and adds the dated changelog section.
2. Merge it once CI is green. That is the whole release action.
3. Watch the `Release` run: it tags `vX.Y.Z`, creates the GitHub Release, and
   publishes to PyPI.
4. Verify: `pipx install sobatista-ai==X.Y.Z` (or `uv tool install`), then
   `sobai --version`.

**Republishing an existing tag.** Dispatch `release.yml` manually with the tag
(for example after a transient PyPI failure). Every step is idempotent: the tag
is not recreated, the Release is reused, assets are re-uploaded with `--clobber`,
and PyPI upload uses `skip-existing`.

**Pre-releases (alpha/beta/rc) are manual.** SemVer pre-release ordering and PEP
440 differ, and `check_version.py` accepts only exact `x.y.z`, so cut them by
hand:

1. Set the PEP 440 pre-release version (e.g. `0.2.0a1`) in `pyproject.toml` on a
   branch, without a `release:*` label, and do not merge it to `main`.
2. Tag and release it directly: `gh release create v0.2.0a1 --prerelease
   --generate-notes`. Mark it a pre-release so it is not "latest".
3. Dispatch `release.yml` against that tag to publish it. pip will not install it
   without `--pre` or an exact pin.

**A tag that would have to move** means a pull request reached `main` without its
version increment. The release run fails loudly and changes nothing; fix it by
merging a follow-up PR that bumps the version.

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
