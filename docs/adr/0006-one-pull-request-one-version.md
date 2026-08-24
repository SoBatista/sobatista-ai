# ADR-0006: One pull request, one version

- Status: Accepted
- Date: 2026-08-24
- Supersedes: [ADR-0004](0004-versioning-and-releases.md) (prepare/publish split
  via Release Please). The Trusted Publishing and supply-chain decisions in
  ADR-0004 are **retained unchanged**; only how the version is decided and how
  publishing is triggered change here.

## Context

ADR-0004 chose Release Please: a bot maintained a release PR that bumped the
version from Conventional Commits, and merging it created a tag and Release,
which triggered publishing. Operating it surfaced four problems.

1. **The declared impact did not predict the version.** Configured with
   `bump-minor-pre-major` and `bump-patch-for-minor-pre-major`, a `feat:` below
   1.0.0 produced a *patch*, and a breaking change produced a *minor*. A
   contributor ticking `minor` on a 0.1.0 line got 0.1.1, not 0.2.0.
2. **Publishing never fired.** A GitHub Release created with `GITHUB_TOKEN`
   cannot trigger another workflow, so `release.yml` never ran. v0.1.0 was
   tagged and released but never reached PyPI. The documented workaround was a
   personal access token — a long-lived credential this project otherwise
   refuses to hold — or a manual dispatch.
3. **The bot could not maintain the whole version.** Release Please rewrote
   `pyproject.toml` but knew nothing about `uv.lock`, which records the same
   version, so every release PR failed lockfile consistency until a bespoke
   re-locking job was bolted on. Its `extra-files` updater silently no-opped on
   `_FALLBACK_VERSION` because `0.1.0.dev0` is not bare SemVer.
4. **It required loosening repository settings.** Release PR creation needs
   "Allow GitHub Actions to create and approve pull requests" enabled.

## Decision

- **The version is decided by the reviewed pull request, not by a bot.** Every
  PR carries exactly one `release:major|minor|patch` label and bumps
  `[project].version` by that single increment.
  `scripts/check_version.py --pr BASE_REF` proves the label, the version,
  `_FALLBACK_VERSION`, `uv.lock`, and a dated `CHANGELOG.md` section all agree.
  There are no pre-1.0 special cases: `release:minor` on 0.1.1 is always 0.2.0.
- **Every pull request bumps**, including documentation and dependency updates
  (`patch`). One merge is one release.
- **Publishing is triggered by a successful CI run on `main`.** `release.yml`
  builds and verifies the artifacts, then `scripts/release.py --publish` creates
  the annotated tag and the GitHub Release from that version's reviewed
  changelog section, and PyPI publishing runs last. `workflow_run` fires
  normally for `GITHUB_TOKEN`, so **no personal access token is needed**.
- **Tags are plain `vX.Y.Z`.** v0.1.0 carries the component-prefixed
  `sobatista-ai-v0.1.0` that Release Please's manifest mode produced; the
  ordering guard recognises it so the discontinuity is one-off.
- **Nothing is tagged before it is verified.** The tag is created only after
  build, both-artifact smoke installs, and provenance attestation succeed, and
  PyPI — the only irreversible step — runs last.

## Consequences

- The version in review is the version released; the label is the arithmetic.
- Publishing is fully automatic with no long-lived credential, and "Allow GitHub
  Actions to create and approve pull requests" can be disabled again.
- **Dependabot pull requests need a version bump added before merge.** They
  carry no label and do not touch `pyproject.toml`, so they fail release
  metadata until a maintainer pushes the bump onto the branch. This is the
  accepted cost of one-PR-one-version.
- A merge that reaches `main` without a bump fails the release run loudly,
  because the existing tag would have to move — which is refused, never done.
- Pre-releases (alpha/beta/rc) remain manual, as in ADR-0004: SemVer
  pre-release ordering and PEP 440 differ, and `check_version.py` deliberately
  accepts only exact `x.y.z`.
